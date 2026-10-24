#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reddit_dl.py — скачивание видео Reddit напрямую (без аккаунта и сторонних зеркал).

Почему так: у v.redd.it прямые `DASH_*.mp4` отдают 403 без авторизации, но
HLS-мастер-плейлист `HLSPlaylist.m3u8` открыт. yt-dlp умеет byte-range HLS,
поэтому тянем через него с заголовками User-Agent + Referer.

Использование:
  python reddit_dl.py --url "https://www.reddit.com/r/funny/comments/1x9gouq/..." ^
      --out "D:\\AI\\F5-TTS\\assets\\robot_prank.mp4"
  python reddit_dl.py --url "https://v.redd.it/0vyr68q01bwh1/HLSPlaylist.m3u8" --out out.mp4
"""

import argparse
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

YTDLP = r"C:\Users\nasle\.agent-reach-venv\Scripts\yt-dlp.exe"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

ID_RE = re.compile(r"v\.redd\.it/([a-z0-9]+)", re.I)
COMMENTS_RE = re.compile(r"/comments/([a-z0-9]+)/", re.I)
MEDIA_RE = re.compile(r"https://v\.redd\.it/([a-z0-9]+)")


def post_id(url: str) -> str:
    m = COMMENTS_RE.search(url)
    return m.group(1) if m else ""


def video_id(url: str) -> str:
    """id видео: прямо из v.redd.it-ссылки либо из RSS поста (пост-id → видео-id)."""
    m = ID_RE.search(url)
    if m:
        return m.group(1)
    pid = post_id(url)
    if not pid:
        raise SystemExit(f"[ERR] не понял id в ссылке: {url}")
    print(f"[REDDIT] ищу видео-id в RSS поста {pid}...")
    req = urllib.request.Request(
        f"https://www.reddit.com/comments/{pid}/.rss",
        headers={"User-Agent": UA, "Accept": "application/rss+xml,application/xml"})
    body = ""
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode("utf-8", errors="replace")
            break
        except Exception as e:  # noqa: BLE001
            wait = 15 * (attempt + 1)
            print(f"[WARN] RSS поста не отдался ({e}); повтор через {wait} c")
            time.sleep(wait)
    m = MEDIA_RE.search(body)
    if not m:
        raise SystemExit(f"[ERR] в посте {pid} не нашёл видео v.redd.it")
    return m.group(1)


def main():
    ap = argparse.ArgumentParser(description="Скачать видео Reddit через открытый HLS")
    ap.add_argument("--url", required=True, help="ссылка на пост Reddit или v.redd.it")
    ap.add_argument("--out", required=True, help="куда сохранить mp4")
    a = ap.parse_args()

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    vid = video_id(a.url)
    hls = f"https://v.redd.it/{vid}/HLSPlaylist.m3u8"
    print(f"[REDDIT] id={vid}")
    print(f"[REDDIT] HLS: {hls}")

    cmd = [
        YTDLP, "--no-warnings", "--no-playlist",
        "--add-header", f"User-Agent:{UA}",
        "--add-header", "Referer:https://www.reddit.com/",
        "-f", "bv*+ba/b", "--merge-output-format", "mp4",
        "-o", str(out), hls,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if r.returncode != 0 or not out.exists():
        print("[REDDIT] попытка с cookies из браузера...")
        for browser in ("edge", "chrome", "brave", "vivaldi"):
            cmd2 = [
                YTDLP, "--no-warnings", "--no-playlist",
                "--cookies-from-browser", browser,
                "--add-header", f"User-Agent:{UA}",
                "--add-header", "Referer:https://www.reddit.com/",
                "-f", "bv*+ba/b", "--merge-output-format", "mp4",
                "-o", str(out), hls,
            ]
            r2 = subprocess.run(cmd2, capture_output=True, text=True, encoding="utf-8",
                                errors="replace")
            if out.exists() and out.stat().st_size > 0:
                r = r2
                break
        else:
            err = "\n".join(((r.stderr or r.stdout) or "").strip().splitlines()[-8:])
            print(err)
            print(f"[ERR] yt-dlp rc={r.returncode}")
            sys.exit(1)

    tail = "\n".join((r.stdout or "").strip().splitlines()[-6:])
    print(tail)
    print('[OK] сохранено:', out, '(%s байт)' % out.stat().st_size)


if __name__ == "__main__":
    main()
