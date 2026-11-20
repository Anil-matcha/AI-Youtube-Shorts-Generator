import json

data = json.load(open("output/transcript.json", encoding="utf-8"))

segments_to_check = [
    ("MOMENT 1: Cops & Car Radio", 230, 275),
    ("MOMENT 2: Ambush - Shit Going Down", 575, 620),
    ("MOMENT 3: Screw Brian - Gun in Back", 670, 715),
    ("MOMENT 4: Rooftop Shootout / Action", 1085, 1130),
    ("MOMENT 5: Escape Car Panic", 1685, 1725),
    ("MOMENT 6: Drug Lab Discussion", 2280, 2320)
]

for name, s, e in segments_to_check:
    print(f"\n==================== {name} ({s}s - {e}s) ====================")
    for d in data:
        if s <= d["start"] <= e:
            print(f"[{d['start']}s]: {d['text']}")
