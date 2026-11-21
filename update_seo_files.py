"""Write complete, clean UTF-8 SEO packages for Shorts 1 to 15 without character corruption."""

from pathlib import Path

# Load Shorts 1 to 7 from docs/EPISODE_3_SHORTS_SEO_PACKAGE.txt
source_doc = Path("docs/EPISODE_3_SHORTS_SEO_PACKAGE.txt")
with open(source_doc, "r", encoding="utf-8") as f:
    text = f.read()

# Split at SHORT 8
split_marker = "SHORT 8: MANDY"
idx = text.find(split_marker)
if idx != -1:
    # Find the divider line before it
    prev_div = text.rfind("--------------------------------------------------------------------------------", 0, idx)
    base_text = text[:prev_div].strip()
else:
    raise RuntimeError("Could not find SHORT 8 in document")

# Newly formatted Shorts 8 to 15 from Subagent
new_shorts = """
--------------------------------------------------------------------------------
SHORT 8: MANDY HALLWAY FLIRTATION & RENT WEBSITE ROAST
File: output/ep3_short_8_Mandy_AutoPay_Flirt_4K.mp4
Framing: Up & Down (split_stack) | Top: Mandy | Bottom: Jason
Virality Score: 94/100 | Archetype: DIALOGUE_BANTER
--------------------------------------------------------------------------------
[TITLE OPTIONS - A/B TEST READY]
Variant A (Curiosity Gap):  Landlords in GTA 6 are completely unhinged 💀
Variant B (Search Velocity): GTA 6 Mandy Rent Website Secret Dialogue 4K
Variant C (Meme/Relatable):  PayMandyNow.com rent roast in GTA 6 😭

[DESCRIPTION]
#GTA6 #GTA6Shorts #Gaming

She made a custom website just to collect rent... 💀

Mandy roasts Jason in the hallway for paying rent like a dinosaur with her custom site PayMandyNow.com. Rockstar Games delivered top-tier landlord satire and hilarious dialogue interactions in this 4K 60FPS Vice City encounter.

🔥 Watch the full Episode 3 4K 60FPS Walkthrough:
👉 https://youtu.be/Lvfc2eYMRHU

[TAGS (490 Characters)]
gta 6, gta vi, gta 6 gameplay, gta 6 shorts, grand theft auto vi, gta 6 mandy, gta 6 landlord, paymandynow, gta 6 funny moments, gta 6 funny dialogue, gta 6 secret cutscene, gta 6 npc interaction, gta 6 vice city, gta 6 ps5 pro, gta 6 4k 60fps, gta 6 easter eggs, gta 6 details, gta 6 comedy, gta 6 jason and mandy, gta 6 episode 3, rockstar games, gta 6 rent scene, gta 6 viral, gta 6 voice acting, gta 6 leonida, vice city apartments, gta vi funny moments, gta 6 rent meme, gta 6 pay rent

[PINNED COMMENT]
Would you pay your rent through 'PayMandyNow.com' or are you calling the tenant union immediately? 💀🏢 Settle this below 👇

--------------------------------------------------------------------------------
SHORT 9: BRIAN HEDER 15-YR TABLE LORE & MOB STANDOFF
File: output/ep3_short_9_Brian_Table_Ritual_4K.mp4
Framing: Up & Down (split_stack) | Top: Brian Pacing | Bottom: Jason
Virality Score: 93/100 | Archetype: LORE_BACKSTORY / COMEDY
--------------------------------------------------------------------------------
[TITLE OPTIONS - A/B TEST READY]
Variant A (Curiosity Gap):  He sat at this table for 15 YEARS in GTA 6 💀
Variant B (Search Velocity): GTA 6 Brian Heder Mob Standoff Scene 4K
Variant C (Meme/Relatable):  When mob bosses refuse to leave their table 😭

[DESCRIPTION]
#GTA6 #GTAVI #GTA6Lore

This mob boss hasn't moved from this table in 15 years 💀

Brian Heder's legendary restaurant table standoff reveals the hilarious backstory of Vice City's local crime syndicate. Experience intense mob confrontations, razor-sharp voice acting, and deep underworld lore in native 4K 60FPS.

🔥 Watch the full Episode 3 4K 60FPS Walkthrough:
👉 https://youtu.be/Lvfc2eYMRHU

[TAGS (482 Characters)]
gta 6, gta vi, gta 6 gameplay, gta 6 shorts, grand theft auto vi, gta 6 brian heder, gta 6 mob standoff, gta 6 mafia, gta 6 funny dialogue, gta 6 lore, gta 6 story mission, gta 6 cutscenes, gta 6 vice city, gta 6 port gellhorn, gta 6 ps5 pro, gta 6 4k 60fps, gta 6 character lore, gta 6 voice acting, gta 6 details, gta 6 episode 3, rockstar games, gta 6 funny cutscene, gta 6 crime syndicate, gta 6 mafia standoff, gta 6 world building, gta vi lore, gta 6 story mode, gta 6 secrets

[PINNED COMMENT]
Is Brian Heder the most stubborn mob boss in GTA history, or would you also guard your favorite restaurant table for 15 straight years? 🍝🔫

--------------------------------------------------------------------------------
SHORT 10: VICE CITY CAR CHASE: TINDER GHOSTING ROAST
File: output/ep3_short_10_Car_Chase_Tinder_Ghost_4K.mp4
Framing: Up & Down (split_stack) | Top: Brian Screaming | Bottom: Jason Driving
Virality Score: 97/100 (Peak Viral Comedy) | Archetype: DIALOGUE_BANTER / COMEDY
--------------------------------------------------------------------------------
[TITLE OPTIONS - A/B TEST READY]
Variant A (Curiosity Gap):  Arguing about Tinder mid car chase in GTA 6 😭
Variant B (Search Velocity): GTA 6 Vice City Car Chase Funny Dialogue 4K
Variant C (Meme/Relatable):  Couples fighting during a police chase be like 💀

[DESCRIPTION]
#GTA6 #GTA6Moments #GamingMemes

Arguing about dating apps during a 120 MPH car chase 💀

Jason and Brian get into a heated argument about Tinder matches and ghosting while dodging traffic at breakneck speeds in Vice City. Rockstar's signature comedic timing shines in this high-octane 4K 60FPS vehicle pursuit.

🔥 Watch the full Episode 3 4K 60FPS Walkthrough:
👉 https://youtu.be/Lvfc2eYMRHU

[TAGS (482 Characters)]
gta 6, gta vi, gta 6 gameplay, gta 6 shorts, grand theft auto vi, gta 6 car chase, gta 6 jason and lucia, gta 6 tinder argument, gta 6 funny moments, gta 6 police chase, gta 6 driving physics, gta 6 vice city chase, gta 6 dialogue, gta 6 couples fighting, gta 6 ps5 pro, gta 6 4k 60fps, gta 6 voice lines, gta 6 mission walkthrough, gta 6 episode 3, rockstar games, gta 6 neon vice city, gta 6 funny cutscene, gta 6 relationship, gta vi gameplay 4k, gta 6 funny chase, gta 6 driving

[PINNED COMMENT]
Who's more toxic: Jason bringing up dating apps during a getaway, or Brian screaming his lungs out at 120 MPH? 😭🚗💨

--------------------------------------------------------------------------------
SHORT 11: TIKI BAR UNICORNS, LORI PILL POPPING & KENTON REES
File: output/ep3_short_11_Tiki_Bar_Unicorns_4K.mp4
Framing: Up & Down (split_stack) | Top: Lori | Bottom: Kenny & Jason
Virality Score: 91/100 | Archetype: LORE_BACKSTORY / COMEDY
--------------------------------------------------------------------------------
[TITLE OPTIONS - A/B TEST READY]
Variant A (Curiosity Gap):  The weirdest bar conversation in GTA 6... 🦄
Variant B (Search Velocity): GTA 6 Tiki Bar Lori & Kenton Cutscene 4K
Variant C (Meme/Relatable):  Average Friday night in Florida in GTA 6 😭

[DESCRIPTION]
#GTA6 #GTAVI #GTA6Secrets

Florida dive bars in GTA 6 are genuinely terrifying 💊

Lori's wild pill-popping ramblings about unicorns alongside Kenton Rees show the bizarre side of Leonida nightlife. Rockstar captures chaotic Florida bar culture with unbelievable NPC behavior and dialogues in 4K 60FPS.

🔥 Watch the full Episode 3 4K 60FPS Walkthrough:
👉 https://youtu.be/Lvfc2eYMRHU

[TAGS (477 Characters)]
gta 6, gta vi, gta 6 gameplay, gta 6 shorts, grand theft auto vi, gta 6 tiki bar, gta 6 lori, gta 6 kenton rees, gta 6 florida weirdness, gta 6 funny moments, gta 6 secret cutscene, gta 6 npc dialogue, gta 6 dive bar, gta 6 vice city, gta 6 ps5 pro, gta 6 4k 60fps, gta 6 easter eggs, gta 6 details, gta 6 comedy, gta 6 crazy npcs, gta 6 episode 3, rockstar games, gta 6 leonida nightlife, gta 6 random encounter, gta vi secret dialogue, gta 6 hidden lore, gta 6 vice city bars

[PINNED COMMENT]
On a scale of 1 to Florida, how unhinged is this Tiki Bar encounter? Would you order a drink here or sprint for the exit? 🦄🍹

--------------------------------------------------------------------------------
SHORT 12: ROCKSTAR SATIRE AD: MR. GARCIA SUED SURGEON BUTLER / BBL DISASTER
File: output/ep3_short_12_MrGarcia_BBL_Lawyer_4K.mp4
Framing: Fullscreen 9:16 (smart_focus) | TV Commercial Parody
Virality Score: 98/100 (Peak Satire) | Archetype: SATIRE_COMMERCIAL
--------------------------------------------------------------------------------
[TITLE OPTIONS - A/B TEST READY]
Variant A (Curiosity Gap):  He sued his BBL surgeon and won a BUTLER?! 💀
Variant B (Search Velocity): GTA 6 Mr Garcia Botched BBL Commercial 4K
Variant C (Meme/Relatable):  Rockstar's wildest TV satire in GTA 6 history 💀

[DESCRIPTION]
#GTA6 #GTAVISatire #RockstarGames

He sued his plastic surgeon and won him as a butler 😭

Mr. Garcia's botched cosmetic procedure in GTA 6 leads to the most outrageous court settlement in television history. Rockstar Games takes surgical satire and commercial parodies to astronomical new heights in 4K 60FPS.

🔥 Watch the full Episode 3 4K 60FPS Walkthrough:
👉 https://youtu.be/Lvfc2eYMRHU

[TAGS (478 Characters)]
gta 6, gta vi, gta 6 gameplay, gta 6 shorts, grand theft auto vi, gta 6 mr garcia, gta 6 bbl commercial, gta 6 satire ads, gta 6 tv commercials, gta 6 funny moments, gta 6 rockstar satire, gta 6 comedy, gta 6 radio ads, gta 6 television, gta 6 vice city, gta 6 ps5 pro, gta 6 4k 60fps, gta 6 easter eggs, gta 6 details, gta 6 episode 3, rockstar games, gta 6 florida satire, gta 6 parody, gta 6 commercial ad, gta vi satire, gta 6 in game tv, gta 6 tv ad, gta 6 humor, gta 6 ads

[PINNED COMMENT]
Is this the most savage commercial Rockstar has ever animated, or does GTA 5's TV programming still reign supreme? Drop your take 👇

--------------------------------------------------------------------------------
SHORT 13: ROCKSTAR SATIRE AD: KING GATOR MINI-GOLF ("LOOK AT ALL THEM HOLES!")
File: output/ep3_short_13_King_Gator_Golf_4K.mp4
Framing: Fullscreen 9:16 (smart_focus) | TV Commercial Parody
Virality Score: 95/100 | Archetype: SATIRE_COMMERCIAL
--------------------------------------------------------------------------------
[TITLE OPTIONS - A/B TEST READY]
Variant A (Curiosity Gap):  The trashiest commercial in GTA 6 history 🐊
Variant B (Search Velocity): GTA 6 King Gator Mini Golf Satire Ad 4K
Variant C (Meme/Relatable):  Look at all them holes! King Gator in GTA 6 💀

[DESCRIPTION]
#GTA6 #GTA6Parody #GamingHumor

Only Florida would build a mini-golf course like this 🐊

King Gator Mini-Golf brings swamp madness to GTA 6 television with live alligators and wild Southern pitchmen screaming about holes. Rockstar's parody of tourist traps captures the wildest roadside energy in full 4K 60FPS.

🔥 Watch the full Episode 3 4K 60FPS Walkthrough:
👉 https://youtu.be/Lvfc2eYMRHU

[TAGS (482 Characters)]
gta 6, gta vi, gta 6 gameplay, gta 6 shorts, grand theft auto vi, gta 6 king gator, gta 6 mini golf, gta 6 satire ad, gta 6 commercial, gta 6 florida memes, gta 6 alligators, gta 6 funny moments, gta 6 tv parody, gta 6 comedy, gta 6 vice city ads, gta 6 ps5 pro, gta 6 4k 60fps, gta 6 easter eggs, gta 6 details, gta 6 episode 3, rockstar games, gta 6 leonida satire, gta 6 swamp humor, gta 6 commercial parodies, gta vi funny ads, gta 6 tv, gta 6 redneck comedy, gta 6 mini golf ad

[PINNED COMMENT]
Would you play 18 holes at King Gator Mini-Golf knowing there are real alligators waiting in the water hazards? 🐊⛳💀

--------------------------------------------------------------------------------
SHORT 14: OCEAN SALVAGE LORE: SIR TODD BANKCROFT "THE RICH ENGLISH ASSHOLE"
File: output/ep3_short_14_Todd_Bankcroft_Lore_4K.mp4
Framing: Up & Down (split_stack) | Top: Kenny | Bottom: Jason
Virality Score: 92/100 | Archetype: LORE_BACKSTORY
--------------------------------------------------------------------------------
[TITLE OPTIONS - A/B TEST READY]
Variant A (Curiosity Gap):  The story behind this sunken ship in GTA 6 🚢
Variant B (Search Velocity): GTA 6 Sir Todd Bankcroft Ocean Salvage Lore 4K
Variant C (Meme/Relatable):  History lessons hit different in GTA 6 💀

[DESCRIPTION]
#GTA6 #GTA6Secrets #GTA6Lore

The dark history behind GTA 6's richest sunken ship ⚓

Kenny breaks down the offshore salvage history of Sir Todd Bankcroft, the eccentric English aristocrat whose wealth lies rotting on the seabed. Explore high-seas salvage mysteries and historical shipwrecks in stunning 4K 60FPS.

🔥 Watch the full Episode 3 4K 60FPS Walkthrough:
👉 https://youtu.be/Lvfc2eYMRHU

[TAGS (487 Characters)]
gta 6, gta vi, gta 6 gameplay, gta 6 shorts, grand theft auto vi, gta 6 sir todd bankcroft, gta 6 ocean salvage, gta 6 sunken ship lore, gta 6 shipwreck history, gta 6 underwater secrets, gta 6 treasure hunt, gta 6 deep sea, gta 6 kenny salvage, gta 6 dialogue, gta 6 vice city ocean, gta 6 ps5 pro, gta 6 4k 60fps, gta 6 details, gta 6 lore, gta 6 episode 3, rockstar games, gta 6 maritime secrets, gta 6 colonial history, gta vi salvage lore, gta 6 ocean secrets, gta 6 underwater lore

[PINNED COMMENT]
Does Sir Todd Bankcroft deserve having his 100-year-old fortune plundered, or should historical shipwreck gold remain undisturbed on the ocean bed? 🪙🌊

--------------------------------------------------------------------------------
SHORT 15: THE NOOB GETAWAY CRASH: TREE CRASH & HIGHWAY GUARDRAIL SPARKS
File: output/ep3_short_15_Noob_Driver_Tree_Crash_4K.mp4
Framing: Fullscreen 9:16 (smart_focus) | High-Speed Getaway Fail
Virality Score: 96/100 (Peak Relatable Comedy) | Archetype: STUNT_FAIL / ACCIDENT
--------------------------------------------------------------------------------
[TITLE OPTIONS - A/B TEST READY]
Variant A (Curiosity Gap):  The worst getaway driver in GTA 6 history 💀
Variant B (Search Velocity): GTA 6 Epic Highway Crash & Ragdoll Physics 4K
Variant C (Meme/Relatable):  When the getaway driver has 0 driving skill 💀

[DESCRIPTION]
#GTA6 #GTA6Fails #GamingMoments

130 MPH directly into the highway guardrail... 💀💥

Watch what happens when an intense mob getaway meets zero driving skills, crashing head-on into pine trees with violent guardrail sparks. Witness next-generation vehicle deformation and ragdoll physics in crisp 4K 60FPS.

🔥 Watch the full Episode 3 4K 60FPS Walkthrough:
👉 https://youtu.be/Lvfc2eYMRHU

[TAGS (477 Characters)]
gta 6, gta vi, gta 6 gameplay, gta 6 shorts, grand theft auto vi, gta 6 car crash, gta 6 crash physics, gta 6 vehicle deformation, gta 6 getaway fail, gta 6 funny moments, gta 6 highway crash, gta 6 guardrail sparks, gta 6 ragdoll physics, gta 6 driving fail, gta 6 vice city, gta 6 ps5 pro, gta 6 4k 60fps, gta 6 fails, gta 6 stunt fail, gta 6 episode 3, rockstar games, gta 6 car destruction, gta 6 tree collision, gta vi funny crash, gta 6 driving fails, gta 6 instant karma

[PINNED COMMENT]
Rate this getaway driving from 1 to 10... and be honest, have you already crashed exactly like this on day 2? 💀💥🚗
================================================================================
"""

final_text = base_text + "\n" + new_shorts

with open("docs/EPISODE_3_SHORTS_SEO_PACKAGE.txt", "w", encoding="utf-8") as f:
    f.write(final_text)

with open("EPISODE_3_COPY_PASTE_READY.txt", "w", encoding="utf-8") as f:
    f.write(final_text)

print("Successfully written all 15 shorts to docs/EPISODE_3_SHORTS_SEO_PACKAGE.txt and EPISODE_3_COPY_PASTE_READY.txt!")
