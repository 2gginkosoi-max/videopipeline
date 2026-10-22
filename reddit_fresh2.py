#!/usr/bin/env python3
"""Догрузка RSS Reddit с большими задержками против 429."""
import sys, time, re, json, urllib.request
import xml.etree.ElementTree as ET

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
NS = {"a": "http://www.w3.org/2005/Atom"}

SUBS = ["funny", "BeAmazed", "Damnthatsinteresting", "PublicFreakout", "ThatsInsane", "nextfuckinglevel"]

def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/rss+xml,application/xml,text/xml,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")

def parse_feed(sub):
    url = f"https://www.reddit.com/r/{sub}/hot/.rss"
    root = ET.fromstring(fetch(url))
    out = []
    for entry in root.findall("a:entry", NS):
        title = (entry.findtext("a:title", default="", namespaces=NS) or "").strip()
        link_el = entry.find("a:link", NS)
        link = link_el.get("href") if link_el is not None else ""
        content = entry.findtext("a:content", default="", namespaces=NS) or ""
        updated = entry.findtext("a:updated", default="", namespaces=NS) or ""
        vids = re.findall(r'https://v\.redd\.it/[^\s"\'<>]+', content)
        imgs = re.findall(r'https://i\.redd\.it/[^\s"\'<>]+', content)
        out.append({"sub": sub, "title": title, "link": link, "updated": updated,
                    "images": imgs, "videos": vids})
    return out

all_posts = []
for i, sub in enumerate(SUBS):
    for attempt in range(3):
        try:
            posts = parse_feed(sub)
            nv = sum(1 for p in posts if p["videos"])
            print(f"[OK] r/{sub}: {len(posts)} ({nv} video)")
            all_posts.extend(posts)
            break
        except Exception as e:
            print(f"[FAIL] r/{sub} try{attempt+1}: {e}")
            time.sleep(20)
    time.sleep(12)

path = r"D:\AI\VIDEO_PIPELINE\output\reddit_fresh2.json"
with open(path, "w", encoding="utf-8") as f:
    json.dump(all_posts, f, ensure_ascii=False, indent=2)
print(f"\n[OK] {path} ({len(all_posts)} постов)")

print("\n===== С ВИДЕО =====")
for p in all_posts:
    if p["videos"]:
        print(f"\n[{p['sub']}] {p['title']}")
        print(f"   {p['updated']}")
        print(f"   {p['link']}")
        print(f"   {p['videos'][0]}")
