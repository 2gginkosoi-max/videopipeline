# -*- coding: utf-8 -*-
"""vertical.py — вертикальная композиция 9:16 и поиск вебки в кадре.

Раскладка клипа:
    • фон 1080×1920 — кадр, растянутый «по заполнению» и размытый;
    • основное видео — по центру, с сохранением пропорций;
    • вебка (если найдена) — сверху или снизу, с тонкой рамкой.

Вебка ищется по лицам: OpenCV Haar на нескольких кадрах, затем выбирается
устойчивая область у края кадра. Если OpenCV нет или лиц не нашли — просто
вертикальная композиция без вебки.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

OUT_W, OUT_H = 1080, 1920
CAM_RATIO = 0.34          # ширина вебки в долях ширины кадра
MAIN_MAX_H = 1500         # максимум высоты основного видео (оставляем место вебке)
CAM_MARGIN = 90           # отступ вебки от верха/низа
SAMPLE_W = 640            # ширина кадров для анализа


def _even(value: float) -> int:
    return max(2, int(round(value / 2.0)) * 2)


def probe_size(ffprobe: str, path: Path) -> tuple:
    """-> (width, height) первого видеопотока."""
    p = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        w, h = (p.stdout or "").strip().splitlines()[0].split("x")[:2]
        return int(w), int(h)
    except (ValueError, IndexError):
        return 0, 0


def _clamp_rect(x: float, y: float, w: float, h: float,
                src_w: int, src_h: int) -> tuple:
    """Прямоугольник внутри кадра, края выровнены по чётным пикселям."""
    w = min(w, src_w)
    h = min(h, src_h)
    x = max(0.0, min(x, src_w - w))
    y = max(0.0, min(y, src_h - h))
    x2, y2 = _even(x), _even(y)
    w2, h2 = _even(w), _even(h)
    if x2 + w2 > src_w:
        x2 = _even(src_w - w2)
    if y2 + h2 > src_h:
        y2 = _even(src_h - h2)
    return int(x2), int(y2), int(w2), int(h2)


def _cluster_key(cx: float, cy: float) -> tuple:
    return int(round(cx * 12)), int(round(cy * 12))

def detect_webcam(path: Path, duration: float, ffmpeg: str, ffprobe: str,
                  samples: int = 12):
    """Найти область вебки. -> dict(x, y, w, h, corner, score) или None.

    Логика: берём несколько кадров, ищем лица. Вебка встраивается в угол,
    поэтому учитываем только лица вне центральной зоны. Область считается
    вебкой, если похожее лицо найдено минимум в трети кадров.
    """
    try:
        import cv2  # type: ignore
    except Exception:  # noqa: BLE001
        return None

    src_w, src_h = probe_size(ffprobe, path)
    if duration <= 0 or src_w <= 0 or src_h <= 0:
        return None

    cascade_file = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(str(cascade_file))
    if cascade.empty():
        return None

    step = max(1.0, duration / samples)
    with tempfile.TemporaryDirectory(prefix="cam_") as tmp:
        pattern = str(Path(tmp) / "f_%03d.png")
        cmd = [ffmpeg, "-v", "error", "-i", str(path),
               "-vf", f"fps=1/{step:.3f},scale={SAMPLE_W}:-2",
               "-frames:v", str(samples), pattern]
        subprocess.run(cmd, capture_output=True)

        groups: dict = {}
        for frame in sorted(Path(tmp).glob("f_*.png")):
            img = cv2.imread(str(frame))
            if img is None:
                continue
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            gray = cv2.equalizeHist(gray)   # помогает на низком битрейте
            faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6,
                                             minSize=(20, 20))
            fh, fw = gray.shape[:2]
            for (fx, fy, bw, bh) in faces:
                nx, ny = fx / fw, fy / fh
                nw, nh = bw / fw, bh / fh
                # лицо в вебке небольшое: 2–20% ширины кадра и <=10% площади.
                # Крупные лица — это уже контент видео, а не вебка.
                if not (0.02 <= nw <= 0.20 and nw * nh <= 0.10):
                    continue
                cx, cy = nx + nw / 2, ny + nh / 2
                # вебка живёт у края, а не в центре кадра
                if 0.30 < cx < 0.70 and 0.30 < cy < 0.70:
                    continue
                item = groups.setdefault(_cluster_key(cx, cy), {"count": 0, "boxes": []})
                item["count"] += 1
                item["boxes"].append((nx, ny, nw, nh))

        if not groups:
            return None

        _, best = max(groups.items(), key=lambda kv: kv[1]["count"])
        if best["count"] < max(3, int(samples * 0.55)):
            return None

        boxes = best["boxes"]
        nx = sum(b[0] for b in boxes) / len(boxes)
        ny = sum(b[1] for b in boxes) / len(boxes)
        nw = sum(b[2] for b in boxes) / len(boxes)
        nh = sum(b[3] for b in boxes) / len(boxes)

        # расширяем лицо до квадратной области вебки
        side = max(nw * 2.4, nh * 2.4, 0.20)
        cx, cy = nx + nw / 2, ny + nh / 2
        x, y = (cx - side / 2) * src_w, (cy - side / 2) * src_h
        w, h = side * src_w, side * src_h
        if w * h > 0.45 * src_w * src_h:
            return None

        x, y, w, h = _clamp_rect(x, y, w, h, src_w, src_h)
        corner = ("top" if cy < 0.5 else "bottom") + "-" + ("left" if cx < 0.5 else "right")
        return {"x": x, "y": y, "w": w, "h": h, "corner": corner,
                "score": best["count"]}

def build_filter(src_w: int, src_h: int, cam: dict | None,
                 cam_pos: str = "auto", subs_name: str | None = None,
                 fonts_dir: str | None = None) -> tuple:
    """Собрать filter_complex для клипа 1080×1920.

    -> (filter_complex, output_label)
    subs_name — имя ASS-файла рядом с выходным клипом (или None).
    """
    if src_w <= 0 or src_h <= 0:
        src_w, src_h = OUT_W, OUT_H

    scale = min(OUT_W / src_w, MAIN_MAX_H / src_h)
    main_w, main_h = _even(src_w * scale), _even(src_h * scale)

    parts = ["[0:v]split=3[bg0][mn0][cam0]" if cam else "[0:v]split=2[bg0][mn0]"]

    # фон: маленький кадр -> размытие -> апскейл (дешево и мягко)
    parts.append("[bg0]scale=540:960:force_original_aspect_ratio=increase,"
                 "crop=540:960,boxblur=12:2,scale=1080:1920,setsar=1[bg]")

    # основное видео
    parts.append(f"[mn0]scale={main_w}:{main_h},setsar=1[mn1]")
    if cam:
        # в основном кадре вебку замазываем, чтобы не дублировалась
        px, py = _even(cam["x"] * scale), _even(cam["y"] * scale)
        pw, ph = _even(cam["w"] * scale), _even(cam["h"] * scale)
        parts.append("[mn1]split=2[m1][m2]")
        parts.append(f"[m2]crop={pw}:{ph}:{px}:{py},boxblur=24:2[pt]")
        parts.append(f"[m1][pt]overlay={px}:{py}[mn]")
    else:
        parts.append("[mn1]null[mn]")

    parts.append("[bg][mn]overlay=(W-w)/2:(H-h)/2[base]")

    out_label = "base"
    if cam:
        cam_w = _even(OUT_W * CAM_RATIO)
        cam_h = cam_w  # квадратная вебка аккуратно смотрится в Shorts
        cam_y = CAM_MARGIN if cam_pos == "top" else OUT_H - cam_h - CAM_MARGIN
        parts.append(f"[cam0]crop={cam['w']}:{cam['h']}:{cam['x']}:{cam['y']},"
                     f"scale={cam_w}:{cam_h},setsar=1,"
                     f"pad=iw+6:ih+6:3:3:color=white@0.55[cam]")
        parts.append(f"[base][cam]overlay=(W-w)/2:{cam_y}[comp]")
        out_label = "comp"

    if subs_name:
        fonts = f":fontsdir='{fonts_dir}'" if fonts_dir else ""
        parts.append(f"[{out_label}]ass={subs_name}{fonts}[vout]")
        out_label = "vout"

    return ";".join(parts), out_label


def main_video_height(src_w: int, src_h: int) -> int:
    scale = min(OUT_W / max(1, src_w), MAIN_MAX_H / max(1, src_h))
    return _even(src_h * scale)


def cam_position(cam: dict | None, requested: str) -> str:
    """auto -> та же сторона, где вебка была в исходнике."""
    req = (requested or "auto").strip().lower()
    if req in ("top", "bottom"):
        return req
    if not cam:
        return "bottom"
    return "top" if cam["corner"].startswith("top") else "bottom"
