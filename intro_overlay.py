#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""intro_overlay.py — вставка интро «перья разлетаются» поверх готового ролика.

Идея взята с канала-ориентира «ПРЕМИЯ ДАРВИНА»: на первом кадре экран полностью
закрыт (у них — осенние листья), затем за ~0.5-1.0 с «разлетается» и открывает видео.

Реализация: клип с белыми перьями на чёрном фоне (assets/intro/feathers.mp4)
раскладывается в 3 слоя (разный масштаб + отражение) — чтобы перья закрывали кадр
плотнее, чем один слой, — чёрный фон превращается в прозрачность (альфа = яркость),
и всё это накладывается на первые `--dur` секунд ролика. Опционально добавляется
короткая белая вспышка и whoosh на нулевом кадре.

Пример:
  python intro_overlay.py --video output\\final_video.mp4 ^
      --out output\\final_video_feathers.mp4 --flash --whoosh
"""
import argparse
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

W, H, FPS = 1080, 1920, 30
VP = Path(r"D:\AI\VIDEO_PIPELINE")
DEFAULT_FEATHERS = VP / "assets" / "intro" / "feathers.mp4"
WHOOSH = VP / "assets" / "audio" / "whoosh.wav"
WHOOSH_DB = -9.0

# слои перьев: (масштаб, отражение) — 'n' без отражения, 'h' по горизонтали, 'v' по вертикали
LAYERS = [(1.0, "n"), (1.5, "h"), (2.1, "v")]


def build_filter(dur: float, flash: bool, feather_idx: int, alpha_gain: float,
                 flash_dur: float = 0.40, flash_fade: float = 0.30) -> str:
    parts = []
    for i, (z, flip) in enumerate(LAYERS, start=1):
        pre = (f"trim=start=0:end={dur},setpts=PTS-STARTPTS,"
               f"scale={W}:{H},scale=iw*{z}:ih*{z},crop={W}:{H},fps={FPS}")
        if flip == "h":
            pre += ",hflip"
        elif flip == "v":
            pre += ",vflip"
        parts.append(f"[{feather_idx}:v]{pre},format=rgb24[c{i}]")
        parts.append(f"[{feather_idx}:v]{pre},format=gray,"
                     f"lut=y=min(255\\,val*{alpha_gain})[a{i}]")
        parts.append(f"[c{i}][a{i}]alphamerge[f{i}]")

    cur = "[0:v]"
    if flash:
        # ВАЖНО: источник color=white бесконечный — его обязательно обрезаем по времени,
        # иначе overlay с eof_action=repeat растягивает ролик на часы.
        parts.append(f"[2:v]trim=start=0:end={flash_dur},setpts=PTS-STARTPTS,"
                     f"format=rgba,colorchannelmixer=aa=0.55,"
                     f"fade=t=out:st=0:d={flash_fade}:alpha=1[wf]")
        parts.append(f"{cur}[wf]overlay=0:0:eof_action=pass[e0]")
        cur = "[e0]"
    for i in range(1, len(LAYERS) + 1):
        parts.append(f"{cur}[f{i}]overlay=0:0:eof_action=pass[e{i}]")
        cur = f"[e{i}]"
    parts.append(f"{cur}null[vout]")
    return ";".join(parts)


def get_duration(path: str) -> float:
    """Длительность ролика в секундах (для страховки от «бесконечных» фильтров)."""
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def build_audio_intro(src_wav: str, dst_wav: str) -> bool:
    """Добавляет whoosh в самое начало готового микса."""
    try:
        from pydub import AudioSegment
    except ImportError:
        print("[WARN] pydub недоступен — whoosh не добавлен")
        return False
    if not Path(src_wav).exists() or not WHOOSH.exists():
        print("[WARN] нет исходного микса или whoosh — пропускаю")
        return False
    mix = AudioSegment.from_file(src_wav)
    wh = AudioSegment.from_file(str(WHOOSH)).apply_gain(WHOOSH_DB)
    mix = mix.overlay(wh, position=0)
    mix.export(dst_wav, format="wav")
    print(f"[OK] интро-микс с whoosh: {dst_wav}")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", default=str(VP / "output" / "final_video.mp4"))
    ap.add_argument("--feathers", default=str(DEFAULT_FEATHERS))
    ap.add_argument("--out", default=str(VP / "output" / "final_video_feathers.mp4"))
    ap.add_argument("--dur", type=float, default=1.2, help="длина слоя перьев, сек")
    ap.add_argument("--alpha-gain", type=float, default=1.0)
    ap.add_argument("--flash", action="store_true", help="белая вспышка на первом кадре")
    ap.add_argument("--whoosh", action="store_true", help="whoosh в начало дорожки")
    ap.add_argument("--audio", default=r"D:\AI\F5-TTS\out\voiceover_mix.wav",
                    help="микс голоса для whoosh (необязательно)")
    ap.add_argument("--preview-sec", type=float, default=0.0,
                    help=">0 — отрендерить только первые N секунд (быстрая проба)")
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--bitrate", default="12M")
    a = ap.parse_args()

    for p in (a.video, a.feathers):
        if not Path(p).exists():
            print(f"[ERROR] не найдено: {p}")
            return 1

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)

    # --- входы ---
    cmd = ["ffmpeg", "-y", "-i", a.video, "-i", a.feathers]
    next_idx = 2
    if a.flash:
        cmd += ["-f", "lavfi", "-i", f"color=c=white:s={W}x{H}:r={FPS}"]
        next_idx += 1
    tmp_wav = str(Path(a.out).with_suffix("")) + "_intro.wav"
    use_wav = bool(a.whoosh and build_audio_intro(a.audio, tmp_wav))
    if use_wav:
        cmd += ["-i", tmp_wav]
        audio_idx = next_idx
    else:
        audio_idx = 0  # дорожка исходного ролика

    # --- фильтры и выходные опции ---
    fc = build_filter(a.dur, a.flash, 1, a.alpha_gain)
    cmd += ["-filter_complex", fc, "-map", "[vout]", "-map", f"{audio_idx}:a"]
    if use_wav:
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-c:a", "copy"]

    if a.preview_sec > 0:
        cmd += ["-t", f"{a.preview_sec:.3f}"]
    else:
        # страховка от «бесконечных» источников: жёстко ограничиваем длину ролика
        cmd += ["-t", f"{get_duration(a.video):.3f}"]

    cmd += ["-c:v", "libx264", "-crf", str(a.crf), "-b:v", a.bitrate,
            "-pix_fmt", "yuv420p", "-r", str(FPS), a.out]

    print(f"[FFMPEG] Интро: перья {a.dur}c | слоёв {len(LAYERS)} | "
          f"вспышка={'да' if a.flash else 'нет'} | whoosh={'да' if a.whoosh else 'нет'}")
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode == 0:
        print(f"[OK] Готово: {a.out}")
        return 0
    print("[ERROR] FFmpeg:")
    print(r.stderr[-2500:])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
