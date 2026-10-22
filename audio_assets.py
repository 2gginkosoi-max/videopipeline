#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audio_assets.py — локальная генерация музыкальных подложек и звуковых акцентов.

Требование ORIGINALITY_GUIDE.md (Правило 2): звуковые акценты (whoosh, click) и
фоновая музыка (тише голоса). Готовых лицензионных файлов в системе нет — генерируем
их через FFmpeg lavfi. Разные подложки = разный визуально-звуковой стиль роликов.

Выход: D:\\AI\\VIDEO_PIPELINE\\assets\\audio\\
  bed_am.wav, bed_c.wav, bed_em.wav, bed_dm.wav  — музыкальные подложки (30 c)
  whoosh.wav, click.wav                          — акценты
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = Path(r"D:\AI\VIDEO_PIPELINE\assets\audio")

# Аккорды (частоты в Гц) — разные «настроения», чтобы стиль роликов отличался
BEDS = {
    "am": [220.00, 261.63, 329.63],   # A minor
    "c":  [261.63, 329.63, 392.00],   # C major
    "em": [164.81, 196.00, 246.94],   # E minor
    "dm": [146.83, 174.61, 220.00],   # D minor
}


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print("[FFMPEG ERROR]", " ".join(cmd))
        print(r.stderr[-1500:])
        return False
    return True


def make_bed(name, freqs, dur=30):
    out = OUT / f"bed_{name}.wav"
    if out.exists():
        print(f"[SKIP] {out.name} уже есть")
        return True
    ins = []
    fc = []
    for i, f in enumerate(freqs):
        ins += ["-f", "lavfi", "-i", f"sine=frequency={f}:duration={dur}"]
        fc.append(f"[{i}:a]")
    graph = ("".join(fc) + f"amix=inputs={len(freqs)}:normalize=0,"
             "tremolo=f=0.33:d=0.5,"
             "aecho=0.8:0.9:70|190:0.35|0.22,"
             "lowpass=f=1600,volume=0.5[a]")
    cmd = ["ffmpeg", "-y"] + ins + ["-filter_complex", graph, "-map", "[a]",
                                    "-ar", "44100", "-ac", "2", str(out)]
    ok = run(cmd)
    print(("[OK] " if ok else "[FAIL] ") + out.name)
    return ok


def make_whoosh():
    out = OUT / "whoosh.wav"
    if out.exists():
        print("[SKIP] whoosh.wav уже есть")
        return True
    cmd = ["ffmpeg", "-y", "-f", "lavfi",
           "-i", "anoisesrc=duration=0.45:color=pink:amplitude=0.6",
           "-af", "highpass=f=450,lowpass=f=4200,"
                  "afade=t=in:st=0:d=0.10,afade=t=out:st=0.22:d=0.23,volume=1.3",
           "-ar", "44100", "-ac", "2", str(out)]
    ok = run(cmd)
    print(("[OK] " if ok else "[FAIL] ") + out.name)
    return ok


def make_click():
    out = OUT / "click.wav"
    if out.exists():
        print("[SKIP] click.wav уже есть")
        return True
    cmd = ["ffmpeg", "-y", "-f", "lavfi",
           "-i", "sine=frequency=1500:duration=0.07",
           "-af", "afade=t=out:st=0.01:d=0.06,volume=0.8",
           "-ar", "44100", "-ac", "2", str(out)]
    ok = run(cmd)
    print(("[OK] " if ok else "[FAIL] ") + out.name)
    return ok


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ok = True
    for name, freqs in BEDS.items():
        ok &= make_bed(name, freqs)
    ok &= make_whoosh()
    ok &= make_click()
    print("[DONE] аудио-ассеты готовы" if ok else "[DONE] были ошибки")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
