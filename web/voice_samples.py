# -*- coding: utf-8 -*-
"""voice_samples.py — готовые примеры звучания голосов.

F5-TTS грузит модель 2–3 минуты, поэтому синтезировать пример «по кнопке»
нельзя: человек ждал бы минуты. Примеры готовятся заранее (один раз) и
отдаются как обычные аудиофайлы — прослушивание начинается мгновенно.

Если готового примера нет, отдаём сам референс голоса: это тот же тембр,
и файл уже лежит на диске, так что ожидания всё равно нет.

Как сгенерировать примеры (один запуск на все встроенные голоса):

    python voice_samples.py --builtin

Для клонированного голоса (референс уже есть, пример делает тот же скрипт):

    python voice_samples.py --user <user_id> <voice_id>
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

WEB = Path(__file__).resolve().parent
if str(WEB) not in sys.path:
    sys.path.insert(0, str(WEB))

import voices  # noqa: E402

F5 = Path(r"D:\AI\F5-TTS")
CKPT = F5 / "models" / "ru" / "F5TTS_v1_Base" / "model_240000_inference.safetensors"
VOCAB = F5 / "models" / "ru" / "F5TTS_v1_Base" / "vocab.txt"
FFMPEG = voices.FFMPEG

# одна фраза на все голоса: короткая, нейтральная, показывает тембр
SAMPLE_TEXT = ("Привет! Так звучит мой голос. "
               "Свежие новости и интересные истории — каждый день.")


# ------------------------------------------------------------------ пути

def builtin_sample(key: str) -> Path:
    return voices.BUILTIN_DIR / "samples" / f"{key}.mp3"


def user_sample(user_id: str, voice_id: str) -> Path:
    return voices.user_voice_dir(user_id) / "samples" / f"{voice_id}.mp3"


def sample_file(voice_id: str, user_id: str = "", prepare: bool = False):
    """Файл для прослушивания: готовый пример или сам референс.

    prepare=True разрешает подготовить референс «на месте» (медленно),
    поэтому в списке голосов используется prepare=False.
    -> Path | None
    """
    if voice_id in voices.BUILTIN_BY_KEY:
        mp3 = builtin_sample(voice_id)
        if mp3.exists() and mp3.stat().st_size > 1000:
            return mp3
        wav = voices.BUILTIN_DIR / f"{voice_id}.wav"
        if wav.exists():
            return wav
        if prepare:
            wav, _ = voices.builtin_paths(voice_id)
            return wav
        return None

    if not user_id:
        return None

    mp3 = user_sample(user_id, voice_id)
    if mp3.exists() and mp3.stat().st_size > 1000:
        return mp3

    # клон: референс — это уже запись его голоса
    import db
    v = db.get_voice(voice_id)
    if not v or v["user_id"] != user_id:
        return None
    ref = Path(v["ref_wav"])
    return ref if ref.exists() else None


def sample_ts(path) -> int:
    """Версия примера для cache-busting в браузере."""
    try:
        return int(Path(path).stat().st_mtime)
    except OSError:
        return 0


# ------------------------------------------------------------------ синтез

def _mp3(src_wav: Path, dst_mp3: Path) -> bool:
    """wav -> mp3 (96 kbps: ~10 c речи = ~120 КБ)."""
    dst_mp3.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [str(FFMPEG), "-y", "-loglevel", "error", "-i", str(src_wav),
             "-codec:a", "libmp3lame", "-b:a", "96k", str(dst_mp3)],
            check=True, timeout=120,
        )
        return dst_mp3.exists() and dst_mp3.stat().st_size > 1000
    except Exception:  # noqa: BLE001
        return False


def synth_batch(jobs: list, log=print) -> dict:
    """Озвучить фразу одним процессом (модель грузится один раз).

    jobs: [(ref_wav, ref_text, out_path_mp3)] -> {out_path: ok}
    """
    if not jobs:
        return {}

    # модель и ASR — как в f5_synth.py (ASR на CPU, иначе OOM на 4 ГБ VRAM)
    if str(F5) not in sys.path:
        sys.path.insert(0, str(F5))
    import f5_tts.infer.utils_infer as ui
    ui.device = "cpu"
    from f5_tts.api import F5TTS

    from f5_lock import GpuLock, wait_for_resources

    lock = GpuLock(log=log)
    if not lock.acquire(timeout_s=1800, note="voice_samples"):
        log("[samples] F5 занят, пропускаю")
        return {}

    result = {}
    try:
        wait_for_resources(min_vram_gb=1.8, min_ram_gb=1.5, timeout_s=300, log=log)
        t0 = time.time()
        log("[samples] загружаю модель…")
        f5 = F5TTS(model="F5TTS_v1_Base", ckpt_file=str(CKPT),
                   vocab_file=str(VOCAB), device="cuda")
        log(f"[samples] модель за {time.time() - t0:.0f} c")

        tmp_dir = F5 / "out" / "_samples_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        for ref, ref_text, out in jobs:
            out = Path(out)
            try:
                log(f"[samples] {out.name} ← {Path(ref).name}")
                wav, _sr, _spec = f5.infer(
                    ref_file=str(ref), ref_text=ref_text or "",
                    gen_text=SAMPLE_TEXT, nfe_step=64, speed=0.95,
                )
                tmp_wav = tmp_dir / (out.stem + ".wav")
                f5.export_wav(wav, str(tmp_wav))
                result[str(out)] = _mp3(tmp_wav, out)
                tmp_wav.unlink(missing_ok=True)
                log(f"[samples] {out.name}: "
                    f"{'готов' if result[str(out)] else 'ОШИБКА'}")
            except Exception as exc:  # noqa: BLE001
                result[str(out)] = False
                log(f"[samples] {out.name}: ошибка {exc}")
    finally:
        try:
            lock.release()
        except Exception:  # noqa: BLE001
            pass
    return result


def _builtin_jobs() -> list:
    jobs = []
    for meta in voices.BUILTIN:
        key = meta["key"]
        out = builtin_sample(key)
        if out.exists() and out.stat().st_size > 1000:
            continue
        wav, txt = voices.builtin_paths(key)
        if not wav:
            continue
        ref_text = txt.read_text(encoding="utf-8").strip() if txt else ""
        jobs.append((wav, ref_text, out))
    return jobs


def _user_jobs(user_id: str, voice_id: str) -> list:
    import db
    v = db.get_voice(voice_id)
    if not v or v["user_id"] != user_id:
        return []
    ref = Path(v["ref_wav"])
    if not ref.exists():
        return []
    return [(ref, v.get("ref_text") or "", user_sample(user_id, voice_id))]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--builtin", action="store_true", help="все встроенные голоса")
    ap.add_argument("--user", nargs=2, metavar=("USER_ID", "VOICE_ID"))
    ap.add_argument("--force", action="store_true", help="перегенерировать")
    a = ap.parse_args()

    if a.force and a.builtin:
        for meta in voices.BUILTIN:
            builtin_sample(meta["key"]).unlink(missing_ok=True)

    if a.builtin:
        jobs = _builtin_jobs()
    elif a.user:
        jobs = _user_jobs(a.user[0], a.user[1])
    else:
        ap.error("нужно --builtin или --user USER_ID VOICE_ID")

    if not jobs:
        print("[samples] всё готово, генерировать нечего")
        return 0

    print(f"[samples] к генерации: {len(jobs)}")
    res = synth_batch(jobs)
    ok = sum(1 for v in res.values() if v)
    print(f"[samples] готово {ok} из {len(jobs)}")
    return 0 if ok == len(jobs) else 1


if __name__ == "__main__":
    sys.exit(main())
