import sys
sys.path.insert(0, "C:/Users/techd/Documents/workspace-spring-tool-suite-4-4.27.0-new/ai-shorts-generator")
from generate_ep1_shorts_seo import SHORTS_METADATA, build_tag_string, FULL_EPISODE_TITLE, CHANNEL_URL

print("=== ALL 10 SHORTS METADATA VALIDATION ===")
all_passed = True
for m in SHORTS_METADATA:
    s_id = m["id"]
    tag_str = build_tag_string(m["tags"])
    p_title = m["primary_title"]
    
    # Calculate full description length
    hashtags_str = " ".join(m["hashtags"])
    full_desc = (
        f"{m['desc_hook']}\n\n"
        f"🎬 SCENE BREAKDOWN & NARRATIVE LORE:\n"
        f"{m['desc_story']}\n\n"
        f"{m['desc_details']}\n\n"
        f"{m['desc_topics']}\n\n"
        f"🎮 WATCH THE FULL 1-HOUR WALKTHROUGH EPISODE:\n"
        f"👉 \"{FULL_EPISODE_TITLE}\" is streaming now on the channel!\n"
        f"🔗 Full Video Link: Search \"{FULL_EPISODE_TITLE}\" on YouTube or check our channel homepage!\n\n"
        f"🔔 JOIN THE JOURNEY - PIYUSH MAKHIJA GAMING:\n"
        f"Hey everyone! Main Piyush Makhija hu, bringing you high-octane PC & PS5 gaming in True 4K 60FPS! "
        f"Subscribe now for daily GTA 6 gameplay, secret guides, story leaks, and cinematic walkthroughs:\n"
        f"👉 {CHANNEL_URL}?sub_confirmation=1\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✨ Visual Standard: True 4K Vertical (2160x3840 @ 60FPS)\n"
        f"🎧 Audio Standard: EBU R128 Broadcast Loudness Normalized (-14 LUFS)\n"
        f"🎮 Platform: PlayStation 5 Pro & High-End PC Max Settings\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{hashtags_str}"
    )
    
    t_len = len(tag_str)
    d_len = len(full_desc)
    ti_len = len(p_title)
    
    print(f"Short {s_id:02d} | Title: {ti_len:2d}/50 | Desc: {d_len:4d}/5000 | Tags: {t_len:3d}/500 | '{p_title}'")
    
    if ti_len > 50:
        print(f"  ❌ Title too long! {ti_len} chars")
        all_passed = False
    if t_len > 500:
        print(f"  ❌ Tags exceed 500! {t_len} chars")
        all_passed = False
    if d_len > 5000:
        print(f"  ❌ Desc exceeds 5000! {d_len} chars")
        all_passed = False
    if d_len < 1500:
        print(f"  ❌ Desc too short! {d_len} chars")
        all_passed = False

if all_passed:
    print("\n✅ ALL 10 SHORTS PASSED ALL STRICT CHECKS WITH FLYING COLORS!")
else:
    print("\n❌ SOME CHECKS FAILED!")
