#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""goose_overlay.py — «гусь-соведущий»: круглый говорящий гусь в углу кадра.

Канал называется «ГУСЬ ПЕРЕВОДИЛА», поэтому гусь — постоянный элемент бренда:
поверх готового ролика (1080x1920) в свободное место кадра вставляется круглый
«аватар» с говорящим гусём. Гусь зациклен на всю длину ролика, звук гуся по
умолчанию ВЫКЛЮЧЕН (голос диктора — главный).

Почему так сделано:
  * круг + белое кольцо — «аватар-пузырь» (модно, отделяет гуся от b-roll);
  * маска и кольцо — статические PNG (генерируются PIL-ом один раз), а НЕ geq:
    geq считает выражение на каждый пиксель каждого кадра и рендер убивает
    (для 400x400x30fps это сотни миллионов вычислений);
  * кроп берётся квадратом по центру «полезной» области, чтобы гусь был крупно;
  * ролик перекодируется один раз (crf 18) — визуальная потеря минимальна.

Где место в кадре: заголовок занимает верх (MarginV 200, Alignment 8),
субтитры — низ (MarginV 400, Alignment 2). Свободны бока в средней полосе —
там и живёт гусь (по умолчанию справа, по центру по вертикали).

Пример:
  python goose_overlay.py --video output\\final_video.mp4 --goose assets\\goose\\goose_anchor.webm ^
      --out output\\final_video_goose.mp4 --pos mid-right --size 400
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

W, H, FPS = 1080, 1920, 30
VP = Path(r"D:\AI\VIDEO_PIPELINE")
ASSETS = VP / "assets" / "goose"
DEFAULT_GOOSE = ASSETS / "goose_anchor.webm"

