#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""motionmap.py — карта динамики видео: где движение, где смена плана, где «пусто».

Нужна, когда агент не видит картинку: выбираем фрагменты b-roll по движению/деталям,
а не «на глаз». Кадры извлекаются ffmpeg-ом с шагом 1 c.

Использование: python motionmap.py <video> [step_sec]
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def edge_energy(im: Image.Image) -> float:
    g = im.convert("L").resize((180, 180)).filter(ImageFilter.FIND_EDGES)
    px = list(g.getdata())
    return sum(px) / len(px)


def main() -> None:
    src = Path(sys.argv[1])
    step = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
    tmp = Path(tempfile.mkdtemp(prefix="motion_"))
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src),
                    "-vf", f"fps=1/{step},scale=180:180", "-q:v", "3",
                    str(tmp / "%04d.jpg")], check=True)
    frames = sorted(tmp.glob("*.jpg"))
    print(f"=== {src.name}: {len(frames)} кадров с шагом {step} c ===")
    print("  t(c)  motion detail  bar")
    prev = None
    for i, f in enumerate(frames):
        im = Image.open(f)
        det = edge_energy(im)
        mot = 0.0
        if prev is not None:
            d = ImageChops.difference(im, prev).convert("L")
            px = list(d.getdata())
            mot = sum(px) / len(px)
        prev = im
        bar = "#" * int(min(60, mot * 1.2)) + "." * int(min(30, det / 4))
        flag = " <== СМЕНА ПЛАНА" if mot > 28 else ""
        print(f"  {i * step:5.0f}  {mot:5.1f}  {det:6.1f}  {bar}{flag}")


if __name__ == "__main__":
    main()
