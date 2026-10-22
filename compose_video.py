#!/usr/bin/env python3
"""
compose_video.py — сборка вертикального видео (1080x1920) из B-roll-видео с Reddit
+ ASS-субтитры/заголовок. Видео зацикливается, если короче озвучки.
"""

import argparse
import sys
import subprocess
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_AUDIO = r"D:\AI\F5-TTS\out\voiceover.wav"
DEFAULT_ASS = r"D:\AI\VIDEO_PIPELINE\output\subs.ass"
DEFAULT_OUT = r"D:\AI\VIDEO_PIPELINE\output\final_video.mp4"
DEFAULT_VIDEO = r"D:\AI\F5-TTS\assets\bro_stole_strength.mp4"

DEFAULT_WIDTH = 1080
DEFAULT_HEIGHT = 1920
DEFAULT_FPS = 30
DEFAULT_CRF = 18
DEFAULT_BITRATE = "12M"


def parse_args():
    parser = argparse.ArgumentParser(description="Сборка видео с видео-B-roll")
    parser.add_argument("--audio", "-a", type=str, default=DEFAULT_AUDIO)
    parser.add_argument("--ass", "-s", type=str, default=DEFAULT_ASS)
    parser.add_argument("--video", "-v", type=str, default=DEFAULT_VIDEO)
    parser.add_argument("--out", "-o", type=str, default=DEFAULT_OUT)
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS)
    parser.add_argument("--crf", type=int, default=DEFAULT_CRF)
    parser.add_argument("--bitrate", type=str, default=DEFAULT_BITRATE)
    return parser.parse_args()


def get_duration(path: str) -> float:
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return float(result.stdout.strip())
    except Exception:
        return 30.0


def compose(audio_path: str, ass_path: str, video_path: str,
            out_path: str, width: int, height: int, fps: int,
            crf: int, bitrate: str) -> bool:
    for p, name in [(audio_path, "Аудио"), (ass_path, "ASS"), (video_path, "Видео")]:
        if not Path(p).exists():
            print(f"[ERROR] {name} не найдено: {p}")
            return False

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    duration = get_duration(audio_path)
    video_duration = get_duration(video_path)
    print(f"   Длительность аудио: {duration:.2f} сек")
    print(f"   Длительность видео: {video_duration:.2f} сек")

    ass_escaped = ass_path.replace("\\", "\\\\").replace(":", "\\:")

    # Видео -> 1080x1920 (crop по центру), 30 fps, обрезка до длины аудио, затем ASS
    filter_complex = (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        f"setsar=1,"
        f"fps={fps},"
        f"trim=duration={duration:.3f},"
        f"setpts=PTS-STARTPTS[v];"
        f"[v]ass=filename='{ass_escaped}':original_size={width}x{height}[vout]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", video_path,   # зацикливаем видео
        "-i", audio_path,                          # озвучка
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "1:a",
        "-t", str(duration),
        "-c:v", "libx264",
        "-crf", str(crf),
        "-b:v", bitrate,
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        "-shortest",
        out_path,
    ]

    print(f"\n[FFMPEG] Сборка видео...")
    print(f"   Видео: {video_path}")
    print(f"   ASS: {ass_path}")
    print(f"   Выход: {out_path}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
        if result.returncode == 0:
            print(f"[OK] Видео сохранено: {out_path}")
            return True
        else:
            print(f"[ERROR] Ошибка FFmpeg:")
            print(result.stderr[-3000:])
            return False
    except Exception as e:
        print(f"[ERROR] {e}")
        return False


def main():
    args = parse_args()
    print("=" * 60)
    print("[FFMPEG] Сборка видео с видео-B-roll")
    print("=" * 60)
    success = compose(
        audio_path=args.audio, ass_path=args.ass, video_path=args.video,
        out_path=args.out,
        width=args.width, height=args.height, fps=args.fps,
        crf=args.crf, bitrate=args.bitrate,
    )
    if not success:
        sys.exit(1)
    print("\n[DONE] Готово!")
    print(f"   Файл: {args.out}")


if __name__ == "__main__":
    main()
