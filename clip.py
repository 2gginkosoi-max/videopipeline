#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clip.py — нарезка длинного видео на короткие вертикальные клипы (Shorts).

Что делает:
  1. берёт локальный файл или ссылку (yt-dlp);
  2. считает громкость по времени и моменты смены сцен;
  3. выбирает N лучших окон по ~30 с без пересечений;
  4. режет в 1080x1920 (обрезка кадра или размытый фон);
  5. по флагу --subs — распознаёт речь (faster-whisper) и жжёт субтитры
     тем же стилем, что и основной конвейер (make_ass.py);
  6. по флагу --revoice — переозвучивает клип выбранным голосом F5-TTS;
  7. режим --mode beat: короткие хайлайты, нарезанные по долям музыки.

Этапы печатаются как «===== Название =====» — веб-панель показывает их
в правом логе.

Примеры:
  python clip.py --input D:\\video\\long.mp4 --out-dir D:\\out --count 4
  python clip.py --url https://youtu.be/XXX --out-dir D:\\out --subs
  python clip.py --input game.mp4 --music beat.mp3 --mode beat --out-dir D:\\out
"""

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

VP = Path(r"D:\AI\VIDEO_PIPELINE")
F5 = Path(r"D:\AI\F5-TTS")
PY = sys.executable or r"D:\AI\python310\python.exe"

W, H = 1080, 1920          # формат Shorts
FPS = 30

STYLE_CHOICES = ("classic", "clean", "neon", "min", "cinema")


def _tool(name: str) -> str:
    """ffmpeg/ffprobe: из PATH, иначе из папки tools."""
    p = shutil.which(name)
    if p:
        return p
    alt = Path(r"C:\Users\nasle\tools\ffmpeg") / (name + ".exe")
    return str(alt) if alt.exists() else name


FFMPEG = _tool("ffmpeg")
FFPROBE = _tool("ffprobe")


def stage(title: str) -> None:
    print(f"\n===== {title} =====", flush=True)


def log(msg: str) -> None:
    print(msg, flush=True)


def run(cmd: list, what: str = "", timeout: float = 0) -> int:
    """Запуск с прозрачным логом. Возвращает код."""
    if what:
        log(f"[..] {what}")
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout or None)
    except subprocess.TimeoutExpired:
        log("[ERROR] таймаут команды")
        return 124
    if p.returncode != 0:
        tail = (p.stderr or p.stdout or "").strip().splitlines()[-6:]
        for ln in tail:
            log("      " + ln)
    return p.returncode


# ------------------------------------------------------------------ источник

def probe(path: str) -> dict:
    p = subprocess.run(
        [FFPROBE, "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        d = json.loads(p.stdout or "{}")
    except ValueError:
        d = {}
    fmt = d.get("format") or {}
    streams = d.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    a = next((s for s in streams if s.get("codec_type") == "audio"), {})
    return {
        "duration": float(fmt.get("duration") or 0),
        "width": int(v.get("width") or 0),
        "height": int(v.get("height") or 0),
        "fps": v.get("avg_frame_rate") or "30/1",
        "has_audio": bool(a),
    }


def download(url: str, dest_dir: Path) -> Path:
    stage("Скачивание видео")
    dest_dir.mkdir(parents=True, exist_ok=True)
    tmpl = str(dest_dir / "source.%(ext)s")
    cmd = [PY, "-m", "yt_dlp", "-f",
           "bv*[height<=1080]+ba/b[height<=1080]/b",
           "--merge-output-format", "mp4", "-o", tmpl, "--no-playlist", url]
    if run(cmd, "yt-dlp", timeout=3600) != 0:
        raise SystemExit("[ERROR] не удалось скачать видео по ссылке")
    files = sorted(dest_dir.glob("source.*"), key=lambda f: f.stat().st_size, reverse=True)
    if not files:
        raise SystemExit("[ERROR] файл не появился после скачивания")
    return files[0]


# ------------------------------------------------------------------ анализ

def extract_wav(src: str, out: Path, sr: int = 16000) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    run([FFMPEG, "-y", "-i", src, "-vn", "-ac", "1", "-ar", str(sr),
         "-c:a", "pcm_s16le", str(out)], "дорожка для анализа", timeout=1800)
    return out


def rms_curve(wav: Path, hop: float = 0.25) -> "list[float]":
    """Громкость по окнам 0.25 с, нормированная по 95-му перцентилю."""
    import numpy as np
    import soundfile as sf

    y, sr = sf.read(str(wav), dtype="float32", always_2d=False)
    if getattr(y, "ndim", 1) > 1:
        y = y.mean(axis=1)
    frame = max(1, int(hop * sr))
    n = len(y) // frame
    if n == 0:
        return [0.0]
    blocks = y[: n * frame].reshape(n, frame)
    rms = np.sqrt((blocks ** 2).mean(axis=1))
    p95 = float(np.percentile(rms, 95)) or 1.0
    rms = np.clip(rms / p95, 0.0, 2.0)
    # сглаживание ~1 с
    k = max(1, int(1.0 / hop))
    rms = np.convolve(rms, np.ones(k) / k, mode="same")
    return [float(x) for x in rms]


def scene_times(src: str) -> "list[float]":
    """Моменты смены сцен (фильтр scdet)."""
    p = subprocess.run(
        [FFMPEG, "-hide_banner", "-i", src, "-an",
         "-vf", "scdet=threshold=10", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=1800)
    out = []
    for m in re.finditer(r"lavfi\.scd\.time:\s*([0-9.]+)", p.stderr or ""):
        try:
            out.append(float(m.group(1)))
        except ValueError:
            pass
    return out


def score_windows(rms: "list[float]", scenes: "list[float]", duration: float,
                  length: float, hop: float = 0.25, step: float = 1.0):
    """Оценка всех окон длины length. Возвращает [(score, start)] по убыванию."""
    import numpy as np

    if duration < length:
        length = max(5.0, duration - 0.5)
    win = max(1, int(length / hop))
    arr = np.asarray(rms, dtype="float32")
    n = len(arr)
    if n <= win:
        return [(1.0, 0.0)]

    # префиксные суммы — среднее по окну за O(1)
    csum = np.concatenate([[0.0], np.cumsum(arr)])
    csum2 = np.concatenate([[0.0], np.cumsum(arr * arr)])
    starts = np.arange(0, max(1, n - win), max(1, int(step / hop)))
    mean = (csum[starts + win] - csum[starts]) / win
    var = np.maximum(0.0, (csum2[starts + win] - csum2[starts]) / win - mean ** 2)
    std = np.sqrt(var)

    sc = np.asarray(sorted(scenes), dtype="float32")
    dens = np.zeros(len(starts), dtype="float32")
    if len(sc):
        t0 = starts * hop
        t1 = t0 + length
        idx = np.searchsorted(sc, t1) - np.searchsorted(sc, t0)
        dens = np.clip(idx / 5.0, 0, 1)

    def norm(v):
        lo, hi = float(v.min()), float(v.max())
        return (v - lo) / (hi - lo) if hi - lo > 1e-6 else np.zeros_like(v)

    score = 0.55 * norm(mean) + 0.25 * norm(std) + 0.20 * dens
    # не берём самое начало и самый конец: там заставки и титры
    sec = starts * hop
    edge = np.ones(len(sec), dtype="float32")
    edge[sec < 3.0] = 0.25
    edge[sec + length > duration - 2.0] = 0.25
    score = score * edge

    order = np.argsort(-score)
    return [(float(score[i]), float(starts[i] * hop)) for i in order]


def pick_starts(scored, count: int, length: float, duration: float,
                min_gap: float = 1.0) -> "list[float]":
    chosen = []
    for score, start in scored:
        if len(chosen) >= count:
            break
        if start + length > duration + 0.01:
            continue
        if any(abs(start - c) < length + min_gap for c in chosen):
            continue
        chosen.append(start)
    chosen.sort()
    return chosen


# ------------------------------------------------------------------ монтаж

def fit_filter(fit: str) -> str:
    """Приведение кадра к 1080x1920: обрезка по центру или размытый фон."""
    if fit == "blur":
        return (
            "split=2[bg][fg];"
            f"[bg]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},boxblur=24:4[bg2];"
            f"[fg]scale={W}:-2[fg2];"
            f"[bg2][fg2]overlay=(W-w)/2:(H-h)/2,setsar=1"
        )
    return (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},setsar=1")


def cut(src: str, start: float, dur: float, out: Path, fit: str,
        with_audio: bool = True) -> bool:
    vf = f"{fit_filter(fit)},fps={FPS}"
    cmd = [FFMPEG, "-y", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", src,
           "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-pix_fmt", "yuv420p"]
    if with_audio:
        cmd += ["-c:a", "aac", "-b:a", "160k", "-ac", "2", "-ar", "48000"]
    else:
        cmd += ["-an"]
    cmd += ["-movflags", "+faststart", str(out)]
    return run(cmd, f"фрагмент {start:.1f}s", timeout=900) == 0


def burn_subs(clip: Path, style: str, work: Path) -> bool:
    """Распознать речь клипа и впечатать субтитры нашим ASS-стилем."""
    wav = work / (clip.stem + ".wav")
    srt = work / (clip.stem + ".srt")
    ass = work / (clip.stem + ".ass")
    if run([FFMPEG, "-y", "-i", str(clip), "-vn", "-ac", "1", "-ar", "16000",
            str(wav)], "дорожка клипа", timeout=600) != 0:
        return False
    rc = run([PY, str(F5 / "stt.py"), "--audio", str(wav), "--srt", str(srt),
              "--model", "small", "--language", "ru"], "распознавание речи",
             timeout=900)
    if rc != 0 or not srt.exists() or srt.stat().st_size < 20:
        log("[WARN] речь не распознана — клип без субтитров")
        return False
    if run([PY, str(VP / "make_ass.py"), "--srt", str(srt), "--out", str(ass),
            "--style", style, "--no-title"], "сборка ASS", timeout=300) != 0:
        return False
    tmp = work / (clip.stem + "_subs.mp4")
    rc = run([FFMPEG, "-y", "-i", str(clip), "-vf",
              f"ass={str(ass).replace(chr(92), '/')}",
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
              "-c:a", "copy", str(tmp)], "впечатывание субтитров", timeout=900)
    if rc == 0 and tmp.exists():
        tmp.replace(clip)
        return True
    return False


def revoice(clip: Path, ref: str, ref_text: str, work: Path) -> bool:
    """Заменить звук клипа речью выбранного голоса (F5-TTS)."""
    if not ref or not Path(ref).exists():
        log("[WARN] голос не найден — оставляю оригинальный звук")
        return False
    wav = work / (clip.stem + ".wav")
    srt = work / (clip.stem + ".srt")
    if not wav.exists():
        run([FFMPEG, "-y", "-i", str(clip), "-vn", "-ac", "1", "-ar", "16000",
             str(wav)], "дорожка клипа", timeout=600)
    if not srt.exists() or srt.stat().st_size < 20:
        run([PY, str(F5 / "stt.py"), "--audio", str(wav), "--srt", str(srt),
             "--model", "small", "--language", "ru"], "распознавание речи",
            timeout=900)
    text = ""
    if srt.exists():
        lines = []
        for ln in srt.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            s = ln.strip()
            if s and not s.isdigit() and "-->" not in s:
                lines.append(s)
        text = " ".join(lines)
    if len(text) < 10:
        log("[WARN] нечего озвучивать — оставляю оригинальный звук")
        return False

    txt = work / (clip.stem + ".txt")
    txt.write_text(text, encoding="utf-8")
    voice = work / (clip.stem + "_voice.wav")
    cmd = [PY, str(F5 / "say_f5.py"), "--file", str(txt), "--out", str(voice),
           "--ref", ref, "--no-verify"]
    if ref_text:
        cmd += ["--ref-text", ref_text]
    if run(cmd, "озвучка голосом", timeout=1800) != 0 or not voice.exists():
        log("[WARN] озвучка не удалась — оставляю оригинальный звук")
        return False

    tmp = work / (clip.stem + "_voice.mp4")
    rc = run([FFMPEG, "-y", "-i", str(clip), "-i", str(voice),
              "-map", "0:v", "-map", "1:a", "-c:v", "copy",
              "-c:a", "aac", "-b:a", "160k", "-shortest", str(tmp)],
             "замена звука", timeout=600)
    if rc == 0 and tmp.exists():
        tmp.replace(clip)
        return True
    return False


# ------------------------------------------------------------------ под бит

def beat_segments(music: str, every: int, max_total: float) -> "list[float]":
    """Длительности кусков между долями музыки."""
    import librosa
    import numpy as np

    wav = Path(music).with_suffix(".beat.wav")
    run([FFMPEG, "-y", "-i", music, "-vn", "-ac", "1", "-ar", "22050",
         str(wav)], "подготовка музыки", timeout=600)
    y, sr = librosa.load(str(wav), sr=22050, mono=True)
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
    beats = [float(b) for b in np.atleast_1d(beats)]
    if len(beats) < 4:
        raise SystemExit("[ERROR] не удалось найти доли в музыке")
    log(f"     темп ~{float(np.atleast_1d(tempo)[0]):.0f} BPM, долей: {len(beats)}")

    durs = []
    total = 0.0
    i = 0
    while i + every < len(beats):
        d = beats[i + every] - beats[i]
        d = max(0.6, min(d, 4.0))
        if total + d > max_total:
            break
        durs.append(round(d, 3))
        total += d
        i += every
    return durs


def build_beat_montage(src: str, music: str, out: Path, rms, scenes,
                       duration: float, fit: str, every: int,
                       max_total: float, work: Path, keep_original: bool) -> bool:
    stage("Поиск хайлайтов под бит")
    durs = beat_segments(music, every, max_total)
    log(f"     кусков: {len(durs)}, суммарно {sum(durs):.1f} с")

    scored = score_windows(rms, scenes, duration, min(durs) if durs else 2.0)
    used = []
    parts = []
    for i, d in enumerate(durs):
        cand = [(s, st) for s, st in scored
                if st + d <= duration and not any(abs(st - u) < 2.0 for u in used)]
        if not cand:
            break
        # каждый следующий кусок — из другого места, но тоже яркий
        score, start = cand[min(i, len(cand) - 1)]
        used.append(start)
        seg = work / f"beat_{i:03d}.mp4"
        if not cut(src, start, d, seg, fit, with_audio=keep_original):
            continue
        parts.append(seg)

    if not parts:
        log("[ERROR] не удалось нарезать куски")
        return False

    stage("Склейка под музыку")
    lst = work / "beat_list.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    silent = work / "beat_silent.mp4"
    if run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
            "-c", "copy", str(silent)], "склейка", timeout=900) != 0:
        return False

    cmd = [FFMPEG, "-y", "-i", str(silent), "-i", music]
    if keep_original:
        cmd += ["-filter_complex",
                "[0:a]volume=0.30[g];[1:a]volume=1.0[m];"
                "[g][m]amix=inputs=2:duration=first:dropout_transition=0[a]",
                "-map", "0:v", "-map", "[a]"]
    else:
        cmd += ["-map", "0:v", "-map", "1:a"]
    cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
            "-movflags", "+faststart", str(out)]
    return run(cmd, "музыка поверх", timeout=900) == 0


# ------------------------------------------------------------------ main

def parse_args():
    ap = argparse.ArgumentParser(description="Нарезка длинного видео на Shorts")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--input", help="локальный файл")
    src.add_argument("--url", help="ссылка (yt-dlp)")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--count", type=int, default=4, help="сколько клипов")
    ap.add_argument("--length", type=float, default=30.0, help="длина клипа, с")
    ap.add_argument("--fit", choices=["crop", "blur"], default="crop",
                    help="9:16: обрезка кадра или размытый фон")
    ap.add_argument("--subs", action="store_true", help="впечатать субтитры")
    ap.add_argument("--style", default="classic", choices=list(STYLE_CHOICES))
    ap.add_argument("--revoice", action="store_true",
                    help="переозвучить клипы выбранным голосом")
    ap.add_argument("--voice-ref", default="")
    ap.add_argument("--voice-ref-text", default="")
    ap.add_argument("--mode", choices=["clips", "beat"], default="clips")
    ap.add_argument("--music", default="", help="трек/бит для режима beat")
    ap.add_argument("--beat-every", type=int, default=2, help="долей на кусок")
    ap.add_argument("--max-total", type=float, default=45.0,
                    help="максимальная длина монтажа под бит, с")
    ap.add_argument("--keep-original", action="store_true",
                    help="в режиме beat оставить тихий оригинальный звук")
    return ap.parse_args()


def main() -> None:
    a = parse_args()
    t0 = time.time()
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "_work"
    work.mkdir(parents=True, exist_ok=True)

    # 1. источник
    if a.url:
        src = download(a.url, work)
    else:
        src = Path(a.input)
    if not src.exists():
        raise SystemExit(f"[ERROR] файл не найден: {src}")

    stage("Подготовка источника")
    info = probe(str(src))
    duration = info["duration"]
    log(f"     {src.name}: {duration:.0f} с, {info['width']}x{info['height']}")
    if duration < 8:
        raise SystemExit("[ERROR] видео слишком короткое для нарезки")

    # 2. анализ
    stage("Анализ звука и картинки")
    wav = extract_wav(str(src), work / "source.wav")
    rms = rms_curve(wav) if info["has_audio"] else [0.0]
    scenes = scene_times(str(src))
    log(f"     громкость: {len(rms)} окон, смен сцен: {len(scenes)}")

    manifest = []

    if a.mode == "beat":
        if not a.music or not Path(a.music).exists():
            raise SystemExit("[ERROR] для режима beat нужен файл музыки (--music)")
        out = out_dir / "beat_montage.mp4"
        ok = build_beat_montage(str(src), a.music, out, rms, scenes, duration,
                                a.fit, a.beat_every, a.max_total, work,
                                a.keep_original)
        if not ok:
            raise SystemExit("[ERROR] монтаж под бит не удался")
        manifest.append({"file": str(out), "title": "Хайлайты под бит",
                         "start": 0, "dur": a.max_total})
    else:
        stage("Поиск лучших моментов")
        scored = score_windows(rms, scenes, duration, a.length)
        starts = pick_starts(scored, a.count, a.length, duration)
        if not starts:
            raise SystemExit("[ERROR] не удалось выбрать моменты")
        for i, st in enumerate(starts, 1):
            log(f"     клип {i}: {st:.1f} с (оценка {scored[0][0]:.2f})")

        stage("Нарезка фрагментов")
        for i, st in enumerate(starts, 1):
            out = out_dir / f"clip_{i:02d}.mp4"
            if not cut(str(src), st, a.length, out, a.fit):
                log(f"[WARN] клип {i} не нарезался")
                continue
            manifest.append({
                "file": str(out),
                "title": f"Момент {i} · {int(st // 60):02d}:{int(st % 60):02d}",
                "start": round(st, 2), "dur": a.length,
            })

        if a.subs:
            stage("Распознавание речи для субтитров")
            for item in manifest:
                log(f"     {Path(item['file']).name}")
                burn_subs(Path(item["file"]), a.style, work)

        if a.revoice:
            stage("Озвучка голосом")
            for item in manifest:
                log(f"     {Path(item['file']).name}")
                revoice(Path(item["file"]), a.voice_ref, a.voice_ref_text, work)

    # 4. манифест
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    stage("Готово")
    log(f"     клипов: {len(manifest)}, за {time.time() - t0:.0f} с")
    for item in manifest:
        p = Path(item["file"])
        log(f"     {p.name} — {p.stat().st_size / 1024 / 1024:.1f} MB")
    print("[DONE]", flush=True)


if __name__ == "__main__":
    main()
