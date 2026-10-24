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
import os
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

# Локальная модель через Ollama лучше держит русский, чем бесплатный
# openai-fast (тот на длинных промптах выдаёт словесный салат).
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
OLLAMA_TAGS = "http://127.0.0.1:11434/api/tags"
OLLAMA_TIMEOUT = 300
# Порядок важен: gemma3:4b на этом промпте уходит в фантазии (пингвин с книгой),
# qwen3.5:4b держится фактов — с него и начинаем.
LOCAL_PREFER = ("qwen3.5:4b", "qwen2.5:latest", "gemma3:4b")
_local_model = None
_local_checked = False

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


def _local_model_name() -> str:
    """Какая локальная модель доступна в Ollama ('' если сервера нет)."""
    global _local_model, _local_checked
    if _local_checked:
        return _local_model or ""
    _local_checked = True
    try:
        with urllib.request.urlopen(OLLAMA_TAGS, timeout=2) as r:
            names = [m.get("name", "") for m in json.loads(
                r.read().decode("utf-8", errors="replace")).get("models", [])]
    except Exception:  # noqa: BLE001
        names = []
    for pref in LOCAL_PREFER:
        if pref in names:
            _local_model = pref
            break
    else:
        _local_model = names[0] if names else ""
    if _local_model:
        print(f"[LLM] локальная модель: {_local_model}", flush=True)
    return _local_model