# пресеты положения: x/y считаются от размера круга.
# Справа отступ 110 px, а не 40: справа в Shorts висит рейл (лайк/репост/⋯)
# примерно на высоте центра — гусь не должен прятаться под кнопками.
POS_PRESETS = {
    "top-right": lambda s: (W - s - 110, 560),
    "mid-right": lambda s: (W - s - 110, (H - s) // 2),
    "low-right": lambda s: (W - s - 110, H - s - 620),   # выше нижних субтитров
    "top-left": lambda s: (40, 560),
    "mid-left": lambda s: (40, (H - s) // 2),
}


def make_mask(size: int, path: Path) -> None:
    """Круглая маска (серое на чёрном) с 4x сглаживанием."""
    ss = 4
    img = Image.new("L", (size * ss, size * ss), 0)
    ImageDraw.Draw(img).ellipse((0, 0, size * ss - 1, size * ss - 1), fill=255)
    img.resize((size, size), Image.LANCZOS).save(path)


def make_ring(size: int, w_white: int, w_dark: int, path: Path) -> None:
    """Кольцо «аватара»: тёмная окантовка снаружи + белое кольцо внутри, центр — прозрачный."""
    ss = 4
    total = size + 2 * (w_white + w_dark)
    rgb = Image.new("RGB", (total * ss, total * ss), (255, 255, 255))
    d = ImageDraw.Draw(rgb)
    d.ellipse((0, 0, total * ss - 1, total * ss - 1), fill=(24, 24, 24))
    d.ellipse((w_dark * ss, w_dark * ss,
               (total - w_dark) * ss - 1, (total - w_dark) * ss - 1), fill=(255, 255, 255))
    hole = (w_dark + w_white) * ss
    alpha = Image.new("L", (total * ss, total * ss), 255)
    ImageDraw.Draw(alpha).ellipse((hole, hole, total * ss - hole - 1, total * ss - hole - 1), fill=0)
    out = rgb.resize((total, total), Image.LANCZOS).convert("RGBA")
    out.putalpha(alpha.resize((total, total), Image.LANCZOS))
    out.save(path)


def duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def main() -> int:
    ap = argparse.ArgumentParser(description="Круглый гусь-соведущий поверх ролика")
    ap.add_argument("--video", default=str(VP / "output" / "final_video.mp4"))
    ap.add_argument("--goose", default=str(DEFAULT_GOOSE))
    ap.add_argument("--out", default=str(VP / "output" / "final_video_goose.mp4"))
    ap.add_argument("--size", type=int, default=400, help="диаметр круга, px")
    ap.add_argument("--crop", type=int, default=720, help="сторона квадратного кропа гуся")
    ap.add_argument("--crop-x", type=int, default=240, help="смещение кропа по X в исходнике")
    ap.add_argument("--crop-y", type=int, default=0, help="смещение кропа по Y в исходнике")
    ap.add_argument("--pos", default="top-right", choices=sorted(POS_PRESETS),
                    help="где живёт гусь (top-right — верх справа, вне рейла и заголовка)")
    ap.add_argument("--x", type=int, default=None, help="явный X (перебивает --pos)")
    ap.add_argument("--y", type=int, default=None, help="явный Y (перебивает --pos)")
    ap.add_argument("--ring", type=int, default=8, help="толщина белого кольца, px (0 = без кольца)")
    ap.add_argument("--ring-dark", type=int, default=3, help="тёмная окантовка снаружи, px")
    ap.add_argument("--hflip", action="store_true", help="отразить гуся по горизонтали")
    ap.add_argument("--goose-audio", type=float, default=0.0,
                    help="громкость гуся 0..1 (0 = гусь молчит, голос диктора главный)")
    ap.add_argument("--preview-sec", type=float, default=0.0, help=">0 — только первые N секунд")
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--bitrate", default="12M")
    a = ap.parse_args()

    video, goose = Path(a.video), Path(a.goose)
    for p in (video, goose):
        if not p.exists():
            print(f"[ERROR] не найдено: {p}")
            return 1

    ASSETS.mkdir(parents=True, exist_ok=True)
    mask_png = ASSETS / f"mask_{a.size}.png"
    ring_png = ASSETS / f"ring_{a.size}_{a.ring}_{a.ring_dark}.png"
    if not mask_png.exists():
        make_mask(a.size, mask_png)
        print(f"[OK] маска: {mask_png}")
    use_ring = a.ring > 0
    if use_ring and not ring_png.exists():
        make_ring(a.size, a.ring, a.ring_dark, ring_png)
        print(f"[OK] кольцо: {ring_png}")

    x, y = POS_PRESETS[a.pos](a.size)
    if a.x is not None:
        x = a.x
    if a.y is not None:
        y = a.y
    ring_off = (a.ring + a.ring_dark) if use_ring else 0

    # --- входы ---
    cmd = ["ffmpeg", "-y", "-i", str(video),
           "-stream_loop", "-1", "-i", str(goose),
           "-framerate", str(FPS), "-loop", "1", "-i", str(mask_png)]
    if use_ring:
        cmd += ["-framerate", str(FPS), "-loop", "1", "-i", str(ring_png)]

    # --- фильтры ---
    pre = (f"crop={a.crop}:{a.crop}:{a.crop_x}:{a.crop_y},"
           f"scale={a.size}:{a.size}:flags=lanczos,fps={FPS}")
    if a.hflip:
        pre += ",hflip"
    parts = [
        f"[1:v]{pre},format=rgba[g0]",
        "[g0][2:v]alphamerge[gs]",
        f"[0:v][gs]overlay={x}:{y}:eof_action=pass[v1]",
    ]
    vout = "[v1]"
    if use_ring:
        parts.append(f"[v1][3:v]overlay={x - ring_off}:{y - ring_off}:eof_action=pass[v2]")
        vout = "[v2]"
    parts.append(f"{vout}null[vout]")

    cmd += ["-filter_complex", ";".join(parts), "-map", "[vout]"]

    # --- звук ---
    if a.goose_audio > 0:
        fc = cmd[cmd.index("-filter_complex") + 1]
        fc += (f";[1:a]volume={a.goose_audio},afade=t=in:d=0.3[ga];"
               f"[0:a][ga]amix=inputs=2:duration=first:normalize=0[aout]")
        cmd[cmd.index("-filter_complex") + 1] = fc
        cmd += ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-map", "0:a", "-c:a", "copy"]

    total = a.preview_sec if a.preview_sec > 0 else duration(video)
    cmd += ["-t", f"{total:.3f}"]
    cmd += ["-c:v", "libx264", "-crf", str(a.crf), "-b:v", a.bitrate,
            "-pix_fmt", "yuv420p", "-r", str(FPS), str(a.out)]

    print(f"[GOOSE] {goose.name} → круг {a.size}px, кольцо={a.ring}/{a.ring_dark}, "
          f"позиция {a.pos} ({x},{y}), зациклен на {duration(video):.1f} c, "
          f"звук гуся={'выкл' if a.goose_audio <= 0 else a.goose_audio}")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print("[ERROR] FFmpeg:")
        print((r.stderr or "")[-3000:])
        return 1
    print(f"[OK] Готово: {a.out}")
    # Маркер успеха: originality_check честно считает гуся отдельным визуальным
    # элементом ТОЛЬКО когда оверлей реально вписан (маркер пишется на успехе и
    # стирается в начале каждого прогона конвейера — чтобы не врать про прошлый ролик).
    marker = VP / "output" / "goose_overlay.json"
    try:
        marker.write_text(json.dumps(
            {"video": str(Path(a.out).resolve()), "pos": a.pos, "size": a.size,
             "ring": a.ring, "loop": True, "goose_audio": a.goose_audio,
             "written_at": time.strftime("%Y-%m-%d %H:%M:%S")},
            ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        print(f"[WARN] маркер гуся не записан: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
