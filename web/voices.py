# -*- coding: utf-8 -*-
"""voices.py — реестр голосов F5-TTS: встроенные, клонирование, определение пола.

F5-TTS — модель клонирования: «голос» = референс (wav 5–10 c) + точный текст референса.
Порядок важен: сначала режем аудио, потом снимаем текст именно с этой дорожки.
"""

import json
import re
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

WEB = Path(__file__).resolve().parent
BUILTIN_DIR = WEB / "voices" / "builtin"
USERS_DIR = WEB / "users"

FFMPEG = r"C:\Users\nasle\tools\ffmpeg\ffmpeg.exe"
PY = r"D:\AI\python310\python.exe"
STT = r"D:\AI\F5-TTS\stt.py"

# Референс должен быть 5–10 c: длинный референс «протекает» в озвучку на стыке батчей.
REF_SECONDS = 8.0

BUILTIN = [
    # --- дикторы, найденные в репозитории (реальная речь, разные тембры) ---
    {"key": "sauron",   "name": "Саурон",         "gender": "male",
     "src": r"D:\AI\F5-TTS\out\sauron_short.wav"},
    {"key": "voice12",  "name": "Диктор 12с",     "gender": "male",
     "src": r"D:\AI\F5-TTS\ref\voice_ref_12s.wav"},
    {"key": "robot",    "name": "Робот",          "gender": "male",
     "src": r"D:\AI\F5-TTS\assets\robot_prank.mp4"},
    {"key": "katyusha", "name": "Катюша",         "gender": "female",
     "src": r"D:\AI\F5-TTS\out\katyusha_voice_clone.wav"},
    {"key": "asu",      "name": "Асу",            "gender": "female",
     "src": r"D:\AI\F5-TTS\out\asu_vo.wav"},
    {"key": "pig",      "name": "Хрюн",           "gender": "male",
     "src": r"D:\AI\F5-TTS\out\news_short_07_pig.wav"},
]

BUILTIN_BY_KEY = {v["key"]: v for v in BUILTIN}


# ------------------------------------------------------------------ аудио

def read_wav_mono(path) -> tuple:
    """-> (samples float32, sample_rate) или (None, None)."""
    try:
        with wave.open(str(path), "rb") as w:
            n, sr, ch, sw = w.getnframes(), w.getframerate(), w.getnchannels(), w.getsampwidth()
            raw = w.readframes(n)
    except Exception:  # noqa: BLE001
        return None, None
    if sw != 2:
        return None, None
    data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    return data, sr


def detect_f0(path) -> float | None:
    """Средний основной тон (Гц) по автокорреляции на голосовых фреймах."""
    data, sr = read_wav_mono(path)
    if data is None or sr is None or len(data) < sr * 0.5:
        return None
    win, hop = int(sr * 0.04), int(sr * 0.02)
    lo, hi = int(sr / 400), int(sr / 60)
    vals = []
    for i in range(0, len(data) - win, hop):
        frame = data[i:i + win]
        if np.sqrt(np.mean(frame ** 2)) < 0.02:
            continue
        frame = frame - frame.mean()
        corr = np.correlate(frame, frame, mode="full")[win - 1:]
        if corr[0] <= 0:
            continue
        seg = corr[lo:hi]
        if not len(seg):
            continue
        k = int(np.argmax(seg)) + lo
        if corr[k] / corr[0] < 0.3:
            continue
        vals.append(sr / k)
    return float(np.median(vals)) if vals else None


def detect_gender(path) -> str:
    """Голос по основному тону. Русские ориентиры: мужчины ~100–160 Гц, женщины ~165–230 Гц."""
    f = detect_f0(path)
    if f is None:
        return "unknown"
    if f < 165:
        return "male"
    if f < 250:
        return "female"
    return "neutral"


