#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""compose_broll.py — монтаж 1080x1920 ИЗ ПЛАНА b-roll (plan.json).

В отличие от compose_segments.py (один исходник, нарезка по времени), здесь
каждый шот берёт СВОЙ медиафайл из плана broll_agent.py — то есть футаж
подбирается под КОНКРЕТНУЮ новость, а не переиспользуется старый ролик.

Правило картинки то же, что в compose_segments.py:
фото/кадр НЕ растягиваем; фон = увеличенная размытая копия кадра.
Фото — Ken Burns (медленный зум/пан). Видео — кроп под 9:16
(широкий кадр вписываем целиком поверх размытого фона, чтобы не терять края).

Дизайн субтитров/заголовка НЕ меняется: поверх готовой дорожки выжигается
уже собранный ASS (make_ass.py) и накладывается готовый аудиомикс.

CLI:
  python compose_broll.py --plan PLAN.json --audio VOICE_MIX.wav \
      --ass output\\subs.ass --out output\\final_video.mp4 [--work DIR]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

W, H, FPS = 1080, 1920, 30
FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


def probe_duration(path: str) -> float:
    cmd = [FFPROBE, "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def probe_wh(path: str):
    cmd = [FFPROBE, "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=width,height",
           "-of", "csv=s=x:p=0", path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        w, h = r.stdout.strip().split("x")
        return int(w), int(h)
    except ValueError:
        return 0, 0


def run(cmd) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError("ffmpeg fail:\n" + " ".join(map(str, cmd)) +
                           "\n" + (r.stderr or "")[-2500:])


def even(n: int) -> int:
    n = int(n)
    return max(2, n - (n % 2))


def image_clip(src: str, dur: float, effect: str, out: str) -> None:
    """Фото -> Ken Burns поверх размытого фона (кадр не растягиваем)."""
    iw, ih = probe_wh(src)
    if iw <= 0 or ih <= 0:
        iw, ih = W, H
    s = min(W / iw, H / ih)
    fw, fh = even(round(iw * s)), even(round(ih * s))
    nfr = max(1, round(dur * FPS))
    zmax, zpan = 1.12, 1.10
    inc = (zmax - 1.0) / nfr

    if effect == "zoom_out":
        zexpr = f"if(lte(on,1),{zmax:.4f},max(1.0,{zmax:.4f}-{inc:.6f}*on))"
        xexpr, yexpr = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif effect == "pan_right":
        zexpr = f"{zpan:.4f}"
        xexpr, yexpr = f"(iw-iw/zoom)*on/{nfr}", "(ih-ih/zoom)/2"
    elif effect == "pan_left":
        zexpr = f"{zpan:.4f}"
        xexpr, yexpr = f"(iw-iw/zoom)*(1-on/{nfr})", "(ih-ih/zoom)/2"
    else:  # zoom_in
        zexpr = f"min(1.0+{inc:.6f}*on,{zmax:.4f})"
        xexpr, yexpr = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"

    fc = (
        f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
        f"crop={W}:{H},boxblur=28:2,eq=brightness=-0.12[bg];"
        f"[0:v]scale={fw * 2}:{fh * 2},zoompan=z='{zexpr}':x='{xexpr}':y='{yexpr}':"
        f"d=1:s={fw}x{fh}:fps={FPS}[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2:shortest=1,format=yuv420p,setsar=1[v]"
    )
    run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
         "-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}", "-i", src,
         "-filter_complex", fc, "-map", "[v]", "-t", f"{dur:.3f}",
         "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-pix_fmt", "yuv420p", "-an", out])


