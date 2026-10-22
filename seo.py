#!/usr/bin/env python3
"""
seo.py — автоматический SEO-пакет для Shorts (русский), работает надёжно.

Как выбирается «самый крутой» заголовок:
  • берём пул кандидатов: файл title_pool.txt (если есть) + кандидаты от LLM
    (Pollinations, best-effort, со СТРОГИМ фильтром мусора) + варианты из брифа;
  • каждый кандидат оценивается эвристикой «кликабельности»;
  • побеждает кандидат с максимальным баллом — это и есть авто-выбор.

Дополнительно генерируются: ОПИСАНИЕ, ХЭШТЕГИ, КЛЮЧЕВЫЕ слова, ЭКРАННЫЙ заголовок.

Файлы на выходе:
  D:\\AI\\F5-TTS\\title.txt            — лучший заголовок (для YouTube)
  D:\\AI\\F5-TTS\\description.txt       — описание + хэштеги (для YouTube)
  D:\\AI\\F5-TTS\\tags.txt              — теги через запятую (для YouTube)
  D:\\AI\\VIDEO_PIPELINE\\output\\screen_title.txt — заголовок в кадре
  D:\\AI\\VIDEO_PIPELINE\\output\\keywords.txt     — слова для красных субтитров
  D:\\AI\\VIDEO_PIPELINE\\output\\seo.json         — весь пакет (аудит)

Пример:  python seo.py --brief-file brief.txt --n 7
"""

import argparse
import json
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

POLL_LEGACY = "https://text.pollinations.ai/"
POLL_MODEL = "openai-fast"

ROOT = Path(r"D:\AI\VIDEO_PIPELINE")
DEFAULT_BRIEF = ROOT / "brief.txt"
POOL_FILE = ROOT / "title_pool.txt"
SEO_JSON = ROOT / "output" / "seo.json"

TITLE_TXT = Path(r"D:\AI\F5-TTS\title.txt")
DESC_TXT = Path(r"D:\AI\F5-TTS\description.txt")
TAGS_TXT = Path(r"D:\AI\F5-TTS\tags.txt")
SCREEN_TITLE_TXT = ROOT / "output" / "screen_title.txt"
KEYWORDS_TXT = ROOT / "output" / "keywords.txt"

POWER_WORDS = [
    "шок", "невероятн", "впервые", "рекорд", "сенсац", "вот это", "только в",
    "устроил", "против", " vs ", "снял", "поймал", "спас", "жёстк", "жестк",
    "реальн", "настоящ", "внезапн", "абсурд", "позор", "секрет", "не ожидал",
    "австрал", "кенгуру", "бокс", "дерутся", "жесть", "двор", "сосед", "птиц",
    "воров", "вор", "кот", "котят", "молок", "камер", "стащил", "ограбл", "крал",
    # Тема-наводнение
    "стамбул", "наводнен", "затоп", "ливень", "ливн", "стихийн", "унёс", "унес",
    "машин", "под вод", "водой",
    # Тема-космос (SpaceX / медуза)
    "spacex", "медуз", "космическ", "ракет", "запуск", "неб", "свечен", "сияни",
    # Тема-жирафы (бои шеями / «некинг»)
    "жираф", "шеями", "шеей", "некинг", "саванн", "драл", "дерутся", "бой", "удар",
    # Тема-утки (спасение утят из ливневки)
    "утят", "утён", "утк", "ливнев", "решётк", "решетк", "сток", "крякв", "гусеобразн",
    # Тема-салон (школьники в Lamborghini, Хайдерабад, 20.10.2026)
    "ламборгин", "lamborghini", "суперкар", "школьник", "витрин", "салон",
]