def _loudest_slice(path, seconds: float) -> tuple[float, float]:
    """Найти участок длиной `seconds` с наибольшей энергией речи -> (start, end)."""
    data, sr = read_wav_mono(path)
    if data is None or sr is None:
        return 0.0, seconds
    total = len(data) / sr
    if total <= seconds:
        return 0.0, total
    win = int(sr * 0.05)
    count = max(1, len(data) // win)
    energy = np.array([
        np.sqrt(np.mean(data[i * win:(i + 1) * win] ** 2)) for i in range(count)
    ])
    need = int(seconds / 0.05)
    if need >= count:
        return 0.0, total
    csum = np.concatenate([[0], np.cumsum(energy)])
    scores = csum[need:] - csum[:-need]
    best = int(np.argmax(scores))
    start = best * 0.05
    return start, min(start + seconds, total)


def extract_wav(src, dst, start=None, duration=None) -> bool:
    """Привести любой аудио/видео к wav 24 кГц моно (то, что ждёт F5)."""
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src)]
    if start is not None:
        cmd += ["-ss", f"{start:.2f}"]
    if duration is not None:
        cmd += ["-t", f"{duration:.2f}"]
    cmd += ["-vn", "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(dst)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode == 0 and Path(dst).exists() and Path(dst).stat().st_size > 1000


def transcribe(wav_path) -> str:
    """Текст референса через Whisper (stt.py)."""
    segments = transcribe_segments(wav_path)
    return " ".join(t for _, _, t in segments)


def _parse_srt(srt_path: Path) -> list:
    """SRT -> [(start_sec, end_sec, text)]."""
    out = []
    if not srt_path.exists():
        return out
    raw = srt_path.read_text(encoding="utf-8", errors="replace")

    def to_sec(ts):
        ts = ts.replace(",", ".")
        parts = ts.split(":")
        try:
            h = float(parts[0]); m = float(parts[1]); s = float(parts[2])
        except (IndexError, ValueError):
            return None
        return h * 3600 + m * 60 + s

    blocks = re.split(r"\n\s*\n", raw.strip())
    for b in blocks:
        lines = [ln.strip() for ln in b.splitlines() if ln.strip()]
        if len(lines) < 2 or "-->" not in lines[1]:
            continue
        a, z = lines[1].split("-->")
        st, en = to_sec(a.strip()), to_sec(z.strip())
        if st is None or en is None:
            continue
        text = " ".join(lines[2:]).strip()
        if text:
            out.append((st, en, text))
    return out


def transcribe_segments(wav_path, language: str = "ru") -> list:
    """Whisper по файлу -> [(start, end, text)] с таймкодами."""
    srt = Path(wav_path).with_suffix(".asr.srt")
    cmd = [PY, STT, "--audio", str(wav_path), "--srt", str(srt), "--model", "small"]
    if language != "auto":
        cmd += ["--language", language]
    else:
        cmd += ["--language", "auto"]
    try:
        subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=1200)
    except subprocess.TimeoutExpired:
        return []
    segs = _parse_srt(srt)
    srt.unlink(missing_ok=True)
    return segs


def transcribe_segments_any(wav_path) -> list:
    """Сначала русский, потом автоопределение (на случай иностранной речи)."""
    segs = transcribe_segments(wav_path, "ru")
    if segs:
        return segs
    return transcribe_segments(wav_path, "auto")


def pick_speech_window(segments: list, target: float = REF_SECONDS) -> tuple:
    """Выбрать речевой отрезок ~target c по таймкодам ASR.

    Возвращает (start, end, text). Отрезок берётся по реальной речи,
    а не по громкости — иначе в б-roll с музыкой попадает музыка.
    """
    if not segments:
        return None

    # склеиваем соседние сегменты: речь с паузами внутри
    merged = []
    for st, en, tx in segments:
        if merged and st - merged[-1][1] < 0.6:
            ps, pe, pt = merged[-1]
            merged[-1] = (ps, en, (pt + " " + tx).strip())
        else:
            merged.append((st, en, tx))

    best = None
    for i in range(len(merged)):
        j = i
        while j < len(merged) and merged[j][1] - merged[i][0] <= target * 1.45:
            j += 1
        if j == i:
            j = i + 1
        span_end = merged[j - 1][1]
        words = sum(len(merged[k][2].split()) for k in range(i, j))
        dur = span_end - merged[i][0]
        if dur < 2.5 or words < 4:
            continue
        # плотность слов важнее длины: речь, а не протяжное «аааа»
        score = words / max(dur, 0.5)
        if best is None or score > best[0]:
            text = " ".join(merged[k][2] for k in range(i, j))
            best = (score, merged[i][0], min(span_end, merged[i][0] + target), text)

    if best is None:
        # речи почти нет — берём самый длинный кусок, он хоть что-то даст
        s, e, t = max(merged, key=lambda x: x[1] - x[0])
        return (s, min(e, s + target), t)

    _, start, end, text = best
    return (start, end, text)


def make_reference(src_path, dst_wav, target: float = REF_SECONDS) -> tuple:
    """Сделать референс из любого исходника. -> (ok, ref_text)"""
    src_path = Path(src_path)
    raw = Path(dst_wav).with_suffix(".raw.wav")
    if not extract_wav(src_path, raw):
        return False, ""

    data, sr = read_wav_mono(raw)
    total = (len(data) / sr) if data is not None and sr else 0.0

    if total <= target * 1.25:
        # короткий клик — берём целиком
        if not extract_wav(raw, dst_wav):
            raw.unlink(missing_ok=True)
            return False, ""
        raw.unlink(missing_ok=True)
        text = transcribe(dst_wav)
        return True, text

    # длинный — ищем речевой отрезок по таймкодам Whisper
    segments = transcribe_segments_any(raw)
    win = pick_speech_window(segments, target)
    if not win:
        raw.unlink(missing_ok=True)
        return False, ""
    start, end, text = win
    ok = extract_wav(raw, dst_wav, start=start, duration=end - start)
    raw.unlink(missing_ok=True)
    if not ok:
        return False, ""
    return True, text.strip()


