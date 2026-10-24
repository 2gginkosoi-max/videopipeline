# -*- coding: utf-8 -*-
"""db.py — SQLite-хранилище профилей: пользователи, голоса, видео, сценарии, новости."""

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data" / "app.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          TEXT PRIMARY KEY,
    username    TEXT UNIQUE NOT NULL,
    email       TEXT UNIQUE,
    pass_hash   TEXT NOT NULL,
    salt        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS voices (
    id          TEXT PRIMARY KEY,
    user_id     TEXT,
    key         TEXT,
    name        TEXT NOT NULL,
    ref_wav     TEXT NOT NULL,
    ref_text    TEXT DEFAULT '',
    gender      TEXT DEFAULT 'unknown',
    builtin     INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS videos (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    job_id      TEXT,
    title       TEXT,
    filename    TEXT NOT NULL,
    path        TEXT NOT NULL,
    size        INTEGER DEFAULT 0,
    duration    INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scenarios (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    title       TEXT DEFAULT '',
    text        TEXT NOT NULL,
    source      TEXT DEFAULT 'manual',
    news_link   TEXT DEFAULT '',
    used        INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS news_cache (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    sub         TEXT,
    title       TEXT NOT NULL,
    link        TEXT,
    video_url   TEXT,
    thumb       TEXT,
    updated     TEXT,
    title_ru    TEXT DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS news_tr (
    link        TEXT PRIMARY KEY,
    title_ru    TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_videos_user ON videos(user_id);
CREATE INDEX IF NOT EXISTS idx_voices_user ON voices(user_id);
CREATE INDEX IF NOT EXISTS idx_scenarios_user ON scenarios(user_id);
CREATE INDEX IF NOT EXISTS idx_news_user ON news_cache(user_id, created_at);
"""


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex[:16]


def conn() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    if c is None:
        c = sqlite3.connect(str(DB_PATH), timeout=30, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        _local.conn = c
    return c


def init_db() -> None:
    c = conn()
    c.executescript(SCHEMA)
    # миграция старых баз: колонка title_ru появилась позже
    cols = [r[1] for r in c.execute("PRAGMA table_info(news_cache)").fetchall()]
    if "title_ru" not in cols:
        c.execute("ALTER TABLE news_cache ADD COLUMN title_ru TEXT DEFAULT ''")
    c.commit()


def query(sql: str, args: tuple = ()) -> list:
    return conn().execute(sql, args).fetchall()


def one(sql: str, args: tuple = ()):
    return conn().execute(sql, args).fetchone()


def execute(sql: str, args: tuple = ()) -> sqlite3.Cursor:
    c = conn()
    cur = c.execute(sql, args)
    c.commit()
    return cur


# ------------------------------------------------------------------ users

def create_user(username: str, email: str, pass_hash: str, salt: str) -> dict:
    uid = new_id()
    execute(
        "INSERT INTO users (id, username, email, pass_hash, salt, created_at)"
        " VALUES (?,?,?,?,?,?)",
        # пустая почта -> NULL: иначе UNIQUE(email) не даёт завести второго
        # пользователя без почты
        (uid, username, (email or "").strip() or None, pass_hash, salt, now()),
    )
    return get_user(uid)


def get_user(uid: str):
    return one("SELECT * FROM users WHERE id = ?", (uid,))


def get_user_by_name(username: str):
    return one("SELECT * FROM users WHERE lower(username) = lower(?)", (username,))


def get_user_by_email(email: str):
    return one("SELECT * FROM users WHERE lower(email) = lower(?)", (email,))


# ------------------------------------------------------------------ sessions

def create_session(user_id: str, days: int = 30) -> str:
    token = uuid.uuid4().hex + uuid.uuid4().hex[:8]
    expires = (datetime.now() + timedelta(days=days)).isoformat(timespec="seconds")
    execute(
        "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?,?,?,?)",
        (token, user_id, now(), expires),
    )
    return token


def get_user_by_token(token: str):
    if not token:
        return None
    row = one(
        "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id"
        " WHERE s.token = ? AND s.expires_at > ?",
        (token, now()),
    )
    return row


def drop_session(token: str) -> None:
    execute("DELETE FROM sessions WHERE token = ?", (token,))


# ------------------------------------------------------------------ voices

def add_voice(user_id, name: str, ref_wav: str, ref_text: str = "",
              gender: str = "unknown", builtin: int = 0, key: str = "") -> dict:
    vid = new_id()
    execute(
        "INSERT INTO voices (id, user_id, key, name, ref_wav, ref_text, gender, builtin, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (vid, user_id, key, name, ref_wav, ref_text, gender, builtin, now()),
    )
    return dict(one("SELECT * FROM voices WHERE id = ?", (vid,)))


def list_voices(user_id) -> list:
    rows = query(
        "SELECT * FROM voices WHERE builtin = 1 OR user_id = ?"
        " ORDER BY builtin DESC, created_at DESC",
        (user_id,),
    )
    return [dict(r) for r in rows]


def get_voice(vid: str):
    r = one("SELECT * FROM voices WHERE id = ?", (vid,))
    return dict(r) if r else None


def get_builtin_override(key: str):
    r = one("SELECT * FROM voices WHERE builtin = 1 AND key = ? LIMIT 1", (key,))
    return dict(r) if r else None


def set_builtin_override(key: str, name: str, gender: str) -> None:
    """Переопределить название/пол встроенного голоса (хранится в БД)."""
    row = get_builtin_override(key)
    if row:
        execute("UPDATE voices SET name = ?, gender = ? WHERE id = ?",
                (name, gender, row["id"]))
    else:
        execute(
            "INSERT INTO voices (id, user_id, key, name, ref_wav, ref_text, gender, builtin, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (new_id(), None, key, name, "", "", gender, 1, now()),
        )


def delete_voice(vid: str, user_id: str) -> bool:
    v = get_voice(vid)
    if not v or v["builtin"]:
        return False
    if v["user_id"] != user_id:
        return False
    execute("DELETE FROM voices WHERE id = ?", (vid,))
    return True


# ------------------------------------------------------------------ videos

def add_video(user_id: str, job_id: str, title: str, path: str,
              size: int = 0, duration: int = 0) -> dict:
    vid = new_id()
    fn = Path(path).name
    execute(
        "INSERT INTO videos (id, user_id, job_id, title, filename, path, size, duration, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (vid, user_id, job_id, title, fn, path, size, duration, now()),
    )
    return dict(one("SELECT * FROM videos WHERE id = ?", (vid,)))


def list_videos(user_id: str) -> list:
    rows = query("SELECT * FROM videos WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
    return [dict(r) for r in rows]


def get_video(vid: str, user_id: str):
    r = one("SELECT * FROM videos WHERE id = ? AND user_id = ?", (vid, user_id))
    return dict(r) if r else None


def delete_video(vid: str, user_id: str) -> bool:
    v = get_video(vid, user_id)
    if not v:
        return False
    try:
        Path(v["path"]).unlink(missing_ok=True)
    except OSError:
        pass
    execute("DELETE FROM videos WHERE id = ?", (vid,))
    return True


# ------------------------------------------------------------------ scenarios

def add_scenario(user_id: str, text: str, title: str = "", source: str = "manual",
                 news_link: str = "") -> dict:
    sid = new_id()
    execute(
        "INSERT INTO scenarios (id, user_id, title, text, source, news_link, created_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (sid, user_id, title, text, source, news_link, now()),
    )
    return dict(one("SELECT * FROM scenarios WHERE id = ?", (sid,)))


def list_scenarios(user_id: str, limit: int = 50) -> list:
    rows = query(
        "SELECT * FROM scenarios WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    )
    return [dict(r) for r in rows]


def delete_scenario(sid: str, user_id: str) -> bool:
    r = one("SELECT id FROM scenarios WHERE id = ? AND user_id = ?", (sid, user_id))
    if not r:
        return False
    execute("DELETE FROM scenarios WHERE id = ?", (sid,))
    return True


# ------------------------------------------------------------------ news cache

def cache_news(user_id: str, posts: list) -> None:
    execute("DELETE FROM news_cache WHERE user_id = ?", (user_id,))
    rows = []
    for p in posts:
        rows.append((new_id(), user_id, p.get("sub", ""), p.get("title", ""),
                     p.get("link", ""), p.get("video_url", ""), p.get("thumb", ""),
                     p.get("updated", ""), p.get("title_ru", ""), now()))
    conn().executemany(
        "INSERT INTO news_cache (id, user_id, sub, title, link, video_url, thumb, updated, title_ru, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    conn().commit()


def get_cached_news(user_id: str, limit: int = 60) -> list:
    rows = query(
        "SELECT * FROM news_cache WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    )
    return [dict(r) for r in rows]


def find_cached_news(user_id: str, link: str):
    r = one("SELECT * FROM news_cache WHERE user_id = ? AND link = ? LIMIT 1",
            (user_id, link))
    return dict(r) if r else None


# ------------------------------------------------------- переводы заголовков

def get_translations(links: list) -> dict:
    """link -> title_ru для уже переведённых постов."""
    if not links:
        return {}
    marks = ",".join("?" * len(links))
    rows = query(f"SELECT link, title_ru FROM news_tr WHERE link IN ({marks})",
                 tuple(links))
    return {r["link"]: r["title_ru"] for r in rows}


def save_translations(mapping: dict) -> None:
    """Запомнить переводы, чтобы не гонять LLM повторно."""
    if not mapping:
        return
    rows = [(link, ru, now()) for link, ru in mapping.items() if link and ru]
    if not rows:
        return
    conn().executemany(
        "INSERT INTO news_tr (link, title_ru, created_at) VALUES (?,?,?)"
        " ON CONFLICT(link) DO UPDATE SET title_ru = excluded.title_ru",
        rows,
    )
    conn().commit()
