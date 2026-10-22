# -*- coding: utf-8 -*-
"""Фаза 1: поиск футажа (без скачивания).
Источники: Wikimedia Commons (видео+фото), NASA (видео+фото), Openverse (фото).
Результат: search_results.json + читаемый отчёт search_report.txt
"""
import json, os, re, time, urllib.parse
import requests

P = r"D:\AI\VIDEO_PIPELINE\longform"
OUT = os.path.join(P, "media")
os.makedirs(OUT, exist_ok=True)
UA = "VideoPipelineLongform/1.0 (educational news digest; contact: local)"
S = requests.Session()
S.headers.update({"User-Agent": UA})

blocks = json.load(open(os.path.join(P, "blocks.json"), encoding="utf-8"))["blocks"]
res = {}

def get(url, params=None, tries=3, timeout=30):
    for i in range(tries):
        try:
            r = S.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 503):
                time.sleep(2 + 2 * i)
                continue
            return None
        except Exception:
            time.sleep(1.5 * (i + 1))
    return None

def wiki_search(kw, kind, limit=8):
    """kind: 'video' | 'image'"""
    ft = "filetype:video" if kind == "video" else "filetype:bitmap"
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"{ft} {kw}", "gsrnamespace": "6", "gsrlimit": str(limit),
        "prop": "videoinfo" if kind == "video" else "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
        "viprop": "url|size|mime|derivatives|extmetadata",
    }
    d = get("https://commons.wikimedia.org/w/api.php", params)
    if not d or "query" not in d:
        return []
    out = []
    for pid, page in d["query"].get("pages", {}).items():
        info = (page.get("videoinfo") or page.get("imageinfo") or [{}])[0]
        mime = info.get("mime", "")
        if kind == "video" and not mime.startswith("video/"):
            continue
        if kind == "image" and mime not in ("image/jpeg", "image/png"):
            continue
        url = info.get("url")
        w, h = info.get("width", 0), info.get("height", 0)
        size = info.get("size", 0)
        dur = info.get("duration", 0) or 0
        transcode = None
        best_w = -1
        for dv in (info.get("derivatives") or []):
            dw = dv.get("width") or 0
            if 600 <= dw <= 1280 and dw > best_w and dv.get("type", "").startswith("video/"):
                best_w, transcode = dw, dv.get("src")
        lic = ""
        em = info.get("extmetadata") or {}
        if "LicenseShortName" in em:
            lic = re.sub("<[^>]+>", "", str(em["LicenseShortName"].get("value", "")))
        out.append({"source": "wikimedia", "kind": kind, "title": page.get("title", ""),
                    "url": transcode or url, "orig_url": url, "width": w, "height": h,
                    "size_mb": round(size / 1048576, 1), "dur": round(float(dur), 1),
                    "license": lic, "page": "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(page.get("title", ""))})
    return out

def nasa_search(kw, kind, limit=6):
    d = get("https://images-api.nasa.gov/search", {"q": kw, "media_type": kind, "page_size": limit})
    if not d:
        return []
    out = []
    for it in d.get("collection", {}).get("items", [])[:limit]:
        data = (it.get("data") or [{}])[0]
        href = it.get("href")
        if not href:
            continue
        man = get(href)
        if not man:
            continue
        url = None
        if kind == "video":
            for f in man:
                if f.endswith("~small.mp4") or f.endswith("~mobile.mp4"):
                    url = f
                    break
            if not url:
                for f in man:
                    if f.endswith(".mp4"):
                        url = f
                        break
        else:
            for f in man:
                if f.endswith("~medium.jpg") or f.endswith("~orig.jpg") or f.endswith(".jpg"):
                    url = f
                    break
        if not url:
            continue
        out.append({"source": "nasa", "kind": kind, "title": data.get("title", ""),
                    "url": url, "orig_url": url, "width": 0, "height": 0, "size_mb": 0,
                    "dur": 0, "license": "NASA (public domain)", "page": "https://images.nasa.gov/",
                    "nasa_id": data.get("nasa_id", "")})
    return out

def openverse_search(kw, limit=8):
    d = get("https://api.openverse.org/v1/images/", {"q": kw, "page_size": limit})
    if not d:
        return []
    out = []
    for it in d.get("results", [])[:limit]:
        w, h = it.get("width") or 0, it.get("height") or 0
        if w < 1600:
            continue
        out.append({"source": "openverse", "kind": "image", "title": it.get("title") or "",
                    "url": it.get("url"), "orig_url": it.get("url"), "width": w, "height": h,
                    "size_mb": 0, "dur": 0, "license": f"{it.get('license','')} {it.get('license_version','')}".strip(),
                    "page": it.get("foreign_landing_url") or ""})
    return out

for b in blocks:
    bid = b["id"]
    res[bid] = {}
    for kw in b["keywords"]:
        cands = []
        if bid == "space":
            cands += nasa_search(kw, "video", 5)
            cands += nasa_search(kw, "image", 3)
        cands += wiki_search(kw, "video", 6)
        cands += wiki_search(kw, "image", 6)
        if bid in ("economy", "society", "final", "science", "intro", "tech"):
            cands += openverse_search(kw, 6)
        # дедуп по url
        seen, uniq = set(), []
        for c in cands:
            if not c.get("url") or c["url"] in seen:
                continue
            seen.add(c["url"])
            uniq.append(c)
        res[bid][kw] = uniq
        print(f"{bid:9s} | {kw:45s} -> {len(uniq)}", flush=True)
        time.sleep(0.35)

json.dump(res, open(os.path.join(P, "search_results.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# отчёт
lines = []
for bid, kws in res.items():
    lines.append(f"\n########## {bid} ##########")
    for kw, cands in kws.items():
        lines.append(f"\n=== {kw} ({len(cands)}) ===")
        for c in sorted(cands, key=lambda x: (x["kind"] != "video")):
            lines.append(f"  [{c['source']:9s} {c['kind']:5s}] {c['width']}x{c['height']} "
                         f"{c['size_mb']}MB d={c['dur']}s | {c['title'][:95]}")
            lines.append(f"      {c['url'][:150]}")
open(os.path.join(P, "search_report.txt"), "w", encoding="utf-8-sig").write("\n".join(lines))
print("\nOK -> search_results.json, search_report.txt")
