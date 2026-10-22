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
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request as StarletteRequest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import auth          # noqa: E402
import db            # noqa: E402
import llm           # noqa: E402
import news as news_mod  # noqa: E402
import voices        # noqa: E402

# ---------------------------------------------------------------- paths

VP = Path(r"D:\AI\VIDEO_PIPELINE")
F5 = Path(r"D:\AI\F5-TTS")
WEB = Path(__file__).resolve().parent
PY = r"D:\AI\python310\python.exe"
UPLOADS = WEB / "uploads"
OUTPUT = VP / "output"
ARCHIVE = OUTPUT / "archive"
SHARED_BRIEF = VP / "brief.txt"

for p in (UPLOADS, OUTPUT, ARCHIVE, WEB / "data", WEB / "voices" / "builtin"):
    p.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="ГУСЬ ПЕРЕВОДИЛА", docs_url="/api/docs", redoc_url=None)
app.mount("/static", StaticFiles(directory=str(WEB / "static")), name="static")
templates = Jinja2Templates(directory=str(WEB / "templates"))

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

    goose_pos = data.get("goose_pos") or "top-right"
    if goose_pos in ("top-right", "mid-right", "low-right", "top-left", "mid-left"):
        cmd += ["--goose-pos", goose_pos]

    if data.get("no_goose"):
        cmd.append("--no-goose")
    if data.get("sharpen"):
        cmd += ["--sharpen", str(data["sharpen"]).strip()]
    if data.get("skip_voice"):
        cmd.append("--skip-voice")
    if data.get("skip_download"):
        cmd.append("--skip-download")
    if data.get("skip_publish"):
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
            msg = f"[ERROR] не удалось запустить процесс: {exc}"
            job["log"].append(msg)
            broadcast("log", {"job_id": job["id"], "line": msg})
            broadcast("job_end", {"job_id": job["id"], "status": "error", "returncode": -1})
            return

        assert proc.stdout is not None
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").rstrip()
            job["log"].append(line)
            broadcast("log", {"job_id": job["id"], "line": line})

        rc = await proc.wait()

    job["returncode"] = rc
    job["finished"] = datetime.now().isoformat(timespec="seconds")
    job["status"] = "done" if rc == 0 else "error"

    # регистрируем готовый ролик в профиле
    if rc == 0 and user_id:
        final = Path(meta.get("final", ""))
        if final.exists():
            try:
                rec = db.add_video(
                    user_id=user_id, job_id=job["id"], title=meta.get("title", ""),
                    path=str(final), size=final.stat().st_size)
                job["video_id"] = rec["id"]
                broadcast("video_ready", {"job_id": job["id"], "video_id": rec["id"],
                                          "title": rec["title"]})
            except Exception as exc:  # noqa: BLE001
                broadcast("log", {"job_id": job["id"],
                                  "line": f"[WARN] не удалось сохранить ролик в профиль: {exc}"})

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
    return templates.TemplateResponse(request, "index.html", {"active": "run"})


@app.get("/results", response_class=HTMLResponse)
async def results_page(request: StarletteRequest):
    return templates.TemplateResponse(request, "results.html", {
        "active": "results", "videos": list_videos()})


@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: StarletteRequest):
    return templates.TemplateResponse(request, "profile.html", {"active": "profile"})


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
            })
    return {"voices": out}


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
        raise HTTPException(400, "Не удалось выделить голос из файла")

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
    subs = data.get("subs") or [s["key"] for s in news_mod.SUBS]
    mode = data.get("mode") or "hot"
    uid = user["id"]

    async def work():
        job_id = "news_" + uuid.uuid4().hex[:8]
        broadcast("news_start", {"job_id": job_id, "subs": subs, "mode": mode})

        def progress(text, i, total):
            broadcast("news_progress", {"job_id": job_id, "text": text,
                                         "current": i, "total": total})

        try:
            posts = await asyncio.to_thread(
                news_mod.search, subs, mode, True, progress)
        except Exception as exc:  # noqa: BLE001
            broadcast("news_end", {"job_id": job_id, "ok": False,
                                   "error": str(exc), "posts": []})
            return

        if posts:
            db.cache_news(uid, posts)
        broadcast("news_end", {"job_id": job_id, "ok": True,
                               "posts": db.get_cached_news(uid)})

    asyncio.create_task(work())
    return {"ok": True, "message": "Поиск запущен, результаты придут в лог"}


@app.post("/api/news/scenario")
async def api_news_scenario(payload: dict,
                             user: dict | None = Depends(auth.current_user)):
    """Сгенерировать сценарий по найденной новости."""
    auth.require_user(user)
    data = payload or {}
    title = (data.get("title") or "").strip()
    context = (data.get("context") or "").strip()
    link = (data.get("link") or "").strip()
    if not title:
        raise HTTPException(400, "Не выбрана новость")

    variants = await asyncio.to_thread(llm.generate_variants, title)
    if not variants:
        one = await asyncio.to_thread(llm.generate_scenario, title, context)
        variants = [one] if one else []

    if not variants:
        raise HTTPException(503, "LLM не ответил. Попробуйте ещё раз или напишите сценарий вручную")

    saved = []
    for v in variants[:3]:
        rec = db.add_scenario(user_id=user["id"], text=v["script"], title=v.get("title", ""),
                              source="reddit", news_link=link)
        v["id"] = rec["id"]
        saved.append(v)
    return {"ok": True, "variants": saved}


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


@app.on_event("startup")
async def on_startup():
    db.init_db()
    # встроенные голоса готовятся в фоне — интерфейс не должен ждать ASR
    def worker():
        try:
            voices.prepare_all_builtin(log=lambda m: print(m, flush=True))
        except Exception as exc:  # noqa: BLE001
            print(f"[VOICE] подготовка не удалась: {exc}", flush=True)
    asyncio.get_running_loop().run_in_executor(None, worker)


if __name__ == "__main__":
    import uvicorn

    db.init_db()
    print("=" * 62)
    print("  ГУСЬ ПЕРЕВОДИЛА — веб-конвейер")
    print("  http://127.0.0.1:8000")
    print("=" * 62)
    sys.stdout.flush()
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
