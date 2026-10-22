# -*- coding: utf-8 -*-
"""Считает слова и хронометраж блоков, пишет blocks_timing.json."""
import json, os

P = r"D:\AI\VIDEO_PIPELINE\longform"
d = json.load(open(os.path.join(P, "blocks.json"), encoding="utf-8"))
wpm = d["voice_wpm"]
tot_w = 0
tot_s = 0.0
out = []
for b in d["blocks"]:
    w = len(b["narration"].split())
    s = w / wpm * 60.0
    tot_w += w
    tot_s += s
    out.append({"id": b["id"], "label": b["label"], "color": b["color"],
                "words": w, "dur": round(s, 1), "shots": len(b["keywords"])})
    print(f"{b['id']:9s} words={w:4d}  dur={s:6.1f}s  keywords={len(b['keywords'])}")
print(f"TOTAL words={tot_w} dur={tot_s:.1f}s = {tot_s/60:.2f} min")

json.dump(out, open(os.path.join(P, "blocks_timing.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
