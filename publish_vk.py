#!/usr/bin/env python3
"""
publish_vk.py — публикация готового ролика в VK (пост на стену + клип).

Использует VK API напрямую (без n8n):
  1) video.save  → получаем upload_url
  2) POST файла → загрузка
  3) wall.post   → пост на стену с вложенным видео (опционально, --wall)
  4) clips.saveVideo → клип (опционально, --clip)

Токен: файл vk_token.txt рядом со скриптом (одна строка, scope video,wall,offline).
Группа: аргумент --group-id или файл vk_config.json {"group_id": 123456}.

Пример:
  python publish_vk.py --video "D:\\AI\\VIDEO_PIPELINE\\output\\final_video.mp4" --wall --clip

Без флагов --wall/--clip скрипт только подготовит данные (аналог --no-post).
"""

import argparse
import json
import sys
import time
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).resolve().parent
TOKEN_FILE = SCRIPT_DIR / "vk_token.txt"
CONFIG_FILE = SCRIPT_DIR / "vk_config.json"
DEFAULT_SEO_JSON = SCRIPT_DIR / "output" / "seo.json"
VK_API = "https://api.vk.com/method/"
VK_VERSION = "5.199"


def read_text(path) -> str:
    p = Path(path)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8-sig").strip()


def load_json(path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:  # noqa: BLE001
        return {}


def load_token() -> str:
    token = read_text(TOKEN_FILE)
    if not token:
        print(f"[ERROR] нет токена: создай файл {TOKEN_FILE}")
        print("        (одна строка — сам VK-токен, без кавычек)")
        sys.exit(1)
    return token


def load_group_id(explicit) -> int | None:
    if explicit:
        return int(explicit)
    cfg = load_json(CONFIG_FILE)
    gid = cfg.get("group_id")
    return int(gid) if gid else None


def vk(method: str, token: str, **params) -> dict:
    """POST-запрос к VK API с повтором при антиспам (6, 29) и TooManyRequests."""
    params["access_token"] = token
    params["v"] = VK_VERSION
    for attempt in range(4):
        r = requests.post(VK_API + method, data=params, timeout=60)
        try:
            j = r.json()
        except Exception:  # noqa: BLE001
            print(f"[WARN] {method}: не-JSON ответ (HTTP {r.status_code}): {r.text[:200]}")
            time.sleep(2 * (attempt + 1))
            continue
        if "error" in j:
            err = j["error"]
            code = err.get("error_code")
            if code in (6, 29, 10):  # too many requests / captcha
                time.sleep(2 * (attempt + 1))
                continue
            print(f"[ERROR] {method}: {err.get('error_msg')} (code={code})")
            extra = {k: err.get(k) for k in ("request_params", "captcha_sid") if k in err}
            if extra:
                print(f"        {json.dumps(extra, ensure_ascii=False)[:400]}")
            sys.exit(1)
        return j.get("response", j)
    print(f"[ERROR] {method}: не удалось после повторов")
    sys.exit(1)


def upload_file(upload_url: str, file_path: Path) -> dict:
    """Multipart-загрузка файла на upload_url (возвращается VK)."""
    with open(file_path, "rb") as f:
        r = requests.post(upload_url, files={"video_file": (file_path.name, f)}, timeout=600)
    try:
        j = r.json()
    except Exception:  # noqa: BLE001
        print(f"[ERROR] upload: не-JSON ответ: {r.text[:300]}")
        sys.exit(1)
    if "error" in j:
        print(f"[ERROR] upload: {j['error']}")
        sys.exit(1)
    return j


def resolve_meta(a) -> tuple:
    seo = load_json(a.seo_json)
    title = a.title or seo.get("title") or read_text(r"D:\AI\F5-TTS\title.txt")
    if not title:
        title = Path(a.video).stem
    description = a.description or seo.get("description") or read_text(r"D:\AI\F5-TTS\description.txt")
    hashtags = seo.get("hashtags") or []
    if hashtags and "#" not in description:
        description = (description.rstrip() + "\n\n" + " ".join(hashtags)).strip()
    # убираем #shorts из заголовка для VK (формат не нужен, мешает клипам)
    title_vk = title.replace("#shorts", "").replace("#Shorts", "").strip(" .")
    return title_vk, description


def post_wall(token: str, group_id: int | None, video_ref: str, message: str) -> dict:
    owner_id = f"-{group_id}" if group_id else "0"
    resp = vk("wall.post", token,
              owner_id=owner_id,
              message=message,
              from_group=1,  # всегда от имени сообщества, не от лица пользователя
              attachments=video_ref)
    post_id = resp.get("post_id")
    print(f"[VK] пост на стене: owner={owner_id} post_id={post_id}")
    return resp


def post_clip(token: str, group_id: int | None, video_path: Path,
              title: str, description: str) -> dict:
    if not group_id:
        print("[ERROR] клипы VK требуют group_id (укажи --group-id или vk_config.json)")
        sys.exit(1)
    # 1) saveVideo — получаем upload_url (клип создаётся после загрузки файла)
    saved = vk("clips.saveVideo", token,
               group_id=group_id,
               title=title[:80],
               description=description,
               wallpost=0)
    upload_url = saved.get("upload_url")
    if not upload_url:
        print(f"[ERROR] clips.saveVideo не вернул upload_url: {saved}")
        sys.exit(1)
    # 2) загрузка файла
    up = upload_file(upload_url, video_path)
    clip_id = up.get("video_id") or saved.get("video_id")
    clip_owner = saved.get("video_owner_id") or f"-{group_id}"
    print(f"[VK] клип загружен: clip_id={clip_id} owner={clip_owner}")
    return {"video_id": clip_id, "owner_id": clip_owner}


def publish(video: str, seo_json: str = str(DEFAULT_SEO_JSON),
            title: str | None = None, description: str | None = None,
            group_id: int | None = None, wall: bool = True, clip: bool = True) -> dict:
    """Программный вход: публикует видео в VK. Возвращает dict с результатом."""
    video_p = Path(video)
    if not video_p.exists():
        raise FileNotFoundError(f"нет файла видео: {video_p}")

    class _A:  # мини-namespace вместо argparse
        pass

    a = _A()
    a.title, a.description, a.seo_json = title, description, seo_json
    t, d = resolve_meta(a)
    gid = load_group_id(group_id)
    token = load_token()

    result = {"video": str(video_p), "title": t, "group_id": gid}
    if clip:
        result["clip"] = post_clip(token, gid, video_p, t, d)
    if wall:
        # грузим отдельное видео для стены (клип — другой тип вложения, не рискуем)
        saved = vk("video.save", token,
                   group_id=gid or 0, name=t, description=d, wallpost=0)
        upload_url = saved.get("upload_url")
        if not upload_url:
            raise RuntimeError(f"video.save не вернул upload_url: {saved}")
        up = upload_file(upload_url, video_p)
        vid = up.get("video_id") or saved.get("video_id")
        vowner = saved.get("video_owner_id") or ("-" + str(gid) if gid else token_user_id(token))
        ref = f"video{vowner}_{vid}"
        print(f"[VK] видео загружено: {ref}")
        result["wall"] = post_wall(token, gid, ref, d)

    out = SCRIPT_DIR / "output" / "vk_publish.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] результат: {out}")
    return result


