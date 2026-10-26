#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Веб-интерфейс «ГУСЬ ПЕРЕВОДИЛА».

Бэкенд НЕ переписывает логику конвейера — он запускает существующий
auto_news.py как subprocess и транслирует stdout в браузер через WebSocket.

Возможности:
  • профили пользователей (регистрация/вход, SQLite);
  • поиск свежих новостей в Reddit + генерация сценария (бесплатный LLM);
  • выбор голоса: встроенные F5-TTS + клон любого голоса из загрузки;
  • запуск конвейера в фоне, живой лог по WebSocket;
  • личный кабинет: свои ролики, голоса, сценарии.

Запуск:
    D:\\AI\\python310\\python.exe D:\\AI\\VIDEO_PIPELINE\\web\\app.py
    -> http://127.0.0.1:8000
"""

import asyncio
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request as StarletteRequest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import auth          # noqa: E402
import db            # noqa: E402
import llm           # noqa: E402
import news as news_mod  # noqa: E402
import voices        # noqa: E402
import voice_samples # noqa: E402
import vision        # noqa: E402
import subs as subs_mod        # noqa: E402
import vertical as vertical_mod  # noqa: E402

# ---------------------------------------------------------------- paths

# Пути берём из config.py: по умолчанию — исторические D:\AI\..., но их можно
# переопределить переменными окружения (VIDEO_PIPELINE_DIR, F5TTS_DIR,
# PIPELINE_PYTHON) и тогда сервер запускается из любого каталога/контейнера.
from config import FFMPEG, FFPROBE, F5, PY, VP  # noqa: E402

WEB = Path(__file__).resolve().parent
UPLOADS = WEB / "uploads"
OUTPUT = VP / "output"
ARCHIVE = OUTPUT / "archive"
SHARED_BRIEF = VP / "brief.txt"

for p in (UPLOADS, OUTPUT, ARCHIVE, WEB / "data", WEB / "voices" / "builtin"):
    p.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="ГУСЬ ПЕРЕВОДИЛА", docs_url="/api/docs", redoc_url=None)
app.mount("/static", StaticFiles(directory=str(WEB / "static")), name="static")
templates = Jinja2Templates(directory=str(WEB / "templates"))


def _asset_v(rel: str) -> int:
    """Версия статики по mtime — браузер не держит старый JS/CSS после правок."""
    try:
        return int((WEB / "static" / rel).stat().st_mtime)
    except OSError:
        return 0


templates.env.globals["asset_v"] = _asset_v

# ---------------------------------------------------------------- state

JOBS: dict = {}          # job_id -> dict
SUBSCRIBERS: list = []   # список asyncio.Queue
PIPELINE_SEM = asyncio.Semaphore(1)   # конвейер один: общие промежуточные файлы


def now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def broadcast(kind: str, payload: dict) -> None:
    msg = {"kind": kind, "ts": now(), **payload}
    for q in list(SUBSCRIBERS):
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            pass


# Этапы конвейера: auto_news.py печатает их как «===== Название =====».
# В панель справа уходит только название этапа (и таймер), без техвывода.
STAGE_RE = re.compile(r"^={3,}\s*([^=\s][^=]*?)\s*={3,}\s*$")
STAGE_NAMES = {
    "Проверка сценария (оригинальность/структура)": "Проверка сценария",
    "Скачивание b-roll (Reddit)": "Скачивание видео",
    "Скачивание b-roll": "Скачивание видео",
    "Подготовка текста (ударения RUAccent)": "Подготовка текста",
    "Озвучка F5-TTS": "Озвучка голосом",
    "Ускорение темпа (atempo)": "Выравнивание темпа речи",
    "Аудио-ассеты (музыка/акценты)": "Музыка и звуковые акценты",
    "Аудиомикс (музыка + whoosh/click)": "Сведение звука",
    "Whisper (субтитры)": "Распознавание речи для субтитров",
    "Правка субтитров (fix_srt)": "Вычитка субтитров",
    "SEO": "Заголовок и описание",
    "Сборка ASS": "Субтитры и заголовок в кадре",
    "Монтаж видео": "Монтаж видео",
    "Автопроверка оригинальности": "Проверка оригинальности",
}


def _seo_snapshot(since_ts: float) -> dict:
    """Заголовок/теги, которые seo.py только что выбрал для ЭТОГО ролика."""
    f = OUTPUT / "seo.json"
    try:
        if not f.exists() or f.stat().st_mtime < since_ts:
            return {}
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {"title": d.get("title", ""), "tags": d.get("tags") or [],
            "hashtags": d.get("hashtags") or []}


def make_job(cmd: list, meta: dict) -> dict:
    job = {
        "id": uuid.uuid4().hex[:12],
        "user_id": meta.get("user_id"),
        "status": "queued",
        "started": datetime.now().isoformat(timespec="seconds"),
        "finished": None,
        "returncode": None,
        "cmd": cmd,
        "meta": meta,
        "log": [],
        "stage": "",
        "stage_index": 0,
        "stages": [],        # [{"label": ..., "step": n}] — для восстановления UI
        "video_id": None,
    }
    JOBS[job["id"]] = job
    return job


# ---------------------------------------------------------------- helpers

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def slugify(text: str, limit: int = 40) -> str:
    """Имя файла: латиница, цифры и подчёркивания (кириллицу транслитерируем)."""
    s = (text or "").lower()
    s = "".join(_TRANSLIT.get(ch, ch) for ch in s)
    s = re.sub(r"[^0-9a-z]+", "_", s)[:limit].strip("_")
    return s or "video"


def list_videos() -> list:
    """Готовые ролики: output/*.mp4 + output/archive/*.mp4."""
    items = []
    for folder, archived in ((OUTPUT, False), (ARCHIVE, True)):
        if not folder.exists():
            continue
        for f in sorted(folder.glob("*.mp4")):
            try:
                st = f.stat()
            except OSError:
                continue
            items.append({
                "name": f.name,
                "folder": str(folder),
                "archived": archived,
                "size": st.st_size,
                "size_h": f"{st.st_size / 1024 / 1024:.1f} MB",
                "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%d.%m.%Y %H:%M"),
                "ts": st.st_mtime,
            })
    items.sort(key=lambda x: -x["ts"])
    return items


def voice_ref_for(voice_id: str, user_id: str) -> tuple:
    """-> (ref_wav, ref_text, voice_name) для выбранного голоса."""
    if not voice_id:
        return "", "", ""
    v = voices.BUILTIN_BY_KEY.get(voice_id)
    if v:
        wav, txt = voices.builtin_paths(voice_id)
        if not wav:
            raise HTTPException(400, f"Не удалось подготовить голос «{v['name']}»")
        return str(wav), (txt.read_text(encoding="utf-8").strip() if txt else ""), v["name"]
    row = db.get_voice(voice_id)
    if not row or row["user_id"] != user_id:
        raise HTTPException(404, "Голос не найден")
    ref = Path(row["ref_wav"])
    if not ref.exists():
        raise HTTPException(400, "Файл голоса потерян, загрузите заново")
    return str(ref), (row["ref_text"] or ""), row["name"]


def build_cmd(data: dict, user_id: str) -> tuple:
    """Собрать команду для auto_news.py. -> (cmd, meta)"""
    cmd = [PY, str(VP / "auto_news.py")]

    udir = voices.user_video_dir(user_id).parent
    udir.mkdir(parents=True, exist_ok=True)

    script = (data.get("script") or "").strip()
    if script:
        # сценарий пишем в файл пользователя: иначе упрётся в лимит
        # длины командной строки Windows (8191 символ)
        script_file = udir / "scenario.txt"
        script_file.write_text(script + "\n", encoding="utf-8")
        cmd += ["--script-file", str(script_file)]

    asset = (data.get("asset") or "").strip()
    if asset:
        cmd += ["--asset", asset]

    url = (data.get("video_url") or "").strip()
    if url:
        cmd += ["--video-url", url]

    segments = (data.get("segments") or "").strip()
    if segments:
        cmd += ["--segments", segments]

    try:
        factor = float(data.get("factor") or 1.15)
    except (TypeError, ValueError):
        factor = 1.15
    cmd += ["--factor", str(factor)]

    privacy = data.get("privacy") or "unlisted"
    if privacy in ("public", "unlisted", "private"):
        cmd += ["--privacy", privacy]

    category = (data.get("category") or "25").strip()
    cmd += ["--category", category]

    bed = (data.get("bed") or "auto").strip()
    if bed:
        cmd += ["--bed", bed]

    # стиль субтитров из шага 5 (make_ass.py --style)
    sub_style = (data.get("sub_style") or "classic").strip()
    if sub_style not in ("classic", "clean", "neon", "min", "cinema"):
        sub_style = "classic"
    cmd += ["--style", sub_style]

    if data.get("sharpen"):
        cmd += ["--sharpen", str(data["sharpen"]).strip()]
    if data.get("skip_voice"):
        cmd.append("--skip-voice")
    if data.get("skip_download"):
        cmd.append("--skip-download")
    # Публикации в конвейере больше нет: ролик сохраняется в профиль,
    # скачивает и выкладывает пользователь сам.
    cmd.append("--skip-publish")

    # голос
    voice_name = ""
    if not data.get("skip_voice"):
        ref, ref_text, voice_name = voice_ref_for(data.get("voice_id") or "", user_id)
        if ref:
            cmd += ["--voice-ref", ref]
            if ref_text:
                cmd += ["--voice-ref-text", ref_text]

    # персональный бриф для SEO
    brief = udir / "brief.txt"
    brief.write_text(
        f"Тема: {data.get('topic') or (script[:120] if script else 'видео')}\n"
        f"Контекст: {data.get('context') or ''}\n"
        f"Сценарий:\n{script}\n",
        encoding="utf-8")
    cmd += ["--brief-file", str(brief)]

    # персональный выходной файл
    vdir = voices.user_video_dir(user_id)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    title_slug = slugify(data.get("title") or data.get("topic") or "video")
    final = vdir / f"{stamp}_{title_slug}.mp4"
    cmd += ["--final", str(final)]

    meta = {
        "user_id": user_id,
        "title": data.get("title") or data.get("topic") or "Без названия",
        "topic": data.get("topic") or "",
        "context": data.get("context") or "",
        "voice": voice_name,
        "final": str(final),
        "script": script[:400],
    }
    return cmd, meta


async def run_job(job: dict) -> None:
    """Запустить процесс и транслировать вывод в лог + WebSocket."""
    cmd = job["cmd"]
    meta = job["meta"]
    user_id = meta.get("user_id")

    async with PIPELINE_SEM:
        job["status"] = "running"
        broadcast("job_start", {"job_id": job["id"], "cmd": " ".join(cmd[1:])})
        job["log"].append(f"$ {' '.join(cmd[1:])}")
        job_started = time.time()

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(VP),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"},
            )
        except Exception as exc:  # noqa: BLE001
            job["status"] = "error"
            job["finished"] = datetime.now().isoformat(timespec="seconds")
            job["log"].append(f"[ERROR] не удалось запустить процесс: {exc}")
            broadcast("job_end", {"job_id": job["id"], "status": "error", "returncode": -1})
            return

        assert proc.stdout is not None
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").rstrip()
            # Полный вывод auto_news оставляем в job["log"] (для отладки), а в
            # панель справа отдаём ТОЛЬКО этапы: «что сейчас происходит».
            job["log"].append(line)
            # ошибки/предупреждения показываем в правой панели, иначе причина
            # остановки видна только в консоли сервера
            if line.startswith("[ERROR]") or line.startswith("[WARN]"):
                broadcast("log", {"job_id": job["id"], "line": line})
            m = STAGE_RE.match(line)
            if m:
                label = m.group(1).strip()
                # публикации в вебе больше нет — этап не показываем
                if label.lower().startswith("публикац"):
                    continue
                prev_label = job["stage"]
                job["stage"] = label
                job["stage_index"] += 1
                shown = STAGE_NAMES.get(label, label)
                job["stages"].append({"label": shown, "step": job["stage_index"]})
                broadcast("stage", {"job_id": job["id"],
                                    "label": shown,
                                    "step": job["stage_index"]})
                # SEO только что закончился — показываем, какие теги он выбрал
                if prev_label == "SEO":
                    snap = _seo_snapshot(job_started)
                    if snap:
                        broadcast("seo", {"job_id": job["id"], **snap})

        rc = await proc.wait()

    job["returncode"] = rc
    job["finished"] = datetime.now().isoformat(timespec="seconds")
    job["status"] = "done" if rc == 0 else "error"

    # регистрируем готовый ролик в профиле
    # (даже если конвейер упал на последнем шаге — файл уже на диске)
    if user_id:
        final = Path(meta.get("final", ""))
        if final.exists() and final.stat().st_size > 0:
            try:
                rec = db.add_video(
                    user_id=user_id, job_id=job["id"], title=meta.get("title", ""),
                    path=str(final), size=final.stat().st_size)
                job["video_id"] = rec["id"]
                size_mb = final.stat().st_size / 1024 / 1024
                broadcast("video_ready", {
                    "job_id": job["id"],
                    "video_id": rec["id"],
                    "title": rec["title"],
                    "name": final.name,
                    "path": str(final),
                    "size_h": f"{size_mb:.1f} MB",
                    "url": f"/api/video/{rec['id']}",
                    "download": f"/api/download/{rec['id']}",
                })
                job["log"].append(f"[OK] ролик сохранён: {final}")
            except Exception as exc:  # noqa: BLE001
                job["log"].append(f"[WARN] не удалось сохранить ролик в профиль: {exc}")

    broadcast("job_end", {"job_id": job["id"], "status": job["status"],
                          "returncode": rc, "video_id": job["video_id"]})


# ---------------------------------------------------------------- auth routes

def _set_session_cookie(response, token: str) -> None:
    response.set_cookie(
        "goose_session", token,
        max_age=60 * 60 * 24 * 30,
        httponly=True,
        samesite="lax",
        path="/",
    )


@app.post("/api/auth/register")
async def api_register(payload: dict, response: Response):
    data = payload or {}
    user = auth.register(data.get("username", ""), data.get("password", ""),
                         data.get("email", ""))
    token = db.create_session(user["id"])
    _set_session_cookie(response, token)
    return {"ok": True, "user": user, "token": token}


@app.post("/api/auth/login")
async def api_login(payload: dict, response: Response):
    data = payload or {}
    user = auth.login(data.get("username", ""), data.get("password", ""))
    token = db.create_session(user["id"])
    _set_session_cookie(response, token)
    return {"ok": True, "user": user, "token": token}


@app.post("/api/auth/logout")
async def api_logout(response: Response, goose_session: str | None = Cookie(default=None)):
    if goose_session:
        db.drop_session(goose_session)
    response.delete_cookie("goose_session", path="/")
    return {"ok": True}


@app.get("/api/auth/me")
async def api_me(user: dict | None = Depends(auth.current_user)):
    return {"user": user}


# ---------------------------------------------------------------- pages

@app.get("/", response_class=HTMLResponse)
async def index(request: StarletteRequest):
    return templates.TemplateResponse(request, "base_layout.html", {})


@app.get("/results", response_class=HTMLResponse)
async def results_page(request: StarletteRequest):
    # старый дизайн убран: архив теперь вкладка на главной
    return RedirectResponse("/#archive", status_code=307)


@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: StarletteRequest):
    # старый дизайн убран: профиль теперь вкладка на главной
    return RedirectResponse("/#profile", status_code=307)


@app.get("/layout", response_class=HTMLResponse)
async def layout_demo(request: StarletteRequest):
    return templates.TemplateResponse(request, "base_layout.html", {})


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: StarletteRequest):
    return templates.TemplateResponse(request, "login.html", {"active": "login"})


# ---------------------------------------------------------------- voices

@app.get("/api/voices")
async def api_voices(user: dict | None = Depends(auth.current_user)):
    """Встроенные + пользовательские голоса."""
    out = []
    index = voices.load_index()

    for meta in voices.BUILTIN:
        entry = index.get(meta["key"])
        if not entry:
            entry = voices.builtin_meta(meta["key"])
        name = entry.get("name", meta["name"])
        gender = entry.get("gender", meta.get("gender", "unknown"))

        # ручное переопределение (название/пол) хранится в БД
        ov = db.get_builtin_override(meta["key"])
        if ov:
            name = ov.get("name") or name
            gender = ov.get("gender") or gender

        out.append({
            "id": meta["key"],
            "name": name,
            "gender": gender,
            "builtin": True,
            "ready": bool(entry.get("ready")),
            "f0": entry.get("f0"),
            "duration": entry.get("duration", 0),
            "ref_text": (entry.get("ref_text") or "")[:160],
            "sample_url": f"/api/voices/{meta['key']}/sample",
            "sample_ts": voice_samples.sample_ts(
                voice_samples.sample_file(meta["key"])),
        })

    if user:
        for v in db.list_voices(user["id"]):
            if v["builtin"]:
                continue
            out.append({
                "id": v["id"], "name": v["name"], "gender": v["gender"],
                "builtin": False, "ready": Path(v["ref_wav"]).exists(),
                "f0": None, "duration": 0,
                "ref_text": (v["ref_text"] or "")[:160],
                "created_at": v["created_at"],
                "sample_url": f"/api/voices/{v['id']}/sample",
                "sample_ts": voice_samples.sample_ts(
                    voice_samples.sample_file(v["id"], user["id"])),
            })
    return {"voices": out}


@app.get("/api/voices/{voice_id}/sample")
async def api_voice_sample(voice_id: str,
                            user: dict | None = Depends(auth.current_user)):
    """Готовый пример голоса: отдаём файл, поэтому играет сразу."""
    auth.require_user(user)
    f = voice_samples.sample_file(voice_id, user["id"])
    if not f or not f.exists():
        raise HTTPException(404, "Пример ещё не готов")
    media = "audio/mpeg" if f.suffix.lower() == ".mp3" else "audio/wav"
    return StreamingResponse(
        f.open("rb"), media_type=media,
        headers={"Cache-Control": "private, max-age=86400"})


@app.post("/api/voices/clone")
async def api_clone_voice(
    file: UploadFile = File(...),
    name: str = Form(""),
    gender: str = Form("auto"),
    user: dict | None = Depends(auth.current_user),
):
    """Клонировать голос из загруженного аудио/видео."""
    auth.require_user(user)
    if not file.filename:
        raise HTTPException(400, "пустой файл")

    ext = Path(file.filename).suffix.lower() or ".wav"
    safe = "".join(c for c in Path(file.filename).stem if c.isalnum() or c in "._-")[:50]
    vdir = voices.user_voice_dir(user["id"])
    src = vdir / f"{uuid.uuid4().hex[:8]}_{safe}{ext}"
    with src.open("wb") as fh:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            fh.write(chunk)

    ref, txt, g, dur = await asyncio.to_thread(
        voices.clone_from_file, src, name, gender)

    if not ref:
        src.unlink(missing_ok=True)
        raise HTTPException(400, "Не удалось выделить голос: нужна чистая речь 5–10 с без музыки, эха и посторонних голосов")

    vname = (name or "").strip() or src.stem
    rec = db.add_voice(user_id=user["id"], name=vname, ref_wav=str(ref),
                       ref_text=(txt.read_text(encoding="utf-8").strip() if txt else ""),
                       gender=g, builtin=0)
    return {"ok": True, "voice": {
        "id": rec["id"], "name": rec["name"], "gender": rec["gender"],
        "builtin": False, "ready": True, "ref_text": rec["ref_text"][:160]}}


@app.patch("/api/voices/{voice_id}")
async def api_update_voice(voice_id: str, payload: dict,
                           user: dict | None = Depends(auth.current_user)):
    """Переименовать голос или сменить его пол (в т.ч. у встроенного)."""
    auth.require_user(user)
    data = payload or {}

    # встроенный голос: правим метку в БД, сам референс не трогаем
    if voice_id in voices.BUILTIN_BY_KEY:
        meta = voices.BUILTIN_BY_KEY[voice_id]
        entry = voices.builtin_meta(voice_id)
        name = (data.get("name") or entry.get("name") or meta["name"]).strip()
        gender = (data.get("gender") or entry.get("gender") or meta["gender"]).strip()
        db.set_builtin_override(voice_id, name, gender)
        return {"ok": True, "voice": {"id": voice_id, "name": name, "gender": gender}}

    v = db.get_voice(voice_id)
    if not v or v["user_id"] != user["id"]:
        raise HTTPException(404, "Голос не найден")
    name = (data.get("name") or v["name"]).strip()
    gender = (data.get("gender") or v["gender"]).strip()
    db.execute("UPDATE voices SET name = ?, gender = ? WHERE id = ?",
               (name, gender, voice_id))
    return {"ok": True, "voice": {"id": voice_id, "name": name, "gender": gender}}


@app.delete("/api/voices/{voice_id}")
async def api_delete_voice(voice_id: str, user: dict | None = Depends(auth.current_user)):
    auth.require_user(user)
    ok = db.delete_voice(voice_id, user["id"])
    if not ok:
        raise HTTPException(404, "Голос не найден")
    return {"ok": True}


@app.post("/api/voices/preview")
async def api_voice_preview(payload: dict,
                             user: dict | None = Depends(auth.current_user)):
    """Синтезировать короткое пробное аудио выбранным голосом."""
    auth.require_user(user)
    data = payload or {}
    text = (data.get("text") or "Проверка голоса. Это тестовое сообщение.").strip()[:220]
    ref, ref_text, vname = voice_ref_for(data.get("voice_id") or "", user["id"])
    if not ref:
        raise HTTPException(400, "Голос не выбран")

    vdir = voices.user_voice_dir(user["id"])
    out = vdir / f"preview_{uuid.uuid4().hex[:8]}.wav"
    cmd = [PY, str(F5 / "say_f5.py"), "--file", "-", "--out", str(out),
           "--ref", ref, "--no-verify"]
    if ref_text:
        cmd += ["--ref-text", ref_text]

    # say_f5.py читает текст из файла, поэтому пишем его рядом и подменяем путь
    txtfile = vdir / f"preview_{uuid.uuid4().hex[:8]}.txt"
    txtfile.write_text(text, encoding="utf-8")
    cmd[cmd.index("--file") + 1] = str(txtfile)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        out_s, _ = await proc.communicate()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Ошибка синтеза: {exc}") from exc

    if not out.exists():
        tail = (out_s or b"").decode("utf-8", errors="replace").strip().splitlines()[-5:]
        raise HTTPException(500, "Голос не отвечает: " + " / ".join(tail))
    return {"ok": True, "url": f"/api/voice-preview/{out.name}", "voice": vname}


@app.get("/api/voice-preview/{name}")
async def api_voice_preview_file(name: str, user: dict | None = Depends(auth.current_user)):
    auth.require_user(user)
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "недопустимое имя")
    f = voices.user_voice_dir(user["id"]) / name
    if not f.exists():
        raise HTTPException(404, "не найдено")
    return StreamingResponse(f.open("rb"), media_type="audio/wav")


# ---------------------------------------------------------------- news

@app.get("/api/news/subs")
async def api_subs():
    return {"subs": news_mod.SUBS, "modes": list(news_mod.MODES.keys())}


@app.get("/api/news")
async def api_news(user: dict | None = Depends(auth.current_user)):
    if not user:
        return {"posts": []}
    return {"posts": db.get_cached_news(user["id"])}


@app.post("/api/news/search")
async def api_news_search(payload: dict,
                           user: dict | None = Depends(auth.current_user)):
    """Найти свежие новости. Reddit медленный — поиск идёт в фоне, прогресс по WS."""
    auth.require_user(user)
    data = payload or {}
    subs = data.get("subs") or news_mod.rotate_subs(1)
    mode = data.get("mode") or "new"
    force = bool(data.get("force"))
    uid = user["id"]

    async def work():
        job_id = "news_" + uuid.uuid4().hex[:8]

        def progress(text, i, total):
            broadcast("news_progress", {"job_id": job_id, "text": text,
                                         "current": i, "total": total})

        broadcast("news_start", {"job_id": job_id, "subs": subs, "mode": mode})

        # 1. Пул прогрет фоновым воркером — отдаём сразу, без ожидания Reddit
        posts = news_mod.pool_posts(200, mode)

        # 2. Пул пуст или мал (сервер только запустился) — идём в Reddit
        if len(posts) < 10:
            wait = news_mod.cooldown_left()
            if wait > 3:
                broadcast("news_end", {
                    "job_id": job_id, "ok": False, "posts": [],
                    "error": f"Reddit ограничил запросы — подождите ~{int(wait)} с"})
                return
            try:
                fresh = await asyncio.to_thread(
                    news_mod.search, subs, mode, True, progress, force, 1)
                if not fresh and force:
                    # 429 — дожидаемся паузы и пробуем другой сабреддит
                    wait = news_mod.cooldown_left()
                    if wait > 0:
                        progress(f" Reddit притормозил, ждём {int(wait)} с…", 1, 2)
                        await asyncio.sleep(min(wait, 90))
                    alt = news_mod.rotate_subs(1, exclude=subs)
                    fresh = await asyncio.to_thread(
                        news_mod.search, alt, mode, True, progress, force, 1)
                posts = news_mod.merge_posts(posts, fresh, limit=200)
            except Exception as exc:  # noqa: BLE001
                broadcast("news_end", {"job_id": job_id, "ok": False,
                                       "error": str(exc), "posts": []})
                return

        if not posts:
            broadcast("news_end", {"job_id": job_id, "ok": True, "posts": []})
            return

        db.cache_news(uid, posts)
        broadcast("news_end", {"job_id": job_id, "ok": True, "posts": posts})

    asyncio.create_task(work())
    return {"ok": True, "message": "Поиск запущен, результаты придут в лог"}


@app.post("/api/news/scenario")
async def api_news_scenario(payload: dict,
                             user: dict | None = Depends(auth.current_user)):
    """Сгенерировать сценарий по найденной новости — с учётом того, что в кадре."""
    auth.require_user(user)
    data = payload or {}
    title_ru = (data.get("title_ru") or "").strip()
    title_en = (data.get("title") or "").strip()
    title = title_ru or title_en
    context = (data.get("context") or "").strip()
    sub = (data.get("sub") or "").strip()
    link = (data.get("link") or "").strip()
    video_url = (data.get("video_url") or "").strip()
    if not title:
        raise HTTPException(400, "Не выбрана новость")

    # Сценарий должен быть про видео, а не про заголовок: скачиваем b-roll
    # (шаг 2 мог это уже сделать) и ждём подпись кадров.
    desc = ""
    if video_url:
        try:
            path = await ensure_broll(video_url)
            if path:
                info = await asyncio.to_thread(vision.describe, path, 180.0)
                desc = (info or {}).get("ru", "")
        except HTTPException:
            desc = ""      # Reddit не отдал видео — пишем по тексту поста
        except Exception as exc:  # noqa: BLE001
            print(f"[scenario] видео не описано: {exc}", flush=True)

    variants = await asyncio.to_thread(
        llm.generate_variants, title, context, desc, sub)
    if not variants:
        one = await asyncio.to_thread(
            llm.generate_scenario, title, context, desc, sub)
        variants = [one] if one else []

    if not variants:
        raise HTTPException(503, "LLM не ответил. Попробуйте ещё раз или напишите сценарий вручную")

    saved = []
    for v in variants[:3]:
        rec = db.add_scenario(user_id=user["id"], text=v["script"], title=v.get("title", ""),
                              source="reddit", news_link=link)
        v["id"] = rec["id"]
        saved.append(v)
    return {"ok": True, "variants": saved, "video": desc}


# ---------------------------------------------------------------- scenarios

@app.get("/api/scenarios")
async def api_scenarios(user: dict | None = Depends(auth.current_user)):
    auth.require_user(user)
    return {"scenarios": db.list_scenarios(user["id"])}


@app.post("/api/scenarios")
async def api_save_scenario(payload: dict,
                             user: dict | None = Depends(auth.current_user)):
    auth.require_user(user)
    data = payload or {}
    text = (data.get("text") or data.get("script") or "").strip()
    if len(text) < 10:
        raise HTTPException(400, "Сценарий слишком короткий")
    rec = db.add_scenario(user_id=user["id"], text=text,
                          title=(data.get("title") or "").strip(),
                          source=data.get("source") or "manual")
    return {"ok": True, "scenario": rec}


@app.post("/api/scenarios/generate")
async def api_generate_scenario(payload: dict,
                                user: dict | None = Depends(auth.current_user)):
    """Предложить варианты сценария по свободной теме."""
    auth.require_user(user)
    topic = ((payload or {}).get("topic") or "").strip()
    if len(topic) < 3:
        raise HTTPException(400, "Опишите тему")
    variants = await asyncio.to_thread(llm.generate_variants, topic)
    if not variants:
        raise HTTPException(503, "LLM не ответил. Попробуйте ещё раз")
    saved = []
    for v in variants:
        rec = db.add_scenario(user_id=user["id"], text=v["script"],
                              title=v.get("title", ""), source="generated")
        v["id"] = rec["id"]
        saved.append(v)
    return {"ok": True, "variants": saved}


@app.delete("/api/scenarios/{sid}")
async def api_delete_scenario(sid: str, user: dict | None = Depends(auth.current_user)):
    auth.require_user(user)
    if not db.delete_scenario(sid, user["id"]):
        raise HTTPException(404, "Сценарий не найден")
    return {"ok": True}


# ---------------------------------------------------------------- videos

@app.get("/api/videos")
async def api_videos(user: dict | None = Depends(auth.current_user)):
    auth.require_user(user)
    items = []
    for v in db.list_videos(user["id"]):
        p = Path(v["path"])
        exists = p.exists()
        items.append({
            "id": v["id"], "title": v["title"], "filename": v["filename"],
            "size": v["size"], "size_h": f"{v['size'] / 1024 / 1024:.1f} MB",
            "created_at": v["created_at"], "exists": exists,
            "url": f"/api/video/{v['id']}" if exists else None,
        })
    return {"videos": items}


@app.get("/api/video/{vid}")
async def api_video(vid: str, user: dict | None = Depends(auth.current_user)):
    auth.require_user(user)
    v = db.get_video(vid, user["id"])
    if not v:
        raise HTTPException(404, "Ролик не найден")
    p = Path(v["path"])
    if not p.exists():
        raise HTTPException(404, "Файл не найден на диске")
    return StreamingResponse(p.open("rb"), media_type="video/mp4",
                             headers={"Accept-Ranges": "bytes"})


@app.get("/api/download/{vid}")
async def api_download(vid: str, user: dict | None = Depends(auth.current_user)):
    auth.require_user(user)
    v = db.get_video(vid, user["id"])
    if not v:
        raise HTTPException(404, "Ролик не найден")
    p = Path(v["path"])
    if not p.exists():
        raise HTTPException(404, "Файл не найден")
    return StreamingResponse(p.open("rb"), media_type="video/mp4", headers={
        "Content-Disposition": f'attachment; filename="{p.name}"'})


@app.delete("/api/videos/{vid}")
async def api_delete_video(vid: str, user: dict | None = Depends(auth.current_user)):
    auth.require_user(user)
    if not db.delete_video(vid, user["id"]):
        raise HTTPException(404, "Ролик не найден")
    return {"ok": True}


# ---------------------------------------------------------------- pipeline

@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...),
                     user: dict | None = Depends(auth.current_user)):
    """Приём загруженного b-roll. Возвращает абсолютный путь для --asset."""
    if not file.filename:
        raise HTTPException(400, "пустой файл")
    ext = Path(file.filename).suffix.lower() or ".mp4"
    safe = "".join(c for c in Path(file.filename).stem if c.isalnum() or c in "._-")[:60]
    uid = user["id"] if user else "public"
    dest = UPLOADS / f"{uid}_{safe}{ext}"
    counter = 1
    while dest.exists():
        dest = UPLOADS / f"{uid}_{safe}_{counter}{ext}"
        counter += 1
    with dest.open("wb") as fh:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            fh.write(chunk)
    return {"ok": True, "path": str(dest), "name": dest.name,
            "size": dest.stat().st_size}


# ---------------------------------------------------------------- b-roll

_BROLL_ID = re.compile(r"v\.redd\.it/([A-Za-z0-9]+)")
_BROLL_LOCKS: dict = {}


def broll_name(url: str) -> str:
    """Имя файла b-roll постоянное: шаг 2 и шаг 3 переиспользуют один файл."""
    m = _BROLL_ID.search(url)
    key = m.group(1) if m else hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    return f"broll_{key}.mp4"


async def ensure_broll(url: str) -> Path | None:
    """Скачать b-roll, если его ещё нет. -> путь к файлу."""
    url = (url or "").strip()
    if not url:
        return None
    tmp = WEB / "static" / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    dest = tmp / broll_name(url)

    lock = _BROLL_LOCKS.get(dest.name)
    if lock is None:
        lock = _BROLL_LOCKS[dest.name] = asyncio.Lock()

    async with lock:
        if dest.exists() and dest.stat().st_size > 0:
            return dest

        stamp = time.time()
        for old in tmp.glob("broll_*.mp4"):
            try:
                if old != dest and stamp - old.stat().st_mtime > 7200:
                    old.unlink()
            except OSError:
                pass

        def download():
            return subprocess.run(
                [PY, str(VP / "reddit_dl.py"), "--url", url, "--out", str(dest)],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=300,
            )

        try:
            proc = await asyncio.to_thread(download)
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(504, "Скачивание не уложилось в 5 минут") from exc

        if proc.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
            try:
                dest.unlink()
            except OSError:
                pass
            tail = (proc.stderr or proc.stdout or "").strip()[-400:]
            raise HTTPException(502, f"Reddit не отдал видео: {tail}")
        return dest


def probe_video(path: Path) -> dict:
    meta = {"duration": 0.0, "width": 0, "height": 0}
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration:stream=width,height", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=60,
        )
        info = json.loads(proc.stdout or "{}")
        meta["duration"] = round(float(info.get("format", {}).get("duration") or 0), 2)
        for st in info.get("streams", []):
            if st.get("width"):
                meta["width"], meta["height"] = st["width"], st["height"]
                break
    except Exception:  # noqa: BLE001
        pass
    return meta


@app.post("/api/broll/check")
async def api_broll_check(payload: dict, user: dict | None = Depends(auth.current_user)):
    """Шаг 2: скачать b-roll по ссылке Reddit и вернуть параметры файла + ссылку на превью."""
    auth.require_user(user)
    url = ((payload or {}).get("video_url") or "").strip()
    if not url:
        raise HTTPException(400, "Пустая ссылка на видео")
    if "v.redd.it" not in url and "reddit.com" not in url:
        raise HTTPException(400, "Поддерживаются только ссылки Reddit")

    dest = await ensure_broll(url)
    meta = await asyncio.to_thread(probe_video, dest)

    # что в кадре: BLIP работает в фоне, шаг 3 дождётся результата
    desc = await asyncio.to_thread(vision.start, dest)
    return {"ok": True, "url": f"/static/tmp/{dest.name}", "path": str(dest),
            "size": dest.stat().st_size, **meta,
            "desc": (desc or {}).get("ru", ""),
            "desc_ready": bool(desc)}


@app.get("/api/broll/desc/{name}")
async def api_broll_desc(name: str, user: dict | None = Depends(auth.current_user)):
    """Что в кадре: фронт опрашивает, пока модель не закончит."""
    auth.require_user(user)
    if not re.fullmatch(r"broll_[A-Za-z0-9]+\.mp4", name):
        raise HTTPException(400, "Некорректное имя файла")
    path = WEB / "static" / "tmp" / name
    if not path.exists():
        raise HTTPException(404, "Файл не найден")
    desc = await asyncio.to_thread(vision.start, path)
    return {"ok": True, "ready": bool(desc), "desc": (desc or {}).get("ru", "")}


@app.post("/api/process")
async def api_process(payload: dict, user: dict | None = Depends(auth.current_user)):
    """Запустить конвейер в фоне."""
    auth.require_user(user)
    data = payload or {}
    if not (data.get("script") or "").strip() and not (data.get("asset") or "").strip() \
            and not (data.get("video_url") or "").strip():
        raise HTTPException(400, "Укажите сценарий или источник b-roll")

    cmd, meta = build_cmd(data, user["id"])
    job = make_job(cmd, meta)
    asyncio.create_task(run_job(job))
    return {"ok": True, "job_id": job["id"], "cmd": " ".join(cmd[1:])}


@app.get("/api/jobs")
async def api_jobs(user: dict | None = Depends(auth.current_user)):
    jobs = [j for j in JOBS.values() if not user or j["meta"].get("user_id") == user["id"]]
    return {"jobs": list(reversed(jobs[-20:]))}


@app.get("/api/jobs/{job_id}")
async def api_job(job_id: str, user: dict | None = Depends(auth.current_user)):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job не найден")
    if user and job["meta"].get("user_id") != user["id"]:
        raise HTTPException(403, "чужой job")
    return job


@app.get("/api/jobs/{job_id}/log")
async def api_job_log(job_id: str, user: dict | None = Depends(auth.current_user)):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job не найден")
    return {"log": job["log"]}


@app.post("/api/open-folder")
async def api_open_folder(payload: dict,
                           user: dict | None = Depends(auth.current_user)):
    """Открыть папку в проводнике (только локальный режим)."""
    target = (payload or {}).get("path") or str(OUTPUT)
    p = Path(target).resolve()
    allowed = {OUTPUT.resolve(), ARCHIVE.resolve()}
    if user:
        allowed.add(voices.user_video_dir(user["id"]).resolve())
    if p not in allowed:
        raise HTTPException(403, "недоступная папка")
    if not p.exists():
        raise HTTPException(404, "папки нет")
    try:
        os.startfile(str(p))  # noqa: S606 - Windows
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"не удалось открыть папку: {exc}") from exc
    return {"ok": True}


# ---------------------------------------------------------------- общий доступ

@app.get("/api/results")
async def api_results():
    return {"videos": list_videos()}


@app.get("/api/video-file/{name}")
async def api_video_file(name: str):
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "недопустимое имя")
    for folder in (OUTPUT, ARCHIVE):
        f = folder / name
        if f.exists() and f.is_file():
            return StreamingResponse(f.open("rb"), media_type="video/mp4",
                                     headers={"Accept-Ranges": "bytes"})
    raise HTTPException(404, "файл не найден")


@app.get("/api/download-file/{name}")
async def api_download_file(name: str):
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "недопустимое имя")
    for folder in (OUTPUT, ARCHIVE):
        f = folder / name
        if f.exists() and f.is_file():
            return StreamingResponse(f.open("rb"), media_type="video/mp4", headers={
                "Content-Disposition": f'attachment; filename="{name}"'})
    raise HTTPException(404, "файл не найден")


# ---------------------------------------------------------------- websocket

@app.websocket("/ws")
async def ws(sock: WebSocket):
    await sock.accept()
    q: asyncio.Queue = asyncio.Queue(maxsize=4000)
    SUBSCRIBERS.append(q)

    # отдельная задача читает от клиента: так сразу замечаем отключение
    # и убираем очередь, а не ждём следующего сообщения
    async def reader():
        try:
            while True:
                await sock.receive_text()
        except Exception:  # noqa: BLE001
            pass

    reader_task = asyncio.create_task(reader())
    try:
        await sock.send_json({"kind": "hello", "ts": now()})
        while True:
            done, _ = await asyncio.wait(
                [reader_task, asyncio.ensure_future(q.get())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            if reader_task in done:
                break
            msg = next(iter(done)).result()
            await sock.send_json(msg)
    except (WebSocketDisconnect, asyncio.CancelledError, RuntimeError):
        pass
    finally:
        reader_task.cancel()
        if q in SUBSCRIBERS:
            SUBSCRIBERS.remove(q)


@app.get("/api/health")
async def health():
    return {"ok": True, "jobs": len(JOBS), "videos": len(list_videos())}


# ---------------------------------------------------------------- нарезка

SLICE_LEN = 45.0        # длина клипа, сек
MIN_CLIP = 1.0          # клипы короче не отдаём
MIN_TAIL = 15.0         # хвостик короче — приклеиваем к предыдущему клипу
# reencode — точные границы (по умолчанию); copy — быстро, но режет по ключевым
# кадрам, поэтому клипы получаются длиннее заданных и перекрываются.
SLICE_MODE = (os.environ.get("SLICE_MODE", "reencode") or "reencode").strip().lower()


def _safe_name(name: str, fallback: str = "video.mp4") -> str:
    base = Path(name or "").name
    base = re.sub(r"[^\w.\-]+", "_", base).strip("._") or fallback
    return base[-80:]


# Скачивание по ссылке: yt-dlp + обход bot-check YouTube.
YTDLP_COOKIES = os.environ.get("YTDLP_COOKIES", "").strip()
YTDLP_BROWSER = os.environ.get("YTDLP_COOKIES_FROM_BROWSER", "").strip()
YTDLP_NO_BROWSER = os.environ.get("YTDLP_NO_BROWSER_COOKIES", "").strip().lower() in (
    "1", "true", "yes", "on")
YTDLP_CLIENTS = ("android_vr", "web_safari", "tv")

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _clean_error(text) -> str:
    """Убрать ANSI-цвета и управляющие символы из вывода yt-dlp."""
    text = _ANSI_RE.sub("", str(text))
    text = _CTRL_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _bot_check(text: str) -> bool:
    low = text.lower()
    return any(k in low for k in (
        "sign in to confirm", "not a bot", "confirm you're not a bot",
        "login required", "cookies",
    ))


def _download_hint(exc: Exception) -> str:
    msg = _clean_error(exc)[:600]
    if _bot_check(msg):
        return (
            "YouTube требует подтвердить вход (bot-check). Что делать: "
            "1) обновите yt-dlp: python -m pip install -U yt-dlp; "
            "2) передайте cookies браузера: YTDLP_COOKIES_FROM_BROWSER=chrome "
            "(или edge/firefox), либо файл cookies: YTDLP_COOKIES=C:\\path\\cookies.txt; "
            "3) проще всего — скачать видео вручную и загрузить его файлом. "
            "Ответ yt-dlp: " + msg
        )
    return msg or "не удалось скачать видео"


def _download_video(url: str, tmp_dir: Path, note=None) -> Path:
    """Скачать видео по ссылке через yt-dlp -> путь к файлу.

    Сначала обычная загрузка. Если YouTube просит вход (bot-check) — пробуем
    cookies из браузера (настроенные или chrome/edge/firefox) и альтернативные
    клиенты YouTube. Каждая попытка пишется в журнал через ``note``.
    """
    try:
        import yt_dlp  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError("yt-dlp не установлен: python -m pip install yt-dlp") from exc

    base = {
        "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "color": "never",
    }

    def attempt(label: str, extra: dict) -> Path:
        stem = tmp_dir / f"dl_{uuid.uuid4().hex[:12]}"
        opts = {**base, **extra, "outtmpl": f"{stem}.%(ext)s"}
        if note:
            note(f"… {label}")
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        files = sorted(tmp_dir.glob(stem.name + ".*"),
                       key=lambda p: p.stat().st_size, reverse=True)
        if not files:
            raise RuntimeError("файл не скачался")
        return files[0]

    try:
        return attempt("загрузка по ссылке", {})
    except Exception as exc:  # noqa: BLE001
        first = exc

    first_text = _clean_error(first)
    if not _bot_check(first_text):
        try:
            return attempt("другой клиент YouTube", {
                "extractor_args": {"youtube": {"player_client": list(YTDLP_CLIENTS)}}})
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(_download_hint(exc)) from exc

    plans: list = []
    if YTDLP_COOKIES:
        plans.append((f"cookies из файла {YTDLP_COOKIES}", {"cookiefile": YTDLP_COOKIES}))
    if YTDLP_BROWSER:
        plans.append((f"cookies из {YTDLP_BROWSER}", {"cookiesfrombrowser": (YTDLP_BROWSER,)}))
    if not YTDLP_NO_BROWSER:
        for browser in ("chrome", "edge", "firefox"):
            plans.append((f"cookies из {browser}", {"cookiesfrombrowser": (browser,)}))
    plans.append(("другой клиент YouTube", {
        "extractor_args": {"youtube": {"player_client": list(YTDLP_CLIENTS)}}}) )

    last = first
    for label, extra in plans:
        try:
            return attempt(label, extra)
        except Exception as exc:  # noqa: BLE001
            last = exc

    raise RuntimeError(_download_hint(last)) from last


def _probe_duration(path: Path) -> float:
    p = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    try:
        return float((p.stdout or "").strip().splitlines()[0])
    except (IndexError, ValueError):
        return 0.0


def _cut_clip(src: Path, start: float, length: float, out: Path, *,
              vertical: bool = True, cam: dict | None = None,
              cam_pos: str = "bottom", src_size: tuple = (0, 0),
              subs_name: str | None = None, fonts_dir: str | None = None):
    """Вырезать ровно ``length`` секунд с позиции ``start``.

    vertical=True — собрать 1080×1920: размытый фон, основное видео по центру,
    вебка (если есть) сверху/снизу, при ``subs_name`` — прожигаем субтитры.
    Перекодирование обязательно: только так границы совпадают с кадрами.
    """
    common = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
              "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{length:.3f}"]

    if vertical:
        graph, label = vertical_mod.build_filter(
            src_size[0], src_size[1], cam, cam_pos, subs_name, fonts_dir)
        cmd = [*common, "-filter_complex", graph,
               "-map", f"[{label}]", "-map", "0:a?"]
    else:
        cmd = [*common, "-map", "0:v:0", "-map", "0:a?"]
        if subs_name:
            fonts = f":fontsdir='{fonts_dir}'" if fonts_dir else ""
            cmd += ["-vf", f"ass={subs_name}{fonts}"]

    if SLICE_MODE == "copy" and not vertical and not subs_name:
        copy_cmd = [*cmd, "-c", "copy", "-avoid_negative_ts", "make_zero", str(out)]
        p = subprocess.run(copy_cmd, capture_output=True, text=True, errors="replace")
        if p.returncode == 0 and out.exists() and out.stat().st_size > 1024:
            return

    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart", str(out)]
    # cwd=папка клипа: имя ASS относительное, без проблем с ':' в путях Windows
    p2 = subprocess.run(cmd, cwd=str(out.parent), capture_output=True,
                        text=True, errors="replace")
    if p2.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        tail = (p2.stderr or "").strip().splitlines()[-4:]
        raise RuntimeError("ffmpeg не смог нарезать: " + " | ".join(tail))

    # libass без шрифтов молча не рисует текст — сообщим об этом один раз
    if subs_name and "fontconfig" in (p2.stderr or "").lower():
        return "шрифты для субтитров не найдены (Montserrat) — текст не отрисован"
    return None


@app.post("/api/slicing/start")
async def api_slicing_start(
    video_file: UploadFile | None = File(None),
    videoFile: UploadFile | None = File(None),
    youtubeUrl: str = Form(""),
    sub_style: str = Form("classic"),
    vertical: str = Form("1"),
    subs: str = Form("1"),
    webcam: str = Form("auto"),
    user: dict | None = Depends(auth.current_user),
):
    """Запуск нарезки видео на клипы: загруженный файл или ссылка (yt-dlp).

    Поле файла принимаем под двумя именами: ``video_file`` (API) и
    ``videoFile`` (форма во вкладке «Нарезка»).
    """
    auth.require_user(user)

    tmp_dir = WEB / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    upload = video_file or videoFile
    input_path: Path | None = None
    dl_lines: list[str] = []   # строки скачивания — попадём ими в лог задачи

    if upload is not None and upload.filename:
        safe = _safe_name(upload.filename)
        input_path = tmp_dir / f"src_{uuid.uuid4().hex[:12]}_{safe}"
        with input_path.open("wb") as out:
            while chunk := await upload.read(1024 * 1024):
                out.write(chunk)
    elif youtubeUrl.strip():
        loop = asyncio.get_running_loop()

        def note(line: str) -> None:
            dl_lines.append(line)
            loop.call_soon_threadsafe(broadcast, "log", {"line": line})

        note("● Нарезка: старт (ссылка) — скачиваю видео…")
        try:
            input_path = await asyncio.to_thread(
                _download_video, youtubeUrl.strip(), tmp_dir, note)
        except Exception as exc:  # noqa: BLE001
            msg = _clean_error(exc)
            note(f"✗ Нарезка: {msg}")
            raise HTTPException(400, msg) from exc
        note(f"● Нарезка: видео скачано "
             f"({input_path.stat().st_size / 1024 / 1024:.1f} МБ)")

    if input_path is None or not input_path.exists() or input_path.stat().st_size == 0:
        raise HTTPException(400, "Укажите видеофайл или ссылку YouTube")

    vertical_on = _truthy(vertical, True)
    subs_on = _truthy(subs, True)
    webcam_mode = (webcam or "auto").strip().lower()
    if webcam_mode not in ("auto", "off", "top", "bottom"):
        webcam_mode = "auto"

    job_id = uuid.uuid4().hex[:12]
    out_dir = voices.user_video_dir(user["id"])
    JOBS[job_id] = {
        "id": job_id,
        "status": "processing",
        "progress": 0.0,
        "user_id": user["id"],
        "input_path": str(input_path),
        "out_dir": str(out_dir),
        "clips": [],
        "error": None,
        "started": datetime.now().isoformat(timespec="seconds"),
        "finished": None,
        "log": list(dl_lines),
        # meta нужен общим эндпоинтам /api/jobs: они фильтруют по user_id
        "meta": {"user_id": user["id"], "kind": "slicing",
                 "sub_style": sub_style or "classic",
                 "vertical": vertical_on, "subs": subs_on,
                 "webcam": webcam_mode},
    }
    if dl_lines:
        # для ссылки строка старта уже ушла в лог до скачивания
        broadcast("slicing", {"job_id": job_id, "status": "start"})
    else:
        _slice_event(job_id, "● Нарезка: старт (файл)", status="start")
    asyncio.create_task(_run_slicing(
        job_id, input_path, vertical=vertical_on, subs_on=subs_on,
        style=sub_style or "classic", webcam_mode=webcam_mode))

    return {"ok": True, "job_id": job_id}


def _truthy(value, default: bool = True) -> bool:
    """Флаг из формы: "0"/"false"/"off"/"no"/пусто -> False."""
    text = str(value if value is not None else "").strip().lower()
    if not text:
        return default
    return text not in ("0", "false", "off", "no", "нет")


def _slice_event(job_id: str, line: str, **extra) -> None:
    """Строка в лог задачи + в правую панель (WebSocket)."""
    job = JOBS.get(job_id)
    if job is not None:
        job.setdefault("log", []).append(line)
    broadcast("log", {"job_id": job_id, "line": line})
    if extra:
        broadcast("slicing", {"job_id": job_id, **extra})


async def _run_slicing(job_id: str, input_path: Path, *, vertical: bool = True,
                       subs_on: bool = True, style: str = "classic",
                       webcam_mode: str = "auto") -> None:
    """Нарезать видео на клипы 9:16 с субтитрами."""
    job = JOBS.get(job_id)
    if not job:
        return

    out_dir = Path(job["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        duration = await asyncio.to_thread(_probe_duration, input_path)
        if duration <= 0:
            raise RuntimeError("не удалось определить длительность видео")

        ranges: list[tuple[float, float]] = []
        start = 0.0
        while start < duration - 0.05:
            end = min(start + SLICE_LEN, duration)
            if end - start >= MIN_CLIP:
                ranges.append((start, end))
            start = end
        if not ranges:
            raise RuntimeError("видео короче одного клипа")
        # короткий хвост (5–15 с) лучше приклеить к предыдущему клипу,
        # чем отдавать обрубок, который никуда не годится
        if len(ranges) >= 2 and ranges[-1][1] - ranges[-1][0] < MIN_TAIL:
            ranges[-2] = (ranges[-2][0], ranges[-1][1])
            ranges.pop()

        src_w, src_h = (0, 0)
        cam = None
        if vertical:
            src_w, src_h = await asyncio.to_thread(
                vertical_mod.probe_size, FFPROBE, input_path)
            if webcam_mode != "off":
                _slice_event(job_id, "• ищу вебку в кадре…", status="progress", progress=0.0)
                cam = await asyncio.to_thread(
                    vertical_mod.detect_webcam, input_path, duration, FFMPEG, FFPROBE)
                if cam:
                    _slice_event(job_id,
                                 f"• вебка: {cam['corner']} {cam['w']}×{cam['h']} "
                                 f"(в {cam['score']} кадрах)",
                                 status="progress", progress=0.0)
                else:
                    _slice_event(job_id, "• вебка не найдена — только вертикаль и фон",
                                 status="progress", progress=0.0)
            _slice_event(job_id, "• формат: 1080×1920, размытый фон",
                         status="progress", progress=0.0)

        words: list = []
        if subs_on:
            _slice_event(job_id, "• распознаю речь (faster-whisper)…",
                         status="progress", progress=0.0)
            try:
                words = await asyncio.to_thread(subs_mod.transcribe_words, input_path)
                _slice_event(job_id, f"• слов распознано: {len(words)}",
                             status="progress", progress=0.0)
            except Exception as exc:  # noqa: BLE001
                _slice_event(job_id, "! субтитры пропущены: " + _clean_error(exc)[:300])
                words = []

        _slice_event(job_id, f"• Нарезка: {duration:.1f} с → {len(ranges)} клипов",
                     status="progress", progress=0.0)

        cam_pos = vertical_mod.cam_position(cam, webcam_mode)
        margin_v = 620 if (cam and cam_pos == "bottom") else 400
        fonts_dir = os.environ.get("SUB_FONTS_DIR", "").strip() or None

        clips = []
        for i, (start, end) in enumerate(ranges):
            out_name = f"sliced_{job_id}_{i:03d}.mp4"
            out_path = out_dir / out_name
            ass_path = out_dir / f"sliced_{job_id}_{i:03d}.ass"
            subs_name = None
            n_words = 0
            if words:
                n_words = subs_mod.build_clip_ass(
                    words, start, end, style, ass_path, margin_v=margin_v)
                if n_words:
                    subs_name = ass_path.name
            try:
                warn = await asyncio.to_thread(
                    _cut_clip, input_path, start, end - start, out_path,
                    vertical=vertical, cam=cam, cam_pos=cam_pos,
                    src_size=(src_w, src_h), subs_name=subs_name,
                    fonts_dir=fonts_dir)
                if warn and not job.get("fonts_warned"):
                    job["fonts_warned"] = True
                    _slice_event(job_id, "! " + warn)
            finally:
                if ass_path.exists():
                    ass_path.unlink(missing_ok=True)

            actual = await asyncio.to_thread(_probe_duration, out_path)
            clips.append({
                "filename": out_name,
                "duration": round(actual or (end - start), 1),
                "url": f"/api/slicing/clip/{job_id}/{out_name}",
                "subs": bool(n_words),
                "words": n_words,
            })
            job["clips"] = list(clips)
            job["progress"] = round((i + 1) / len(ranges), 3)
            _slice_event(job_id,
                         f"• клип {i + 1}/{len(ranges)} — {clips[-1]['duration']:.1f} с"
                         + (f", слов {n_words}" if n_words else ""),
                         status="progress", progress=job["progress"])

        job["status"] = "completed"
        job["finished"] = datetime.now().isoformat(timespec="seconds")
        _slice_event(job_id, f"✓ Нарезка готова: {len(clips)} клипов",
                     status="done", clips=len(clips), progress=1.0)
    except Exception as exc:  # noqa: BLE001
        job["status"] = "failed"
        job["error"] = str(exc)
        job["finished"] = datetime.now().isoformat(timespec="seconds")
        _slice_event(job_id, f"✗ Нарезка: {exc}", status="error", error=str(exc))
    finally:
        try:
            input_path.unlink(missing_ok=True)
        except OSError:
            pass


@app.get("/api/slicing/clip/{job_id}/{name}")
async def api_slicing_clip(job_id: str, name: str,
                           user: dict | None = Depends(auth.current_user)):
    """Отдать нарезанный клип (только владельцу задачи)."""
    auth.require_user(user)
    job = JOBS.get(job_id)
    if not job or job.get("user_id") != user["id"]:
        raise HTTPException(404, "клип не найден")
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "недопустимое имя")
    path = Path(job["out_dir"]) / name
    if not path.is_file():
        raise HTTPException(404, "файл не найден")
    return FileResponse(path, media_type="video/mp4")


@app.on_event("startup")
async def on_startup():
    db.init_db()
    # фоновый пул новостей: Reddit даёт ~1 запрос в минуту, поэтому греем заранее
    try:
        news_mod.start_prefetch()
    except Exception as exc:  # noqa: BLE001
        print(f"[NEWS] префетч не запустился: {exc}", flush=True)
    # встроенные голоса готовятся в фоне — интерфейс не должен ждать ASR
    def worker():
        try:
            voices.prepare_all_builtin(log=lambda m: print(m, flush=True))
        except Exception as exc:  # noqa: BLE001
            print(f"[VOICE] подготовка не удалась: {exc}", flush=True)
    asyncio.get_running_loop().run_in_executor(None, worker)


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.environ.get("PORT", "8000") or 8000)

    db.init_db()
    print("=" * 62)
    print("  ГУСЬ ПЕРЕВОДИЛА — веб-конвейер")
    print(f"  http://{host}:{port}")
    print(f"  пайплайн: {VP}")
    print("=" * 62)
    sys.stdout.flush()
    uvicorn.run(app, host=host, port=port, log_level="info")