# Тематические теги: если слово темы есть в брифе — добавляем теги.
# ВАЖЕН ПОРЯДОК: первое совпадение выигрывает. Общие ключи ("неб", "ракет") идут
# после специфичных, чтобы не перехватывать чужие темы (напр. "кот" раньше "неб").
TOPIC_TAGS = {
    # Тема выпуска: школьники в салоне Lamborghini, Хайдерабад (20.10.2026).
    # САМЫЕ ПЕРВЫЕ: ловим и кириллицу, и латиницу бренда, иначе «машин» из брифа
    # уводит хэштеги в общий #авто/#cars без конкретики.
    "ламборгин": ["#ламборгини", "#lamborghini", "#суперкары"],
    "lamborghini": ["#ламборгини", "#lamborghini", "#суперкары"],
    "суперкар": ["#суперкары", "#lamborghini", "#авто"],
    "хайдерабад": ["#хайдерабад", "#индия", "#ламборгини"],
    # Тема-утки (спасение утят из ливневой решётки, 19.10.2026). Ключи стоят САМЫМИ
    # ПЕРВЫМИ: иначе «ливн» (ливневка) перехватывает тему и ролик уходит в
    # #ливень/#наводнение, а «птиц» — в общий #птицы без конкретики.
    "утят": ["#утята", "#животные", "#ducklings", "#утки", "#спасение", "#птицы"],
    "утён": ["#утята", "#животные", "#ducklings", "#утки", "#спасение", "#птицы"],
    "крякв": ["#утки", "#животные", "#ducks", "#птицы", "#спасение"],
    "утк": ["#утки", "#животные", "#ducks", "#птицы"],
    "ливнев": ["#ливневка", "#город", "#спасение", "#животные"],
    # Тема выпуска: наводнение в Стамбуле (16.10.2026). Специфичные ключи — В НАЧАЛЕ,
    # чтобы build_hashtags выбрал их первыми.
    "стамбул": ["#стамбул", "#наводнение", "#istanbul", "#турция", "#flood", "#природа"],
    "наводнен": ["#наводнение", "#flood", "#природа", "#погода", "#стихия"],
    "ливн": ["#ливень", "#наводнение", "#flood", "#погода"],
    "затоп": ["#наводнение", "#flood", "#стамбул", "#природа"],
    "турци": ["#турция", "#стамбул", "#istanbul"],
    "кенгуру": ["#кенгуру", "#kangaroo", "#австралия", "#australia", "#животные",
                "#wildlife", "#boxing", "#reddit"],
    "австрал": ["#австралия", "#australia", "#aussie", "#кенгуру", "#wildlife"],
    "птиц": ["#птицы", "#birds", "#plover", "#чибис"],
    # Тема-гиббоны (сиаманги и незнакомые предметы, 19.10.2026): самые узкие ключи
    # идут ПЕРЕД «обезьян», иначе ролик получит общий набор #обезьяны без вида.
    "сиаманг": ["#гиббоны", "#обезьяны", "#gibbon", "#приматы", "#зоопарк", "#животные"],
    "гиббон": ["#гиббоны", "#обезьяны", "#gibbon", "#приматы", "#зоопарк", "#животные"],
    "вольер": ["#зоопарк", "#zoo", "#животные", "#обезьяны"],
    # Специфичные темы ДО "кот": иначе «кот» ловит слово «который» и перебивает тему.
    "шимпанзе": ["#обезьяны", "#monkeys", "#приматы", "#primates", "#животные", "#wildlife", "#заповедник"],
    "обезьян": ["#обезьяны", "#monkeys", "#приматы", "#primates", "#животные", "#wildlife"],
    "примат": ["#приматы", "#primates", "#обезьяны", "#monkeys", "#животные"],
    "горилл": ["#обезьяны", "#monkeys", "#приматы", "#primates", "#животные"],
    "макак": ["#обезьяны", "#monkeys", "#приматы", "#primates", "#животные"],
    "кот": ["#коты", "#cats", "#животные", "#pets"],
    "волк": ["#волк", "#wolf", "#медведь", "#bear", "#животные", "#wildlife", "#природа", "#nature"],
    "медвед": ["#медведь", "#bear", "#волк", "#wolf", "#животные", "#wildlife", "#природа", "#nature"],
    "собак": ["#собаки", "#dogs", "#животные", "#pets"],
    # Тема-жирафы: специфичный ключ до общих (неб/машин не перехватят).
    "жираф": ["#жирафы", "#giraffe", "#животные", "#wildlife", "#природа", "#nature"],
    "некинг": ["#жирафы", "#giraffe", "#природа", "#nature"],
    # Тема-роботы: ключ ДО «машин», иначе слово «машины» («машины — инструмент
    # для работы») уводит ролик про робота в #авто/#cars.
    "робот": ["#роботы", "#технологии", "#AI", "#tech"],
    "рокки": ["#роботы", "#технологии", "#AI", "#tech"],
    # Тема-стихия (торнадо/ураган/наводнение-ветер): специфичные ключи ДО «машин»,
    # иначе слово «машинист» из брифа уводит ролик в #авто/#cars.
    "торнадо": ["#торнадо", "#tornado", "#природа", "#стихия", "#погода"],
    "смерч": ["#смерч", "#торнадо", "#tornado", "#стихия", "#погода"],
    "ураган": ["#ураган", "#торнадо", "#tornado", "#стихия", "#погода"],
    "небраск": ["#небраска", "#nebraska", "#сша", "#usa", "#торнадо"],
    "машин": ["#авто", "#cars", "#технологии"],
    "деньг": ["#деньги", "#экономика", "#finance"],
    "spacex": ["#spacex", "#космос", "#space", "#starship", "#наука"],
    "starship": ["#starship", "#spacex", "#космос", "#space", "#наука"],
    "медуз": ["#космос", "#space", "#spacex", "#наука", "#астрономия"],
    "нло": ["#космос", "#space", "#НЛО", "#ufo", "#наука"],
    "ракет": ["#космос", "#spacex", "#space", "#starship", "#астрономия"],
    "неб": ["#космос", "#space", "#наука"]
}

