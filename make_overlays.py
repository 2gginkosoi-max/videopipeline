#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_overlays.py — ОТКЛЮЧЕНО (13.10.2026).

Пользователь запретил вставку с рамкой и словами по центру кадра — «никогда
не делай её больше». В ролике остаются ТОЛЬКО нижние субтитры и верхний заголовок.

Скрипт оставлен на диске, но больше не вызывается из auto_news.py (шаг 9 удалён)
и его вывод (output\\overlays.ass) НЕ передаётся в compose_segments.py.
Если запустить вручную — он по-прежнему сгенерирует старый ASS с InfoCard,
поэтому запускать его не нужно.
"""

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print("[DISABLED] make_overlays.py отключён: инфо-карточки по центру запрещены.")
sys.exit(0)

# --- старый код ниже оставлен для истории, не исполняется ---

import argparse
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

W, H = 1080, 1920
BAR_Y, BAR_H = 1860, 16
CARD_X, CARD_W, CARD_H, CARD_Y = 90, 900, 190, 640

# Палитра акцентов (BBGGRR): разные ролики — разный стиль (гайд: без одного шаблона)
ACCENTS = ["3300FF", "00D7FF", "006BFF", "FFE500"]

HEADER_TMPL = """[Script Info]
Title: Overlays (progress bar + info cards)
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: BarTrack,Montserrat Black,20,&H66000000,&H66000000,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: BarFill,Montserrat Black,20,&H00{ACCENT}&,&H00{ACCENT}&,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: InfoBox,Montserrat Black,20,&H99000000,&H99000000,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: InfoAccent,Montserrat Black,20,&H00{ACCENT}&,&H00{ACCENT}&,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: InfoCard,Montserrat Black,44,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,3,0,5,140,140,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def a_time(s: float) -> str:
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = int(s % 60)
    cs = int((s % 1) * 100)
    return f"{h}:{m:02d}:{sec:02d}.{cs:02d}"


def rect(x, y, w, h):
    return (r"{\an7\pos(" + f"{int(x)},{int(y)}" + r")\p1}"
            + f"m 0 0 l {int(w)} 0 {int(w)} {int(h)} 0 {int(h)}" + r"{\p0}")


def duration_of(audio: str) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", audio],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def build(events: list, dur: float, cards: list, accent: str) -> str:
    out = [HEADER_TMPL.format(ACCENT=accent)]

    # ---- прогресс-бар ----
    out.append(f"Dialogue: 0,{a_time(0)},{a_time(dur)},BarTrack,,0,0,0,,"
               + rect(0, BAR_Y, W, BAR_H))
    step = 0.2
    n = max(1, int(dur / step))
    for i in range(n):
        t = i * step
        w = max(2, int(W * (t / dur))) if dur else 0
        out.append(f"Dialogue: 0,{a_time(t)},{a_time(min(t + step, dur))},BarFill,,0,0,0,,"
                   + rect(0, BAR_Y, w, BAR_H))
    events.append(("bar", n))

    # ---- инфо-карточки ----
    k = len(cards)
    if k:
        start0 = 2.0
        end0 = max(start0 + 1.0, dur - 1.2)
        win = (end0 - start0) / k
        for i, text in enumerate(cards):
            st = start0 + i * win
            en = min(st + min(win, 5.0), dur)
            out.append(f"Dialogue: 0,{a_time(st)},{a_time(en)},InfoBox,,0,0,0,,"
                       + rect(CARD_X, CARD_Y, CARD_W, CARD_H))
            out.append(f"Dialogue: 0,{a_time(st)},{a_time(en)},InfoAccent,,0,0,0,,"
                       + rect(CARD_X, CARD_Y, 12, CARD_H))
            anim = (r"{\fad(200,180)\fscx88\fscy88\t(0,220,\fscx100\fscy100)}")
            pos = r"{\an5\pos(" + f"{CARD_X + CARD_W // 2},{CARD_Y + CARD_H // 2}" + r")}"
            out.append(f"Dialogue: 1,{a_time(st)},{a_time(en)},InfoCard,,0,0,0,,"
                       + anim + pos + text)
    events.append(("cards", k))
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--cards-file", default=r"D:\AI\VIDEO_PIPELINE\output\infocards.txt")
    ap.add_argument("--out", default=r"D:\AI\VIDEO_PIPELINE\output\overlays.ass")
    ap.add_argument("--dur", type=float, default=0.0)
    ap.add_argument("--accent", default="auto",
                    help="цвет акцента оверлеев (BBGGRR) или auto — по тексту карточек")
    a = ap.parse_args()

    dur = a.dur or duration_of(a.audio)
    if dur <= 0:
        print("[ERROR] не удалось определить длительность аудио")
        return 1

    cards = []
    cf = Path(a.cards_file)
    if cf.exists():
        for line in cf.read_text(encoding="utf-8-sig").splitlines():
            t = line.strip()
            if t and not t.startswith("#"):
                cards.append(t)
    cards = cards[:3]

    accent = a.accent
    if accent == "auto":
        seed = "".join(cards) or Path(a.audio).name
        accent = ACCENTS[sum(ord(ch) for ch in seed) % len(ACCENTS)]

    events = []
    ass = build(events, dur, cards, accent)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(ass, encoding="utf-8")
    print(f"[OK] Оверлеи: {out}")
    print(f"    Длительность: {dur:.2f} c | прогресс-бар: да | "
          f"инфо-карточек: {len(cards)} | акцент: &H00{accent}&")
    for c in cards:
        print(f"      • {c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
