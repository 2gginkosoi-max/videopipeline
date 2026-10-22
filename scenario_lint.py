#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scenario_lint.py — проверка сценария на «пересказ vs новая ценность»
(ORIGINALITY_GUIDE, Правило 1) + генерация текстов инфо-карточек.

Проверяет наличие: хука, контекста, аналитики (≥1), прогноза/вывода (≥1),
и прикидывает длительность (цель 20–50 c).

Пишет:
  output/scenario_report.json  — отчёт;
  output/infocards.txt         — 2–3 тезиса для инфографики (если файла нет).

Пример:
  python scenario_lint.py --scenario D:\\AI\\F5-TTS\\scenario.txt
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_SCENARIO = r"D:\AI\F5-TTS\scenario.txt"
OUT_DIR = Path(r"D:\AI\VIDEO_PIPELINE\output")

ANALYTIC = ["потому что", "дело в том", "это значит", "на самом деле", "причина",
            "почему", "связано", "говорит о", "тренд", "статистик", "по данным",
            "исследован", "эксперты", "показывает", "означает", "вывод", "по сути",
            "в итоге", "это не просто", "по словам", "учёные", "зоолог"]
FORECAST = ["прогноз", "скоро", "дальше", "теперь", "может", "будет", "станет",
            "вероятно", "последств", "риск", "совет", "рекоменд", "стоит",
            "что это значит", "ждите", "следующ", "в будущем", "через год",
            "через полгода", "полгода", "месяц", "так что", "иначе", "поэтому"]
HOOK = ["?", "шок", "невероятн", "никогда", "впервые", "секрет", "правда",
        "запрещ", "провал", "позор", "внимание", "представ", "только что",
        "вы не поверите", "обман", "ошибк", "воров", "попались", "преступл",
        "краж", "украл", "стащил", "поймал", "камера",
        # Формула Дарвина (FORMULA_DARWIN.md): хук-перевёртыш узнаваемой фразы.
        # Эти зачины считаются валидным хуком наравне с вопросами/«шок».
        "похоже", "кажется", "знаете", "что будет, если", "больше не",
        "не ", "уже не", "а не ", "вместо"]

WPM = 186  # слов в минуту после atempo 1.15 (замер по роликам 5–7)


def sentences(text: str):
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def hits(sentence: str, markers) -> int:
    low = " " + sentence.lower() + " "
    return sum(1 for m in markers if m in low)


# Ведущие «связки», которые портят карточку — убираем их перед обрезкой
CONNECT = [r"^дело в том,?\s*что\s+", r"^дело в том,?\s*", r"^так что\s+", r"^так\s+",
           r"^по данным\s+[^,]*,?\s*", r"^по словам\s+[^,]*,?\s*", r"^на самом деле\s+",
           r"^в итоге\s+", r"^по сути\s+", r"^и вот\s+"]
BOUND = [" и ", " что ", ", ", " потому что ", " когда ", " если ", " но "]


def cardify(sentence: str) -> str:
    """Короткая «инфографическая» формулировка из предложения сценария."""
    s = sentence.replace("—", ",").strip(" .,!?")
    for _ in range(4):  # снимаем ведущие связки каскадом (напр. «по данным…, так…»)
        before = s
        for pat in CONNECT:
            s2 = re.sub(pat, "", s, count=1, flags=re.I)
            if s2 != s:
                s = s2.strip()
                break
        if s == before:
            break
    # обрезаем по первому смысловому шву, если там ≥3 и ≤6 слов
    for b in BOUND:
        i = s.find(b)
        if i > 0:
            head = s[:i].strip()
            if 3 <= len(head.split()) <= 6:
                return head.upper()
    words = s.split()
    if len(words) > 6:
        return " ".join(words[:6]).upper() + "…"
    return s.upper()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default=DEFAULT_SCENARIO)
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    a = ap.parse_args()

    src = Path(a.scenario)
    if not src.exists():
        print(f"[ERROR] нет сценария: {src}")
        return 1
    text = src.read_text(encoding="utf-8-sig").strip()
    sents = sentences(text)
    words = len(re.findall(r"[А-Яа-яЁёA-Za-z0-9]+", text))
    est = words / WPM * 60

    hook = sents[0] if sents else ""
    hook_ok = len(hook.split()) <= 14 and hits(hook, HOOK) > 0
    # Формула Дарвина: хук может быть перевёртышем без вопросительного знака,
    # поэтому первое предложение до 12 слов тоже считаем хуком, если оно есть.
    if not hook_ok and hook and len(hook.split()) <= 12:
        hook_ok = True
    body = sents[1:] if len(sents) > 1 else []
    analytic = [s for s in body if hits(s, ANALYTIC) > 0]
    forecast = [s for s in body if hits(s, FORECAST) > 0]

    dur_ok = 20 <= est <= 50
    checks = {
        "hook_present": hook_ok,
        "analytics_count": len(analytic),
        "forecast_count": len(forecast),
        "words": words,
        "est_duration_s": round(est, 1),
        "duration_ok": dur_ok,
        "is_retelling_risk": len(analytic) == 0 and len(forecast) == 0,
    }
    passed = (hook_ok and len(analytic) >= 1 and len(forecast) >= 1 and dur_ok)

    # --- инфо-карточки: тезисы аналитики/прогноза, иначе — фразы с цифрами ---
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cards_file = out_dir / "infocards.txt"
    stale = (not cards_file.exists()) or (cards_file.stat().st_mtime < src.stat().st_mtime)
    if stale:
        pool = forecast + analytic
        if not pool:
            pool = [s for s in body if re.search(r"\d", s)] or sents[-2:]
        cards = [c for c in (cardify(s) for s in pool[:3]) if c]
        cards_file.write_text("\n".join(cards) + ("\n" if cards else ""), encoding="utf-8")

    report = {"checks": checks, "passed": passed,
              "sentences": len(sents),
              "analytic_sentences": analytic, "forecast_sentences": forecast}
    (out_dir / "scenario_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("[LINT] Сценарий (Правило 1: не пересказ, а ценность)")
    print(f"  хук (первые 3 c): {'OK' if hook_ok else 'СЛАБЫЙ'}  → «{hook}»")
    print(f"  аналитика: {len(analytic)} тезис(ов)" +
          ("" if analytic else "  ← нужен самостоятельный вывод"))
    print(f"  прогноз:   {len(forecast)} тезис(ов)" +
          ("" if forecast else "  ← нужен прогноз/последствия"))
    print(f"  слов: {words} | оценка длительности: {est:.1f} c " +
          ("(20–50 OK)" if dur_ok else "(вне 20–50 — исправить)"))
    print(f"  инфо-карточки: {cards_file}")
    print(("[LINT] PASS" if passed else "[LINT] WARN — сценарий не проходит Правило 1"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
