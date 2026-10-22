#!/usr/bin/env python3
"""
photo_processor.py — обработка фото: размытый фон + статичное фото по центру
БЕЗ Кена Бёрнса (никакого зума, никакого сдвига).
"""

import sys
import subprocess
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_WIDTH = 1080
DEFAULT_HEIGHT = 1920
DEFAULT_FPS = 30


def process_photo(input_path: str, output_path: str, duration: float = 3.0,
                  width: int = DEFAULT_WIDTH, height: int = DEFAULT_HEIGHT,
                  fps: int = DEFAULT_FPS) -> bool:
    """Обработка фото: размытый фон + статичное фото по центру"""
    
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    # Формула: размытый фон + оригинальное фото по центру (БЕЗ зума)
    filter_complex = (
        # Фон: увеличиваем, обрезаем, размываем boxblur=30, затемняем
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        f"boxblur=30:30,"
        f"eq=brightness=-0.1[bg];"
        # Передний план: вписываем в 1080x1920 с сохранением пропорций
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease[fg];"
        # Накладываем передний план по центру поверх размытого фона
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2"
    )
    
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", input_path,
        "-filter_complex", filter_complex,
        "-t", str(duration),
        "-c:v", "libx264",
        "-crf", "18",
        "-preset", "slow",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        output_path
    ]
    
    print(f"[PHOTO] Обработка: {input_path}")
    print(f"   Выход: {output_path}")
    print(f"   Длительность: {duration} сек")
    print(f"   Размытие фона: boxblur=30, затемнение: -0.1")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode == 0:
            print(f"[OK] Обработано: {output_path}")
            return True
        else:
            print(f"[ERROR] Ошибка FFmpeg:")
            print(result.stderr[-2000:])
            return False
    except Exception as e:
        print(f"[ERROR] {e}")
        return False


if __name__ == "__main__":
    # Тестовая обработка
    input_photo = r"D:\AI\F5-TTS\assets\mud_wizard.jpg"
    output_dir = r"D:\AI\VIDEO_PIPELINE\output\processed_photos"
    
    if Path(input_photo).exists():
        process_photo(input_photo, str(Path(output_dir) / "photo_00.mp4"), duration=3.0)
    else:
        print(f"[ERROR] Фото не найдено: {input_photo}")
