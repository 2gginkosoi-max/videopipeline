# -*- coding: utf-8 -*-
"""Фаза 0: вытащить реальные медиа со страниц новостей (og:image, <img>, <video>, iframe).
Результат: page_media.json + скачанные картинки в media/page/<story>/
"""
import json, os, re, time
import requests
from urllib.parse import urljoin, urlparse

P = r"D:\AI\VIDEO_PIPELINE\longform"
OUT = os.path.join(P, "media", "page")
os.makedirs(OUT, exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Language": "ru,en;q=0.8"})

STORIES = {
    "tech_muse":      "https://nplus1.ru/news/2026/10/13/muse-wonder",
    "tech_gemini":    "https://habr.com/ru/companies/gptunnel/news/1094038/",
    "tech_openai":    "https://habr.com/ru/news/1094118/",
    "bee_sting":      "https://naked-science.ru/article/biology/zasnyali-zhalo-pchely",
    "space_sun":      "https://naked-science.ru/article/astronomy/destabilizatsiyu-solnechnoi-sistemy",
    "space_dark":     "https://naked-science.ru/article/astronomy/tm-v-mp",
    "caviar":         "https://www.kommersant.ru/doc/9025958",
    "caviar_lenta":   "https://lenta.ru/news/2026/10/14/rossiyane-stali-massovo-perehodit-na-bolee-deshevuyu-ikru/",
    "portion":        "https://www.kommersant.ru/doc/9025943",
    "escooter":       "https://www.kommersant.ru/doc/9025967",
    "wildlife":       "https://nplus1.ru/material/2026/10/14/wildlife-photographer-of-the-year-2026",
    "puppy":          "https://lenta.ru/news/2026/10/14/desyatimesyachnyy-schenok-spas-hozyaev-ot-dikogo-hischnika/",
    "sleep":          "https://nplus1.ru/news/2026/10/14/frequent-and-unintentional",
}

def meta(html, prop):
    for pat in (rf'<meta[^>]+(?:property|name)=["\']{prop}["\'][^>]*>',):
        m = re.search(pat, html, re.I)
        if m:
            c = re.search(r'content=["\']([^"\']+)["\']', m.group(0), re.I)
            if c:
                return c.group(1)
    return None

res = {}
for key, url in STORIES.items():
    try:
        r = S.get(url, timeout=30)
        html = r.text
    except Exception as ex:
        res[key] = {"url": url, "error": str(ex)}
        print(f"{key:14s} ERR {ex}")
        continue
    imgs = []
    for p in ("og:image", "og:image:secure_url", "twitter:image"):
        v = meta(html, p)
        if v:
            imgs.append(v)
    # <img src / data-src / srcset>
    for m in re.finditer(r'<img[^>]+>', html, re.I):
        tag = m.group(0)
        cand = None
        for attr in ("data-src", "data-original", "data-lazy-src", "src"):
            a = re.search(rf'{attr}=["\']([^"\']+)["\']', tag, re.I)
            if a and a.group(1) and not a.group(1).startswith("data:"):
                cand = a.group(1)
                break
        if not cand:
            ss = re.search(r'srcset=["\']([^"\']+)["\']', tag, re.I)
            if ss:
                cand = ss.group(1).split(",")[-1].strip().split(" ")[0]
        if cand:
            imgs.append(cand)
    # video
    videos = []
    for m in re.finditer(r'<(?:video|source)[^>]+src=["\']([^"\']+)["\']', html, re.I):
        videos.append(m.group(1))
    for m in re.finditer(r'(?:youtube(?:-nocookie)?\.com/embed/|youtu\.be/|rutube\.ru/video/|vk\.com/video_ext\.php\?oid=[^&]+&id=)([A-Za-z0-9_\-]+)', html, re.I):
        videos.append(m.group(0))
    imgs = [urljoin(url, u) for u in imgs]
    imgs = [u for u in dict.fromkeys(imgs) if re.search(r"\.(jpe?g|png|webp)(\?|$)", u, re.I)]
    res[key] = {"url": url, "imgs": imgs[:40], "videos": list(dict.fromkeys(videos))[:10]}
    print(f"{key:14s} imgs={len(imgs)} videos={len(res[key]['videos'])}")
    time.sleep(0.4)

json.dump(res, open(os.path.join(P, "page_media.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# скачать og:image + первые крупные картинки
def download(u, path):
    try:
        r = S.get(u, timeout=40, stream=True)
        if r.status_code != 200:
            return None
        data = r.content
        if len(data) < 30000:
            return None
        open(path, "wb").write(data)
        return len(data)
    except Exception:
        return None

dl = {}
for key, d in res.items():
    if "imgs" not in d:
        continue
    os.makedirs(os.path.join(OUT, key), exist_ok=True)
    dl[key] = []
    for i, u in enumerate(d["imgs"][:12]):
        ext = ".jpg"
        m = re.search(r"\.(jpe?g|png|webp)", u, re.I)
        if m:
            ext = "." + m.group(1).lower().replace("jpeg", "jpg")
        fn = os.path.join(OUT, key, f"p{i:02d}{ext}")
        n = download(u, fn)
        if n:
            dl[key].append({"file": fn, "url": u, "bytes": n})
    print(f"{key:14s} downloaded {len(dl[key])}")
json.dump(dl, open(os.path.join(P, "page_media_downloaded.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("OK")
