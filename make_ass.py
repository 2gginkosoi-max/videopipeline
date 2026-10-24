#!/usr/bin/env python3
"""
make_ass.py — собирает ASS: заголовок (верх, цветные блоки) + субтитры
(одно слово, ключевые — красные), с "выскакиванием" за 150 мс.

Управляется аргументами, но по умолчанию работает как раньше.

Пример:
  python make_ass.py --srt D:\\AI\\F5-TTS\\subtitles.srt ^
      --title "КЕНГУРУ УСТРОИЛИ БОКС" ^
      --keywords-file D:\\AI\\VIDEO_PIPELINE\\output\\keywords.txt ^
      --out D:\\AI\\VIDEO_PIPELINE\\output\\subs.ass
"""

import argparse
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_SRT = r"D:\AI\F5-TTS\subtitles.srt"
DEFAULT_OUT = r"D:\AI\VIDEO_PIPELINE\output\subs.ass"
DEFAULT_TITLE_FILE = r"D:\AI\VIDEO_PIPELINE\output\screen_title.txt"
DEFAULT_KEYWORDS = r"D:\AI\VIDEO_PIPELINE\output\keywords.txt"

RED = r"{\c&H3300FF&}"     # #FF0033
WHITE = r"{\c&HFFFFFF&}"
YELLOW = r"{\c&H00D7FF&}"  # #FFD700
TITLE_PALETTE = [RED, WHITE, YELLOW, WHITE]

# --- Стили субтитров (слово в кадре) -------------------------------------
# classic — как было: белые слова, ключевые красным, «выскакивание»;
# clean   — только белые, появляются по одному, без вспышек;
# neon    — белое слово с холодным свечением;
# min     — мелкий текст без обводки;
# cinema  — шрифт с засечками, разрядка, спокойное появление.
STYLES = {
    "classic": dict(
        font="Montserrat Black", size=90, white="&H00FFFFFF", key="&H003300FF",
        outline_color="&H00000000", outline=6, shadow=3, spacing=0, bold=-1,
        tags=r"{\fscx80\fscy80\t(0,150,\fscx100\fscy100)}",
    ),
    "clean": dict(
        font="Montserrat Black", size=90, white="&H00FFFFFF", key=None,
        outline_color="&H00000000", outline=5, shadow=2, spacing=0, bold=-1,
        tags="",
    ),
    "neon": dict(
        font="Montserrat Black", size=90, white="&H00FFFFFF", key=None,
        outline_color="&H00FFE500", outline=2, shadow=0, spacing=0, bold=-1,
        tags=r"{\fad(100,0)\blur4\fscx80\fscy80\t(0,150,\fscx100\fscy100)}",
    ),
    "min": dict(
        font="Montserrat", size=64, white="&H00FFFFFF", key=None,
        outline_color="&H00000000", outline=2, shadow=0, spacing=1, bold=0,
        tags="",
    ),
    "cinema": dict(
        font="Georgia", size=76, white="&H00E6F0F5", key=None,
        outline_color="&H00000000", outline=3, shadow=2, spacing=2, bold=0,
        tags=r"{\fad(80,0)}",
    ),
}

# --- Ключевые слова для красного выделения (база) ---
KEY_WORDS = {
    # Угрозы/негатив/слежка/экстрим
    "война", "скандал", "атака", "обман", "штраф", "провал", "позор",
    "арестован", "запрещено", "уволен", "взрыв", "угроза", "опасность",
    "монстр", "распилил", "убийство",
    # Субъекты действия
    "ютубер", "канал", "дорог", "шоссе", "суд", "google", "гугл", "openai",
    # Эмоции
    "ирония", "шок", "ужас", "удивительно", "невероятно", "кража", "мошенничество",
    # Тема этого выпуска (котята-воришки молока)
    "котёнка", "котёнок", "котята", "кот", "коты", "котёнком",
    "молоко", "молока", "пакет", "пакета", "добыча", "добычей",
    "вор", "вора", "воров", "воры", "ограбление", "кража",
    "камера", "камеру", "кадр", "двор", "дворе",
    # Тема этого выпуска (наводнение в Стамбуле)
    "стамбул", "стамбуле", "стамбула", "стамбулом",
    "вода", "воды", "воду", "водой", "стена", "стеной",
    "ливень", "ливня", "ливни", "дождь", "дожди", "дождя",
    "наводнение", "наводнения", "потоп", "подтопление",
    "поток", "потоки", "река", "реки", "реках",
    "машины", "машину", "машин", "автомобили", "автомобиль",
    "улицы", "улицах", "улиц", "проспект", "проспектам",
    "затопило", "затопленным", "уносила", "унёс", "унес",
    "канализация", "ливневая", "климат", "климата",
    # Тема этого выпуска (SpaceX / космическая медуза)
    "spacex", "космос", "космосе", "космическую", "космический",
    "медуза", "медузу", "медузы", "светящаяся", "светящуюся",
    "ракета", "ракеты", "ракетный", "ракетных", "запуск", "запуска", "запусков",
    "небо", "небе", "свечение", "сияние", "облако", "облаком",
    "сумерках", "сумерки", "астрономов", "старте", "солнцем", "солнце",
    # Тема этого выпуска (домашний робот Рокки)
    "робот", "робота", "роботы", "роботов", "роботам", "робот-помощник",
    "рокки", "ии", "ассистент", "ассистенты", "ассистентов",
    "уничтожить", "уничтожение", "перезагрузка", "извинился", "извинение",
    "фильтры", "инструкция", "инструкцией",
    # Тема этого выпуска (жирафы дерутся шеями)
    "жираф", "жирафа", "жирафы", "жирафов", "жирафам",
    "шея", "шеи", "шею", "шеей", "шеями", "некинг",
    "самец", "самца", "самцы", "самкам", "стадо", "стаде", "статус",
    "удар", "оружие", "череп", "челюсть", "челюстью", "дубина",
    "саванна", "саванны", "зоологов", "бой", "победа", "соперник", "соперника",
    # Тема этого выпуска (утята в ливневой решётке)
    "утята", "утят", "утёнок", "утята-", "утка", "утки", "утиные", "кряквы", "кряква",
    "ливневая", "ливневой", "ливневку", "решётка", "решётке", "решётку", "решетка",
    "сток", "стока", "колодец", "колодце", "канализация", "щели", "щелями",
    "спасатели", "спасателей", "пожарные", "пожарных", "спасение",
    "гнездо", "гнезда", "выводок", "кладка", "кладке", "плавают", "плавать",
    "мать", "матерью", "сердце", "пушистых", "комочек",
}