def parse_args():
    ap = argparse.ArgumentParser(description="Публикация ролика в VK (стена + клипы)")
    ap.add_argument("--video", required=True)
    ap.add_argument("--title", default=None)
    ap.add_argument("--description", default=None)
    ap.add_argument("--seo-json", default=str(DEFAULT_SEO_JSON))
    ap.add_argument("--group-id", default=None, help="ID сообщества (для клипов обязателен)")
    ap.add_argument("--wall", action="store_true", help="Опубликовать пост на стене")
    ap.add_argument("--clip", action="store_true", help="Опубликовать как клип (нужен group_id)")
    ap.add_argument("--dry-run", action="store_true", help="Только показать данные, ничего не публиковать")
    return ap.parse_args()


def main():
    a = parse_args()
    video = Path(a.video)
    if not video.exists():
        print(f"[ERROR] нет файла видео: {video}")
        sys.exit(1)

    title, description = resolve_meta(a)
    group_id = load_group_id(a.group_id)
    print(f"[META] title   : {title}")
    print(f"       group_id: {group_id}")
    print(f"       wall    : {a.wall}  clip: {a.clip}")
    print(f"       desc    : {description[:110]}{'...' if len(description) > 110 else ''}")

    if a.dry_run or (not a.wall and not a.clip):
        print("[SKIP] публикация не запрошена (--wall/--clip) или --dry-run")
        return

    publish(str(video), seo_json=a.seo_json, group_id=a.group_id,
            wall=a.wall, clip=a.clip)


def token_user_id(token: str) -> str:
    r = vk("users.get", token)
    if isinstance(r, list) and r:
        return str(r[0].get("id", ""))
    return "0"


if __name__ == "__main__":
    main()
