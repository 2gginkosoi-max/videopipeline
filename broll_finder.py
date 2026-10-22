#!/usr/bin/env python3
"""
broll_finder.py — поиск и скачивание B-roll с Pixabay, Mixkit, Videvo
Приоритет: Reddit -> Pixabay -> Mixkit -> Videvo
"""

import sys
import os
import json
import requests
from pathlib import Path
from typing import List, Dict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUTPUT_DIR = Path(r"D:\AI\VIDEO_PIPELINE\output\broll")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Ключ Pixabay (можно получить бесплатно на pixabay.com)
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "")


def search_pixabay_videos(query: str, max_results: int = 5) -> List[Dict]:
    """Поиск видео на Pixabay"""
    if not PIXABAY_API_KEY:
        print(f"[SKIP] Pixabay API ключ не найден")
        return []
    
    url = "https://pixabay.com/api/videos/"
    params = {
        "key": PIXABAY_API_KEY,
        "q": query,
        "per_page": max_results,
        "video_type": "all",
        "order": "popular",
    }
    
    try:
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            videos = []
            for hit in data.get("hits", []):
                videos.append({
                    "type": "video",
                    "url": hit["videos"]["large"]["url"] if "large" in hit.get("videos", {}) else hit["videos"]["medium"]["url"],
                    "duration": hit.get("duration", 0),
                    "tags": hit.get("tags", ""),
                    "source": "pixabay",
                })
            print(f"[OK] Pixabay: {len(videos)} видео по запросу '{query}'")
            return videos
        else:
            print(f"[ERROR] Pixabay: HTTP {resp.status_code}")
            return []
    except Exception as e:
        print(f"[ERROR] Pixabay: {e}")
        return []


def search_pixabay_photos(query: str, max_results: int = 5) -> List[Dict]:
    """Поиск фото на Pixabay"""
    if not PIXABAY_API_KEY:
        return []
    
    url = "https://pixabay.com/api/"
    params = {
        "key": PIXABAY_API_KEY,
        "q": query,
        "per_page": max_results,
        "image_type": "all",
        "order": "popular",
    }
    
    try:
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            photos = []
            for hit in data.get("hits", []):
                photos.append({
                    "type": "photo",
                    "url": hit["largeImageURL"],
                    "tags": hit.get("tags", ""),
                    "source": "pixabay",
                })
            print(f"[OK] Pixabay: {len(photos)} фото по запросу '{query}'")
            return photos
        else:
            print(f"[ERROR] Pixabay: HTTP {resp.status_code}")
            return []
    except Exception as e:
        print(f"[ERROR] Pixabay: {e}")
        return []


def search_mixkit(query: str, max_results: int = 5) -> List[Dict]:
    """Поиск на Mixkit (без API, через веб-скрапинг)"""
    # Mixkit не имеет публичного API, но можно использовать поиск через веб-сайт
    # Пока возвращаем пустой список — нужен веб-скрапинг
    print(f"[INFO] Mixkit требует веб-скрапинг (не реализовано)")
    return []


def search_videvo(query: str, max_results: int = 5) -> List[Dict]:
    """Поиск на Videvo (без API)"""
    # Videvo также требует веб-скрапинг
    print(f"[INFO] Videvo требует веб-скрапинг (не реализовано)")
    return []


def download_file(url: str, output_path: str) -> bool:
    """Скачивание файла"""
    try:
        resp = requests.get(url, timeout=60, stream=True)
        if resp.status_code == 200:
            with open(output_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        else:
            print(f"[ERROR] HTTP {resp.status_code}: {url}")
            return False
    except Exception as e:
        print(f"[ERROR] {e}")
        return False


def find_broll(keywords: List[str], min_fragments: int = 7) -> List[Dict]:
    """Поиск B-roll по ключевым словам"""
    all_media = []
    
    for keyword in keywords:
        print(f"\n[SEARCH] Поиск по ключевому слову: {keyword}")
        
        # Pixabay
        videos = search_pixabay_videos(keyword, max_results=3)
        photos = search_pixabay_photos(keyword, max_results=3)
        all_media.extend(videos)
        all_media.extend(photos)
        
        # Mixkit/Videvo (заглушки)
        all_media.extend(search_mixkit(keyword, max_results=2))
        all_media.extend(search_videvo(keyword, max_results=2))
    
    # Сортируем: видео первыми
    all_media.sort(key=lambda x: (0 if x["type"] == "video" else 1, x.get("duration", 0)))
    
    print(f"\n[SUMMARY] Найдено {len(all_media)} медиафайлов")
    print(f"   Видео: {sum(1 for m in all_media if m['type'] == 'video')}")
    print(f"   Фото: {sum(1 for m in all_media if m['type'] == 'photo')}")
    
    return all_media


def download_broll(media_list: List[Dict], output_dir: Path) -> List[Path]:
    """Скачивание B-roll"""
    downloaded = []
    
    for i, media in enumerate(media_list):
        ext = "mp4" if media["type"] == "video" else "jpg"
        filename = f"broll_{i:02d}_{media['source']}.{ext}"
        output_path = output_dir / filename
        
        if output_path.exists():
            print(f"[SKIP] Уже существует: {filename}")
            downloaded.append(output_path)
            continue
        
        print(f"[DL] {media['url'][:60]}... -> {filename}")
        if download_file(media["url"], str(output_path)):
            downloaded.append(output_path)
        
        # Ограничиваем количество скачиваний
        if len(downloaded) >= 10:
            break
    
    return downloaded


if __name__ == "__main__":
    # Пример ключевых слов для новости о "грязевом волшебнике"
    keywords = ["mud wizard", "mud bath", "spa treatment", "alternative medicine", "germany france"]
    
    media = find_broll(keywords)
    
    if media:
        downloaded = download_broll(media, OUTPUT_DIR)
        print(f"\n[DONE] Скачано {len(downloaded)} файлов в {OUTPUT_DIR}")
    else:
        print("\n[WARN] B-roll не найден")
