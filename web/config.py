# -*- coding: utf-8 -*-
"""config.py — единая точка настройки путей проекта.

По умолчанию используются исторические пути Windows (D:\\AI\\...), поэтому на
рабочей машине ничего не меняется. Если такого каталога нет (свежий клон
репозитория, Linux, Docker, HuggingFace Spaces) — берём путь относительно
репозитория, чтобы сервер запускался из любого места.

Переопределение через переменные окружения (см. .env.example):
    VIDEO_PIPELINE_DIR — корень пайплайна (auto_news.py, reddit_dl.py, output/)
    F5TTS_DIR          — каталог F5-TTS (say_f5.py, stt.py, models/)
                         (синонимы: F5_TTS_DIR, F5_DIR)
    PIPELINE_PYTHON    — интерпретатор для сабпроцессов конвейера
    FFMPEG_PATH        — путь к ffmpeg (по умолчанию — из PATH)
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parent
REPO_ROOT = WEB.parent


def _env_path(*names: str) -> "Path | None":
    """Первая непустая переменная окружения среди names (как Path)."""
    for name in names:
        raw = os.environ.get(name)
        if raw and raw.strip():
            return Path(raw.strip()).expanduser().resolve()
    return None


def _existing_dir(default: Path, fallback: Path) -> Path:
    return default if default.is_dir() else fallback


# Корень пайплайна: скрипты, output/, brief.txt
VP = _env_path("VIDEO_PIPELINE_DIR") or _existing_dir(
    Path(r"D:\AI\VIDEO_PIPELINE"), REPO_ROOT)

# F5-TTS: модели, say_f5.py, stt.py, референсы голосов
F5 = _env_path("F5TTS_DIR", "F5_TTS_DIR", "F5_DIR") or _existing_dir(
    Path(r"D:\AI\F5-TTS"), REPO_ROOT / "F5-TTS")


def _python() -> str:
    env = os.environ.get("PIPELINE_PYTHON", "").strip()
    if env:
        return str(Path(env).expanduser())
    legacy = Path(r"D:\AI\python310\python.exe")
    return str(legacy) if legacy.is_file() else sys.executable


# Интерпретатор, которым запускаются auto_news.py / say_f5.py / stt.py
PY = _python()


def _ffmpeg() -> str:
    env = os.environ.get("FFMPEG_PATH", "").strip()
    if env:
        return env
    legacy = Path(r"C:\Users\nasle\tools\ffmpeg\ffmpeg.exe")
    return str(legacy) if legacy.is_file() else (shutil.which("ffmpeg") or "ffmpeg")


FFMPEG = _ffmpeg()


def _ffprobe() -> str:
    env = os.environ.get("FFPROBE_PATH", "").strip()
    if env:
        return env
    legacy = Path(r"C:\Users\nasle\tools\ffmpeg\ffprobe.exe")
    if legacy.is_file():
        return str(legacy)
    if FFMPEG and os.path.sep in FFMPEG:
        sibling = Path(FFMPEG).with_name("ffprobe" + (".exe" if os.name == "nt" else ""))
        if sibling.is_file():
            return str(sibling)
    return shutil.which("ffprobe") or "ffprobe"


FFPROBE = _ffprobe()

# Кэш моделей HuggingFace (SmolVLM и пр.)
HF_CACHE = _env_path("HF_HOME") or _existing_dir(
    Path(r"D:\AI\hf_cache"), REPO_ROOT / ".cache" / "hf")
