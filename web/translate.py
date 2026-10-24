# -*- coding: utf-8 -*-
"""translate.py — заголовки Reddit по-русски.

Сайт русскоязычный, а лента англоязычная, поэтому заголовки постов
переводим на русский. Два бесплатных пути без ключей:

  1. Google (clients5, батч до ~10 заголовков за запрос) — быстро и точно;
  2. MyMemory (по одному заголовку) — если Google ограничил запросы.

Переводы кэшируются в таблице news_tr, поэтому один и тот же пост
переводится один раз. Любая ошибка перевода не ломает поиск:
заголовок просто остаётся на английском.
"""

import html
import json
import re
import urllib.parse
import urllib.request

import db

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
GOOGLE = "https://clients5.google.com/translate_a/t?client=dict-chrome-ex&sl=auto&tl=ru"
MYMEMORY = "https://api.mymemory.translated.net/get"

BATCH = 10          # заголовков за один запрос к Google
MAX_QS = 1500       # сколько символов заголовков влезает в URL

_LAT = re.compile(r"[a-z]", re.I)
_CYR = re.compile(r"[а-яё]", re.I)


def _needs_translation(text: str) -> bool:
    """Переводим только то, где латиницы больше, чем кириллицы."""
    return len(_LAT.findall(text)) > len(_CYR.findall(text))


def _http(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _unwrap(data, n: int) -> list:
    """clients5 отдаёт либо ["перевод", ...], либо [["перевод","en"], ...]."""
    if not isinstance(data, list) or len(data) != n:
        return []
    out = []
    for item in data:
        if isinstance(item, str):
            out.append(item.strip())
        elif isinstance(item, list) and item and isinstance(item[0], str):
            out.append(item[0].strip())
        else:
            return []
    return out


def _google_chunk(titles: list) -> list:
    qs = "".join("&q=" + urllib.parse.quote(t) for t in titles)
    data = json.loads(_http(GOOGLE + qs))
    return _unwrap(data, len(titles))


def _google_all(titles: list) -> list:
    """Перевод пачками; [] если хоть одна пачка не удалась."""
    out = []
    i = 0
    while i < len(titles):
        chunk, size = [], 0
        while i < len(titles) and len(chunk) < BATCH and size + len(titles[i]) < MAX_QS:
            chunk.append(titles[i])
            size += len(titles[i]) + 8
            i += 1
        try:
            part = _google_chunk(chunk)
        except Exception:  # noqa: BLE001
            return []
        if len(part) != len(chunk):
            return []
        out.extend(part)
    return out


def _mymemory(title: str) -> str:
    url = (MYMEMORY + "?q=" + urllib.parse.quote(title) + "&langpair=en|ru")
    data = json.loads(_http(url, timeout=20))
    text = (data.get("responseData") or {}).get("translatedText") or ""
    return html.unescape(text).strip()


def translate_text(text: str) -> str:
    """Перевести одну фразу (EN -> RU). При ошибке вернуть исходник."""
    text = (text or "").strip()
    if not text or not _needs_translation(text):
        return text
    try:
        part = _google_all([text])
        if len(part) == 1 and part[0].strip():
            return part[0].strip()
    except Exception:  # noqa: BLE001
        pass
    try:
        return _mymemory(text) or text
    except Exception:  # noqa: BLE001
        return text


def enrich(posts: list) -> list:
    """Дописать в посты title_ru (на месте). Никогда не бросает исключений."""
    need = [p for p in posts
            if p.get("title") and not p.get("title_ru")
            and _needs_translation(p["title"])]
    if not need:
        return posts

    try:
        known = db.get_translations([p.get("link") for p in need if p.get("link")])
    except Exception:  # noqa: BLE001
        known = {}
    for p in need:
        ru = known.get(p.get("link") or "")
        if ru:
            p["title_ru"] = ru

    todo = [p for p in need if not p.get("title_ru")]
    if not todo:
        return posts

    saved = {}

    def put(post, ru):
        ru = (ru or "").strip()
        if not ru or ru.lower() == (post.get("title") or "").strip().lower():
            return
        post["title_ru"] = ru
        if post.get("link"):
            saved[post["link"]] = ru

    batch = _google_all([p["title"] for p in todo])
    if len(batch) == len(todo):
        for post, ru in zip(todo, batch):
            put(post, ru)
    else:
        for post in todo:          # Google не дал — переводим по одному
            try:
                put(post, _mymemory(post["title"]))
            except Exception:  # noqa: BLE001
                continue

    try:
        db.save_translations(saved)
    except Exception:  # noqa: BLE001
        pass
    return posts
