#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""say_f5_checked.py — озвучка F5-TTS с ПОФРАЗНОЙ генерацией и проверкой.

Зачем: F5-TTS на длинном тексте (800+ символов) теряет/глотает концы фраз,
и хвост озвучки обрывается. Здесь текст бьётся на короткие фразы, каждая
генерируется отдельно, склеивается через ffmpeg, а затем проверяется:

  1) покрытие слов ASR-транскрипта vs сценарий (цель >= 95%);
  2) последняя фраза сценария присутствует в конце транскрипта;
  3) ударения в voice.txt (знак `+` перед ударной гласной, «ё»).

Если проверка провалена — печатает FAIL и возвращает код 1 (перегенерация).

Запуск:
  python say_f5_checked.py --voice-file D:\AI\F5-TTS\voice.txt \
      --script-file D:\AI\F5-TTS\script_clean.txt \
      --out D:\AI\F5-TTS\out\voiceover.wav
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, r"D:\AI\F5-TTS")
from f5_run import run_f5, run_quiet  # noqa: E402

PY = r"D:\AI\python310\python.exe"
F5 = Path(r"D:\AI\F5-TTS")
FFMPEG = r"C:\Users\nasle\tools\ffmpeg\ffmpeg.exe"
FFPROBE = r"C:\Users\nasle\tools\ffmpeg\ffprobe.exe"
TMP = Path(r"D:\AI\temp\opencode\f5_parts")
PARTS_LOG = Path(r"D:\AI\temp\opencode\f5_part_live.log")


WORD_RE = re.compile(r"[А-Яа-яЁёA-Za-z0-9]+")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig").strip()


def split_phrases(text: str):
    """Делим на короткие фразы: по .!? и запятым, чтобы каждая <= ~90 символов."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(p) <= 110:
            out.append(p)
            continue
        # дробим длинную фразу по запятым
        chunks, cur = [], ""
        for piece in re.split(r"(?<=,)\s+", p):
            if len(cur) + len(piece) + 1 <= 110:
                cur = (cur + " " + piece).strip()
            else:
                if cur:
                    chunks.append(cur)
                cur = piece.strip()
        if cur:
            chunks.append(cur)
        out.extend(chunks)
    return out


def synth_part(text: str, out: Path) -> bool:
    cmd = [PY, str(F5 / "f5_synth.py"), "--text", text, "--out", str(out),
           "--speed", "0.95", "--nfe", "64"]
    # Живой лог + тайм-аут + повторы (см. f5_run.py): фраза не «зависает» навсегда.
    # Тайм-аут 1500 c > ожидания замка (900 c) в f5_synth, чтобы при конкуренции
    # процесс завершался сам с понятным сообщением, а не убивался родителем.
    return run_f5(cmd, out, timeout_s=1500, retries=2,
                  log_path=PARTS_LOG, log=print)


def concat(parts, out: Path):
    lst = out.with_suffix(".txt")
    lst.write_text("\n".join(f"file '{p.as_posix()}'" for p in parts),
                   encoding="utf-8")
    cmd = [FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
           "-c", "copy", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode == 0


def duration(path: Path) -> float:
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def asr_text(audio: Path) -> str:
    run_quiet([PY, str(F5 / "stt.py"), "--audio", str(audio)], timeout_s=900)
    # stt.py пишет srt; читаем его как источник транскрипта
    srt = F5 / "subtitles.srt"
    if srt.exists():
        raw = srt.read_text(encoding="utf-8-sig")
        lines = [l.strip() for l in raw.splitlines()
                 if l.strip() and not l.strip().isdigit()
                 and "-->" not in l]
        return " ".join(lines)
    return ""


def _lev(a: str, b: str) -> int:
    """Расстояние Левенштейна (для мягкого сравнения слов ASR и сценария)."""
    if a == b:
        return 0
    if not a or not b:
        return max(len(a), len(b))
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _fuzzy_contains(word: str, pool) -> bool:
    """Слово найдено, если совпало точно или отличается на 1-2 буквы
    (Whisper путает «ё/о», «д/т» и падежи имён собственных)."""
    if word in pool:
        return True
    limit = 1 if len(word) <= 5 else 2
    for w in pool:
        if abs(len(w) - len(word)) > limit:
            continue
        if _lev(word, w) <= limit:
            return True
    return False


def check(transcript: str, script: str, voice: str, audio: Path):
    tw = set(w.lower() for w in WORD_RE.findall(transcript))
    sw = set(w.lower() for w in WORD_RE.findall(script))
    matched = [w for w in sw if _fuzzy_contains(w, tw)]
    cov = (len(matched) / len(sw)) if sw else 0.0
    missed = sorted(w for w in sw if w not in matched)
    print(f"[CHECK] Покрытие слов (мягкое): {cov:.1%} (нужно >= 95%)")
    if missed:
        print(f"[CHECK] Не найдено в ASR ({len(missed)}): {', '.join(missed[:20])}")

    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", script.strip()) if s.strip()]
    tail_ok = False
    if sents:
        tail_words = [w.lower() for w in WORD_RE.findall(sents[-1])][:6]
        tail_ok = all(w in tw for w in tail_words)
    print(f"[CHECK] Хвост (последняя фраза): {'OK' if tail_ok else 'ОБРЕЗАН'}")

    marks = re.findall(r"\w*\+\w*", voice)
    print(f"[CHECK] Ударений в voice.txt: {len(marks)}")
    dur = duration(audio)
    print(f"[CHECK] Длительность: {dur:.1f} c")

    ok = cov >= 0.95 and tail_ok and len(marks) > 0
    print(f"[CHECK] ИТОГ: {'PASS' if ok else 'FAIL'}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice-file", default=str(F5 / "voice.txt"))
    ap.add_argument("--script-file", default=str(F5 / "script_clean.txt"))
    ap.add_argument("--out", default=str(F5 / "out" / "voiceover.wav"))
    a = ap.parse_args()

    voice = read(Path(a.voice_file))
    script = read(Path(a.script_file))
    out = Path(a.out)

    phrases = split_phrases(voice)
    print(f"[F5] Фраз: {len(phrases)}")
    TMP.mkdir(parents=True, exist_ok=True)
    for i, p in enumerate(TMP.glob("part_*.wav")):
        p.unlink()

    parts = []
    for i, ph in enumerate(phrases, 1):
        part = TMP / f"part_{i:03d}.wav"
        print(f"  [{i}/{len(phrases)}] {ph[:70]}")
        if not synth_part(ph, part):
            print(f"[ERROR] не сгенерирована фраза {i}")
            return 1
        parts.append(part)

    if not concat(parts, out):
        print("[ERROR] склейка не удалась")
        return 1
    print(f"[OK] Озвучка: {out}")

    transcript = asr_text(out)
    ok = check(transcript, script, voice, out)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
