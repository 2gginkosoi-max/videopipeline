#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Веб-интерфейс для конвейера "ГУСЬ ПЕРЕВОДИЛА".

Бэкенд НЕ переписывает логику конвейера — он только запускает существующий
auto_news.py как subprocess и транслирует его stdout в браузер через WebSocket.

Запуск:
    D:\\AI\\python310\\python.exe D:\\AI\\VIDEO_PIPELINE\\web\\app.py
    -> http://127.0.0.1:8000
"""

import asyncio
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

# ---------------------------------------------------------------- paths

VP = Path(r"D:\AI\VIDEO_PIPELINE")
F5 = Path(r"D:\AI\F5-TTS")
WEB = Path(__file__).resolve().parent
PY = r"D:\AI\python310\python.exe"
UPLOADS = WEB / "uploads"
OUTPUT = VP / "output"
ARCHIVE = OUTPUT / "archive"

for p in (UPLOADS, OUTPUT, ARCHIVE):
    p.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="ГУСЬ ПЕРЕВОДИЛА", docs_url="/api/docs", redoc_url=None)
app.mount("/static", StaticFiles(directory=str(WEB / "static")), name="static")
templates = Jinja2Templates(directory=str(WEB / "templates"))

# ---------------------------------------------------------------- state

JOBS = {}          # job_id -> dict
SUBSCRIBERS = []   # список asyncio.Queue


def now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def broadcast(kind: str, payload: dict) -> None:
    """Разослать событие всем подключённым WebSocket-клиентам."""
    msg = {"kind": kind, "ts": now(), **payload}
    for q in list(SUBSCRIBERS):
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            pass


def make_job(cmd: list, meta: dict) -> dict:
    job = {
        "id": uuid.uuid4().hex[:12],
        "status": "running",
        "started": datetime.now().isoformat(timespec="seconds"),
        "finished": None,
        "returncode": None,
        "cmd": cmd,
        "meta": meta,
        "log": [],
    }
    JOBS[job["id"]] = job
    return job


# ---------------------------------------------------------------- helpers

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


def build_cmd(data: dict) -> list:
    """Собрать команду для auto_news.py из данных формы."""
    cmd = [PY, str(VP / "auto_news.py")]

    script = (data.get("script") or "").strip()
    if script:
        cmd += ["--script", script]

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

    return cmd


async def run_job(job: dict) -> None:
    """Запустить процесс и транслировать вывод в лог + WebSocket."""
    cmd = job["cmd"]
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
    broadcast("job_end", {"job_id": job["id"], "status": job["status"], "returncode": rc})


# ---------------------------------------------------------------- routes

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {
        "active": "run",
        "jobs": list(JOBS.values())[-5:][::-1],
    })


@app.get("/results", response_class=HTMLResponse)
async def results_page(request: Request):
    return templates.TemplateResponse(request, "results.html", {
        "active": "results",
        "videos": list_videos(),
    })


@app.get("/api/results")
async def api_results():
    return {"videos": list_videos()}


@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...)):
    """Приём загруженного b-roll. Возвращает абсолютный путь для --asset."""
    if not file.filename:
        raise HTTPException(400, "пустой файл")
    ext = Path(file.filename).suffix.lower() or ".mp4"
    safe = "".join(c for c in Path(file.filename).stem if c.isalnum() or c in "._-")[:60]
    dest = UPLOADS / f"{safe or 'upload'}{ext}"
    counter = 1
    while dest.exists():
        dest = UPLOADS / f"{safe or 'upload'}_{counter}{ext}"
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
async def api_process(payload: dict):
    """Запустить конвейер в фоне."""
    data = payload or {}
    if not (data.get("script") or "").strip() and not (data.get("asset") or "").strip() \
            and not (data.get("video_url") or "").strip():
        raise HTTPException(400, "Укажите сценарий или источник b-roll")

    cmd = build_cmd(data)
    job = make_job(cmd, {
        "script": (data.get("script") or "")[:200],
        "asset": data.get("asset") or "",
        "privacy": data.get("privacy") or "unlisted",
    })
    asyncio.create_task(run_job(job))
    return {"ok": True, "job_id": job["id"], "cmd": " ".join(cmd[1:])}


@app.get("/api/jobs")
async def api_jobs():
    return {"jobs": list(JOBS.values())}


@app.get("/api/jobs/{job_id}")
async def api_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job не найден")
    return job


@app.get("/api/jobs/{job_id}/log")
async def api_job_log(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job не найден")
    return {"log": job["log"]}


@app.post("/api/open-folder")
async def api_open_folder(payload: dict):
    """Открыть папку в проводнике (только локальный режим)."""
    target = (payload or {}).get("path") or str(OUTPUT)
    p = Path(target).resolve()
    allowed = {OUTPUT.resolve(), ARCHIVE.resolve()}
    if p not in allowed:
        raise HTTPException(403, "недоступная папка")
    if not p.exists():
        raise HTTPException(404, "папки нет")
    try:
        os.startfile(str(p))  # noqa: S606 - Windows
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"не удалось открыть папку: {exc}") from exc
    return {"ok": True}


@app.get("/api/download/{name}")
async def api_download(name: str):
    """Скачать готовый ролик (output/ или archive/)."""
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "недопустимое имя")
    for folder in (OUTPUT, ARCHIVE):
        f = folder / name
        if f.exists() and f.is_file():
            return StreamingResponse(
                f.open("rb"),
                media_type="video/mp4",
                headers={"Content-Disposition": f'attachment; filename="{name}"'},
            )
    raise HTTPException(404, "файл не найден")


@app.get("/api/video/{name}")
async def api_video(name: str):
    """Потоковое воспроизведение в браузере."""
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "недопустимое имя")
    for folder in (OUTPUT, ARCHIVE):
        f = folder / name
        if f.exists() and f.is_file():
            return StreamingResponse(
                f.open("rb"),
                media_type="video/mp4",
                headers={"Accept-Ranges": "bytes"},
            )
    raise HTTPException(404, "файл не найден")


@app.websocket("/ws")
async def ws(sock: WebSocket):
    await sock.accept()
    q: asyncio.Queue = asyncio.Queue(maxsize=2000)
    SUBSCRIBERS.append(q)
    try:
        await sock.send_json({"kind": "hello", "ts": now(),
                              "jobs": list(JOBS.values())[-5:][::-1]})
        while True:
            msg = await q.get()
            await sock.send_json(msg)
    except (WebSocketDisconnect, asyncio.CancelledError, RuntimeError):
        pass
    finally:
        if q in SUBSCRIBERS:
            SUBSCRIBERS.remove(q)


@app.get("/api/health")
async def health():
    return {"ok": True, "jobs": len(JOBS), "videos": len(list_videos())}


if __name__ == "__main__":
    import uvicorn

    print("=" * 60)
    print("  ГУСЬ ПЕРЕВОДИЛА — веб-конвейер")
    print("  http://127.0.0.1:8000")
    print("=" * 60)
    sys.stdout.flush()
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
