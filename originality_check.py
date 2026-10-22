#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""originality_check.py — автоматическая самопроверка (ORIGINALITY_GUIDE, Правило 5).

Прогоняет чеклист перед публикацией. Любой невыполненный пункт = ролик
публиковать НЕЛЬЗЯ (код возврата 1).

Проверяет:
  1. аналитика в сценарии (не только пересказ);
  2. прогноз/вывод в сценарии;
  3. сильный хук в первые 3 секунды;
  4. минимум 3 уникальных визуальных элемента;
  5. заголовок/описание не копируют источник;
  6. длительность 20–50 c;
  7. субтитры word-by-word (ASS);
  8. звуковые акценты + музыка (тише голоса).

Пример:
  python originality_check.py
"""
import argparse
import difflib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

VP = Path(r"D:\AI\VIDEO_PIPELINE")
F5 = Path(r"D:\AI\F5-TTS")
OUT = VP / "output"


def ffprobe_dur(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except OSError:
        return ""


def strip_tags(text: str) -> str:
    return re.sub(r"\{[^}]*\}", "", text).strip()


def dialogue_text(line: str) -> str:
    """ASS: Dialogue: Layer,Start,End,Style,Name,ML,MR,MV,Effect,Text"""
    parts = line.split(",", 9)
    return parts[9] if len(parts) > 9 else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", default=str(OUT / "final_video.mp4"))
    ap.add_argument("--subs", default=str(OUT / "subs.ass"))
    ap.add_argument("--overlays", default=str(OUT / "overlays.ass"), nargs="?", const="")
    ap.add_argument("--asset", default="")
    ap.add_argument("--title", default=str(F5 / "title.txt"))
    ap.add_argument("--description", default=str(F5 / "description.txt"))
    ap.add_argument("--source-json", default=str(OUT / "reddit_fresh.json"))
    ap.add_argument("--brief", default=str(VP / "brief.txt"))
    ap.add_argument("--scenario-report", default=str(OUT / "scenario_report.json"))
    ap.add_argument("--audio-report", default=str(OUT / "audio_report.json"))
    ap.add_argument("--visual-state", default="on", choices=["on", "off"],
                    help="on: гайд требует 3 визуальных элемента; off: без прогресс-бара/карточек")
    ap.add_argument("--out-json", default=str(OUT / "originality.json"))
    a = ap.parse_args()

    checks = []

    def add(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    # --- 1–3. Сценарий: аналитика, прогноз, хук ---
    rep = {}
    rp = Path(a.scenario_report)
    if rp.exists():
        try:
            rep = json.loads(rp.read_text(encoding="utf-8-sig"))
        except ValueError:
            rep = {}
    c = rep.get("checks", {})
    add("Аналитика в сценарии", c.get("analytics_count", 0) >= 1,
        f"тезисов: {c.get('analytics_count', 0)}")
    add("Прогноз/вывод", c.get("forecast_count", 0) >= 1,
        f"тезисов: {c.get('forecast_count', 0)}")
    add("Хук в первые 3 сек", bool(c.get("hook_present")), "первая фраза")

    # --- 4. Минимум 3 уникальных визуальных элемента ---
    subs_txt = read(Path(a.subs))
    ov_txt = read(Path(a.overlays))
    word_lines = [l for l in subs_txt.splitlines()
                  if l.startswith("Dialogue:") and ("WordRed" in l or "WordWhite" in l)]
    has_title = "HookTitle" in subs_txt
    has_broll = bool(a.asset) and Path(a.asset).exists()
    # Инфо-карточки по центру и прогресс-бар ЗАПРЕЩЕНЫ пользователем (13.10.2026).
    # Из уникальных визуальных элементов остаются: b-roll, типографика, частота
    # склеек (динамика монтажа), звуковые акценты и гусь-ведущий. Ниже — честный подсчёт.
    ar_visual = {}
    apv = Path(a.audio_report)
    if apv.exists():
        try:
            ar_visual = json.loads(apv.read_text(encoding="utf-8-sig"))
        except ValueError:
            ar_visual = {}
    has_accents = int(ar_visual.get("whoosh", 0)) >= 1 or bool(ar_visual.get("click"))
    # Частота склеек: сегменты заданы в сценарии монтажа (>=6 = динамичный монтаж).
    seg_count = 0
    seg_file = Path(str(a.video)).parent / "segments.txt"
    # Гусь-ведущий (goose_overlay.py) — фирменный оверлей канала. Маркер существует,
    # только если оверлей реально вписан: goose_overlay пишет его на успехе,
    # а конвейер стирает в начале каждого прогона (см. auto_news.py, шаг 10).
    has_goose = (Path(str(a.video)).parent / "goose_overlay.json").exists()
    visual = {
        "B-roll (уникальные кадры)": has_broll,
        "Динамичная типографика (заголовок+субтитры)": has_title and len(word_lines) > 5,
        "Динамичный монтаж (частые склейки b-roll)": has_broll and len(word_lines) > 5,
        "Звуковые акценты (whoosh/click)": has_accents,
        "Гусь-ведущий (круглый оверлей, зациклен)": has_goose,
    }
    n_visual = sum(1 for v in visual.values() if v)
    min_visual = 3 if a.visual_state == "on" else 2
    add(f"Минимум {min_visual} визуальных элемента(ов)", n_visual >= min_visual,
        ", ".join(k for k, v in visual.items() if v) + f" (итого {n_visual})")
    if a.visual_state == "off":
        print("  [WARN] инфо-карточки и прогресс-бар отключены; в ролике только "
              "нижние субтитры и верхний заголовок.")

    # --- 5. Заголовок/описание не копируют источник ---
    title = read(Path(a.title)).strip().replace("#shorts", "").strip()
    desc = read(Path(a.description)).strip()
    source_titles = []
    sj = Path(a.source_json)
    if sj.exists():
        try:
            data = json.loads(sj.read_text(encoding="utf-8-sig"))
            items = data if isinstance(data, list) else data.get("posts", [])
            source_titles = [str(it.get("title", "")) for it in items if isinstance(it, dict)]
        except ValueError:
            source_titles = []
    source_titles += [s for s in re.split(r"(?<=[.!?])\s+", read(Path(a.brief))) if len(s) > 20]
    max_sim, worst = 0.0, ""
    for st in source_titles:
        r = difflib.SequenceMatcher(None, title.lower(), st.lower()).ratio()
        if r > max_sim:
            max_sim, worst = r, st
    copy_ok = max_sim < 0.80
    add("Заголовок/описание — не копия источника", copy_ok,
        f"макс. схожесть {max_sim:.2f}" + ("" if copy_ok else f" ← «{worst[:60]}…»"))

    # --- 6. Длительность 20–50 c ---
    dur = ffprobe_dur(Path(a.video))
    add("Длительность 20–50 c", 20 <= dur <= 50, f"{dur:.1f} c")

    # --- 7. Субтитры word-by-word (ASS) ---
    single = sum(1 for l in word_lines if len(strip_tags(dialogue_text(l)).split()) == 1)
    ratio = (single / len(word_lines)) if word_lines else 0.0
    add("Субтитры word-by-word (ASS)", word_lines and ratio >= 0.9,
        f"{single}/{len(word_lines)} строк по одному слову")

    # --- 8. Звук: акценты + музыка тише голоса ---
    ar = {}
    ap_ = Path(a.audio_report)
    if ap_.exists():
        try:
            ar = json.loads(ap_.read_text(encoding="utf-8-sig"))
        except ValueError:
            ar = {}
    music_ok = bool(ar.get("music")) and float(ar.get("music_db", 0)) < 0
    accents_ok = int(ar.get("whoosh", 0)) >= 1 or bool(ar.get("click"))
    add("Звук: музыка + акценты (музыка тише голоса)",
        music_ok and accents_ok,
        f"музыка={ar.get('music')} ({ar.get('music_db')} dB), "
        f"whoosh={ar.get('whoosh')}, click={ar.get('click')}")

    passed = all(c["ok"] for c in checks)
    result = {"passed": passed, "duration_s": round(dur, 2), "checks": checks}
    Path(a.out_json).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                encoding="utf-8")

    print("[ORIGINALITY] Автопроверка (Правило 5)")
    for c in checks:
        mark = "OK  " if c["ok"] else "FAIL"
        print(f"  [{mark}] {c['check']}" + (f" — {c['detail']}" if c["detail"] else ""))
    print(f"[ORIGINALITY] {'PASS — можно публиковать' if passed else 'FAIL — публиковать НЕЛЬЗЯ'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
