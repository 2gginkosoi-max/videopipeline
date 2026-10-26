#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""auto_news.py — полный конвейер «новость → оригинальный Shorts → публикация».

Соответствует ORIGINALITY_GUIDE.md / AGENTS.md (обязательный стандарт).

Шаги:
  0. проверка сценария (хук/аналитика/прогноз, 20–50 c) — scenario_lint.py;
  1. скачивание b-roll (если задан --video-url и файла ещё нет);
  2. подготовка текста (санитайз + ударения RUAccent) — prep_voice.py;
  3. озвучка F5-TTS — say_f5.py;
  4. ускорение темпа (atempo 1.15) — speed_up.py;
  5. звук: музыка + акценты — audio_assets.py + mix_audio.py;
  5.5 b-roll ПОД ТЕКУЩУЮ НОВОСТЬ — broll_agent.py (plan.json), иначе старый
      режим: один --asset на весь ролик;
  6. субтитры Whisper — stt.py + fix_srt.py;
  7. SEO: авто-заголовок + описание + хэштеги — seo.py;
  8. ASS: заголовок + однословные субтитры — make_ass.py;
  9. оверлеи: прогресс-бар + инфо-карточки — make_overlays.py;
 10. монтаж 1080x1920 — compose_segments.py;
 11. АВТОПРОВЕРКА оригинальности — originality_check.py (без PASS публикация запрещена);
 12. публикация в YouTube через n8n — publish.py.

Пример:
  python auto_news.py --asset "D:\\AI\\F5-TTS\\assets\\milk_cats.mp4" --skip-download ^
      --segments "0.8:2.9,5.0:2.9,9.5:2.9,17.5:2.9,22.5:2.9"
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PY = r"D:\AI\python310\python.exe"
F5 = r"D:\AI\F5-TTS"
VP = r"D:\AI\VIDEO_PIPELINE"
YTDLP = r"C:\Users\nasle\.agent-reach-venv\Scripts\yt-dlp.exe"
BROLL_AGENT = r"D:\AI\Video\broll_agent.py"

VOICEOVER = rf"{F5}\out\voiceover.wav"
VOICEOVER_FAST = rf"{F5}\out\voiceover_fast.wav"
VOICEOVER_MIX = rf"{F5}\out\voiceover_mix.wav"
VOICE_TXT = rf"{F5}\voice.txt"
SCRIPT_CLEAN = rf"{F5}\script_clean.txt"
STRESS_OVR = rf"{VP}\stress_overrides.txt"
SUBTITLES = rf"{F5}\subtitles.srt"
SUBS_ASS = rf"{VP}\output\subs.ass"
OVERLAYS_ASS = rf"{VP}\output\overlays.ass"
FINAL = rf"{VP}\output\final_video.mp4"
BROLL_DIR = rf"{VP}\output\broll"
BROLL_PLAN = rf"{BROLL_DIR}\plan.json"


def run(cmd, label):
    print(f"\n===== {label} =====", flush=True)
    r = subprocess.run(cmd)
    if r.returncode != 0:
        print(f"[ERROR] шаг «{label}» завершился с кодом {r.returncode}")
        sys.exit(1)


def run_allow_fail(cmd, label):
    print(f"\n===== {label} =====", flush=True)
    return subprocess.run(cmd).returncode


def accent_times(segments: str) -> str:
    """Секунды склеек (кроме первой) — для whoosh."""
    times, acc = [], 0.0
    for i, tok in enumerate(segments.split(",")):
        try:
            s, d = tok.split(":")
            d = float(d)
        except ValueError:
            continue
        if i:
            times.append(round(acc, 2))
        acc += d
    return ",".join(str(t) for t in times)