# Ложные срабатывания ключей: ключ совпал, но слово о другом.
TOPIC_EXCLUDE = {
    "машин": ("машинист",),   # «машинист» — человек, а не транспорт
}

BASE_TAGS = ["#shorts", "#новости", "#интересное", "#факты", "#разбор"]
# Было (спам-набор, который YouTube не ранжирует): #вирусное #тренды #trending
# #viral #news #funny #reels — заменено 19.10.2026 на осмысленные слова канала.

# ORIGINALITY_GUIDE: хэштеги в видео — 2–3 релевантных, БЕЗ спама.
HASHTAG_LIMIT = 3

# Чувствительные темы → обязательный дисклеймер (ORIGINALITY_GUIDE / AGENTS.md)
SENSITIVE = {
    "финанс": "Не является инвестиционной рекомендацией.",
    "инвест": "Не является инвестиционной рекомендацией.",
    "акци": "Не является инвестиционной рекомендацией.",
    "банк": "Не является инвестиционной рекомендацией.",
    "кредит": "Не является инвестиционной рекомендацией.",
    "вклад": "Не является инвестиционной рекомендацией.",
    "медиц": "Не является медицинской рекомендацией. Обратитесь к врачу.",
    "здоров": "Не является медицинской рекомендацией. Обратитесь к врачу.",
    "лекарств": "Не является медицинской рекомендацией. Обратитесь к врачу.",
    "болезн": "Не является медицинской рекомендацией. Обратитесь к врачу.",
    "политик": "Мнение автора может не совпадать с вашим.",
    "выбор": "Мнение автора может не совпадать с вашим.",
    "президент": "Мнение автора может не совпадать с вашим.",
    "парламент": "Мнение автора может не совпадать с вашим.",
}
CTA = "Подписывайтесь — новые разборы каждый день."

# ---------------------------------------------------------------------------
def heuristic_score(title: str) -> float:
    t = title.strip()
    low = " " + t.lower() + " "
    s = 0.0
    if "#shorts" in low:
        s += 2.0
    n = len(t)
    if 25 <= n <= 70:
        s += 2.5
    elif 70 < n <= 95:
        s += 1.0
    elif n > 100:
        s -= 6.0
    for w in POWER_WORDS:
        if w in low:
            s += 0.7
    if re.search(r"\d", t):
        s += 0.8
    if "?" in t or "!" in t:
        s += 0.5
    if len(re.findall(r"\b[А-ЯЁA-Z]{3,}\b", t)) >= 1:
        s += 0.5
    if t.lower().startswith("только в"):
        s += 0.6
    if t.count("#") > 3:
        s -= 2.0
    if t.count('"') or t.count("«") > 1:
        s -= 0.5
    return round(s, 2)


