#!/usr/bin/env python3
"""
reddit_fresh.py — тянет свежие посты через RSS Reddit (без авторизации),
выделяет те, у которых есть фото (i.redd.it) или видео (v.redd.it).
С задержками, чтобы не ловить 429.
"""
import sys
import time
import re
import json
import urllib.request
import xml.etree.ElementTree as ET

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

# Без новостной повестки, но «новость/событие» с видео: сортируем по hot
SUBS = [
    ("nextfuckinglevel", "hot"),
    ("Damnthatsinteresting", "hot"),
    ("interestingasfuck", "hot"),
    ("ThatsInsane", "hot"),
    ("mildlyinteresting", "hot"),
    ("PublicFreakout", "hot"),
]

NS = {"a": "http://www.w3.org/2005/Atom"}


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/rss+xml,application/xml,text/xml,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def parse_feed(sub: str, mode: str):
    url = f"https://www.reddit.com/r/{sub}/{mode}/.rss"
    xml = fetch(url)
    root = ET.fromstring(xml)
    out = []
    for entry in root.findall("a:entry", NS):
        title = (entry.findtext("a:title", default="", namespaces=NS) or "").strip()
        link_el = entry.find("a:link", NS)
        link = link_el.get("href") if link_el is not None else ""
        content = entry.findtext("a:content", default="", namespaces=NS) or ""
        updated = entry.findtext("a:updated", default="", namespaces=NS) or ""

        # ищем прямые медиа-ссылки
        imgs = re.findall(r'https://i\.redd\.it/[^\s"\'<>]+', content)
        vids = re.findall(r'https://v\.redd\.it/[^\s"\'<>]+', content)
        # превью/thumbnail
        thumbs = re.findall(r'https://[ab]\.thumbs\.redditmedia\.com/[^\s"\'<>]+', content)

        out.append({
            "sub": sub,
            "title": title,
            "link": link,
            "updated": updated,
            "images": imgs,
            "videos": vids,
            "thumb": thumbs[0] if thumbs else "",
        })
    return out


def main():
    all_posts = []
    for i, (sub, mode) in enumerate(SUBS):
        try:
            posts = parse_feed(sub, mode)
            n_vid = sum(1 for p in posts if p["videos"])
            n_img = sum(1 for p in posts if p["images"])
            print(f"[OK] r/{sub}: {len(posts)} постов ({n_vid} video, {n_img} img)")
            all_posts.extend(posts)
        except Exception as e:
            print(f"[FAIL] r/{sub}: {e}")
        if i < len(SUBS) - 1:
            time.sleep(6)  # пауза против 429

    # Только посты с медиа
    media = [p for p in all_posts if p["videos"] or p["images"]]
    print(f"\nВсего постов: {len(all_posts)}, с медиа: {len(media)}")

    out_path = r"D:\AI\VIDEO_PIPELINE\output\reddit_fresh.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_posts, f, ensure_ascii=False, indent=2)
    print(f"[OK] Сохранено: {out_path}")

    # Показываем только с видео (для футажа)
    print("\n===== ПОСТЫ С ВИДЕО =====")
    for p in media:
        if p["videos"]:
            print(f"\n[{p['sub']}] {p['title']}")
            print(f"   updated: {p['updated']}")
            print(f"   link:    {p['link']}")
            print(f"   video:   {p['videos'][0]}")


if __name__ == "__main__":
    main()