def _ask_ollama(prompt: str, timeout: int = OLLAMA_TIMEOUT,
                temperature: float = 0.75, num_predict: int = 420,
                keep_alive: str = "5m") -> str:
    model = _local_model_name()
    if not model:
        return ""
    body = {
        "model": model,
        "stream": False,
        "think": False,
        "messages": [{"role": "user", "content": prompt}],
        "options": {"temperature": temperature, "num_predict": num_predict,
                    "num_ctx": 4096},
        "keep_alive": keep_alive,
    }
    req = urllib.request.Request(OLLAMA_URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8", errors="replace"))
    return (d.get("message", {}).get("content") or "").strip()


# Черновик 4B-модели почти всегда с парой ошибок в падежах. Отдельный
# проход «только грамматика» их вычищает и не трогает смысл (проверено).
_POLISH_PROMPT = """Исправь в тексте только грамматику: падежи, согласование, запятые. Смысл, порядок фраз и длину не меняй, ничего не добавляй и не сокращай.
Верни только исправленный текст, без пояснений.

{text}"""


def _polish(text: str) -> str:
    if not text:
        return text
    try:
        out = _ask_ollama(_POLISH_PROMPT.format(text=text), temperature=0.2,
                          num_predict=400, keep_alive="20s")
    except Exception as exc:  # noqa: BLE001
        print(f"[LLM] вычитка не удалась: {type(exc).__name__}: {exc}", flush=True)
        return text
    out = _clean(out).replace("**", "").strip()
    if not out:
        return text
    src, got = len(text.split()), len(out.split())
    # вычитка не должна переписывать текст заново
    if got < src * 0.7 or got > src * 1.35:
        print(f"[LLM] вычитка изменила длину ({src} -> {got}), оставляю черновик",
              flush=True)
        return text
    return _CLEAN_WS.sub(" ", out).strip()


def ask(prompt: str, model: str = MODEL, timeout: int = TIMEOUT,
        json_mode: bool = False, retries: int = RETRIES) -> str:
    """Один запрос к LLM. Возвращает текст ответа (пустая строка при ошибке).

    Сначала пробуем локальную модель (без лимитов и по-русски лучше), потом
    бесплатный Pollinations. JSON-режим — только Pollinations.
    """
    if json_mode:
        prompt = prompt + JSON_HINT
    else:
        try:
            text = _ask_ollama(prompt)
            if text:
                return text
        except Exception as exc:  # noqa: BLE001
            print(f"[LLM] ollama: {type(exc).__name__}: {exc}", flush=True)

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
# Бесплатная модель (GPT-OSS 20B) не держит длинный список правил: начинается
# «словесный салат» (проверено 24.10.2026 на живом ролике). Работает обратное:
# короткий промпт и один готовый пример, один сценарий на запрос.

EXAMPLE = """ЗАГОЛОВОК: Бобёр валит дерево за секунду
ТЕКСТ: В кадре бобёр перегрызает ствол и дерево падает за пару секунд. Зачем ему столько силы? Так он строит плотину и поднимает уровень воды, чтобы нора оставалась недоступной. Чем больше таких плотин, тем сильнее меняется русло реки. Если бобры продолжат заселять новые места, через десять лет карта местных рек будет другой."""

_LINE_FORMAT = """Напиши так же 70-90 слов, это обязательный объём. Первая фраза про то, что видно в кадре. Вторая фраза — вопрос, который цепляет, и в конце обязательно знак вопроса. Больше вопросов в тексте не задавай.
Потом объясни смысл. В конце — утверждение о том, к чему это приведёт, а не вопрос.
Вопрос задавай прямо от себя, а не пересказывай его словами вроде человек спрашивает.
Не придумывай того, чего нет в кадре и заголовке. Если не знаешь, кто этот человек, называй его просто человек.
Не обращайся к зрителю, никаких вы, давайте и представьте.
Без тире, двоеточий и скобок. Формат ответа ровно две строки:
ЗАГОЛОВОК: до 50 символов, без выдуманных профессий
ТЕКСТ: сценарий одним абзацем"""

SCENARIO_PROMPT = """Ты пишешь текст озвучки для YouTube Shorts на русском. Пиши так, как в примере.

Пример:
{example}

Тема ролика: {title}
Контекст: {context}

{lines}"""

# Сценарий пишется по видеоряду, а не по одному заголовку: иначе модель
# придумывает сюжет, которого в ролике нет.

GROUNDED_PROMPT = """Ты пишешь текст озвучки для YouTube Shorts на русском. Пиши так, как в примере.

Пример:
{example}

Ролик:
В кадре: {video}
Заголовок поста: {title}
Сабреддит: {sub}
Текст поста: {context}

{lines}
Если описание кадров противоречит заголовку поста, верь заголовку."""

_VARIANT_ANGLES = (
    "",
    "Начни со сравнения, которое цепляет.",
)

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


_STOP = {
    "этот", "этого", "этому", "этим", "который", "которая", "которое",
    "которые", "потому", "поэтому", "когда", "только", "чтобы", "если",
    "очень", "просто", "даже", "всегда", "никогда", "можно", "нельзя",
    "каждый", "своих", "своими", "такой", "такая", "такое", "такие",
    "будет", "будут", "бывает", "становится", "оказывается",
}


def _content_words(text: str) -> list:
    """Значимые слова для проверки «текст про то же самое»."""
    words = re.findall(r"[а-яё]{5,}", (text or "").lower())
    return [w for w in words if w not in _STOP]


def _same_topic(script: str, title: str, video: str, context: str) -> bool:
    """Пересечение по корням с фактами поста. Грубо, зато без словаря."""
    facts = {w[:5] for w in _content_words(f"{title} {video} {context}")}
    if not facts:
        return True
    got = {w[:5] for w in _content_words(script)}
    return bool(facts & got)


def _validate(script: str, title: str, video: str, context: str) -> str:
    """"" если сценарий годный, иначе причина отказа."""
    n = len(script.split())
    if n < 40:
        return "слишком короткий"
    if n > 170:
        return "слишком длинный"
    low = script.lower()
    for bad in ("как языковая модель", "не могу", "вот сценарий", "вот текст"):
        if bad in low:
            return "служебный ответ"
    if "?" not in script:
        return "в хуке нет вопроса"
    if not _same_topic(script, title, video, context):
        return "не про этот ролик"
    return ""


def _build_prompt(title: str, context: str, video: str, sub: str,
                  extra: str = "") -> str:
    if video or context:
        prompt = GROUNDED_PROMPT.format(
            example=EXAMPLE, title=title or "нет", sub=sub or "нет",
            context=(context or "нет")[:900],
            video=video or "нет описания", lines=_LINE_FORMAT)
    else:
        prompt = SCENARIO_PROMPT.format(
            example=EXAMPLE, title=title or "нет",
            context=context or "нет", lines=_LINE_FORMAT)
    return prompt + ("\n" + extra if extra else "")


def _one(title: str, context: str, video: str, sub: str, model: str,
         extra: str = "") -> dict | None:
    prompt = _build_prompt(title, context, video, sub, extra)
    last = None
    for attempt in range(2):
        raw = ask(prompt, model=model)
        if not raw:
            continue
        blocks = _parse_blocks(raw)
        if blocks:
            b = blocks[0]
            script, ttl = b["script"], (b["title"] or title).strip()
        else:
            # ответ без маркеров: считаем всё текстом сценария
            text = _clean(raw)
            text = re.sub(r"^\s*(ЗАГОЛОВОК|ТЕКСТ|СЦЕНАРИЙ)\s*:.*$", "",
                          text, flags=re.M)
            script = _CLEAN_WS.sub(" ", text).strip()
            ttl = title
        if not script:
            continue
        last = {"title": ttl, "script": script}
        why = _validate(script, title, video, context)
        if not why:
            return {"title": ttl, "script": _polish(script)}
        print(f"[LLM] {why} (попытка {attempt + 1}/2)", flush=True)
    # Не отдаём мусор: лучше пусто, чем текст не про тот ролик
    if last:
        print(f"[LLM] отбраковал сценарий: {last['script'][:80]}...", flush=True)
    return None


def generate_scenario(title: str, context: str = "", video: str = "",
                      sub: str = "", model: str = MODEL) -> dict | None:
    """Сгенерировать сценарий под тему. -> {"title":..., "script":...} или None"""
    return _one(title, context, video, sub, model)


def generate_variants(topic: str, context: str = "", video: str = "",
                      sub: str = "", model: str = MODEL) -> list:
    """Три варианта — тремя отдельными запросами (три за раз модель валит)."""
    out = []
    for angle in _VARIANT_ANGLES:
        if out:
            time.sleep(4)      # бесплатный тариф душит частые запросы
        one = _one(topic, context, video, sub, model, extra=angle)
        if one and _usable(one["script"]):
            out.append(one)
    return out