def valid_title(t: str) -> bool:
    t = re.sub(r"^\s*\d+[\.\)]\s*", "", t).strip().strip('"\'').strip()
    if not (18 <= len(t) <= 100):
        return False
    bad = ["count", "char", "length", "score", "title:", "variant", "reasoning",
           "format", "{", "}", "|", "under ", "numbering", "==", "http", "тitle"]
    low = t.lower()
    if any(b in low for b in bad):
        return False
    cyr = len(re.findall(r"[А-Яа-яЁё]", t))
    lat = len(re.findall(r"[A-Za-z]", t))
    if cyr == 0 or cyr < lat * 0.6:
        return False
    if t.count(",") > 3 or t.count(":") > 1:
        return False
    # отбросить «перечисление мыслей»
    if re.search(r"\d+\s*(символ|char|знак)", low):
        return False
    return True


def norm_title(t: str) -> str:
    t = re.sub(r"^\s*\d+[\.\)]\s*", "", t).strip().strip('"\'').strip()
    t = re.sub(r"\s+", " ", t).replace("‑", "-").replace("–", "-").replace("—", "-")
    if "#shorts" not in t.lower():
        t = t.rstrip(" .!") + " #shorts"
    return t


# ---------------------------------------------------------------------------
def call_llm(prompt: str, retries: int = 3, timeout: int = 120) -> str:
    url = (POLL_LEGACY + urllib.parse.quote(prompt)
           + f"?model={POLL_MODEL}&seed={random.randint(1, 10**9)}")
    last = ""
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
            print(f"   [LLM] попытка {attempt}/{retries}: {last}")
            time.sleep(4 * attempt)
    raise RuntimeError(last)


def llm_titles(facts: str, n: int) -> list:
    prompt = (f"Новость: {facts}. "
              f"Придумай {n} разных коротких цепляющих заголовков для YouTube Shorts на русском. "
              "Каждый до 90 символов, в конце #shorts. Каждый с новой строки, без нумерации и пояснений.")
    text = call_llm(prompt)
    out = []
    for line in text.splitlines():
        line = line.strip()
        if valid_title(line):
            out.append(norm_title(line))
    return out


def llm_meta(facts: str) -> tuple:
    prompt = (f"Новость: {facts}. "
              "Ответь строго в формате:\n"
              "DESCRIPTION: <описание видео из двух предложений на русском>\n"
              "HASHTAGS: <12 хэштегов через пробел>\n"
              "KEYWORDS: <10 русских слов через запятую>")
    text = call_llm(prompt)
    desc = ""
    m = re.search(r"DESCRIPTION:\s*(.+?)(?=HASHTAGS:|$)", text, re.DOTALL | re.IGNORECASE)
    if m:
        d = re.sub(r"\s+", " ", m.group(1)).strip()
        if 20 <= len(d) <= 600 and valid_title(d):
            desc = d
    tags = []
    m = re.search(r"HASHTAGS:\s*(.+)", text, re.IGNORECASE)
    if m:
        tags = re.findall(r"#[\wА-Яа-яЁё_]+", m.group(1))
    kw = []
    m = re.search(r"KEYWORDS:\s*(.+)", text, re.IGNORECASE)
    if m:
        kw = [w.strip().lower().strip(".,!?;:") for w in re.split(r"[,\n;]", m.group(1)) if w.strip()]
    return desc, tags, kw


# ---------------------------------------------------------------------------
def build_tags(brief: str, llm_tags: list) -> list:
    """Теги для поля «теги» YouTube: только релевантное, без спама.

    Набор берём у ОДНОЙ темы (первое совпадение, как в build_hashtags), а не у всех
    сразу: иначе в брифe про робота слово «машины» добавляло в теги #авто, #cars.
    """
    low = brief.lower()
    tags = list(BASE_TAGS)
    for key, extra in TOPIC_TAGS.items():
        if topic_match(low, key):
            tags += extra
            break
    tags += llm_tags
    # уникализируем, не даём свалку
    seen, out = set(), []
    for t in tags:
        t = t.strip()
        if not t:
            continue
        if not t.startswith("#"):
            t = "#" + t
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out[:15]


def topic_match(low: str, key: str) -> bool:
    """Тема найдена как отдельное слово/начало слова, а не подстрока.
    Иначе «кот» ловится внутри «который», а «машинист» — внутри «машин».
    Исключения (TOPIC_EXCLUDE) описывают такие ложные слова."""
    pat = r"(?:^|[^а-яёa-z])" + re.escape(key)
    for m in re.finditer(pat, low):
        tail = re.match(r"[а-яёa-z]*", low[m.end():]).group(0)
        word = key + tail
        if any(word.startswith(p) for p in TOPIC_EXCLUDE.get(key, ())):
            continue
        return True
    return False


