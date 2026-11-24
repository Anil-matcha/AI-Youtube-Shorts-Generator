import glob
import os
import subprocess
import json

art_dir = "C:/Users/techd/.gemini/antigravity-cli/brain/8fe2d0f4-e993-4a8d-ad30-cf4f4ea5ac6a"
shorts = sorted(glob.glob("ai-shorts-generator/output/ep1_short_*_4K.mp4"))

print(f"Total Shorts Found: {len(shorts)}\n")
for s in shorts:
    name = os.path.basename(s)
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration,size,bit_rate:stream=width,height,r_frame_rate,codec_name",
        "-of", "json", s
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    meta = json.loads(res.stdout)
    v_stream = next(st for st in meta["streams"] if "width" in st)
    w = v_stream["width"]
    h = v_stream["height"]
    fps = v_stream["r_frame_rate"]
    codec = v_stream["codec_name"]
    dur = float(meta["format"]["duration"])
    size_mb = float(meta["format"]["size"]) / (1024 * 1024)
    bitrate_mbps = (float(meta["format"]["bit_rate"]) / 1_000_000) if "bit_rate" in meta["format"] else 0
    print(f"{name:50s} | {w}x{h} @ {fps:10s} ({codec}) | {dur:4.1f}s | {size_mb:5.1f} MB | {bitrate_mbps:.1f} Mbps")

    # Extract sample verification frame at 5s
    v_frame = os.path.join(art_dir, f"verify_{name[:-4]}.jpg")
    f_cmd = ["ffmpeg", "-y", "-ss", "5.0", "-i", s, "-vframes", "1", "-q:v", "2", v_frame]
    subprocess.run(f_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
