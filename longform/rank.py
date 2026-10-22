# -*- coding: utf-8 -*-
"""Фаза 1b: ранжирование кандидатов футажа + чёрный список + отчёт для ручного выбора."""
import json, os, re

P = r"D:\AI\VIDEO_PIPELINE\longform"
res = json.load(open(os.path.join(P, "search_results.json"), encoding="utf-8"))

BLACK = re.compile(
    r"(police|bodycam|body\s*cam|dashcam|shootout|fatal|hit.and.run|killed|dead body|"
    r"crash|collision aftermath|death|trailer|teaser|anthem|unboxing|teardown|review|"
    r"gameplay|movie|film|song|music video|lyrics|speech|interview|podcast|lecture|"
    r"tutorial|webinar|documentary|full episode|news bulletin|press conference|"
    r"rotten|gore|blood|autopsy|execution|war|missile|drone strike|explosion)", re.I)

BONUS_SRC = re.compile(r"(nasa|esa|esо|eso|svs|hubble|webb|jwst|apollo|iss|european southern)", re.I)


def score(c, kw):
    t = c.get("title") or ""
    if BLACK.search(t):
        return -1
    s = 0.0
    s += 30 if c["kind"] == "video" else 12
    if c["source"] == "nasa":
        s += 8
    if c["source"] == "wikimedia":
        s += 4
    if BONUS_SRC.search(t) or BONUS_SRC.search(c.get("license", "")):
        s += 6
    w = c.get("width") or 0
    if c["kind"] == "video":
        if w < 960:
            s -= 22
        s += min(w, 1920) / 120.0
        d = c.get("dur") or 0
        if 5 <= d <= 45:
            s += 12
        elif d < 3:
            s -= 18
        elif d > 120:
            s -= 8
        mb = c.get("size_mb") or 0
        if mb > 900:
            s -= 30
        elif mb > 400:
            s -= 10
    else:
        if w < 1600:
            s -= 25
        else:
            s += min(w, 4000) / 200.0
        ar = (c.get("width") or 1) / max(1, (c.get("height") or 1))
        if ar > 1.2:
            s += 6
    toks = [x for x in re.split(r"\W+", kw.lower()) if len(x) > 3]
    hit = sum(1 for x in toks if x in t.lower())
    s += 14 * hit
    return s


out = {}
for bid, kws in res.items():
    out[bid] = {}
    for kw, cands in kws.items():
        ranked = []
        for c in cands:
            sc = score(c, kw)
            if sc < 0:
                continue
            ranked.append((round(sc, 1), c))
        ranked.sort(key=lambda x: -x[0])
        # разнообразие: не больше 2 видео и 2 фото в топ-4
        picked, nv, ni = [], 0, 0
        for sc, c in ranked:
            if c["kind"] == "video" and nv >= 2:
                continue
            if c["kind"] == "image" and ni >= 2:
                continue
            if c["kind"] == "video":
                nv += 1
            else:
                ni += 1
            picked.append({"score": sc, **c})
            if len(picked) >= 4:
                break
        out[bid][kw] = picked

json.dump(out, open(os.path.join(P, "picks.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

lines = []
for bid, kws in out.items():
    lines.append(f"\n########## {bid} ##########")
    for kw, picks in kws.items():
        lines.append(f"\n=== {kw} ===")
        if not picks:
            lines.append("   (пусто)")
        for i, c in enumerate(picks):
            lines.append(f"  {i}) [{c['source']:9s} {c['kind']:5s}] {c['width']}x{c['height']} "
                         f"{c['size_mb']}MB d={c['dur']}s sc={c['score']} | {c['title'][:90]}")
            lines.append(f"       {c['url'][:145]}")
open(os.path.join(P, "picks_report.txt"), "w", encoding="utf-8-sig").write("\n".join(lines))
print("OK -> picks.json, picks_report.txt")
empty = [(b, k) for b, ks in out.items() for k, v in ks.items() if not v]
print("EMPTY:", len(empty))
for b, k in empty:
    print("   ", b, "|", k)