def build_hashtags(brief: str, best: str) -> list:
    """2–3 РЕЛЕВАНТНЫХ хэштега (ORIGINALITY_GUIDE: без спама)."""
    low = (brief + " " + best).lower()
    picked = []
    for key, extra in TOPIC_TAGS.items():
        if topic_match(low, key):
            picked = extra
            break
    if not picked:
        picked = ["#новости", "#интересное"]
    out, seen = [], set()
    for t in ["#shorts"] + picked:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:HASHTAG_LIMIT]


def sensitivity_note(brief: str) -> str:
    """Дисклеймер для финансов/медицины/политики (AGENTS.md, п.4)."""
    low = brief.lower()
    for key, note in SENSITIVE.items():
        if topic_match(low, key):
            return note
    return ""


def build_description(brief: str, best: str, llm_desc: str, hashtags: list,
                      note: str = "") -> str:
    """Описание: 2–3 предложения по делу + CTA + (дисклеймер) + 2–3 хэштега."""
    if llm_desc:
        body = re.sub(r"\s+", " ", llm_desc).strip()
        if not body.endswith((".", "!", "?")):
            body += "."
    else:
        chunks = [s.strip() for s in re.split(r"(?<=[.!?])\s+", brief) if s.strip()]
        body = " ".join(chunks[:2]).strip()
        if body and not body.endswith((".", "!", "?")):
            body += "."
    parts = [p for p in (body, CTA, note) if p]
    return ("\n\n".join(parts) + "\n\n" + " ".join(hashtags)).strip()


def build_screen_title(brief: str, best: str) -> str:
    # Короткий заголовок в кадре: 3 ПОДРЯД идущих слова из ОСНОВНОЙ части (до двоеточия),
    # чтобы фраза оставалась грамотной. Раньше слова вынимались через стоп-список из части
    # ПОСЛЕ двоеточия — и «Утята в ливневке: тридцать граммов и широкие щели…» превращалось
    # в бессмысленное «ТРИДЦАТЬ ГРАММОВ ШИРОКИЕ».
    part = best.split(":", 1)[0] if ":" in best else best
    words = re.findall(r"[А-Яа-яЁё0-9]+", part.replace("#shorts", ""))[:3]
    # стартовый предлог/союз не годится («В ГОРОДЕ ЭТО…»), — сдвигаем на слово;
    # хвостовой предлог тоже отбрасываем («УТЁНОК ВЕСОМ В»)
    stop = {"в", "во", "на", "и", "а", "с", "со", "за", "из", "у", "о", "к", "по",
            "для", "не", "то", "же", "бы", "как", "что"}
    if len(words) > 1 and words[0].lower() in stop:
        words = words[1:]
    while len(words) > 1 and words[-1].lower() in stop:
        words.pop()
    return " ".join(w.upper() for w in words) or "НОВОСТЬ ДНЯ"


# ---------------------------------------------------------------------------
def collect_candidates(brief: str, n: int, use_llm: bool = True) -> list:
    """Возвращает список (title, source). Пул имеет приоритет."""
    cands = []
    if POOL_FILE.exists():
        for line in POOL_FILE.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and valid_title(line):
                cands.append((norm_title(line), "pool"))
    if use_llm:
        facts = brief.replace("\n", " ")[:500]
        try:
            for t in llm_titles(facts, n):
                cands.append((t, "llm"))
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] LLM-заголовки недоступны ({e})")
    seen, uniq = set(), []
    for c, src in cands:
        if c.lower() not in seen:
            seen.add(c.lower())
            uniq.append((c, src))
    return uniq


