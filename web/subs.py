# -*- coding: utf-8 -*-
"""subs.py — распознавание речи и субтитры для нарезки.

Транскрипция делается один раз на всё исходное видео (faster-whisper,
word_timestamps=True), затем из общего списка слов собираются ASS для каждого
клипа — так не нужно гонять модель на каждый 45-секундный кусок.

Стили берутся из make_ass.py (classic/clean/neon/min/cinema), чтобы нарезка
выглядела так же, как ролики основного конвейера.
"""

from __future__ import annotations

import os
import re
import sys
import threading
from pathlib import Path

WEB = Path(__file__).resolve().parent
if str(WEB) not in sys.path:
    sys.path.insert(0, str(WEB))

from config import VP  # noqa: E402

if str(VP) not in sys.path:
    sys.path.insert(0, str(VP))

from make_ass import KEY_WORDS, STYLES, seconds_to_ass_time  # noqa: E402

_model = None
_model_lock = threading.Lock()


def _load_model():
    """Ленивая загрузка faster-whisper (модель живёт в памяти процесса)."""
    global _model
    with _model_lock:
        if _model is not None:
            return _model

        from faster_whisper import WhisperModel  # type: ignore

        name = os.environ.get("WHISPER_MODEL", "small").strip() or "small"
        local_dir = os.environ.get("WHISPER_MODEL_DIR", "").strip()
        device = os.environ.get("WHISPER_DEVICE", "").strip()
        compute = os.environ.get("WHISPER_COMPUTE", "").strip()

        if not device:
            device = "cpu"
            try:
                import ctranslate2  # type: ignore
                if ctranslate2.get_cuda_device_count() > 0:
                    device = "cuda"
            except Exception:  # noqa: BLE001
                pass
        if not compute:
            compute = "float16" if device == "cuda" else "int8"

        try:
            _model = WhisperModel(local_dir or name, device=device, compute_type=compute)
        except Exception as exc:  # noqa: BLE001
            if device != "cuda":
                raise
            # CUDA-библиотек может не быть — тихо уходим на CPU
            print(f"[SUBS] CUDA недоступна ({exc}), перехожу на CPU", flush=True)
            device, compute = "cpu", "int8"
            _model = WhisperModel(local_dir or name, device=device, compute_type=compute)
        print(f"[SUBS] модель {name} на {device}/{compute}", flush=True)
        return _model


def transcribe_words(path: Path, language: str | None = None) -> list:
    """-> [(start, end, word), ...] в секундах исходного видео."""
    model = _load_model()
    lang = language or os.environ.get("WHISPER_LANG", "").strip() or None
    segments, _info = model.transcribe(
        str(path), language=lang, word_timestamps=True,
        vad_filter=True, beam_size=1, condition_on_previous_text=False,
    )
    words = []
    for seg in segments:
        for w in (getattr(seg, "words", None) or []):
            text = (w.word or "").strip()
            if text:
                words.append((float(w.start), float(w.end), text))
    return words


def _is_key_word(word: str) -> bool:
    w = word.lower().strip(".,!?;:«»\"'()")
    if any(c.isdigit() for c in word):
        return True
    if w in KEY_WORDS:
        return True
    if word and word[0].isupper():
        return True
    return any(c in w for c in ("евро", "доллар", "тыс", "млн", "млрд"))


def _esc(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")")


def _style_block(st: dict, margin_v: int) -> str:
    out = ""
    for name, color in (("WordWhite", st["white"]), ("WordRed", st["key"] or st["white"])):
        out += (f"Style: {name},{st['font']},{st['size']},{color},{color},"
                f"{st['outline_color']},&H80000000,{st['bold']},0,0,0,100,100,"
                f"{st['spacing']},0,1,{st['outline']},{st['shadow']},2,0,0,{margin_v},1\n")
    return out


def build_clip_ass(words: list, clip_start: float, clip_end: float, style: str,
                   out_path: Path, margin_v: int = 400) -> int:
    """Собрать ASS для клипа [clip_start, clip_end]. -> число слов (0 = пусто)."""
    st = STYLES.get(style) or STYLES["classic"]

    # слова, чья середина попала в клип
    picked = []
    for start, end, text in words:
        mid = (start + end) / 2
        if clip_start - 0.05 <= mid <= clip_end + 0.05:
            s = max(0.0, start - clip_start)
            e = max(s + 0.08, min(end - clip_start, clip_end - clip_start))
            picked.append((s, e, text))
    if not picked:
        return 0

    ass = (
        "[Script Info]\n"
        "Title: clip subtitles\n"
        "ScriptType: v4.00+\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        f"PlayResX: 1080\nPlayResY: 1920\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
        "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding\n"
    )
    ass += _style_block(st, margin_v)
    ass += ("\n[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")

    for start, end, text in picked:
        sname = "WordRed" if (st["key"] and _is_key_word(text)) else "WordWhite"
        ass += (f"Dialogue: 0,{seconds_to_ass_time(start)},{seconds_to_ass_time(end)},"
                f"{sname},,0,0,0,,{st['tags']}{_esc(text)}\n")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(ass, encoding="utf-8")
    return len(picked)
