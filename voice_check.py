#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""voice_check.py — проверка озвучки: совпадает ли распознанная речь со сценарием.

Зачем: F5-TTS на длинном тексте иногда теряет/глотает концовку. Внешне это
выглядит как «короткий ролик с непонятными словами»: монтаж подгоняется под
аудио, а субтитры делаются по аудио (Whisper) — и тоже получаются кривыми.

Здесь мы распознаём готовый voiceover и сравниваем слова со сценарием:
    • покрытие слов (сколько слов сценария реально прозвучало);
    • хвост сценария (последние слова — их F5 теряет чаще всего).

Код возврата 1 — озвучка плохая, auto_news не должен собирать такой ролик.

Пример:
    python voice_check.py --wav D:\\AI\\F5-TTS\\out\\voiceover.wav ^
        --script D:\\AI\\F5-TTS\\script_clean.txt --min-coverage 90
"""

import argparse
import difflib
import os
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WORD_RE = re.compile(r"[А-Яа-яЁёA-Za-z0-9]+")


def norm(word: str) -> str:
    return word.lower().replace("ё", "е")


def words(text: str) -> list:
    return [norm(w) for w in WORD_RE.findall(text or "")]


def _model_settings() -> tuple:
    name = os.environ.get("WHISPER_MODEL", "small").strip() or "small"
    local = os.environ.get("WHISPER_MODEL_DIR", "").strip()
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
    return local or name, device, compute


def asr_faster_whisper(wav: Path):
    """Основной путь: faster-whisper (он же стоит для субтитров нарезки)."""
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except Exception:  # noqa: BLE001
        return None

    model_name, device, compute = _model_settings()
    lang = os.environ.get("WHISPER_LANG", "").strip() or None
    try:
        model = WhisperModel(model_name, device=device, compute_type=compute)
        segments, _ = model.transcribe(
            str(wav), language=lang, vad_filter=True, beam_size=1,
            condition_on_previous_text=False,
        )
        return " ".join(s.text.strip() for s in segments if s.text).strip()
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] faster-whisper не смог: {exc}")
        return None


def asr_stt(wav: Path):
    """Запасной путь: stt.py из F5-TTS (классический Whisper -> SRT)."""
    py = os.environ.get("PIPELINE_PYTHON", "").strip() or sys.executable
    f5 = Path(os.environ.get("F5TTS_DIR", "").strip() or r"D:\AI\F5-TTS")
    stt = f5 / "stt.py"
    if not stt.exists():
        return None
    srt = Path(wav).with_suffix(".check.srt")
    cmd = [py, str(stt), "--audio", str(wav), "--srt", str(srt)]
    try:
        subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=1800)
    except subprocess.TimeoutExpired:
        return None
    if not srt.exists():
        return None
    raw = srt.read_text(encoding="utf-8", errors="replace")
    srt.unlink(missing_ok=True)
    lines = [ln.strip() for ln in raw.splitlines()
             if ln.strip() and "-->" not in ln and not ln.strip().isdigit()]
    return " ".join(lines).strip() or None

def coverage(script: list, asr: list) -> float:
    """Доля слов сценария, найденных в распознанном тексте (по порядку)."""
    if not script:
        return 1.0
    matcher = difflib.SequenceMatcher(a=script, b=asr, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    return matched / len(script)


def missing_words(script: list, asr: list, limit: int = 15) -> list:
    pool = list(asr)
    missing = []
    for word in script:
        if word in pool:
            pool.remove(word)
        elif len(missing) < limit:
            missing.append(word)
    return missing


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", required=True, help="озвучка (voiceover.wav)")
    ap.add_argument("--script", required=True, help="очищенный сценарий (script_clean.txt)")
    ap.add_argument("--min-coverage", type=float, default=90.0,
                    help="минимальное покрытие слов сценария, %%")
    ap.add_argument("--min-tail", type=float, default=60.0,
                    help="минимальное покрытие последних слов сценария, %%")
    ap.add_argument("--warn-only", action="store_true",
                    help="не падать, только предупредить")
    a = ap.parse_args()

    wav = Path(a.wav)
    script_path = Path(a.script)
    if not wav.exists():
        print(f"[ERROR] нет файла озвучки: {wav}")
        return 0 if a.warn_only else 1
    if not script_path.exists():
        print(f"[ERROR] нет сценария: {script_path}")
        return 0 if a.warn_only else 1

    script_words = words(script_path.read_text(encoding="utf-8-sig"))
    if not script_words:
        print("[WARN] сценарий пустой — проверять нечего")
        return 0

    text = asr_faster_whisper(wav) or asr_stt(wav)
    if text is None:
        print("[WARN] ASR недоступен (нет faster-whisper и stt.py) — проверка пропущена")
        return 0

    asr_words = words(text)
    cov = coverage(script_words, asr_words) * 100.0
    tail_n = min(8, len(script_words))
    tail_cov = coverage(script_words[-tail_n:],
                        asr_words[-max(16, tail_n * 2):]) * 100.0

    duration = 0.0
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=noprint_wrappers=1:nokey=1", str(wav)],
                           capture_output=True, text=True)
        duration = float(r.stdout.strip())
    except (ValueError, OSError):
        pass

    print(f"[VOICE] озвучка: {duration:.1f} c | слов в сценарии: {len(script_words)} | "
          f"распознано: {len(asr_words)}")
    print(f"[VOICE] покрытие: {cov:.1f}% (порог {a.min_coverage:.0f}%) | "
          f"хвост: {tail_cov:.1f}% (порог {a.min_tail:.0f}%)")

    if cov >= a.min_coverage and tail_cov >= a.min_tail:
        print("[OK] озвучка совпадает со сценарием")
        return 0

    print("[ERROR] озвучка не совпадает со сценарием.")
    miss = missing_words(script_words, asr_words)
    if miss:
        print("[ERROR] не прозвучали слова: " + ", ".join(miss))
    if tail_cov < a.min_tail:
        print("[ERROR] потерян конец сценария — F5-TTS часто «съедает» хвост "
              "на длинном тексте.")
        print("        Что делать: перегенерировать озвучку, сократить сценарий "
              "или разбить его на короткие фразы (say_f5_checked.py).")
    if a.warn_only:
        print("[WARN] --warn-only: продолжаю несмотря на провал проверки")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