def video_clip(src: str, dur: float, out: str) -> None:
    """Видео -> кроп под 9:16 (широкий кадр — целиком поверх размытого фона)."""
    vdur = probe_duration(src)
    w, h = probe_wh(src)
    loop = vdur < dur - 0.05
    src_ar = (w / h) if (w and h) else (9 / 16)
    target_ar = W / H
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error"]
    if loop:
        cmd += ["-stream_loop", "-1"]
    if src_ar > target_ar + 0.08:
        fc = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
              f"boxblur=28:2,eq=brightness=-0.12[bg];"
              f"[0:v]scale={W}:-2[fg];"
              f"[bg][fg]overlay=(W-w)/2:(H-h)/2:shortest=1,format=yuv420p,setsar=1[v]")
        cmd += ["-i", src, "-t", f"{dur:.3f}", "-filter_complex", fc, "-map", "[v]",
                "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-pix_fmt", "yuv420p", "-an", out]
    else:
        fc = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
              f"fps={FPS},format=yuv420p,setsar=1")
        cmd += ["-i", src, "-t", f"{dur:.3f}", "-vf", fc, "-r", str(FPS),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-pix_fmt", "yuv420p", "-an", out]
    run(cmd)


def compose(plan_path: str, audio: str, ass: str, out: str, work: str | None) -> bool:
    for p in (plan_path, audio, ass):
        if not Path(p).exists():
            print(f"[ERROR] не найдено: {p}")
            return False

    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    shots = plan.get("shots") or []
    if not shots:
        print("[ERROR] в плане нет шотов — сначала запустите broll_agent.py")
        return False
    gaps = plan.get("gaps") or []
    if gaps:
        print(f"[ERROR] в плане {len(gaps)} дыр(ы) без медиа — монтаж невозможен")
        return False

    out_dir = Path(out).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir = Path(work) if work else out_dir / "broll_build"
    work_dir.mkdir(parents=True, exist_ok=True)

    adur = probe_duration(audio)
    pdir = float(plan.get("duration") or 0.0)
    ratio = (adur / pdir) if pdir else 1.0
    if abs(ratio - 1.0) > 0.005:
        print(f"   План {pdir:.2f}c != аудио {adur:.2f}c -> масштаб таймингов {ratio:.4f}")
        for sh in shots:
            sh["start"] = round(float(sh["start"]) * ratio, 3)
            sh["end"] = round(float(sh["end"]) * ratio, 3)
        shots[-1]["end"] = round(adur, 3)

    print(f"   Аудио: {adur:.2f} сек | шотов: {len(shots)}")

    clips = []
    for i, sh in enumerate(shots):
        media = sh.get("media") or {}
        src = media.get("path")
        if not src or not Path(src).exists():
            print(f"[ERROR] шот {i} без медиафайла: {src}")
            return False
        dur = max(0.2, float(sh["end"]) - float(sh["start"]))
        clip = str(work_dir / f"c{i:03d}.mp4")
        print(f"   [{i}] {dur:5.2f}c  {media.get('type', '?'):5s}  {Path(src).name}")
        if media.get("type") == "video":
            video_clip(src, dur, clip)
        else:
            image_clip(src, dur, media.get("effect", "zoom_in"), clip)
        clips.append(clip)

    list_path = str(work_dir / "concat.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for c in clips:
            f.write("file '" + c.replace("\\", "/").replace("'", "'\\''") + "'\n")
    base = str(work_dir / "base.mp4")
    run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat",
         "-safe", "0", "-i", list_path, "-c", "copy", base])
    print(f"[FFMPEG] Дорожка собрана: {base}")

    def esc(p: str) -> str:
        return p.replace("\\", "\\\\").replace(":", "\\:")

    final_cmd = [FFMPEG, "-y", "-i", base, "-i", audio,
                 "-vf", f"ass=filename='{esc(ass)}':original_size={W}x{H}",
                 "-map", "0:v", "-map", "1:a",
                 "-t", f"{adur:.3f}",
                 "-c:v", "libx264", "-crf", "18", "-b:v", "12M",
                 "-c:a", "aac", "-b:a", "192k",
                 "-pix_fmt", "yuv420p", "-r", str(FPS), "-shortest",
                 "-movflags", "+faststart", out]
    print(f"[FFMPEG] Финал: {out}")
    run(final_cmd)
    print(f"[OK] Готово: {out}")
    return True


def main():
    ap = argparse.ArgumentParser(description="Монтаж вертикального ролика из plan.json")
    ap.add_argument("--plan", required=True)
    ap.add_argument("--audio", required=True)
    ap.add_argument("--ass", required=True)
    ap.add_argument("--out", default=r"D:\AI\VIDEO_PIPELINE\output\final_video.mp4")
    ap.add_argument("--work", default=None)
    a = ap.parse_args()
    ok = compose(a.plan, a.audio, a.ass, a.out, a.work)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
