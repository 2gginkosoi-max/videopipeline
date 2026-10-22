#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mix_audio.py — финальный аудиомикс: голос + музыка (тише голоса) + звуковые акценты.

Требование ORIGINALITY_GUIDE.md (Правило 2/5): в ролике должны быть звуковые акценты
(whoosh/click) и фоновая музыка, которая НЕ громче голоса.

Работает через pydub (уже установлен вместе с F5-TTS).

Пример:
  python mix_audio.py --voice D:\\AI\\F5-TTS\\out\\voiceover_fast.wav ^
      --out D:\\AI\\F5-TTS\\out\\voiceover_mix.wav ^
      --accents-at "0,2.9,5.8,8.7,11.6" --bed auto
"""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pydub import AudioSegment  # noqa: E402

AUDIO_DIR = Path(r"D:\AI\VIDEO_PIPELINE\assets\audio")
DEFAULT_VOICE = r"D:\AI\F5-TTS\out\voiceover_fast.wav"
DEFAULT_OUT = r"D:\AI\F5-TTS\out\voiceover_mix.wav"

MUSIC_DB = -21.0   # музыка заметно тише голоса (требование: не громче)
WHOOSH_DB = -9.0   # whoosh на склейках
CLICK_DB = -12.0   # click на хуке
BOOM_DB = -7.0     # «бум»-акцент на хуке и финале (удержание)
RISER_DB = -11.0   # райзер перед поворотом


def pick_bed(voice_path: str, bed_arg: str) -> Path:
    beds = sorted(AUDIO_DIR.glob("bed_*.wav"))
    if not beds:
        return Path()
    if bed_arg and bed_arg != "auto":
        # допускаем «am» или полный путь
        for b in beds:
            if b.stem == f"bed_{bed_arg}" or str(b) == bed_arg:
                return b
    # «auto» — детерминированно по имени голоса (разным роликам — разные подложки)
    h = int(hashlib.md5(Path(voice_path).name.encode("utf-8")).hexdigest(), 16)
    return beds[h % len(beds)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", default=DEFAULT_VOICE)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--accents-at", default="", help="секунды через запятую (whoosh)")
    ap.add_argument("--bed", default="auto", help="auto | am | c | em | dm | путь")
    a = ap.parse_args()

    vp = Path(a.voice)
    if not vp.exists():
        print(f"[ERROR] нет голоса: {vp}")
        return 1

    voice = AudioSegment.from_file(str(vp))
    D = len(voice)
    print(f"[MIX] голос: {D/1000:.2f} c")

    bed = pick_bed(a.voice, a.bed)
    music_used = ""
    if bed and bed.exists():
        music = AudioSegment.from_file(str(bed))
        if len(music) < D:
            reps = D // len(music) + 1
            music = music * reps
        music = music[:D]
        music = music.apply_gain(MUSIC_DB)
        music = music.fade_in(500).fade_out(900)
        mix = voice.overlay(music)
        music_used = bed.name
        print(f"[MIX] музыка: {bed.name} ({MUSIC_DB:+.0f} dB, тише голоса)")
    else:
        mix = voice
        print("[WARN] музыкальная подложка не найдена — микс без музыки")

    whoosh_p = AUDIO_DIR / "whoosh.wav"
    click_p = AUDIO_DIR / "click.wav"
    accents = 0
    if whoosh_p.exists() and a.accents_at.strip():
        whoosh = AudioSegment.from_file(str(whoosh_p)).apply_gain(WHOOSH_DB)
        for tok in a.accents_at.split(","):
            tok = tok.strip()
            if not tok:
                continue
            ms = int(float(tok) * 1000)
            if 0 <= ms < D:
                mix = mix.overlay(whoosh, position=ms)
                accents += 1
    if click_p.exists():
        click = AudioSegment.from_file(str(click_p)).apply_gain(CLICK_DB)
        mix = mix.overlay(click, position=120)  # акцент на хуке (первые секунды)

    # --- удержание: «бум» на хуке и в финале + райзер перед поворотом ---
    boom_p = AUDIO_DIR / "boom.wav"
    riser_p = AUDIO_DIR / "riser.wav"
    if boom_p.exists():
        boom = AudioSegment.from_file(str(boom_p)).apply_gain(BOOM_DB)
        mix = mix.overlay(boom, position=60)          # хук
        mix = mix.overlay(boom, position=max(0, D - 1800))  # финал-панч
        accents += 2
    if riser_p.exists() and D > 6000:
        riser = AudioSegment.from_file(str(riser_p)).apply_gain(RISER_DB)
        mix = mix.overlay(riser, position=int(D * 0.55))  # перед поворотом
        accents += 1

    # --- «жирный» голос: компрессия + низкие для плотности (удержание) ---
    mix = mix.compress_dynamic_range()
    from pydub.effects import normalize as _norm  # noqa: E402
    mix = _norm(mix)

    # финальная нормализация по пикам, чтобы не клиппило
    peak = mix.max
    if peak > 0:
        current_db = 20 * math.log10(peak / 32768.0)
        mix = mix.apply_gain(-1.0 - current_db)

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    mix.export(str(out), format="wav")

    report = {"music": music_used or None, "music_db": MUSIC_DB,
              "whoosh": accents, "click": bool(click_p.exists()),
              "duration_s": round(len(mix) / 1000.0, 2)}
    rep_path = Path(r"D:\AI\VIDEO_PIPELINE\output\audio_report.json")
    rep_path.parent.mkdir(parents=True, exist_ok=True)
    rep_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[OK] микс сохранён: {out} | музыка={music_used or 'нет'} | "
          f"whoosh×{accents} | click={'да' if click_p.exists() else 'нет'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