def parse_args():
    ap = argparse.ArgumentParser(description="ASS: заголовок + однословные субтитры")
    ap.add_argument("--srt", default=DEFAULT_SRT)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--title", default=None, help="Заголовок в кадре (иначе screen_title.txt)")
    ap.add_argument("--title-file", default=DEFAULT_TITLE_FILE)
    ap.add_argument("--keywords-file", default=DEFAULT_KEYWORDS)
    ap.add_argument("--extra-keys", default="", help="Доп. ключевые слова через запятую")
    ap.add_argument("--style", default="classic", choices=sorted(STYLES),
                    help="стиль субтитров: classic|clean|neon|min|cinema")
    return ap.parse_args()


def build_keywords(path: str, extra: str) -> set:
    keys = set(KEY_WORDS)
    p = Path(path)
    if p.exists():
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            w = line.strip().lower().strip(".,!?;:")
            if w:
                keys.add(w)
    for w in re.split(r"[,\n;]", extra):
        w = w.strip().lower()
        if w:
            keys.add(w)
    return keys


def build_title(title: str) -> str:
    words = title.split()
    out = []
    for i, w in enumerate(words):
        color = TITLE_PALETTE[i % len(TITLE_PALETTE)]
        out.append(color + w)
    return " ".join(out)


def parse_srt(srt_path: str):
    content = Path(srt_path).read_text(encoding="utf-8-sig")
    pattern = r'(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n(.+?)(?=\n\n|\Z)'
    return re.findall(pattern, content, re.DOTALL)


def srt_time_to_seconds(time_str: str) -> float:
    time_str = time_str.replace(",", ".")
    parts = time_str.split(":")
    h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
    return h * 3600 + m * 60 + s


def seconds_to_ass_time(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int((seconds % 1) * 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def split_words_with_timing(text: str, start_sec: float, end_sec: float):
    words = text.strip().split()
    if not words:
        return []
    word_duration = (end_sec - start_sec) / len(words)
    return [(w, start_sec + i * word_duration, start_sec + (i + 1) * word_duration)
            for i, w in enumerate(words)]


def main():
    a = parse_args()

    srt = Path(a.srt)
    if not srt.exists():
        print(f"[ERROR] нет SRT: {srt}")
        sys.exit(1)

    title = a.title
    if title is None:
        tp = Path(a.title_file)
        title = tp.read_text(encoding="utf-8-sig").strip() if tp.exists() else "НОВОСТЬ ДНЯ"

    keys = build_keywords(a.keywords_file, a.extra_keys)

    def is_key_word(word: str) -> bool:
        w = word.lower().strip(".,!?;:«»\"'()")
        if any(c.isdigit() for c in word):
            return True
        if w in keys:
            return True
        if word and word[0].isupper():
            return True
        if any(c in w for c in ["евро", "доллар", "тыс", "млн", "млрд"]):
            return True
        return False

    matches = parse_srt(str(srt))

    st = STYLES[a.style]

    ass = """[Script Info]
Title: Title + One Word with Key Words Highlight
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: HookTitle,Montserrat Black,80,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,2,0,1,6,3,8,30,30,200,1
"""
    # WordWhite/WordRed собираются из выбранного стиля; classic даёт те же
    # строки, что и раньше (дизайн по умолчанию не меняется).
    for sname, color in (("WordWhite", st["white"]), ("WordRed", st["key"] or st["white"])):
        ass += (f"Style: {sname},{st['font']},{st['size']},{color},{color},"
                f"{st['outline_color']},&H80000000,{st['bold']},0,0,0,100,100,"
                f"{st['spacing']},0,1,{st['outline']},{st['shadow']},2,0,0,400,1\n")

    ass += """
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ass += f"Dialogue: 1,0:00:00.00,1:00:00.00,HookTitle,,0,0,0,,{build_title(title)}\n"

    red = white = 0
    for idx, start, end, text in matches:
        s = srt_time_to_seconds(start)
        e = srt_time_to_seconds(end)
        for word, ws, we in split_words_with_timing(text, s, e):
            style = "WordRed" if (st["key"] and is_key_word(word)) else "WordWhite"
            if style == "WordRed":
                red += 1
            else:
                white += 1
            wt = st["tags"] + word
            ass += f"Dialogue: 0,{seconds_to_ass_time(ws)},{seconds_to_ass_time(we)},{style},,0,0,0,,{wt}\n"

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(ass, encoding="utf-8")
    print(f"[OK] ASS сохранён: {out}")
    print(f"    Заголовок: {title}")
    print(f"    Стиль субтитров: {a.style}")
    print(f"    Красных слов: {red} | белых: {white} | всего: {red + white}")


if __name__ == "__main__":
    main()
