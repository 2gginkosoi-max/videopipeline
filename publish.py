#!/usr/bin/env python3
"""
publish.py — отправка готового ролика в n8n (вебхук) для автопубликации на YouTube.

АВТОМАТИЧЕСКИЙ режим (по умолчанию):
  • если рядом есть output/seo.json — берём из него лучший ЗАГОЛОВОК, ОПИСАНИЕ и ХЭШТЕГИ;
  • хэштеги гарантированно попадают в описание;
  • '#shorts' гарантированно есть в заголовке.

Явные --title/--description/--tags переопределяют авто-значения.

Пример:
  python publish.py --video "D:\\AI\\VIDEO_PIPELINE\\output\\final_video.mp4" --privacy unlisted --category 24

Флаг --wait: после отправки вытягивает из n8n результат (ID видео) и печатает ссылку.
"""

import argparse
import json
import sqlite3
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_WEBHOOK = "http://localhost:5678/webhook/publish-short"
DEFAULT_SEO_JSON = r"D:\AI\VIDEO_PIPELINE\output\seo.json"
DEFAULT_TITLE_FILE = r"D:\AI\F5-TTS\title.txt"
DEFAULT_DESC_FILE = r"D:\AI\F5-TTS\description.txt"
DEFAULT_TAGS_FILE = r"D:\AI\F5-TTS\tags.txt"
N8N_DB = r"D:\AI\n8n-data\.n8n\database.sqlite"


def read_text(path) -> str:
    p = Path(path)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8-sig").strip()


