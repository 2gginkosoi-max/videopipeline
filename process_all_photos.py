#!/usr/bin/env python3
"""
process_all_photos.py — обработка всех фото (размытый фон, без Кена Бёрнса)
"""

import sys
from pathlib import Path

sys.path.insert(0, r"D:\AI\VIDEO_PIPELINE")
from photo_processor import process_photo

photos_dir = Path(r"D:\AI\F5-TTS\assets")
processed_dir = Path(r"D:\AI\VIDEO_PIPELINE\output\processed_photos")
processed_dir.mkdir(parents=True, exist_ok=True)

photo_files = list(photos_dir.glob("*.jpg")) + list(photos_dir.glob("*.jpeg"))
print(f"Найдено фото: {len(photo_files)}")

for i, photo in enumerate(photo_files):
    output = processed_dir / f"photo_{i:02d}.mp4"
    if output.exists():
        print(f"Уже существует: {output.name}")
        continue
    
    print(f"\nОбработка: {photo.name}")
    process_photo(str(photo), str(output), duration=2.5)

processed_count = len(list(processed_dir.glob("*.mp4")))
print(f"\nГотово! Обработано: {processed_count} фото")