def main():
    ap = argparse.ArgumentParser(description="Полный конвейер Shorts")
    ap.add_argument("--video-url", default=None, help="прямая ссылка v.redd.it для b-roll")
    ap.add_argument("--asset", default=rf"{F5}\assets\news.mp4", help="локальный файл b-roll")
    ap.add_argument("--brief-file", default=rf"{VP}\brief.txt")
    ap.add_argument("--script-file", default=rf"{F5}\scenario.txt")
    ap.add_argument("--script", default=None, help="текст сценария (перезапишет scenario.txt)")
    ap.add_argument("--segments", default="0.8:2.9,5.0:2.9,9.5:2.9,17.5:2.9,22.5:2.9")
    ap.add_argument("--factor", type=float, default=1.15)
    ap.add_argument("--privacy", default="unlisted", choices=["public", "unlisted", "private"])
    ap.add_argument("--category", default="25", help="25 Новости, 27 Образование, 24 Развлечения")
    ap.add_argument("--bed", default="auto", help="музыкальная подложка: auto|am|c|em|dm")
    ap.add_argument("--style", default="classic",
                    choices=["classic", "clean", "neon", "min", "cinema"],
                    help="стиль субтитров (шаг 8, make_ass.py)")
    ap.add_argument("--overlays", action="store_true",
                    help="УСТАРЕЛО/ОТКЛЮЧЕНО: инфо-карточки по центру запрещены (только нижние субтитры + верхний заголовок)")
    ap.add_argument("--skip-download", action="store_true")
    ap.add_argument("--skip-voice", action="store_true")
    ap.add_argument("--skip-publish", action="store_true")
    ap.add_argument("--sharpen", default="",
                    help="unsharp для мелкого b-roll (360x360), напр. 5:5:1.0:5:5:0.0")
    ap.add_argument("--voice-ref", default="",
                    help="референс голоса для F5-TTS (wav 5-10 c) — свой клон")
    ap.add_argument("--voice-ref-text", default="",
                    help="точный текст референса (если задан --voice-ref)")
    ap.add_argument("--final", default="",
                    help="куда сохранить готовый ролик (по умолчанию output\\final_video.mp4)")
    a = ap.parse_args()

    # Финальный файл можно перенаправить (веб-интерфейс: свой файл на пользователя).
    final_path = Path(a.final) if a.final else Path(FINAL)
    final_str = str(final_path)
    final_path.parent.mkdir(parents=True, exist_ok=True)

    asset = Path(a.asset)

    # Заголовок ПРЕДЫДУЩЕГО выпуска читаем ЗДЕСЬ: позже seo.py перезапишет title.txt,
    # и архив шага 10.5 тогда назвал бы файл текущим заголовком (так гиббон в архиве
    # получил имя «Утята в ливневке» — чужое имя делает арх бесполезным).
    prev_title = ""
    tp_prev = Path(rf"{F5}\title.txt")
    if tp_prev.exists():
        prev_title = tp_prev.read_text(encoding="utf-8-sig").strip()

    # 0. сценарий + проверка по гайду
    if a.script:
        Path(a.script_file).write_text(a.script.strip() + "\n", encoding="utf-8")
        print(f"[OK] scenario.txt записан ({a.script_file})")
    if not Path(a.script_file).exists():
        print(f"[ERROR] нет сценария: {a.script_file} (передайте --script)")
        sys.exit(1)
    run_allow_fail([PY, rf"{VP}\scenario_lint.py", "--scenario", a.script_file],
                   "Проверка сценария (оригинальность/структура)")

    # 1. b-roll
    if not a.skip_download and a.video_url:
        # Файл b-roll один на все выпуски, поэтому кэш допустим ТОЛЬКО для того же
        # ролика: рядом лежит маркер с URL. Иначе прошлый b-roll молча уедет в
        # новый выпуск — так сценарий про птиц оказался поверх дэшкама с машинами.
        url_marker = asset.with_name(asset.name + ".url")
        prev_url = url_marker.read_text(encoding="utf-8-sig").strip() if url_marker.exists() else ""
        if asset.exists() and prev_url == a.video_url.strip():
            print(f"[SKIP] b-roll уже скачан для этого же видео: {asset}")
        else:
            if asset.exists():
                print(f"[INFO] b-roll другого видео ({prev_url or 'URL неизвестен'}) — качаю заново")
                asset.unlink()
            asset.parent.mkdir(parents=True, exist_ok=True)
            # Reddit через yt-dlp теперь требует cookies, а reddit_dl.py тянет
            # тот же ролик по HLS из RSS. Поэтому сначала пробуем его.
            if "reddit" in a.video_url or "v.redd.it" in a.video_url:
                run_allow_fail([PY, rf"{VP}\reddit_dl.py", "--url", a.video_url,
                                "--out", str(asset)], "Скачивание b-roll (Reddit)")
            if asset.exists() and asset.stat().st_size < 100_000:
                print("[WARN] файл b-roll подозрительно маленький — перекачиваю")
                asset.unlink()
            if not asset.exists():
                run([YTDLP, "--no-warnings", "-f", "bv*+ba/b", "--merge-output-format",
                     "mp4", "-o", str(asset), a.video_url], "Скачивание b-roll")
            url_marker.write_text(a.video_url.strip(), encoding="utf-8")
    if not asset.exists():
        print(f"[ERROR] нет b-roll: {asset}")
        sys.exit(1)

    # 2-3. подготовка текста (санитайз + ударения) + озвучка
    if a.skip_voice:
        print(f"[SKIP] подготовка текста и озвучка (используем {VOICEOVER})")
    else:
        run([PY, rf"{VP}\prep_voice.py", "--src", a.script_file,
             "--voice-out", VOICE_TXT, "--script-out", SCRIPT_CLEAN,
             "--overrides", STRESS_OVR], "Подготовка текста (ударения RUAccent)")
        say_cmd = [PY, rf"{F5}\say_f5.py", "--file", VOICE_TXT]
        if a.voice_ref and Path(a.voice_ref).exists():
            say_cmd += ["--ref", a.voice_ref]
            if a.voice_ref_text:
                say_cmd += ["--ref-text", a.voice_ref_text]
            print(f"[VOICE] свой голос: {a.voice_ref}")
        run(say_cmd, "Озвучка F5-TTS")

    # 3.5. проверка озвучки: F5 иногда теряет хвост длинного текста, и тогда
    # монтаж/субтитры (они строятся по аудио) получаются мусорными.
    if Path(VOICEOVER).exists() and Path(SCRIPT_CLEAN).exists():
        check_rc = run_allow_fail(
            [PY, rf"{VP}\voice_check.py",
             "--wav", VOICEOVER, "--script", SCRIPT_CLEAN,
             "--min-coverage", "90"],
            "Проверка озвучки (ASR vs сценарий)")
        if check_rc != 0:
            allow_bad = os.environ.get("ALLOW_BAD_VOICE", "").strip().lower() in (
                "1", "true", "yes", "on")
            if allow_bad:
                print("[WARN] проверка озвучки провалена, продолжаю (ALLOW_BAD_VOICE=1)")
            else:
                print("[ERROR] озвучка не совпадает со сценарием — сборку останавливаю,")
                print("        чтобы не отдать ролик с обрезанным/неразборчивым голосом.")
                print("        Перегенерируйте озвучку, сократите сценарий или поставьте")
                print("        ALLOW_BAD_VOICE=1, если хотите собрать как есть.")
                sys.exit(1)
    else:
        print("[WARN] проверка озвучки пропущена: нет voiceover.wav или script_clean.txt")

    # 4. ускорение
    run([PY, rf"{VP}\speed_up.py", "--in", VOICEOVER, "--out", VOICEOVER_FAST,
         "--factor", str(a.factor)], "Ускорение темпа (atempo)")

    # 5. звук: музыка + акценты (гайд, Правило 2)
    run([PY, rf"{VP}\audio_assets.py"], "Аудио-ассеты (музыка/акценты)")
    run([PY, rf"{VP}\mix_audio.py", "--voice", VOICEOVER_FAST, "--out", VOICEOVER_MIX,
         "--accents-at", accent_times(a.segments), "--bed", a.bed],
        "Аудиомикс (музыка + whoosh/click)")

    # 6. субтитры по финальному аудио
    run([PY, rf"{F5}\stt.py", "--audio", VOICEOVER_FAST, "--srt", SUBTITLES],
        "Whisper (субтитры)")
    run([PY, rf"{VP}\fix_srt.py", "--srt", SUBTITLES, "--script", SCRIPT_CLEAN],
        "Правка субтитров (fix_srt)")

    # 7. SEO (авто-заголовок + описание + хэштеги)
    run([PY, rf"{VP}\seo.py", "--brief-file", a.brief_file], "SEO")

    # 8. ASS (дизайн субтитров/заголовка — без изменений)
    run([PY, rf"{VP}\make_ass.py", "--srt", SUBTITLES, "--out", SUBS_ASS,
         "--style", a.style], "Сборка ASS")

    # 9.5 АРХИВ предыдущего ролика. Монтаж всегда пишет в output\final_video.mp4,
    # поэтому без архива готовый ролик прошлого выпуска исчезает (так потерялся
    # ролик про робота Рокки). Сохраняем копию до перезаписи.
    prev = final_path
    if prev.exists():
        archive = prev.parent / "archive"
        archive.mkdir(parents=True, exist_ok=True)
        old_title = re.sub(r"\s*#shorts\s*$", "", prev_title, flags=re.I).strip()
        slug = re.sub(r"[^0-9A-Za-zА-Яа-яЁё]+", "_", old_title)[:40].strip("_") or "final"
        stamp = time.strftime("%Y%m%d_%H%M%S")
        dst = archive / f"{stamp}_{slug}.mp4"
        try:
            shutil.copy2(prev, dst)
            print(f"[ARCHIVE] прошлый ролик сохранён: {dst}")
        except OSError as e:  # noqa: BLE001
            print(f"[WARN] архив не удался: {e}")

    # 9. оверлеи ОТКЛЮЧЕНЫ НАВСЕГДА: пользователь запретил вставку с рамкой по центру.
    #    В ролике только нижние субтитры и верхний заголовок.
    extra = []
    print("\n[SKIP] оверлеи (инфо-карточки/прогресс-бар) отключены навсегда")

    # 10. монтаж
    compose_cmd = ([PY, rf"{VP}\compose_segments.py", "--source", str(asset),
                    "--audio", VOICEOVER_MIX, "--ass", SUBS_ASS] + extra +
                   ["--segments", a.segments, "--out", final_str])
    if a.sharpen:
        compose_cmd += ["--sharpen", a.sharpen]
    run(compose_cmd, "Монтаж видео")

    # 11. автопроверка оригинальности (Правило 5)
    rc = run_allow_fail([PY, rf"{VP}\originality_check.py", "--asset", str(asset),
                         "--video", final_str, "--overlays", "",
                         "--visual-state", "on"],
                        "Автопроверка оригинальности")

    # 12. публикация (только если проверка пройдена)
    if a.skip_publish:
        # веб всегда работает без публикации — этап в лог не выводим
        pass
    elif rc != 0:
        print("[BLOCK] Публикация запрещена: автопроверка оригинальности НЕ пройдена.")
        sys.exit(1)
    else:
        run([PY, rf"{VP}\publish.py", "--video", final_str, "--privacy", a.privacy,
             "--category", a.category, "--wait"], "Публикация")

    print("\n[DONE] Конвейер завершён.")


if __name__ == "__main__":
    main()
