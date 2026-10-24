# -*- coding: utf-8 -*-
"""news.py — поиск свежих новостей в Reddit + скачивание b-roll.

Использует RSS Reddit (без авторизации, без API-ключа) — тот же механизм,
что в reddit_fresh.py, но в виде пригодных для веба функций.
"""

import html
import random
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
# при ~1 запросе в минуту. Поэтому ходим строго последовательно с паузой.
REQUEST_DELAY = 60.0
CACHE_TTL = 900.0          # 15 минут
MAX_SUBS_PER_SEARCH = 3

_lock = threading.Lock()
_net_lock = threading.Lock()   # пауза между запросами к Reddit (не блокирует пул)
_cache: dict = {}          # (sub, mode) -> (ts, posts)
_cooldown_until = 0.0      # после 429 не дёргаем Reddit до этого времени
_cooldown_step = 0         # 1 -> 60с, 2 -> 120с, ... (растёт на серии 429)


def _mark_cooldown() -> None:
    """429: наращиваем паузу, чтобы не долбить Reddit впустую."""
    global _cooldown_until, _cooldown_step
    with _lock:
        _cooldown_step = min(_cooldown_step + 1, 4)
        _cooldown_until = max(_cooldown_until, time.time() + 60.0 * _cooldown_step)


def _reset_cooldown() -> None:
    global _cooldown_step
    with _lock:
        _cooldown_step = 0


def cooldown_left() -> float:
    """Сколько ещё секунд Reddit просил не беспокоить."""
    return max(0.0, _cooldown_until - time.time())


def _throttle() -> None:
    """Глобальная пауза между запросами к Reddit (общий для всех потоков)."""
    with _net_lock:
        now = time.time()
        wait = REQUEST_DELAY - (now - getattr(_throttle, "_last", 0.0))
        if _cooldown_until > now:
            wait = max(wait, _cooldown_until - now)
        if wait > 0:
            time.sleep(min(wait, 150.0))
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
                body = r.read().decode("utf-8", errors="replace")
            _reset_cooldown()
            return body
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            code = getattr(exc, "code", None)
            if code == 429:
                _mark_cooldown()
                if attempt + 1 < retries:
                    time.sleep(REQUEST_DELAY * (1 + attempt))
                else:
                    break
            else:
                break
    raise last_err if last_err else RuntimeError("unknown fetch error")

# Сабреддиты с вирусными «новостями» — там ровно тот формат, который идёт в шортс.
SUBS = [
    {"key": "nextfuckinglevel", "name": "NextFuckingLevel", "lang": "en"},
    {"key": "Damnthatsinteresting", "name": "Damnthatsinteresting", "lang": "en"},
    {"key": "interestingasfuck", "name": "InterestingAsFuck", "lang": "en"},
    {"key": "ThatsInsane", "name": "ThatsInsane", "lang": "en"},
    {"key": "PublicFreakout", "name": "PublicFreakout", "lang": "en"},
    {"key": "BeAmazed", "name": "BeAmazed", "lang": "en"},
    {"key": "oddlysatisfying", "name": "OddlySatisfying", "lang": "en"},
    {"key": "NatureIsFuckingLit", "name": "NatureIsFuckingLit", "lang": "en"},
    {"key": "IdiotsInCars", "name": "IdiotsInCars", "lang": "en"},
    {"key": "Whatcouldgowrong", "name": "WhatCouldGoWrong", "lang": "en"},
    {"key": "mechanicalgifs", "name": "MechanicalGifs", "lang": "en"},
    {"key": "BetterEveryLoop", "name": "BetterEveryLoop", "lang": "en"},
]
SUBS_BY_KEY = {s["key"]: s for s in SUBS}

MODES = {"hot": "hot", "new": "new", "top": "top"}


def _strip_html(raw: str) -> str:
    raw = re.sub(r"<!--.*?-->", " ", raw, flags=re.S)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    raw = re.sub(r"\s+", " ", raw)
    return raw.strip()


def parse_feed(sub: str, mode: str = "hot", force: bool = False,
               retries: int = 3) -> list:
    """Разобрать RSS сабреддита -> список постов с медиа.

    force=True — игнорировать кэш и идти в Reddit (свежая выдача по кнопке).
    """
    key = (sub, mode)
    cached = _cache.get(key)
    if not force and cached and time.time() - cached[0] < CACHE_TTL:
        return cached[1]

    url = f"https://www.reddit.com/r/{sub}/{mode}/.rss"
    try:
        xml = _fetch(url, retries=retries)
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] r/{sub}: {exc}")
        if cached and not force:
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
    try:
        import translate
        translate.enrich(out)       # русские заголовки для карточек
    except Exception:  # noqa: BLE001
        pass

    _cache[key] = (time.time(), out)
    return out


def rotate_subs(n: int = MAX_SUBS_PER_SEARCH, exclude=None) -> list:
    """Случайные n сабреддитов: каждая выдача покрывает другой кусок Reddit."""
    skip = set(exclude or [])
    keys = [s["key"] for s in SUBS if s["key"] not in skip]
    if not keys:
        keys = [s["key"] for s in SUBS]
    random.shuffle(keys)
    return keys[:n]


def search(subs: list | None = None, mode: str = "hot", only_video: bool = True,
           on_progress=None, force: bool = False, retries: int = 3) -> list:
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
        results.extend(parse_feed(sub, mode, force=force, retries=retries))

    if only_video:
        results = [p for p in results if p["has_video"]]

    seen, unique = set(), []
    for p in results:
        if p["link"] in seen:
            continue
        seen.add(p["link"])
        unique.append(p)
    return unique


def merge_posts(*groups, limit: int = 200) -> list:
    """Склеить выдачи без повторов, сначала самые свежие."""
    seen, out = set(), []
    for group in groups:
        for p in group or []:
            link = p.get("link") or ""
            if not link or link in seen:
                continue
            seen.add(link)
            out.append(p)
    out.sort(key=lambda p: p.get("updated") or "", reverse=True)
    return out[:limit]


def pool_posts(limit: int = 200, mode: str = "new") -> list:
    """Готовые посты с видео из прогретого пула (несколько сабреддитов)."""
    with _lock:
        groups = [v[1] for (sub, m), v in _cache.items() if m == mode]
    videos = [[p for p in g if p.get("has_video")] for g in groups]
    return merge_posts(*videos, limit=limit)


def refresh_one(mode: str = "new"):
    """Обновить в фоне один сабреддит — самый давно обновлённый."""
    keys = [s["key"] for s in SUBS]
    with _lock:
        stale = min(keys, key=lambda k: _cache.get((k, mode), (0.0, []))[0])
    try:
        posts = parse_feed(stale, mode, force=True, retries=1)
    except Exception:  # noqa: BLE001
        return None
    if not posts:
        _cache[(stale, mode)] = (time.time(), [])   # не застревать на нём
        return None
    return stale


def start_prefetch() -> threading.Thread:
    """Фоновый воркер: раз в минуту обновляет один сабреддит.

    Нужен потому, что Reddit анонимно отдаёт ~1 запрос в минуту: пока
    пользователь читает, пул уже прогревается, и клик отвечает мгновенно.
    """
    def loop():
        while True:
            try:
                refresh_one()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(2.0)          # остальное выждет _throttle перед запросом

    t = threading.Thread(target=loop, name="news-prefetch", daemon=True)
    t.start()
    return t


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
