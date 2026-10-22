#!/usr/bin/env python3
import argparse, subprocess, sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
W,H,FPS=1920,1080,30

def compose(source, segments, out, crf=25, bitrate="5M", style="punch"):
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    parts=[]
    for i,(start,dur) in enumerate(segments):
        end=start+dur
        grade="eq=contrast=1.05:saturation=1.08:brightness=0.01," if style=="punch" else ""
        parts.append(f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS,{grade}split=2[bs{i}][fs{i}];[bs{i}]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=15:15,eq=brightness=-0.05,setsar=1[bg{i}];[fs{i}]scale={W}:{H}:force_original_aspect_ratio=decrease,setsar=1[fg{i}];[bg{i}][fg{i}]overlay=(W-w)/2:(H-h)/2,fps={FPS}[seg{i}]")
    concat_in="".join(f"[seg{i}]" for i in range(len(segments)))
    parts.append(f"{concat_in}concat=n={len(segments)}:v=1:a=0[vout]")
    fc=";".join(parts)
    cmd=["ffmpeg","-y","-i",source,"-filter_complex",fc,"-map","[vout]","-an","-c:v","libx264","-crf",str(crf),"-b:v",bitrate,"-pix_fmt","yuv420p","-preset","fast","-r",str(FPS),out]
    r=subprocess.run(cmd,capture_output=True,text=True,encoding="utf-8",errors="replace")
    return r.returncode==0

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--source",required=True)
    ap.add_argument("--out",required=True)
    ap.add_argument("--segments",required=True)
    a=ap.parse_args()
    segs=[]
    for t in a.segments.split(","):
        s2,d2=t.split(":"); segs.append((float(s2),float(d2)))
    sys.exit(0 if compose(a.source,segs,a.out) else 1)
