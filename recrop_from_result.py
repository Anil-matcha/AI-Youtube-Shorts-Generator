import json
import sys
sys.path.insert(0, ".")
from shorts_generator.local.clipper import crop_highlights_local

with open("result.json") as f:
    result = json.load(f)

source_path = result["source_video_url"]
top = sorted(result["highlights"], key=lambda h: int(h.get("score", 0)), reverse=True)[:10]

print(f"Re-cropping {len(top)} clips from cached highlights (no new Gemini calls)")
shorts = crop_highlights_local(source_path, top, aspect_ratio="9:16")

result["shorts"] = shorts
with open("result.json", "w") as f:
    json.dump(result, f, indent=2)

print("\n" + "=" * 72)
for i, s in enumerate(shorts, 1):
    print(f"\n#{i}  score={s.get('score')}  {s.get('start_time'):.1f}s -> {s.get('end_time'):.1f}s")
    print(f"     title:  {s.get('title')}")
    if s.get("clip_url"):
        print(f"     clip:   {s['clip_url']}")
    else:
        print(f"     clip:   FAILED ({s.get('error')})")
