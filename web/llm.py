# -*- coding: utf-8 -*-
"""llm.py — бесплатный LLM через Pollinations (без API-ключа).

Используется для:
  • генерации сценария новости по постфакту из Reddit;
  • предложения вариантов сценариев;
  • проверки/починки сценария.

Тот же провайдер уже используется в seo.py — новых ключей и подписок не нужно.

Бесплатный тариф без токена работает только с моделью ``openai-fast``.
Основной транспорт — OpenAI-совместимый ``POST /openai``; старый
``GET /{prompt}`` оставлен как запасной путь, потому что он периодически
отдаёт 402/429/timeout.
"""

import json
import random
import re
import time
import urllib.parse
import urllib.request

BASE = "https://text.pollinations.ai/"
OPENAI_URL = BASE + "openai"

# на бесплатном тарифе без ключа работает только openai-fast;
# остальные модели отвечают 402 (нужен токен)
MODEL = "openai-fast"
TIMEOUT = 100
RETRIES = 3

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36",
    "Accept": "text/plain, application/json, */*",
}

JSON_HINT = "\n\nОТВЕТЬ ТОЛЬКО ВАЛИДНЫЙ JSON, БЕЗ ПОЯСНЕНИЙ И БЕЗ БЛОКА ```."


def _unwrap(raw: str) -> str:
    """Достать текст ответа из разных обёрток Pollinations."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    if raw.startswith("{"):
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            return raw
        # OpenAI-совместимый ответ
        try:
            ch = d["choices"][0]["message"]
            if isinstance(ch, dict):
                content = ch.get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()
        except (KeyError, IndexError, TypeError):
            pass
        # плоская обёртка {"response": "..."}
        for key in ("response", "message", "content", "text", "output"):
            if isinstance(d.get(key), str) and d[key].strip():
                return d[key].strip()
        # модель ушла в рассуждения и не дошла до content — ответа нет
        if "reasoning" in d or "tool_calls" in d:
            return ""
        return raw
    return raw


def _ask_openai(prompt: str, model: str, timeout: int) -> str:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "seed": random.randint(1, 10 ** 9),
        # без этого модель уходит в рассуждения и не отдаёт content:
        # ответ обрывается на reasoning, а сам JSON так и не появляется
        "reasoning_effort": "low",
    }).encode("utf-8")
    req = urllib.request.Request(OPENAI_URL, data=body, headers={
        **HEADERS,
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", errors="replace")
    return _unwrap(raw)


def _ask_legacy(prompt: str, model: str, timeout: int) -> str:
    url = (BASE + urllib.parse.quote(prompt)
           + "?" + urllib.parse.urlencode({
               "model": model,
               "seed": random.randint(1, 10 ** 9),
           }))
    req = urllib.request.Request(url, headers=dict(HEADERS))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", errors="replace")
    return _unwrap(raw)


def ask(prompt: str, model: str = MODEL, timeout: int = TIMEOUT,
        json_mode: bool = False, retries: int = RETRIES) -> str:
    """Один запрос к LLM. Возвращает текст ответа (пустая строка при ошибке).

    Бесплатный тариф Pollinations периодически отвечает 402/429/404 —
    поэтому пробуем несколько раз и два разных транспорта.
    """
    if json_mode:
        prompt = prompt + JSON_HINT

    last = ""
    for attempt in range(1, retries + 1):
        for name, fn in (("openai", _ask_openai), ("legacy", _ask_legacy)):
            try:
                text = fn(prompt, model, timeout)
                if text:
                    return text
                last = f"{name}: пустой ответ"
            except Exception as exc:  # noqa: BLE001
                last = f"{name}: {type(exc).__name__}: {exc}"
        print(f"[LLM] попытка {attempt}/{retries}: {last}", flush=True)
        # 402 = исчерпан лимит бесплатного тарифа, 429 = слишком частые запросы
        time.sleep(min(4 * attempt, 20))

    print(f"[LLM] не ответил: {last}", flush=True)
    return ""


def _clean(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```[a-z]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def ask_json(prompt: str, model: str = MODEL, timeout: int = TIMEOUT,
             attempts: int = 3) -> dict | None:
    """Запрос с ожиданием JSON. Модель иногда обрывает ответ — пробуем ещё."""
    for attempt in range(1, attempts + 1):
        raw = ask(prompt, model=model, timeout=timeout, json_mode=True)
        if not raw:
            continue
        raw = _clean(raw)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"[\{\[].*[\}\]]", raw, re.S)
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError:
                    pass
        print(f"[LLM] ответ не JSON (попытка {attempt}/{attempts})", flush=True)
    return None


# ------------------------------------------------------------------ промпты
#
# Модель бесплатного тарифа плохо держит длинный JSON с кириллицей: кавычки
# в тексте ломают экранирование и ответ приходит невалидным. Поэтому просим
# простой текстовый формат с маркерами, а разбираем его регуляркой.

GRAMMAR = """Требования к тексту озвучки:
- 60–140 слов (это 25–50 секунд речи).
- Первые 3 секунды — ХУК: вопрос или интригующая фраза, которая цепляет.
- Дальше — АНАЛИТИКА: свой вывод, почему это важно. Не пересказ новости.
- В конце — ПРОГНОЗ: к чему это приведёт.
- Один абзац, живой разговорный язык, без канцелярита.
- Без тире, двоеточий, многоточий, скобок, эмодзи, хештегов и обращений к зрителю.
- Числа — словами.
- Не рассуждай и не объясняй, сразу пиши готовый текст."""

SCENARIO_PROMPT = """Ты редактор новостного YouTube-Shorts на русском. Канал «ГУСЬ ПЕРЕВОДИЛА».

