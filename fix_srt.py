#!/usr/bin/env python3
"""
fix_srt.py — авто-коррекция опечаток Whisper в субтитрах по тексту сценария.

Идея: слова из сценария — «словарь правильных слов». Каждое слово субтитров,
которого нет в словаре, но которое близко (difflib) к словарю — исправляем.
'ё'/'е' считаются одинаковыми.

Плюс ЯВНЫЕ ПРАВКИ из файла srt_fixes.txt (по одной паре «как услышал=как верно»
на строку) — для ослышек, которые difflib не ловит (напр. «пояс» вместо «поезд»).

Пример:
  python fix_srt.py --srt D:\\AI\\F5-TTS\\subtitles.srt --script D:\\AI\\F5-TTS\\script_clean.txt
"""

import argparse
import difflib
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_SRT = r"D:\AI\F5-TTS\subtitles.srt"
DEFAULT_SCRIPT = r"D:\AI\F5-TTS\scenario.txt"
DEFAULT_FIXES = r"D:\AI\VIDEO_PIPELINE\srt_fixes.txt"


def norm(w: str) -> str:
    return w.lower().replace("ё", "е")


def load_fixes(path: str) -> list:
    """Пары «как услышал = как верно» из файла (комментарии '#' и пустые строки — мимо)."""
    pairs = []
    p = Path(path)
    if not p.exists():
        return pairs
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        plain, good = (x.strip() for x in line.split("=", 1))
        if plain and good:
            pairs.append((plain, good))
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--srt", default=DEFAULT_SRT)
    ap.add_argument("--script", default=DEFAULT_SCRIPT)
    ap.add_argument("--cutoff", type=float, default=0.75)
    ap.add_argument("--fixes", default=DEFAULT_FIXES,
                    help="файл пар «ослышка=верно» (напр. пояс=поезд)")
    a = ap.parse_args()

    srt_path = Path(a.srt)
    script_path = Path(a.script)
    if not srt_path.exists() or not script_path.exists():
        print(f"[ERROR] нет файла: {srt_path} / {script_path}")
        sys.exit(1)

    script_tokens = re.findall(r"[А-Яа-яЁёA-Za-z]+",
                               script_path.read_text(encoding="utf-8-sig"))
    vocab_map = {}
    for w in script_tokens:
        vocab_map.setdefault(norm(w), w.lower())   # нормализовано -> правильное написание
    vocab = sorted(set(vocab_map), key=len, reverse=True)

    text = srt_path.read_text(encoding="utf-8-sig")
    fixes = []

    # 0) ЯВНЫЕ ПРАВКИ (ослышки Whisper, которых difflib не ловит: пояс=поезд)
    for plain, good in load_fixes(a.fixes):
        pat = re.compile(r"(?<![А-Яа-яЁёA-Za-z])" + re.escape(plain)
                         + r"(?![А-Яа-яЁёA-Za-z])", re.IGNORECASE)

        def _rep(m, good=good):
            tok = m.group(0)
            rep = good
            if tok[:1].isupper():
                rep = rep[:1].upper() + rep[1:]
            fixes.append((tok, rep))
            return rep

        text = pat.sub(_rep, text)

    def repl(m):
        tok = m.group(0)
        base = norm(tok)
        if len(base) < 2:
            return tok
        # 1) слово есть в словаре — сверяем написание (ё/е, регистр)
        if base in vocab_map:
            good = vocab_map[base]
            if tok.lower() != good:
                out = good[0].upper() + good[1:] if tok[0].isupper() else good
                fixes.append((tok, out))
                return out
            return tok
        # 2) близкое слово -> исправляем
        if len(base) < 4:
            return tok
        cand = difflib.get_close_matches(base, vocab, n=1, cutoff=a.cutoff)
        if not cand:
            return tok
        good = cand[0]
        if good == base:
            return tok
        out = good[0].upper() + good[1:] if tok[0].isupper() else good
        fixes.append((tok, out))
        return out

    new = re.sub(r"[А-Яа-яЁёA-Za-z]+", repl, text)
    srt_path.write_text(new, encoding="utf-8")

    if fixes:
        print(f"[OK] Исправлено слов: {len(fixes)}")
        for a_, b_ in fixes:
            print(f"    {a_} -> {b_}")
    else:
        print("[OK] Опечаток не найдено")


if __name__ == "__main__":
    main()
