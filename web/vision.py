# -*- coding: utf-8 -*-
"""vision.py — что происходит в кадре.

Сценарий должен быть про видео, а не про заголовок поста. Поэтому перед
генерацией вытаскиваем несколько кадров и просим SmolVLM (256M, локально,
без ключей) описать, что происходит. Подписи переводим на русский.

Модель грузится лениво на время одной задачи и сразу выгружается: на той же
видеокарте работает F5-TTS, вместе им не хватает 4 ГБ.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

WEB = Path(__file__).resolve().parent
if str(WEB) not in sys.path:
    sys.path.insert(0, str(WEB))

from config import HF_CACHE  # noqa: E402

# Модель качается один раз в кэш (на Windows исторически — на диске D).
os.environ.setdefault("HF_HOME", str(HF_CACHE))

MODEL = "HuggingFaceTB/SmolVLM-256M-Instruct"
ASK = "What is happening in this picture? Answer in one short sentence."
FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"

# Основной путь — локальная модель через Ollama: SmolVLM-256M путает сюжет
# (на ролике «мужчина кормит медведя» выдавал «выдёргивают шерсть»), а 4B
# описывает кадр по-русски и по делу.
OLLAMA = "http://127.0.0.1:11434/api/chat"
OLLAMA_TAGS = "http://127.0.0.1:11434/api/tags"
OLLAMA_MODEL = os.environ.get("VISION_MODEL", "qwen3.5:4b")
OLLAMA_TIMEOUT = 240
OLLAMA_ASK = (
    "Опиши, что происходит на этих кадрах из одного видео. По-русски. "
    "Два или три предложения, только то, что видно: кто в кадре, что делает, "
    "где это. Не придумывай того, чего не видно."
)

APP = Path(__file__).resolve().parent
CACHE_FILE = APP / "data" / "vision.json"
FRAMES = (0.08, 0.36, 0.62, 0.88)   # начало, середина, конец ролика
MAX_FRAMES = 4

_lock = threading.Lock()        # модель: загрузка, инференс, выгрузка
_cache_lock = threading.Lock()  # кэш и список задач
_cache = None                   # key -> {"en":..., "ru":..., "ts":...}
_jobs = {}                      # key -> threading.Event

_model = None
_proc = None
_device = "cpu"
_dtype = None


# ------------------------------------------------------------------ кэш

def _load_cache() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    try:
        _cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        if not isinstance(_cache, dict):
            _cache = {}
    except (OSError, ValueError):
        _cache = {}
    return _cache


def _save_cache() -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_cache, ensure_ascii=False), encoding="utf-8")
        tmp.replace(CACHE_FILE)
    except OSError:
        pass


def _key(path: Path) -> str:
    st = path.stat()
    # модель в ключе: старое описание от SmolVLM не должно подхватываться
    raw = f"{path.resolve()}|{st.st_size}|{st.st_mtime_ns}|{OLLAMA_MODEL}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _cached(key: str):
    with _cache_lock:
        return _load_cache().get(key)


# ------------------------------------------------------------------ кадры

def _duration(path: Path) -> float:
    try:
        out = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        return max(0.0, float(out))
    except (ValueError, OSError, subprocess.SubprocessError):
        return 0.0


def _grab_frames(path: Path, key: str) -> list:
    total = _duration(path)
    marks = [f * total for f in FRAMES] if total > 0.8 else [0.0]
    out_dir = APP / "static" / "tmp"
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for i, sec in enumerate(marks[:MAX_FRAMES]):
        dst = out_dir / f"vframe_{key}_{i}.jpg"
        try:
            subprocess.run(
                [FFMPEG, "-y", "-loglevel", "error", "-ss", f"{sec:.2f}",
                 "-i", str(path), "-frames:v", "1", "-vf", "scale=512:-2",
                 str(dst)],
                capture_output=True, timeout=60, check=True,
            )
            if dst.exists() and dst.stat().st_size > 800:
                frames.append(dst)
        except (OSError, subprocess.SubprocessError):
            continue
    return frames


# ------------------------------------------------------------------ модель

def _ensure_model():
    global _model, _proc, _device, _dtype
    if _model is not None:
        return _proc, _model, _device
    import torch
    from transformers import AutoModelForVision2Seq, AutoProcessor

    if _proc is None:
        _proc = AutoProcessor.from_pretrained(MODEL)
        # в transformers 4.46 процессор SmolVLM требует согласованных размеров,
        # иначе ValueError про resolution_max_side
        try:
            _proc.image_processor.size = {"longest_edge": 512}
        except Exception:  # noqa: BLE001
            pass

    dtype = torch.float32
    device = "cpu"
    if torch.cuda.is_available():
        dtype, device = torch.bfloat16, "cuda"
    try:
        m = AutoModelForVision2Seq.from_pretrained(MODEL, torch_dtype=dtype)
        m = m.to(device)
    except Exception:  # noqa: BLE001 — не влезли в VRAM, работаем на CPU
        dtype, device = torch.float32, "cpu"
        m = AutoModelForVision2Seq.from_pretrained(MODEL, torch_dtype=dtype).to("cpu")
    m.eval()
    _model, _device, _dtype = m, device, dtype
    return _proc, _model, _device


def _release_model() -> None:
    global _model, _device
    if _model is None:
        return
    _model = None
    _device = "cpu"
    try:
        import torch
        torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass


def _caption(proc, model, device, frame: Path) -> str:
    import torch
    from PIL import Image

    img = Image.open(frame).convert("RGB")
    messages = [{"role": "user", "content": [{"type": "image"},
                                             {"type": "text", "text": ASK}]}]
    prompt = proc.apply_chat_template(messages, add_generation_prompt=True)
    inputs = proc(text=prompt, images=[img], return_tensors="pt")
    if device == "cuda":
        inputs = inputs.to(device, dtype=torch.bfloat16)
    else:
        inputs = inputs.to(device)
    with torch.no_grad():
        ids = model.generate(**inputs, max_new_tokens=40, do_sample=False)
    return proc.batch_decode(ids[:, inputs["input_ids"].shape[1]:],
                             skip_special_tokens=True)[0]


# ------------------------------------------------------------------ текст

_WORD = re.compile(r"[a-zа-яё']+")
_SERVICE = re.compile(
    r"^(in this (image|picture|photo)|this (image|picture|photo) shows|"
    r"the (image|picture|photo) (shows|depicts)|i can see|we can see)\b[:,]?\s*",
    re.I)


def _clean(text: str) -> str:
    text = " ".join((text or "").split()).strip(" .,;:!?\"'")
    text = _SERVICE.sub("", text).strip()
    if len(text) < 6:
        return ""
    words = _WORD.findall(text.lower())
    if len(words) < 3:
        return ""
    # маленькие модели иногда зацикливаются: «a car a car a car»
    if any(words.count(w) >= 3 for w in set(words)):
        return ""
    return text


def _merge(caps: list) -> str:
    out = []
    for cap in caps:
        cap = _clean(cap)
        if not cap:
            continue
        low = cap.lower()
        if any(low in seen.lower() or seen.lower() in low for seen in out):
            continue
        out.append(cap)
    return "; ".join(out)


def _describe_file(path: Path, key: str) -> dict | None:
    frames = _grab_frames(path, key)
    if not frames:
        return None
    try:
        # 1) локальная 4B-модель через Ollama — по-русски и по делу
        if _ollama_ready():
            try:
                ru = _describe_ollama(frames)
            except Exception as exc:  # noqa: BLE001
                print(f"[vision] ollama не ответил: {exc}", flush=True)
                ru = ""
            if ru and len(ru.split()) >= 8:
                return {"en": "", "ru": ru, "ts": time.time(), "src": "ollama"}

        # 2) запасной путь — SmolVLM + перевод
        caps = []
        with _lock:
            try:
                proc, model, device = _ensure_model()
                for frame in frames:
                    try:
                        caps.append(_caption(proc, model, device, frame))
                    except Exception as exc:  # noqa: BLE001
                        print(f"[vision] кадр не подписался: {exc}", flush=True)
            finally:
                _release_model()
        en = _merge(caps)
        if not en:
            return None
        ru = ""
        try:
            import translate
            ru = translate.translate_text(en)
        except Exception:  # noqa: BLE001
            ru = ""
        return {"en": en, "ru": ru or en, "ts": time.time()}
    finally:
        for frame in frames:
            try:
                frame.unlink()
            except OSError:
                pass


def _ollama_ready() -> bool:
    try:
        with urllib.request.urlopen(OLLAMA_TAGS, timeout=2) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def _describe_ollama(frames: list) -> str:
    """Один запрос со всеми кадрами: модель описывает сцену целиком."""
    import base64
    images = [base64.b64encode(f.read_bytes()).decode() for f in frames]
    body = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "think": False,
        "messages": [{"role": "user", "content": OLLAMA_ASK, "images": images}],
        "options": {"temperature": 0.2, "num_predict": 220, "num_ctx": 4096},
        # сразу отпускаем VRAM: на этой же карте потом работает F5-TTS
        "keep_alive": "20s",
    }
    req = urllib.request.Request(OLLAMA, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as r:
        d = json.loads(r.read().decode("utf-8", errors="replace"))
    return (d.get("message", {}).get("content") or "").strip()


# ------------------------------------------------------------------ API

def _work(path: Path, key: str, ev: threading.Event) -> None:
    try:
        res = _describe_file(path, key)
    except Exception as exc:  # noqa: BLE001
        print(f"[vision] не вышло: {exc}", flush=True)
        res = None
    with _cache_lock:
        if res:
            _load_cache()[key] = res
            _save_cache()
        _jobs.pop(key, None)
    ev.set()


def get(path) -> dict | None:
    """Готовое описание из кэша или None."""
    p = Path(path)
    try:
        return _cached(_key(p))
    except OSError:
        return None


def start(path) -> dict | None:
    """Запустить описание в фоне. -> готовое описание, если уже есть."""
    p = Path(path)
    if not p.exists() or p.stat().st_size < 10_000:
        return None
    key = _key(p)
    hit = _cached(key)
    if hit is not None:
        return hit
    with _cache_lock:
        if key not in _jobs:
            ev = threading.Event()
            _jobs[key] = ev
            threading.Thread(target=_work, args=(p, key, ev), daemon=True).start()
    return None


def describe(path, wait: float = 0.0) -> dict | None:
    """Описание видео: ждём до wait секунд, иначе что успело."""
    p = Path(path)
    hit = start(p)
    if hit is not None or wait <= 0:
        return hit
    ev = _jobs.get(_key(p))
    if ev is not None:
        ev.wait(wait)
    return get(p)


def text(path) -> str:
    """Русское описание кадра для промпта ('' если нет)."""
    res = get(path)
    return (res or {}).get("ru") or ""