def load_seo(path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:  # noqa: BLE001
        return {}


def parse_args():
    ap = argparse.ArgumentParser(description="Публикация ролика через n8n -> YouTube")
    ap.add_argument("--video", required=True)
    ap.add_argument("--title", default=None)
    ap.add_argument("--description", default=None)
    ap.add_argument("--tags", default=None)
    ap.add_argument("--seo-json", default=DEFAULT_SEO_JSON)
    ap.add_argument("--description-file", default=DEFAULT_DESC_FILE)
    ap.add_argument("--tags-file", default=DEFAULT_TAGS_FILE)
    ap.add_argument("--privacy", default="unlisted", choices=["public", "unlisted", "private"])
    ap.add_argument("--category", default="24",
                    help="YouTube categoryId (24=Entertainment, 2=Autos, 25=News, 22=People)")
    ap.add_argument("--webhook", default=DEFAULT_WEBHOOK)
    ap.add_argument("--no-post", action="store_true")
    ap.add_argument("--vk", action="store_true",
                    help="Дополнительно опубликовать в VK (стена+клип через publish_vk.py)")
    ap.add_argument("--vk-wall-only", action="store_true",
                    help="VK: только пост на стене, без клипа")
    ap.add_argument("--no-youtube", action="store_true",
                    help="Пропустить YouTube (напр., только VK)")
    ap.add_argument("--wait", action="store_true",
                    help="Дождаться и вывести результат из n8n (ID видео/ссылку)")
    return ap.parse_args()


def resolve_meta(a) -> tuple:
    seo = load_seo(a.seo_json)

    title = a.title
    if title is None:
        title = seo.get("title") or read_text(DEFAULT_TITLE_FILE)
    if not title:
        title = Path(a.video).stem
    if "#shorts" not in title.lower():
        title = title.rstrip(" .") + " #shorts"

    description = a.description
    if description is None:
        description = seo.get("description") or read_text(a.description_file) or ""

    tags = a.tags
    if tags is None:
        tags = read_text(a.tags_file)
    if not tags and seo.get("hashtags"):
        tags = ", ".join(h.lstrip("#") for h in seo["hashtags"])

    # гарантируем хэштеги в описании
    hashtags = seo.get("hashtags") or []
    if hashtags and "#" not in description:
        description = (description.rstrip() + "\n\n" + " ".join(hashtags)).strip()

    return title, description, tags


def _db():
    return sqlite3.connect(f"file:{N8N_DB}?mode=ro", uri=True, timeout=5)


def max_exec_id() -> int:
    if not Path(N8N_DB).exists():
        return 0
    try:
        con = _db()
        row = con.execute("SELECT MAX(id) FROM execution_entity").fetchone()
        con.close()
        return int(row[0] or 0)
    except Exception:  # noqa: BLE001
        return 0


def _resolve_flatted(raw):
    """n8n хранит execution_data в «flatted»-формате (массив + ссылки-индексы)."""
    arr = json.loads(raw)
    cache = {}

    def resolve(x):
        if isinstance(x, str) and x.isdigit() and int(x) < len(arr):
            i = int(x)
            if i in cache:
                return cache[i]
            cache[i] = {"__ref__": i}
            cache[i] = resolve(arr[i])
            return cache[i]
        if isinstance(x, list):
            return [resolve(i) for i in x]
        if isinstance(x, dict):
            return {k: resolve(v) for k, v in x.items()}
        return x

    return resolve(arr[0])


def execution_result(exec_id: int):
    """Возвращает (status, videoId|None, lastNode)."""
    if not Path(N8N_DB).exists():
        return None, None, None
    try:
        con = _db()
        row = con.execute("SELECT status FROM execution_entity WHERE id=?", (exec_id,)).fetchone()
        if not row:
            con.close()
            return None, None, None
        status = row[0]
        drow = con.execute("SELECT data FROM execution_data WHERE executionId=?",
                           (exec_id,)).fetchone()
        con.close()
    except Exception:  # noqa: BLE001
        return None, None, None

    video_id, last_node = None, None
    if drow and drow[0]:
        try:
            root = _resolve_flatted(drow[0])
            rd = root.get("resultData", {}) if isinstance(root, dict) else {}
            last_node = rd.get("lastNodeExecuted")
            for _name, runs in (rd.get("runData", {}) or {}).items():
                for r in runs:
                    for out in (r.get("data", {}) or {}).get("main", []) or []:
                        for item in (out or []):
                            j = item.get("json", {}) if isinstance(item, dict) else {}
                            for key in ("uploadId", "id", "videoId"):
                                v = j.get(key)
                                if isinstance(v, str) and len(v) == 11 and " " not in v:
                                    video_id = v
        except Exception:  # noqa: BLE001
            pass
    return status, video_id, last_node


def main():
    a = parse_args()

    video = Path(a.video)
    if not video.exists():
        print(f"[ERROR] нет файла видео: {video}")
        sys.exit(1)

    title, description, tags = resolve_meta(a)

    payload = {
        "videoPath": str(video).replace("\\", "/"),
        "title": title,
        "description": description,
        "tags": tags,
        "privacyStatus": a.privacy,
        "categoryId": str(a.category),
    }

    sidecar = video.parent / "publish.json"
    sidecar.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] publish.json: {sidecar}")
    print(f"     title   : {title}")
    print(f"     privacy : {a.privacy}  category: {a.category}")
    print(f"     tags    : {tags[:90]}{'...' if len(tags) > 90 else ''}")
    print(f"     desc    : {description[:110]}{'...' if len(description) > 110 else ''}")

    if a.no_post:
        print("[SKIP] --no-post")
    elif a.no_youtube:
        print("[SKIP] YouTube (--no-youtube)")
    else:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            a.webhook, data=data,
            headers={"Content-Type": "application/json"}, method="POST")

        pre_id = max_exec_id()
        print(f"[POST] {a.webhook}")
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                print(f"[OK] HTTP {resp.status} (запрос принят n8n)")
                if body:
                    print(f"     {body[:300]}")
        except urllib.error.HTTPError as e:
            print(f"[ERROR] HTTP {e.code}: {e.reason}")
            print((e.read().decode("utf-8", errors="replace") or "")[:800])
            sys.exit(1)
        except urllib.error.URLError as e:
            print(f"[ERROR] n8n недоступен: {e.reason}")
            print("        n8n запущен? workflow опубликован?")
            sys.exit(1)

        if a.wait:
            print("[WAIT] Ждём результат загрузки на YouTube...")
            eid = None
            for _ in range(40):  # до ~200 c
                time.sleep(5)
                now_id = max_exec_id()
                if now_id > pre_id:
                    st, _vid, _ln = execution_result(now_id)
                    if st and str(st).lower() in ("success", "error", "crashed"):
                        eid = now_id
                        break
            if eid:
                st, vid, last_node = execution_result(eid)
                print(f"[RESULT] execution #{eid} -> {st} (последний узел: {last_node})")
                print(f"         n8n UI: http://localhost:5678/execution/{eid}")
                if st == "success" and vid:
                    print(f"[YOUTUBE] {a.privacy}: https://youtu.be/{vid}")
                elif st == "success":
                    print("[YOUTUBE] Загрузка успешна, но ID не распознан — смотри n8n UI.")
            else:
                print("[WARN] не удалось прочитать результат из n8n")

    # ---- VK (параллельная ветка, не зависит от YouTube) ----
    if a.vk or a.vk_wall_only:
        # Эта сборка Python кладёт в sys.path[0] python310.zip, а не папку скрипта —
        # публичный import publish_vk падал с ModuleNotFoundError. Добавляем папку сами.
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import publish_vk
        print("\n[VK] публикация в VK ...")
        try:
            publish_vk.publish(str(video), seo_json=a.seo_json,
                               wall=True, clip=not a.vk_wall_only)
        except Exception as e:  # noqa: BLE001
            print(f"[VK-ERROR] публикация в VK не удалась: {e}")


if __name__ == "__main__":
    main()