Напиши сценарий озвучки к короткому новостному ролику.

Тема: {title}
Контекст: {context}

{grammar}

Формат ответа, ровно две строки:
ЗАГОЛОВОК: короткая цепляющая фраза до 60 символов
ТЕКСТ: сценарий одним абзацем"""

VARIANTS_PROMPT = """Ты редактор новостного YouTube-Shorts на русском. Канал «ГУСЬ ПЕРЕВОДИЛА».

Тема ролика: {topic}

Придумай 3 РАЗНЫХ сценария на эту тему. Разный угол, разный хук, разный вывод.

{grammar}

Формат ответа: три блока, между блоками строка из трёх знаков равенства.
В каждом блоке ровно две строки:
ЗАГОЛОВОК: короткая фраза до 60 символов
ТЕКСТ: сценарий одним абзацем"""

_CLEAN_WS = re.compile(r"[ \t]+")
_FIELD = re.compile(r"^\s*(?:[#*\-\s]*)"
                    r"(ЗАГОЛОВОК|ТЕКСТ|СЦЕНАРИЙ|HOOK|ХУК)\s*\d*\s*:?\s*(.*)$",
                    re.I)


def _usable(text: str) -> bool:
    """Отсечь служебные обёртки модели и обрывки."""
    low = text.lower()
    if '"reasoning"' in low or '"tool_calls"' in low or '"choices"' in low:
        return False
    if text.count("{") != text.count("}"):
        return False
    return len(text.split()) >= 20


def _parse_blocks(raw: str) -> list:
    """Разобрать ответ вида «ЗАГОЛОВОК: ... / ТЕКСТ: ...», разделённый ===."""
    raw = _clean(raw)
    raw = raw.replace("**", "").replace("__", "")
    if not _usable(raw):
        return []
    parts = re.split(r"^\s*={3,}\s*$", raw, flags=re.M)
    if len(parts) < 2:
        # модель не поставила === — режем по началу каждого блока
        parts = re.split(r"(?=^\s*ЗАГОЛОВОК\s*:)", raw, flags=re.M | re.I)
    out = []
    for block in parts:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        title = ""
        script_lines = []
        mode = ""
        for line in lines:
            m = _FIELD.match(line)
            if m:
                key, val = m.group(1).upper(), m.group(2).strip()
                if key == "ЗАГОЛОВОК":
                    if not title:
                        title = val
                    mode = ""
                    continue
                mode = "script"
                if val:
                    script_lines.append(val)
                continue

            if mode == "script":
                script_lines.append(line)
            elif not title and len(line) <= 90:
                # блок без маркеров: первая строка — заголовок, дальше текст
                title = line
                mode = "script"
            else:
                mode = "script"
                script_lines.append(line)

        script = _CLEAN_WS.sub(" ", " ".join(script_lines)).strip()
        script = re.sub(r"\s+([,.;:!?])", r"\1", script)
        if _usable(script) and len(script.split()) <= 220:
            out.append({"title": title, "script": script})
    return out


def generate_scenario(title: str, context: str = "", model: str = MODEL) -> dict | None:
    """Сгенерировать сценарий под тему. -> {"title":..., "script":...} или None"""
    prompt = SCENARIO_PROMPT.format(title=title, context=context or "нет",
                                    grammar=GRAMMAR)
    for attempt in range(3):
        raw = ask(prompt, model=model)
        if not raw:
            continue
        blocks = _parse_blocks(raw)
        if blocks:
            b = blocks[0]
            return {"title": (b["title"] or title).strip(),
                    "script": b["script"]}
        # модель могла ответить просто абзацем без маркеров
        text = _clean(raw)
        text = re.sub(r"^\s*(ЗАГОЛОВОК|ТЕКСТ|СЦЕНАРИЙ)\s*:.*$", "",
                      text, flags=re.M)
        text = _CLEAN_WS.sub(" ", text).strip()
        if _usable(text) and 40 <= len(text.split()) <= 220:
            return {"title": title, "script": text}
        print(f"[LLM] сценарий не разобрался (попытка {attempt + 1}/3)",
              flush=True)
    return None


def generate_variants(topic: str, model: str = MODEL) -> list:
    prompt = VARIANTS_PROMPT.format(topic=topic, grammar=GRAMMAR)
    for attempt in range(3):
        raw = ask(prompt, model=model)
        if not raw:
            continue
        blocks = _parse_blocks(raw)
        if len(blocks) >= 2:
            return blocks[:3]
        print(f"[LLM] варианты не разобрались (попытка {attempt + 1}/3): "
              f"блоков {len(blocks)}", flush=True)
    # запасной путь: собрать варианты отдельными запросами
    out = []
    for i in range(3):
        one = generate_scenario(f"{topic} (вариант {i + 1})", model=model)
        if one and _usable(one["script"]):
            out.append(one)
    return out
