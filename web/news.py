# -*- coding: utf-8 -*-
"""news.py — поиск свежих новостей в Reddit + скачивание b-roll.

Использует RSS Reddit (без авторизации, без API-ключа) — тот же механизм,
что в reddit_fresh.py, но в виде пригодных для веба функций.
"""

import html
import re
import subprocess
import sys
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

VP = Path(r"D:\AI\VIDEO_PIPELINE")
PY = r"D:\AI\python310\python.exe"
REDDIT_DL = VP / "reddit_dl.py"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
NS = {"a": "http://www.w3.org/2005/Atom"}

# Reddit жёстко режет частоту запросов: анонимный клиент получает 429 уже
# при ~1 запросе в 10 секунд. Поэтому ходим строго последовательно с паузой.
REQUEST_DELAY = 12.0
CACHE_TTL = 900.0          # 15 минут
MAX_SUBS_PER_SEARCH = 3

_lock = threading.Lock()
_cache: dict = {}          # (sub, mode) -> (ts, posts)


def _throttle() -> None:
    """Глобальная пауза между запросами к Reddit (общий для всех потоков)."""
    with _lock:
        last = getattr(_throttle, "_last", 0.0)
        wait = REQUEST_DELAY - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
        _throttle._last = time.time()


def _fetch(url: str, timeout: int = 25, retries: int = 3) -> str:
    last_err = None
    for attempt in range(retries):
        _throttle()
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "application/rss+xml,application/xml,text/xml,*/*",
            "Accept-Language": "en-US,en;q=0.9",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            code = getattr(exc, "code", None)
            if code == 429:
                # пауза растёт: 15с -> 30с -> 45с
                time.sleep(REQUEST_DELAY * (1 + attempt))
            else:
                break
    raise last_err if last_err else RuntimeError("unknown fetch error")

# Сабреддиты с вирусными «новостями» — там ровно тот формат, который идёт в шортс.
SUBS = [
    {"key": "nextfuckinglevel", "name": "NextFuckingLevel", "lang": "en"},
    {"key": "Damnthatsinteresting", "name": "Damnthatsinteresting", "lang": "en"},
    {"key": "interestingasfuck", "name": "InterestingAsFuck", "lang": "en"},
    {"key": "ThatsInsane", "name": "ThatsInsane", "lang": "en"},
    {"key": "mildlyinteresting", "name": "MildlyInteresting", "lang": "en"},
    {"key": "PublicFreakout", "name": "PublicFreakout", "lang": "en"},
    {"key": "BeAmazed", "name": "BeAmazed", "lang": "en"},
    {"key": "oddlysatisfying", "name": "OddlySatisfying", "lang": "en"},
]
SUBS_BY_KEY = {s["key"]: s for s in SUBS}

MODES = {"hot": "hot", "new": "new", "top": "top"}


def _strip_html(raw: str) -> str:
    raw = re.sub(r"<!--.*?-->", " ", raw, flags=re.S)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    raw = re.sub(r"\s+", " ", raw)
    return raw.strip()


def parse_feed(sub: str, mode: str = "hot") -> list:
    """Разобрать RSS сабреддита -> список постов с медиа."""
    key = (sub, mode)
    cached = _cache.get(key)
    if cached and time.time() - cached[0] < CACHE_TTL:
        return cached[1]

    url = f"https://www.reddit.com/r/{sub}/{mode}/.rss"
    try:
        xml = _fetch(url)
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] r/{sub}: {exc}")
        if cached:
            return cached[1]
        return []

    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []

    out = []
    for entry in root.findall("a:entry", NS):
        title = (entry.findtext("a:title", default="", namespaces=NS) or "").strip()
        link_el = entry.find("a:link", NS)
        link = link_el.get("href") if link_el is not None else ""
        content = entry.findtext("a:content", default="", namespaces=NS) or ""
        updated = entry.findtext("a:updated", default="", namespaces=NS) or ""

        vids = re.findall(r"https://v\.redd\.it/[A-Za-z0-9]+", content)
        imgs = re.findall(r"https://i\.redd\.it/[^\s\"'<>]+", content)
        thumbs = re.findall(r"https://[ab]\.thumbs\.redditmedia\.com/[^\s\"'<>]+", content)

        author_el = entry.find("a:author/a:name", NS)
        author = (author_el.text or "").strip() if author_el is not None else ""

        # первый абзац поста — контекст для сценария
        body = _strip_html(content)
        body = re.sub(r"^submitted by\s+\S+\s*", "", body, flags=re.I)

        out.append({
            "sub": sub,
            "title": title,
            "link": link,
            "updated": updated,
            "author": author,
            "video_url": vids[0] if vids else "",
            "image_url": imgs[0] if imgs else "",
            "thumb": thumbs[0] if thumbs else "",
            "has_video": bool(vids),
            "context": body[:700],
        })
    _cache[key] = (time.time(), out)
    return out


def search(subs: list | None = None, mode: str = "hot", only_video: bool = True,
           on_progress=None) -> list:
    """Собрать посты из нескольких сабреддитов последовательно (без 429)."""
    subs = subs or [s["key"] for s in SUBS]
    mode = mode if mode in MODES else "hot"
    subs = subs[:MAX_SUBS_PER_SEARCH]

    results = []
    for i, sub in enumerate(subs):
        if on_progress:
            try:
                on_progress(f" reddit r/{sub}…", i + 1, len(subs))
            except Exception:  # noqa: BLE001
                pass
        results.extend(parse_feed(sub, mode))

    if only_video:
        results = [p for p in results if p["has_video"]]

    seen, unique = set(), []
    for p in results:
        if p["link"] in seen:
            continue
        seen.add(p["link"])
        unique.append(p)
    return unique


def download_broll(link_or_url: str, dest) -> bool:
    """Скачать видео поста Reddit (v.redd.it) через reddit_dl.py."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [PY, str(REDDIT_DL), "--url", link_or_url, "--out", str(dest)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=1800)
    ok = dest.exists() and dest.stat().st_size > 10000
    if not ok:
        tail = "\n".join((r.stdout or r.stderr or "").strip().splitlines()[-6:])
        print(f"[DL FAIL] {tail}")
    return ok


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    mode = sys.argv[1] if len(sys.argv) > 1 else "hot"
    posts = search(mode=mode)
    print(f"Найдено постов с видео: {len(posts)}")
    for p in posts[:15]:
        print(f"[{p['sub']}] {p['title'][:80]}")
        print(f"    {p['video_url']}")