def generate(brief: str, n: int = 7, use_llm: bool = True) -> dict:
    cands = collect_candidates(brief, n, use_llm=use_llm)
    if not cands:
        raise ValueError("нет ни одного валидного кандидата заголовка")
    scored = []
    for title, src in cands:
        bonus = 1.0 if src == "pool" else 0.0   # редакционный пул довереннее
        scored.append({"title": title, "source": src,
                       "total": round(heuristic_score(title) + bonus, 2)})
    scored.sort(key=lambda x: x["total"], reverse=True)
    best = scored[0]["title"]

    facts = brief.replace("\n", " ")[:500]
    llm_desc, llm_tags, llm_kw = "", [], []
    if use_llm:
        try:
            llm_desc, llm_tags, llm_kw = llm_meta(facts)
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] LLM-meta недоступна ({e})")

    hashtags = build_hashtags(brief, best)
    tags = build_tags(brief, llm_tags)
    note = sensitivity_note(brief + " " + best)
    keywords = [k for k in llm_kw if re.fullmatch(r"[а-яё\-]+", k)][:20]

    return {
        "title": best,
        "screen_title": build_screen_title(brief, best),
        "description": build_description(brief, best, llm_desc, hashtags, note),
        "hashtags": hashtags,
        "tags": tags,
        "disclaimer": note,
        "keywords": keywords,
        "candidates": scored,
    }


def fallback(brief: str) -> dict:
    first = next((l.strip() for l in brief.splitlines() if l.strip()), "Новость дня")
    title = norm_title(first[:88].rstrip(" .,"))
    ht = build_hashtags(brief, title)
    tags = build_tags(brief, [])
    note = sensitivity_note(brief + " " + title)
    return {
        "title": title,
        "screen_title": build_screen_title(brief, title),
        "description": build_description(brief, title, "", ht, note),
        "hashtags": ht,
        "tags": tags,
        "disclaimer": note,
        "keywords": [],
        "candidates": [{"title": title, "total": heuristic_score(title)}],
    }


def write_files(seo: dict) -> None:
    for p in (TITLE_TXT, DESC_TXT, TAGS_TXT, SCREEN_TITLE_TXT, KEYWORDS_TXT):
        p.parent.mkdir(parents=True, exist_ok=True)
    TITLE_TXT.write_text(seo["title"] + "\n", encoding="utf-8")
    DESC_TXT.write_text(seo["description"] + "\n", encoding="utf-8")
    yt_tags = seo.get("tags") or seo["hashtags"]
    TAGS_TXT.write_text(", ".join(h.lstrip("#") for h in yt_tags) + "\n", encoding="utf-8")
    SCREEN_TITLE_TXT.write_text(seo["screen_title"] + "\n", encoding="utf-8")
    KEYWORDS_TXT.write_text("\n".join(seo["keywords"]) + "\n", encoding="utf-8")
    SEO_JSON.parent.mkdir(parents=True, exist_ok=True)
    SEO_JSON.write_text(json.dumps(seo, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="Авто-SEO: выбор заголовка, описание, хэштеги")
    ap.add_argument("--brief", default=None, help="Текст брифа напрямую")
    ap.add_argument("--brief-file", default=str(DEFAULT_BRIEF))
    ap.add_argument("--n", type=int, default=7)
    ap.add_argument("--no-llm", action="store_true")
    a = ap.parse_args()

    if a.brief:
        brief = a.brief
    else:
        p = Path(a.brief_file)
        brief = p.read_text(encoding="utf-8-sig").strip() if p.exists() else ""
    if not brief:
        print(f"[ERROR] нет брифа: {a.brief_file}")
        sys.exit(1)

    print("=" * 60)
    print("[SEO] Генерация и авто-выбор заголовка")
    print("=" * 60)

    try:
        seo = generate(brief, n=a.n, use_llm=not a.no_llm)
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] {e} — фолбэк")
        seo = fallback(brief)

    write_files(seo)
    print(f"[OK] Выбран заголовок: {seo['title']}")
    print(f"[OK] Экранный заголовок: {seo['screen_title']}")
    print(f"[OK] Хэштеги ({len(seo['hashtags'])}): {' '.join(seo['hashtags'])}")
    if seo.get("disclaimer"):
        print(f"[OK] Дисклеймер (чувствительная тема): {seo['disclaimer']}")
    print(f"[OK] Описание:\n{seo['description']}")
    print("\n--- Все кандидаты (балл) ---")
    for t in seo["candidates"]:
        print(f"  [{t['total']:>5}] {t['title']}")
    print(f"\n[OK] {TITLE_TXT} | {DESC_TXT} | {TAGS_TXT}")


if __name__ == "__main__":
    main()
