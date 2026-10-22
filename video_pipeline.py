#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""video_pipeline.py — ОДИН файл вместо цепочки отдельных скриптов.

Зачем: каждый вызов `python.exe script.py` — это новый процесс Python, который
OpenCode видит как «новый чат»/отдельный шаг. Пользователь жалуется, что лимита
не хватает. Этот скрипт выполняет ВСЁ внутри ОДНОГО процесса и в одном запуске.

Шаги:
  1. lint сценария (хук/аналитика/прогноз)
  2. prep_voice (санитайз + ударения RUAccent)
  3. F5-TTS озвучка
  4. atempo 1.15
  5. миксаудио (музыка + whoosh/click)
  6. Whisper субтитры
  7. fix_srt
  8. SEO (заголовок/описание/хэштеги)
  9. make_ass (ASS-субтитры)
 10. compose_segments (монтаж 1080x1920)
 11. originality_check
 12. publish (по флагу)

Пример запуска:
  python video_pipeline.py --script-file <путь> --asset <путь> --segments "0:3,5:3"
"""
import argparse
import subprocess
import sys
from pathlib import Path

PY = r"D:\AI\python310\python.exe"
F5 = Path(r"D:\AI\F5-TTS")
VP = Path(r"D:\AI\VIDEO_PIPELINE")
OUT = VP / "output"

VOICEOVER = F5 / "out" / "voiceover.wav"
VOICEOVER_FAST = F5 / "out" / "voiceover_fast.wav"
VOICEOVER_MIX = F5 / "out" / "voiceover_mix.wav"
VOICE_TXT = F5 / "voice.txt"
SCRIPT_CLEAN = F5 / "script_clean.txt"
SUBTITLES = F5 / "subtitles.srt"
SUBS_ASS = OUT / "subs.ass"
FINAL = OUT / "final_video.mp4"
STRESS_OVR = VP / "stress_overrides.txt"


def run(cmd, label):
    print(f"\n===== {label} =====", flush=True)
    r = subprocess.run(cmd)
    if r.returncode != 0:
        print(f"[ERROR] шаг «{label}» код {r.returncode}")
        sys.exit(1)


def run_allow(cmd, label):
    print(f"\n===== {label} =====", flush=True)
    return subprocess.run(cmd).returncode


def accent_times(segments: str) -> str:
    times, acc = [], 0.0
    for i, tok in enumerate(segments.split(",")):
        try:
            _, d = tok.split(":")
            d = float(d)
        except ValueError:
            continue
        if i:
            times.append(round(acc, 2))
        acc += d
    return ",".join(str(t) for t in times)


def main():
    ap = argparse.ArgumentParser(description="Единый конвейер Shorts")
    ap.add_argument("--script-file", default=str(F5 / "scenario.txt"))
    ap.add_argument("--asset", required=True)
    ap.add_argument("--brief-file", default=str(VP / "brief.txt"))
    ap.add_argument("--segments", required=True)
    ap.add_argument("--screen-title", default=None)
    ap.add_argument("--factor", type=float, default=1.15)
    ap.add_argument("--privacy", default="unlisted",
                    choices=["public", "unlisted", "private"])
    ap.add_argument("--category", default="24")
    ap.add_argument("--bed", default="auto")
    ap.add_argument("--skip-voice", action="store_true")
    ap.add_argument("--skip-publish", action="store_true")
    a = ap.parse_args()

    asset = Path(a.asset)
    if not asset.exists():
        print(f"[ERROR] нет футажа: {asset}")
        sys.exit(1)

    run_allow([PY, str(VP / "scenario_lint.py"), "--scenario", a.script_file],
              "1/11 Проверка сценария")

    if not a.skip_voice:
        run([PY, str(VP / "prep_voice.py"), "--src", a.script_file,
             "--voice-out", str(VOICE_TXT), "--script-out", str(SCRIPT_CLEAN),
             "--overrides", str(STRESS_OVR)], "2/11 Ударения (prep_voice)")
        run([PY, str(VP / "say_f5_checked.py"),
             "--voice-file", str(VOICE_TXT),
             "--script-file", str(SCRIPT_CLEAN),
             "--out", str(VOICEOVER)], "3/11 Озвучка F5-TTS (пофразно + проверка)")

    run([PY, str(VP / "speed_up.py"), "--in", str(VOICEOVER),
         "--out", str(VOICEOVER_FAST), "--factor", str(a.factor)],
        "4/11 Ускорение atempo")

    run([PY, str(VP / "audio_assets.py")], "5/11 Аудио-ассеты")
    run([PY, str(VP / "mix_audio.py"), "--voice", str(VOICEOVER_FAST),
         "--out", str(VOICEOVER_MIX), "--accents-at", accent_times(a.segments),
         "--bed", a.bed], "5/11 Аудиомикс")

    run([PY, str(F5 / "stt.py"), "--audio", str(VOICEOVER_FAST),
         "--srt", str(SUBTITLES)], "6/11 Whisper субтитры")
    run([PY, str(VP / "fix_srt.py"), "--srt", str(SUBTITLES),
         "--script", str(SCRIPT_CLEAN)], "7/11 fix_srt")

    run([PY, str(VP / "seo.py"), "--brief-file", a.brief_file], "8/11 SEO")

    if a.screen_title:
        (OUT / "screen_title.txt").write_text(a.screen_title.strip() + "\n",
                                              encoding="utf-8")
        print(f"[OK] screen_title -> {a.screen_title.strip()}")

    ass_cmd = [PY, str(VP / "make_ass.py"), "--srt", str(SUBTITLES),
               "--out", str(SUBS_ASS)]
    if a.screen_title:
        ass_cmd += ["--title", a.screen_title.strip()]
    run(ass_cmd, "9/11 ASS (субтитры + верхний заголовок)")

    # Автоподгонка сегментов: сумма фрагментов должна закрыть всю озвучку.
    # Иначе ролик обрывается (был случай: 7 сегментов по 2.4 = 16.8 c при аудио 33.5 c).
    segs = []
    for tok in a.segments.split(","):
        try:
            s, d = tok.split(":")
            segs.append((float(s), float(d)))
        except ValueError:
            continue
    audio_dur = 0.0
    try:
        import subprocess as _sp
        r = _sp.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", str(VOICEOVER_MIX)],
                    capture_output=True, text=True)
        audio_dur = float(r.stdout.strip())
    except (ValueError, OSError):
        audio_dur = 0.0
    total = sum(d for _, d in segs)
    src_dur = 0.0
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=noprint_wrappers=1:nokey=1", str(asset)],
                           capture_output=True, text=True)
        src_dur = float(r.stdout.strip())
    except (ValueError, OSError):
        src_dur = 0.0
    if audio_dur > 0 and total < audio_dur and segs and src_dur > 0:
        need = audio_dur - total + 0.3  # небольшой запас, лишнее срежет -t
        # Удлиняем последний сегмент; если не хватает исходника — растягиваем все
        last_s, last_d = segs[-1]
        room = max(0.0, src_dur - last_s)
        add = min(need, room)
        segs[-1] = (last_s, round(last_d + add, 3))
        total = sum(d for _, d in segs)
        if total < audio_dur - 0.3:
            k = (audio_dur + 0.3) / total
            segs = [(s, round(d * k, 3)) for s, d in segs]
        a.segments = ",".join(f"{s}:{d}" for s, d in segs)
        print(f"[OK] автосегменты под аудио {audio_dur:.2f} c -> {a.segments}")

    run([PY, str(VP / "compose_segments.py"), "--source", str(asset),
         "--audio", str(VOICEOVER_MIX), "--ass", str(SUBS_ASS),
         "--segments", a.segments, "--out", str(FINAL)], "10/11 Монтаж")

    rc = run_allow([PY, str(VP / "originality_check.py"), "--asset", str(asset),
                    "--video", str(FINAL), "--overlays", "", "--visual-state", "on"],
                   "11/11 Автопроверка оригинальности")

    if a.skip_publish:
        print("\n[SKIP] публикация")
    elif rc != 0:
        print("\n[BLOCK] публикация запрещена (оригинальность FAIL)")
        sys.exit(1)
    else:
        run([PY, str(VP / "publish.py"), "--video", str(FINAL),
             "--privacy", a.privacy, "--category", a.category, "--wait"],
            "Публикация")

    print("\n[DONE] Конвейер завершён.")


if __name__ == "__main__":
    main()
