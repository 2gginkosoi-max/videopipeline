#!/usr/bin/env python3
import argparse, subprocess, sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
W,H,FPS=1920,1080,30

def make_canvas(source, out, start=0, dur=None, crf=28, bitrate="4M"):
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    vf = f"[0:v]trim=start={start}:end={start+dur} if {dur} else trim=start={start},setpts=PTS-STARTPTS,split=2[bg][fg];[bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=12:12,eq=brightness=-0.04,setsar=1[bgc];[fg]scale={W}:{H}:force_original_aspect_ratio=decrease,setsar=1[fgc];[bgc][fgc]overlay=(W-w)/2:(H-h)/2,fps={FPS}[vout]"
    cmd=["ffmpeg","-y","-i",source,"-filter_complex",vf,"-map","[vout]","-an","-c:v","libx264","-crf",str(crf),"-b:v",bitrate,"-pix_fmt","yuv420p","-preset","ultrafast","-r",str(FPS),out]
    if dur is not None:
        cmd.extend(["-t",str(dur)])
    r=subprocess.run(cmd,capture_output=True,text=True,encoding="utf-8",errors="replace")
    return r.returncode==0

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--source",required=True)
    ap.add_argument("--out",required=True)
    ap.add_argument("--start",type=float,default=0)
    ap.add_argument("--dur",type=float,required=True)
    a=ap.parse_args()
    sys.exit(0 if make_canvas(a.source,a.out,a.start,a.dur) else 1)