def clone_from_file(src_path, name: str, gender: str = "auto") -> tuple:
    """Сделать референс-голос из загруженного файла. -> (wav, txt, gender, duration)"""
    src_path = Path(src_path)
    USERS_DIR.mkdir(parents=True, exist_ok=True)

    ref = src_path.with_suffix(".ref.wav")
    ok, text = make_reference(src_path, ref)
    if not ok:
        src_path.unlink(missing_ok=True)
        return None, None, "unknown", 0.0

    ref.with_suffix(".txt").write_text(text + "\n", encoding="utf-8")

    detected = detect_gender(ref)
    g = detected if gender in ("", "auto", None) else gender

    data, sr = read_wav_mono(ref)
    duration = (len(data) / sr) if data is not None and sr else 0.0
    return ref, ref.with_suffix(".txt"), g, duration


# ------------------------------------------------------------------ встроенные

def builtin_paths(key: str) -> tuple:
    """-> (wav, txt) готового референса; готовит при первом обращении."""
    meta = BUILTIN_BY_KEY[key]
    BUILTIN_DIR.mkdir(parents=True, exist_ok=True)
    wav = BUILTIN_DIR / f"{key}.wav"
    txt = BUILTIN_DIR / f"{key}.txt"
    if wav.exists() and wav.stat().st_size > 1000 and txt.exists():
        return wav, txt

    src = Path(meta["src"])
    if not src.exists():
        return None, None

    ok, text = make_reference(src, wav)
    if not ok:
        wav.unlink(missing_ok=True)
        return None, None

    txt.write_text(text + "\n", encoding="utf-8")
    return wav, txt


def builtin_meta(key: str) -> dict:
    """Лёгкая метаинформация о встроенном голосе (без тяжёлого ASR)."""
    index = load_index()
    if key in index:
        return index[key]
    meta = BUILTIN_BY_KEY.get(key)
    if not meta:
        return {}
    wav = BUILTIN_DIR / f"{key}.wav"
    out = {"id": key, "name": meta["name"], "gender": meta.get("gender", "unknown"),
           "builtin": True, "ready": wav.exists(), "f0": None, "duration": 0.0}
    if wav.exists():
        data, sr = read_wav_mono(wav)
        if data is not None and sr:
            out["duration"] = round(len(data) / sr, 2)
            f = detect_f0(wav)
            out["f0"] = round(f, 1) if f else None
            out["gender"] = detect_gender(wav)
    return out


# ------------------------------------------------------------------ индекс

INDEX_FILE = BUILTIN_DIR / "index.json"


def load_index() -> dict:
    if INDEX_FILE.exists():
        try:
            return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_index(index: dict) -> None:
    BUILTIN_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(json.dumps(index, ensure_ascii=False, indent=2),
                          encoding="utf-8")


def prepare_all_builtin(log=print) -> dict:
    """Подготовить все встроенные голоса и записать индекс. -> index"""
    index = {}
    for meta in BUILTIN:
        key = meta["key"]
        log(f"[VOICE] готовлю «{meta['name']}»…")
        wav, txt = builtin_paths(key)
        entry = {"id": key, "name": meta["name"], "builtin": True,
                 "ready": bool(wav), "f0": None, "duration": 0.0,
                 "gender": meta.get("gender", "unknown")}
        if wav:
            data, sr = read_wav_mono(wav)
            if data is not None and sr:
                entry["duration"] = round(len(data) / sr, 2)
            f = detect_f0(wav)
            entry["f0"] = round(f, 1) if f else None
            entry["gender"] = detect_gender(wav)
            if txt:
                entry["ref_text"] = txt.read_text(encoding="utf-8").strip()[:300]
        index[key] = entry
        log(f"         -> {'готов' if wav else 'НЕ ГОТОВ'} "
            f"F0={entry['f0']} пол={entry['gender']}")
    save_index(index)
    return index


def builtin_gender(key: str) -> str:
    wav, _ = builtin_paths(key)
    if not wav:
        return BUILTIN_BY_KEY[key]["gender"]
    return detect_gender(wav)


def user_voice_dir(user_id: str) -> Path:
    d = USERS_DIR / str(user_id) / "voices"
    d.mkdir(parents=True, exist_ok=True)
    return d


def user_video_dir(user_id: str) -> Path:
    d = USERS_DIR / str(user_id) / "videos"
    d.mkdir(parents=True, exist_ok=True)
    return d


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    prepare_all_builtin()
    print()
    index = load_index()
    for meta in BUILTIN:
        e = index.get(meta["key"], {})
        print(f"{meta['key']:10s} {e.get('name',''):16s} готов={e.get('ready')} "
              f"F0={e.get('f0')} пол={e.get('gender')} {e.get('duration')}c")
        print(f"           {str(e.get('ref_text',''))[:110]}")
