# -*- coding: utf-8 -*-
"""Компактный отчёт: лучший кандидат на каждый ключ."""
import json, os

P = r"D:\AI\VIDEO_PIPELINE\longform"
picks = json.load(open(os.path.join(P, "picks.json"), encoding="utf-8"))
lines = []
for bid, kws in picks.items():
    lines.append(f"\n### {bid}")
    for kw, ps in kws.items():
        if not ps:
            lines.append(f"  {kw:42s} -- ПУСТО")
            continue
        c = ps[0]
        lines.append(f"  {kw:42s} {c['source'][:4]}/{c['kind'][:1]} {c['width']}x{c['height']} "
                     f"d={c['dur']:>5} {c['size_mb']:>6}MB sc={c['score']}")
        lines.append(f"      {c['title'][:88]}")
open(os.path.join(P, "picks_best.txt"), "w", encoding="utf-8-sig").write("\n".join(lines))
print("\n".join(lines))
