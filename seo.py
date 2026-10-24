#!/usr/bin/env python3
"""
seo.py — автоматический SEO-пакет для Shorts (русский), работает надёжно.

Как выбирается «самый крутой» заголовок (пересмотрено 23.10.2026):
  • заголовок делается ПОД ТЕКУЩЕЕ видео: кандидаты от LLM по фактам брифа
    (тема + контекст, без «сценарного» текста) + формульные хуки от темы ролика;
  • каждый кандидат оценивается эвристикой «кликабельности» ПЛЮС релевантностью
    фактам текущего видео — чужой/старый заголовок просто не наберёт баллов;
  • title_pool.txt больше не имеет приоритета: его строки попадают в кандидаты
    только если релевантны теме этого ролика и ещё не использовались;
  • использованные заголовки пишутся в output/used_titles.txt и больше не
    выбираются — у каждого нового видео свой новый заголовок.

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
POLL_OPENAI = POLL_LEGACY + "openai"
POLL_MODEL = "openai-fast"

# Локальная модель через Ollama: бесплатный Pollinations на длинных промптах
# выдаёт словесный салат, локальная 4B держит русский заметно лучше.
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
OLLAMA_TAGS = "http://127.0.0.1:11434/api/tags"
LOCAL_PREFER = ("qwen3.5:4b", "qwen2.5:latest", "gemma3:4b")
_LOCAL = {"checked": False, "model": ""}

ROOT = Path(r"D:\AI\VIDEO_PIPELINE")
DEFAULT_BRIEF = ROOT / "brief.txt"
POOL_FILE = ROOT / "title_pool.txt"
SEO_JSON = ROOT / "output" / "seo.json"
USED_TITLES = ROOT / "output" / "used_titles.txt"

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
    "волк": ["#волк", "#wolf", "#животные", "#wildlife", "#природа", "#nature"],
    "медвед": ["#медведь", "#bear", "#животные", "#wildlife", "#природа", "#nature"],
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
    "кот": ("котор", "котёл", "котел", "котлет"),  # «который» — не кот
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


# --- свежесть и релевантность заголовков (23.10.2026) ------------------------
STOP_WORDS = {
    "это", "этот", "этом", "этого", "эти", "была", "были", "было", "есть", "как",
    "что", "чем", "его", "её", "для", "или", "под", "над", "при", "все", "весь",
    "они", "она", "оно", "ещё", "еще", "уже", "тоже", "себя", "свой", "свои",
    "когда", "чтобы", "может", "можно", "только", "даже", "очень", "такой",
    "такие", "после", "перед", "между", "среди", "более", "менее", "будет",
    "стало", "стали", "него", "неё", "них", "без", "про", "там", "тут", "здесь",
    "который", "которая", "которое", "которые", "почему", "зачем", "видео",
    "кадры", "кадрах",
}


def load_used() -> set:
    """Заголовки, которые уже выходили: повторно выбирать их нельзя."""
    if not USED_TITLES.exists():
        return set()
    out = set()
    for line in USED_TITLES.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.add(norm_title(line).lower())
    return out


def mark_used(title: str) -> None:
    USED_TITLES.parent.mkdir(parents=True, exist_ok=True)
    try:
        with USED_TITLES.open("a", encoding="utf-8") as f:
            f.write(title.strip() + "\n")
    except OSError as e:  # noqa: BLE001
        print(f"[WARN] не записал использованный заголовок ({e})")


def title_facts(brief: str) -> str:
    """Факты ТОЛЬКО о текущем ролике: строка «Тема» и «Контекст».

    Текст после «Сценарий:» намеренно не берём: он длинный и, при слабой
    модели, шумный — из-за него LLM писал заголовки с выдуманными словами
    вместо заголовка по теме видео.
    """
    topic, ctx = "", ""
    for line in brief.splitlines():
        low = line.strip().lower()
        if low.startswith("тема:"):
            topic = line.split(":", 1)[1].strip()
        elif low.startswith("контекст:"):
            ctx = line.split(":", 1)[1].strip()
        elif low.startswith("сценарий:"):
            break
    if not topic:
        topic = next((l.strip() for l in brief.splitlines() if l.strip()), "")
    parts = [p for p in (topic, ctx) if p]
    return ". ".join(parts)[:400]


def content_words(text: str) -> list:
    return [w for w in re.findall(r"[а-яёa-z]{4,}", text.lower()) if w not in STOP_WORDS]


def relevance(title: str, facts: str) -> int:
    """Сколько слов заголовка реально взяты из фактов ЭТОГО видео."""
    facts_words = content_words(facts)
    if not facts_words:
        return 0
    prefixes = {w[:4] for w in facts_words}
    return sum(1 for w in set(content_words(title)) if w[:4] in prefixes)


def formula_titles(brief: str) -> list:
    """Грамотные хуки прямо из темы ролика — страховка, если LLM даст мусор."""
    topic = ""
    for line in brief.splitlines():
        if line.strip().lower().startswith("тема:"):
            topic = line.split(":", 1)[1].strip()
            break
    if not topic:
        topic = next((l.strip() for l in brief.splitlines() if l.strip()), "")
    topic = re.sub(r"[^\w\sА-Яа-яЁё\-:,.!?]+", " ", topic).strip(" .,:—-")
    topic = re.sub(r"\s+", " ", topic)
    if len(topic) < 12:
        return []
    if len(topic) > 70:
        topic = topic[:70].rsplit(" ", 1)[0]
    base = topic[0].upper() + topic[1:]
    low = base[0].lower() + base[1:]
    return [
        f"{base}: что происходит на кадрах? #shorts",
        f"{base} — вот что попало на видео #shorts",
        f"Почему {low}? #shorts",
    ]


# ---------------------------------------------------------------------------
def _poll_openai(prompt: str, timeout: int) -> str:
    """Основной путь: OpenAI-совместимый POST — он стабильнее GET."""
    body = json.dumps({
        "model": POLL_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "seed": random.randint(1, 10 ** 9),
        # без этого модель уходит в рассуждения и не отдаёт content
        "reasoning_effort": "low",
    }).encode("utf-8")
    req = urllib.request.Request(POLL_OPENAI, data=body, headers={
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
    try:
        d = json.loads(raw)
        msg = d["choices"][0]["message"]
        text = (msg.get("content") or "").strip()
        if not text and (msg.get("reasoning") or msg.get("tool_calls")):
            return ""
        if text:
            return text
    except (KeyError, IndexError, TypeError, ValueError):
        pass
    return raw


def _poll_legacy(prompt: str, timeout: int) -> str:
    """Запасной путь: старый GET /{prompt}."""
    url = (POLL_LEGACY + urllib.parse.quote(prompt)
           + f"?model={POLL_MODEL}&seed={random.randint(1, 10**9)}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _local_model() -> str:
    if _LOCAL["checked"]:
        return _LOCAL["model"]
    _LOCAL["checked"] = True
    try:
        with urllib.request.urlopen(OLLAMA_TAGS, timeout=2) as r:
            names = [m.get("name", "") for m in json.loads(
                r.read().decode("utf-8", "replace")).get("models", [])]
    except Exception:  # noqa: BLE001
        names = []
    for pref in LOCAL_PREFER:
        if pref in names:
            _LOCAL["model"] = pref
            break
    else:
        _LOCAL["model"] = names[0] if names else ""
    if _LOCAL["model"]:
        print(f"   [LLM] локальная модель: {_LOCAL['model']}")
    return _LOCAL["model"]


def _ollama(prompt: str, timeout: int = 300) -> str:
    model = _local_model()
    if not model:
        return ""
    body = json.dumps({
        "model": model,
        "stream": False,
        "think": False,
        "messages": [{"role": "user", "content": prompt}],
        "options": {"temperature": 0.8, "num_predict": 500, "num_ctx": 4096},
        # не держим VRAM: следом на этой же карте запускается F5-TTS
        "keep_alive": "20s",
    }).encode("utf-8")
    req = urllib.request.Request(OLLAMA_URL, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    return (d.get("message", {}).get("content") or "").strip()


def call_llm(prompt: str, retries: int = 4, timeout: int = 120) -> str:
    try:
        text = _ollama(prompt)
        if text:
            return text
    except Exception as e:  # noqa: BLE001
        print(f"   [LLM] ollama: {type(e).__name__}: {e}")

    last = ""
    for attempt in range(1, retries + 1):
        for fn in (_poll_openai, _poll_legacy):
            try:
                text = fn(prompt, timeout).strip()
                if text:
                    return text
                last = "пустой ответ (модель ушла в рассуждения)"
            except Exception as e:  # noqa: BLE001
                last = f"{type(e).__name__}: {e}"
        print(f"   [LLM] попытка {attempt}/{retries}: {last}")
        time.sleep(min(4 * attempt, 20))
    raise RuntimeError(last)


def llm_pack(facts: str, n: int) -> dict:
    """Один запрос к LLM вместо двух.

    Бесплатный тариф Pollinations отдаёт ~1 ответ в 30 секунд, поэтому два
    отдельных вызова (заголовки + мета) в одном запуске не проходят: второй
    получал 429. Здесь всё в одном ответе.
    """
    prompt = (
        f"Факты о новом видео: {facts}\n\n"
        f"Придумай {n} разных заголовков для YouTube Shorts на РУССКОМ языке строго "
        "по этим фактам: 40-85 символов, только реальные слова из фактов и обычные "
        "русские слова (без выдуманных названий и имён), интрига, в конце #shorts.\n\n"
        "Ответь строго в формате:\n"
        "TITLES:\n<заголовок>\n<заголовок>\n...\n"
        "DESCRIPTION: <описание видео из двух предложений на русском>\n"
        "HASHTAGS: <12 хэштегов под ЭТО видео через пробел: существительные и короткие "
        "фразы только из фактов выше, без общих слов вроде #видео #интересно>\n"
        "KEYWORDS: <10 русских слов через запятую>")
    text = call_llm(prompt)

    titles = []
    m = re.search(r"TITLES?:\s*(.+?)(?=\n\s*DESCRIPTION:|$)", text, re.DOTALL | re.IGNORECASE)
    block = m.group(1) if m else text
    for line in block.splitlines():
        line = re.sub(r"^\s*\d+[\.\)]\s*", "", line.strip())
        if valid_title(line):
            titles.append(norm_title(line))

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
    return {"titles": titles, "desc": desc, "hashtags": tags, "keywords": kw}


# ---------------------------------------------------------------------------
# Слова, которые не годятся в теги: слишком общие, ничего не дают поиску.
STOP_TAG_WORDS = {
    "видео", "кадры", "кадре", "ролик", "сцена", "сцене", "люди", "человек",
    "история", "новость", "новости", "сегодня", "который", "которая", "которое",
    "которые", "почему", "зачем", "такое", "очень", "просто",
}


# Категории, которые уместны у любого ролика этой темы, даже если слова нет
# дословно в брифе (модель часто предлагает их как осмысленную категорию).
GENERAL_TAG_STEMS = (
    "животн", "природ", "наук", "техно", "космо", "спорт", "здоров", "путеше",
    "культур", "интерес", "wildlife", "nature", "animal", "shorts", "short",
)


def build_tags(brief: str, llm_tags: list, keywords: list | None = None,
               best: str = "") -> list:
    """Теги ПОД КОНКРЕТНЫЙ ролик, а не из общего запаса.

    Основа — что предложила модель по фактам этого видео, потом ключевые слова
    ролика. Словарь тем остаётся только добавкой (и только если ключ реально
    встретился отдельным словом). Общих тегов-заглушек больше нет.
    """
    tags = ["#shorts"]
    src_text = re.sub(r"[^а-яёa-z0-9]", "", (brief + " " + (best or "")).lower())

    def ok(hashtag: str) -> bool:
        word = re.sub(r"[^а-яёa-z0-9]", "", str(hashtag).lower())
        if len(word) < 4 or word in STOP_TAG_WORDS:
            return False
        if any(word.startswith(stem) for stem in GENERAL_TAG_STEMS):
            return True
        # тег должен быть про этот ролик: его слово есть в теме/заголовке
        return word[:5] in src_text

    tags += [t for t in (llm_tags or []) if ok(t)]

    for word in (keywords or [])[:10]:
        if ok(word):
            tags.append("#" + re.sub(r"[^А-Яа-яЁёA-Za-z0-9\-]", "", str(word)))

    low = (brief + " " + (best or "")).lower()
    for key, extra in TOPIC_TAGS.items():
        if topic_match(low, key):
            tags += extra[:4]
            break

    seen, out = set(), []
    roots = set()
    for t in tags:
        t = str(t).strip()
        if not t:
            continue
        if not t.startswith("#"):
            t = "#" + t
        low = t.lower()
        root = re.sub(r"[^а-яёa-z0-9]", "", low)[:5]
        if len(t) < 3 or low in seen or root in roots:
            continue
        seen.add(low)
        roots.add(root)
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


def build_hashtags(brief: str, best: str, llm_tags: list | None = None) -> list:
    """2–3 РЕЛЕВАНТНЫХ хэштега (ORIGINALITY_GUIDE: без спама).

    Сначала берём то, что модель предложила под этот ролик, и только если она
    ничего не дала — словарь темы.
    """
    picked = [t for t in (llm_tags or []) if str(t).startswith("#")]
    if not picked:
        low = (brief + " " + best).lower()
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
        # Описание без служебных ярлыков брифа («Тема:», «Контекст:», «Сценарий:»):
        # раньше они попадали в текст описания YouTube как есть.
        clean = re.sub(r"^\s*(тема|контекст|сценарий|ссылка)\s*:\s*", "",
                       brief, flags=re.IGNORECASE | re.MULTILINE)
        clean = re.sub(r"\s+", " ", clean).strip()
        chunks = [s.strip() for s in re.split(r"(?<=[.!?])\s+", clean) if s.strip()]
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
def collect_candidates(brief: str, n: int, titles: list | None = None) -> list:
    """Кандидаты ПОД ТЕКУЩЕЕ видео: формулы от темы + заголовки от LLM.

    Пул title_pool.txt больше НЕ приоритет: его строки попадают в кандидаты,
    только если они про этот же ролик (совпало хотя бы одно слово темы) и ещё
    не использовались. Иначе каждый новый выпуск получал старый заголовок.
    """
    facts = title_facts(brief)
    used = load_used()
    cands = []

    for t in formula_titles(brief):
        cands.append((t, "formula"))

    for t in (titles or []):
        cands.append((t, "llm"))

    if POOL_FILE.exists():
        for line in POOL_FILE.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and valid_title(line):
                t = norm_title(line)
                if relevance(t, facts) >= 1:
                    cands.append((t, "pool"))

    # Никаких повторов: у каждого нового видео свой новый заголовок.
    fresh = [(t, s) for t, s in cands if t.lower() not in used]
    if fresh:
        cands = fresh
    elif cands:
        print(f"[WARN] все {len(cands)} кандидатов уже использовались — беру лучший из них")

    seen, uniq = set(), []
    for c, src in cands:
        if c.lower() not in seen:
            seen.add(c.lower())
            uniq.append((c, src))
    return uniq


def generate(brief: str, n: int = 7, use_llm: bool = True) -> dict:
    facts = title_facts(brief)
    pack = {"titles": [], "desc": "", "hashtags": [], "keywords": []}
    if use_llm:
        try:
            pack = llm_pack(facts, max(n, 7))
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] LLM недоступен ({e})")

    cands = collect_candidates(brief, n, titles=pack["titles"])
    if not cands:
        raise ValueError("нет ни одного валидного кандидата заголовка")
    scored = []
    for title, src in cands:
        rel = relevance(title, facts)
        # Релевантность фактам важнее «красивости»: раньше пул получал +1.0 и
        # старый заголовок про Lamborghini побеждал свежий про птицу.
        # Формульные хуки (собраны дословно из темы ролика) чуть впереди: у
        # бесплатной модели русский с опечатками, а тут слова гарантированно её.
        bonus = 0.8 if src == "formula" else 0.0
        total = round(heuristic_score(title) + bonus + 0.6 * min(rel, 3), 2)
        scored.append({"title": title, "source": src, "relevance": rel, "total": total})
    scored.sort(key=lambda x: x["total"], reverse=True)
    best = scored[0]["title"]
    mark_used(best)

    llm_desc, llm_tags, llm_kw = pack["desc"], pack["hashtags"], pack["keywords"]
    keywords = [k for k in llm_kw if re.fullmatch(r"[а-яё\-]+", k)][:20]

    hashtags = build_hashtags(brief, best, llm_tags)
    tags = build_tags(brief, llm_tags, keywords, best)
    note = sensitivity_note(brief + " " + best)

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
    print(f"[OK] Теги под ролик ({len(seo['tags'])}): {' '.join(seo['tags'])}")
    if seo.get("disclaimer"):
        print(f"[OK] Дисклеймер (чувствительная тема): {seo['disclaimer']}")
    print(f"[OK] Описание:\n{seo['description']}")
    print("\n--- Все кандидаты (балл | релевантность | источник) ---")
    for t in seo["candidates"]:
        print(f"  [{t['total']:>5}] rel={t.get('relevance', 0):<2} "
              f"({t.get('source', '?')}) {t['title']}")
    print(f"\n[OK] {TITLE_TXT} | {DESC_TXT} | {TAGS_TXT}")


if __name__ == "__main__":
    main()
