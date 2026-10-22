#!/usr/bin/env python3
"""
compose_segments.py — сборка вертикального ролика 1080x1920 из НЕСКОЛЬКИХ
фрагментов исходного видео (квадрат/широкий → по центру, размытый фон-заполнитель),
плюс ASS-заголовок/субтитры и озвучка.

Правило: фото/кадр не растягиваем; фон = увеличенная размытая копия кадра.
"""
import argparse
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

W, H, FPS = 1080, 1920, 30


def get_duration(path: str) -> float:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return float(r.stdout.strip())


def compose(source: str, segments, audio: str, ass: str, out: str,
            crf: int = 18, bitrate: str = "12M", overlays: str = "",
            style: str = "punch", sharpen: str = "") -> bool:
    """
    sharpen: строка параметров unsharp для переднего плана, напр. "5:5:1.0:5:5:0.0".
    Нужно для мелких исходников (360x360): при растяжении до 1080 контуры «мылятся»,
    лёгкое усиление резкости возвращает детали (b-roll низкого разрешения).
    """
    for p in (source, audio, ass):
        if not Path(p).exists():
            print(f"[ERROR] не найдено: {p}")
            return False

    Path(out).parent.mkdir(parents=True, exist_ok=True)
    adur = get_duration(audio)
    print(f"   Аудио: {adur:.2f} сек | фрагментов: {len(segments)}"
          + (f" | unsharp={sharpen}" if sharpen else ""))

    parts = []
    for i, (start, dur) in enumerate(segments):
        end = start + dur
        # «Живой» кадр: лёгкий зум внутри фрагмента (эффект дыхания камеры)
        # + фильтр punch (контраст/насыщенность) — приём удержания из Shorts/TikTok.
        if style == "punch":
            grade = "eq=contrast=1.08:saturation=1.12:brightness=0.01,"
        else:
            grade = ""
        sharp_fg = f",unsharp={sharpen}" if sharpen else ""
        parts.append(
            f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS,"
            f"{grade}"
            f"split=2[bs{i}][fs{i}];"
            f"[bs{i}]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},boxblur=30:30,eq=brightness=-0.1,setsar=1[bg{i}];"
            f"[fs{i}]scale={W}:{H}:force_original_aspect_ratio=decrease,setsar=1{sharp_fg}[fg{i}];"
            f"[bg{i}][fg{i}]overlay=(W-w)/2:(H-h)/2,fps={FPS}[seg{i}]"
        )
    concat_in = "".join(f"[seg{i}]" for i in range(len(segments)))
    parts.append(f"{concat_in}concat=n={len(segments)}:v=1:a=0[vcat]")

    def esc(p: str) -> str:
        return p.replace("\\", "\\\\").replace(":", "\\:")

    filt = f"[vcat]ass=filename='{esc(ass)}':original_size={W}x{H}"
    if overlays and Path(overlays).exists():
        filt += f",ass=filename='{esc(overlays)}':original_size={W}x{H}"
    filt += "[vout]"
    parts.append(filt)
    fc = ";".join(parts)

    cmd = ["ffmpeg", "-y", "-i", source, "-i", audio,
           "-filter_complex", fc,
           "-map", "[vout]", "-map", "1:a",
           "-t", f"{adur:.3f}",
           "-c:v", "libx264", "-crf", str(crf), "-b:v", bitrate,
           "-c:a", "aac", "-b:a", "192k",
           "-pix_fmt", "yuv420p", "-r", str(FPS), "-shortest", out]

    print(f"[FFMPEG] Сборка: {out}")
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode == 0:
        print(f"[OK] Готово: {out}")
        return True
    print("[ERROR] FFmpeg:")
    print(r.stderr[-3000:])
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=r"D:\AI\F5-TTS\assets\coffin_girl.mp4")
    ap.add_argument("--audio", default=r"D:\AI\F5-TTS\out\voiceover.wav")
    ap.add_argument("--ass", default=r"D:\AI\VIDEO_PIPELINE\output\subs.ass")
    ap.add_argument("--out", default=r"D:\AI\VIDEO_PIPELINE\output\final_video.mp4")
    # Оверлеи (инфо-карточки по центру) ОТКЛЮЧЕНЫ пользователем 13.10.2026.
    # По умолчанию путь пустой — второй ASS-слой не подключается.
    ap.add_argument("--overlays", default="",
                    help="(отключено) второй ASS-слой с инфо-карточками")
    # start:duration по умолчанию — растянем по ходу
    ap.add_argument("--segments", default="4:3,20:3,38:3,55:3,72:3,90:3")
    ap.add_argument("--style", default="punch", choices=["punch", "plain"],
                    help="punch: зум+контраст (удержание), plain: как раньше")
    ap.add_argument("--sharpen", default="",
                    help="unsharp для переднего плана (для мелких 360x360-исходников: 5:5:1.0:5:5:0.0)")
    a = ap.parse_args()

    segs = []
    for tok in a.segments.split(","):
        s, d = tok.split(":")
        segs.append((float(s), float(d)))

    ok = compose(a.source, segs, a.audio, a.ass, a.out, overlays=a.overlays,
                 style=a.style, sharpen=a.sharpen)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
