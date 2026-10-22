#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prep_voice.py — подготовка текста для F5-TTS (ударения + «ё» + санитайз).

Зачем: русская модель F5 посимвольная и ударение «угадывает» сама — отсюда
ошибки в произношении. Мы расставляем ударения знаком `+` перед ударной гласной
(модель это поддерживает, проверено на роликах №2/№3/№5) и восстанавливаем «ё».

Что делает:
  1) САНИТАЙЗ (правило озвучки №7): тире/двоеточия/точки-с-запятой/кавычки/скобки
     убираются; ремарки в скобках — (грохот), (пауза 1 сек) — удаляются ЦЕЛИКОМ
     (SCENARIO_RULES §3: это указания для монтажа/пауз, а не текст для озвучки);
     цифры записываются словами; остаются только `, . ! ?`.
  2) РАССТАНОВКА УДАРЕНИЙ — RUAccent (`+` перед ударной гласной, «ё»).
  3) ОВЕРРАЙДЫ — ручные пары `слово=сл+ово` из файла (бьют RUAccent).
  4) Пишет два файла:
       --voice-out   — текст С ударениями (вход для F5-TTS);
       --script-out  — ЧИСТЫЙ текст без `+` (для субтитров/выравнивания/fix_srt).

Пример:
  python prep_voice.py --src D:\\AI\\F5-TTS\\scenario.txt ^
      --voice-out D:\\AI\\F5-TTS\\voice.txt ^
      --script-out D:\\AI\\F5-TTS\\script_clean.txt ^
      --overrides D:\\AI\\VIDEO_PIPELINE\\stress_overrides.txt
