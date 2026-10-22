# -*- coding: utf-8 -*-
"""auth.py — регистрация, вход, cookie-сессия. Только стандартная библиотека."""

import hashlib
import hmac
import os
import secrets

from fastapi import Cookie, HTTPException

import db

COOKIE = "goose_session"
_ITERATIONS = 120_000


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                             salt.encode("utf-8"), _ITERATIONS)
    return dk.hex(), salt


def verify_password(password: str, pass_hash: str, salt: str) -> bool:
    calc, _ = hash_password(password, salt)
    return hmac.compare_digest(calc, pass_hash)


def register(username: str, password: str, email: str = "") -> dict:
    username = (username or "").strip()
    if len(username) < 3:
        raise HTTPException(400, "Имя пользователя — минимум 3 символа")
    if len(username) > 32:
        raise HTTPException(400, "Имя пользователя — максимум 32 символа")
    if len(password or "") < 6:
        raise HTTPException(400, "Пароль — минимум 6 символов")
    if db.get_user_by_name(username):
        raise HTTPException(409, "Такое имя уже занято")
    email = (email or "").strip()
    if email:
        if "@" not in email:
            raise HTTPException(400, "Некорректный e-mail")
        if db.get_user_by_email(email):
            raise HTTPException(409, "Этот e-mail уже зарегистрирован")

    pw, salt = hash_password(password)
    user = db.create_user(username, email, pw, salt)
    return {"id": user["id"], "username": user["username"], "email": user["email"]}


def login(username: str, password: str) -> dict:
    user = db.get_user_by_name(username) or (
        db.get_user_by_email(username) if "@" in (username or "") else None)
    if not user:
        raise HTTPException(401, "Неверное имя пользователя или пароль")
    if not verify_password(password or "", user["pass_hash"], user["salt"]):
        raise HTTPException(401, "Неверное имя пользователя или пароль")
    return {"id": user["id"], "username": user["username"], "email": user["email"]}


def current_user(goose_session: str | None = Cookie(default=None)) -> dict | None:
    """Текущий пользователь или None. Используется как Depends."""
    if not goose_session:
        return None
    row = db.get_user_by_token(goose_session)
    if not row:
        return None
    return {"id": row["id"], "username": row["username"], "email": row["email"]}


def require_user(user: dict | None = None) -> dict:
    if not user:
        raise HTTPException(401, "Нужно войти в аккаунт")
    return user
