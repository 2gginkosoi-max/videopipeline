# -*- coding: utf-8 -*-
"""Патч ключевых слов для поиска футажа (более точные, высокоурожайные запросы)."""
import json, os

P = r"D:\AI\VIDEO_PIPELINE\longform"
p = os.path.join(P, "blocks.json")
d = json.load(open(p, encoding="utf-8"))

KW = {
 "intro": [
   "artificial intelligence robot",
   "server room data center",
   "bumblebee flower macro",
   "milky way night sky stars",
   "city traffic timelapse night",
 ],
 "tech": [
   "data center server racks",
   "computer code screen programming",
   "humanoid robot",
   "circuit board macro",
   "gpu graphics card",
   "surveillance camera",
   "usb flash drive",
   "empty conference room",
   "industrial robot arm factory",
   "server room",
   "smartphone in hands",
   "electric motor",
 ],
 "science": [
   "bumblebee flower slow motion",
   "bees honeycomb hive",
   "3d printer printing",
   "microscope laboratory research",
   "macro insect close up",
   "laboratory pipette liquid",
   "scientist laboratory",
   "engineering laboratory workshop",
   "honeycomb bee",
   "bee pollen leg",
 ],
 "space": [
   "sun solar surface eruption",
   "spiral galaxy webb",
   "solar system planets animation",
   "telescope observatory night",
   "nebula deep space",
   "earth from space",
   "planets orbit animation",
   "night sky stars timelapse",
   "rocket launch slow motion",
   "milky way galaxy",
   "solar prominence",
 ],
 "economy": [
   "red caviar salmon roe",
   "salmon fish",
   "fish market",
   "supermarket shelves",
   "shopping basket",
   "onigiri rice ball",
   "plastic food container",
   "supermarket checkout",
   "price tag shelf",
   "sandwich food",
   "russian ruble banknotes",
   "grocery shopping",
 ],
 "society": [
   "kick scooter rider",
   "electric scooter street",
   "pedestrian crossing",
   "ambulance",
   "road traffic",
   "bicycle lane",
   "traffic camera",
   "street traffic evening",
   "bicycle helmet",
   "cyclist city street",
   "scooter city",
 ],
 "final": [
   "siberian husky dog",
   "elephant herd",
   "octopus",
   "whale shark",
   "veterinarian",
   "safari wildlife africa",
   "brown bear wild",
   "dog running snow",
   "nature photographer wildlife",
 ],
}

for b in d["blocks"]:
    if b["id"] in KW:
        b["keywords"] = KW[b["id"]]

json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("patched:", ", ".join(f"{k}={len(v)}" for k, v in KW.items()))