"""
import argparse
import re
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# --- Числа словами (0..999 999 999 999) -----------------------------------
_U0_19 = ["ноль", "один", "два", "три", "четыре", "пять", "шесть", "семь",
          "восемь", "девять", "десять", "одиннадцать", "двенадцать",
          "тринадцать", "четырнадцать", "пятнадцать", "шестнадцать",
          "семнадцать", "восемнадцать", "девятнадцать"]
_U0_19_F = ["ноль", "одна", "две", "три", "четыре", "пять", "шесть", "семь",
            "восемь", "девять", "десять", "одиннадцать", "двенадцать",
            "тринадцать", "четырнадцать", "пятнадцать", "шестнадцать",
            "семнадцать", "восемнадцать", "девятнадцать"]
_TENS = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят",
         "семьдесят", "восемьдесят", "девяносто"]
_HUNDS = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот",
          "семьсот", "восемьсот", "девятьсот"]
_GROUP = [
    ("", "", ""),                              # 0 — единицы
    ("тысяча", "тысячи", "тысяч"),             # 1 — тысячи
    ("миллион", "миллиона", "миллионов"),      # 2 — миллионы
    ("миллиард", "миллиарда", "миллиардов"),   # 3 — миллиарды
]


def _plural(n: int, forms) -> str:
    one, few, many = forms
    if not one:
        return ""
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not (12 <= n100 <= 14):
        return few
    return many


def _three(n: int, feminine: bool) -> str:
    out = []
    h, rest = divmod(n, 100)
    if h:
        out.append(_HUNDS[h])
    t, u = divmod(rest, 10)
    if t >= 2:
        out.append(_TENS[t])
        if u:
            out.append((_U0_19_F if feminine else _U0_19)[u])
    elif rest:
        out.append((_U0_19_F if feminine else _U0_19)[rest])
    return " ".join(out)


def num_to_words_ru(n: int) -> str:
    if n == 0:
        return "ноль"
    groups = []
    vals = []
    x = n
    while x > 0:
        groups.append(x % 1000)
        x //= 1000
    for i, v in enumerate(groups):
        if not v:
            continue
        name = _plural(v, _GROUP[i]) if i < len(_GROUP) else ""
        fem = (i == 1)  # тысячи — женский род
        words = _three(v, fem)
        vals.append((words + (" " + name if name else "")).strip())
    return " ".join(reversed(vals))


# --- Санитайз --------------------------------------------------------------
def sanitize(text: str, convert_numbers: bool = True) -> str:
    t = text
    # 1) тире → запятая
    t = re.sub(r"\s*[—–―−]\s*", ", ", t)
    # 2) двоеточие/точка-с-запятой → запятая
    t = t.replace(":", ", ").replace(";", ", ")
    # 3) ремарки в скобках — ЦЕЛИКОМ вон (SCENARIO_RULES §3: (грохот), (пауза 1 сек)
    #    задают звук/паузу для монтажа, а не произносятся диктором)
    t = re.sub(r"\([^)]*\)", " ", t)
    # 3.1) кавычки/остатки скобок/прочие символы — вон
    t = re.sub(r"[«»\"“”„'’`()\[\]{}|/\\*#@$%^&~]", "", t)
    # 4) многоточие → точка
    t = t.replace("…", ".")
    t = re.sub(r"\.{2,}", ".", t)
    # 5) цифры словами
    if convert_numbers:
        t = re.sub(r"\d+", lambda m: num_to_words_ru(int(m.group(0))), t)
    # 6) пробелы перед знаками, лишние запятые
    t = re.sub(r"\s+([,.!?])", r"\1", t)
    t = re.sub(r",\s*,+", ",", t)
    t = re.sub(r"([,.!?])(?=[А-Яа-яЁёA-Za-z0-9])", r"\1 ", t)
    t = re.sub(r"\s{2,}", " ", t)
    # 7) пробел после запятой уже обеспечен; финальная чистка
    return t.strip()


# --- Оверрайды ударений ----------------------------------------------------
def load_overrides(path: str) -> list:
    pairs = []
    p = Path(path)
    if not p.exists():
        return pairs
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        plain, accented = line.split("=", 1)
        plain, accented = plain.strip(), accented.strip()
        if plain and accented:
            pairs.append((plain, accented))
    return pairs


def apply_overrides(text: str, pairs: list):
    applied = []
    for plain, accented in pairs:
        pat = re.compile(r"(?<![А-Яа-яЁё])" + re.escape(plain) + r"(?![А-Яа-яЁё])",
                         re.IGNORECASE)
        if pat.search(text):
            def _sub(m):
                rep = accented
                if m.group(0)[:1].isupper():
                    rep = rep[:1].upper() + rep[1:]
                return rep
            text = pat.sub(_sub, text)
            applied.append((plain, accented))
    return text, applied


def main() -> int:
    ap = argparse.ArgumentParser(description="Подготовка текста для F5 (ударения + ё)")
    ap.add_argument("--src", required=True)
    ap.add_argument("--voice-out", required=True)
    ap.add_argument("--script-out", required=True)
    ap.add_argument("--overrides", default=r"D:\AI\VIDEO_PIPELINE\stress_overrides.txt")
    ap.add_argument("--no-numbers", action="store_true",
                    help="не переводить цифры в слова")
    a = ap.parse_args()

    src = Path(a.src)
    if not src.exists():
        print(f"[ERROR] нет файла: {src}")
        return 1

    raw = src.read_text(encoding="utf-8-sig").strip()
    clean = sanitize(raw, convert_numbers=not a.no_numbers)
    # Санитайзим и записываем чистый вариант (вход для субтитров)
    Path(a.script_out).write_text(clean + "\n", encoding="utf-8", newline="\n")

    t0 = time.time()
    try:
        print("[RUAccent] загружаю модель...", flush=True)
        from ruaccent import RUAccent
        acc = RUAccent()
        acc.load(omograph_model_size="turbo3.1", use_dictionary=True, device="CPU")
        print(f"[RUAccent] готово за {time.time() - t0:.0f} c", flush=True)
        accented = acc.process_all(clean)
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] RUAccent недоступен ({type(e).__name__}: {e}) — "
              f"текст БЕЗ ударений (произношение может быть хуже).", flush=True)
        accented = clean
    accented, applied = apply_overrides(accented, load_overrides(a.overrides))
    # на всякий случай чистим то, что RUAccent мог вернуть
    accented = re.sub(r"\s{2,}", " ", accented).strip()

    Path(a.voice_out).write_text(accented + "\n", encoding="utf-8", newline="\n")

    print(f"\nCLEAN  → {a.script_out}")
    print(f"VOICE  → {a.voice_out}")
    if applied:
        print(f"Оверрайды применены: {len(applied)}")
        for p_, a_ in applied:
            print(f"    {p_} -> {a_}")
    print("\n---- С УДАРЕНИЯМИ (вход F5) ----")
    print(accented)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
