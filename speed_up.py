#!/usr/bin/env python3
"""
speed_up.py — ускорение озвучки БЕЗ изменения тона (FFmpeg atempo).
atempo поддерживает 0.5..2.0 за один шаг; для большего — цепочка.

Целевой темп для Shorts на русском: 170-190 слов/мин.
"""
import argparse
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def get_duration(path: str) -> float:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return float(r.stdout.strip())


def build_atempo_chain(factor: float) -> str:
    """atempo поддерживает 0.5..2.0; при большем — разбиваем на цепочку."""
    parts = []
    f = factor
    while f > 2.0:
        parts.append("atempo=2.0")
        f /= 2.0
    while f < 0.5:
        parts.append("atempo=0.5")
        f /= 0.5
    parts.append(f"atempo={f:.5f}")
    return ",".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=r"D:\AI\F5-TTS\out\voiceover.wav")
    ap.add_argument("--out", dest="out", default=r"D:\AI\F5-TTS\out\voiceover_fast.wav")
    ap.add_argument("--factor", type=float, default=1.2)
    a = ap.parse_args()

    if not Path(a.inp).exists():
        print(f"[ERROR] нет файла: {a.inp}")
        sys.exit(1)

    chain = build_atempo_chain(a.factor)
    dur_in = get_duration(a.inp)

    cmd = ["ffmpeg", "-y", "-i", a.inp, "-filter:a", chain,
           "-c:a", "pcm_s16le", a.out]
    print(f"[ATEMPO] {a.inp}")
    print(f"   factor={a.factor}  chain={chain}")
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print("[ERROR] FFmpeg:")
        print(r.stderr[-2000:])
        sys.exit(1)

    dur_out = get_duration(a.out)
    print(f"   Было: {dur_in:.2f} сек -> Стало: {dur_out:.2f} сек")
    print(f"[OK] {a.out}")


if __name__ == "__main__":
    main()
