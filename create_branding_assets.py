"""Module for generating the complete visual branding suite for Piyush Makhija Gaming.

This script creates:
1. Channel Profile Avatar (800x800 PNG)
2. Channel Banner Art (2560x1440 PNG, strictly safe-zone compliant)
3. Video Player Watermark (500x500 Transparent PNG)
4. Episode 1 Master 4K Thumbnail (1920x1080 PNG)
"""

import math
import os
from pathlib import Path
from typing import Tuple
from PIL import Image, ImageDraw, ImageFilter, ImageFont


def get_system_font(font_name: str, size: int) -> ImageFont.FreeTypeFont:
    """Retrieve a system font by name or fallback to default font.

    Args:
        font_name: Base filename of font (e.g. 'impact.ttf', 'arialbd.ttf').
        size: Desired font size in pixels.

    Returns:
        Loaded FreeTypeFont object.
    """
    windir = os.environ.get("WINDIR", "C:\\Windows")
    font_path = os.path.join(windir, "Fonts", font_name)
    if os.path.exists(font_path):
        return ImageFont.truetype(font_path, size)
    fallback_path = os.path.join(windir, "Fonts", "arial.ttf")
    if os.path.exists(fallback_path):
        return ImageFont.truetype(fallback_path, size)
    return ImageFont.load_default()


def draw_text_with_outline(
    draw: ImageDraw.ImageDraw,
    xy: Tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill_color: Tuple[int, ...],
    outline_color: Tuple[int, ...],
    outline_width: int,
) -> None:
    """Draw text with a thick contrasting outline for maximum readability.

    Args:
        draw: PIL ImageDraw object.
        xy: Top-left coordinate tuple (x, y).
        text: String content to draw.
        font: Font object to use.
        fill_color: Primary fill RGBA tuple.
        outline_color: Outline RGBA tuple.
        outline_width: Thickness of outline in pixels.
    """
    x, y = xy
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
    draw.text((x, y), text, font=font, fill=fill_color)


def create_profile_avatar(output_path: Path, raw_art_path: Path | None = None) -> Path:
    """Generate high-contrast 800x800 circular-ready channel profile avatar.

    Args:
        output_path: Destination PNG file path.
        raw_art_path: Optional path to AI-generated background art.

    Returns:
        Resolved Path to generated avatar image.
    """
    size = (800, 800)
    img = Image.new("RGBA", size, (12, 12, 18, 255))
    draw = ImageDraw.Draw(img)

    if raw_art_path and raw_art_path.exists():
        raw_art = Image.open(raw_art_path).convert("RGBA")
        raw_art = raw_art.resize(size, Image.Resampling.LANCZOS)
        img.paste(raw_art, (0, 0))
    else:
        for r in range(400, 0, -4):
            color = (int(20 + 20 * (1 - r / 400)), int(10 + 30 * (1 - r / 400)), int(35 + 45 * (1 - r / 400)), 255)
            draw.ellipse((400 - r, 400 - r, 400 + r, 400 + r), fill=color)

    glow_layer = Image.new("RGBA", size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_layer)

    glow_draw.ellipse((25, 25, 775, 775), outline=(0, 240, 255, 200), width=12)
    glow_draw.ellipse((37, 37, 763, 763), outline=(255, 20, 147, 180), width=6)

    bottom_plate = (160, 640, 640, 720)
    glow_draw.rounded_rectangle(bottom_plate, radius=24, fill=(10, 8, 20, 230), outline=(0, 240, 255, 220), width=3)

    img = Image.alpha_composite(img, glow_layer)
    final_draw = ImageDraw.Draw(img)

    font_brand = get_system_font("impact.ttf", 46)
    font_sub = get_system_font("segoeui.ttf", 20)

    name_text = "PIYUSH MAKHIJA GAMING"
    bbox_name = font_brand.getbbox(name_text)
    name_w = bbox_name[2] - bbox_name[0]
    draw_text_with_outline(final_draw, ((800 - name_w) // 2, 650), name_text, font_brand, (0, 240, 255, 255), (0, 0, 0, 255), 4)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG", optimize=True)
    return output_path


def create_channel_banner(output_path: Path, raw_bg_path: Path | None = None) -> Path:
    """Generate 2560x1440 YouTube channel banner with centered safe-zone graphics.

    Safe zone strictly adheres to 1235x338 px centered at (663, 551, 1897, 889).

    Args:
        output_path: Destination PNG file path.
        raw_bg_path: Optional path to AI-generated background art.

    Returns:
        Resolved Path to generated banner image.
    """
    canvas_w, canvas_h = 2560, 1440
    img = Image.new("RGBA", (canvas_w, canvas_h), (10, 8, 18, 255))
    draw = ImageDraw.Draw(img)

    if raw_bg_path and raw_bg_path.exists():
        raw_bg = Image.open(raw_bg_path).convert("RGBA")
        raw_bg = raw_bg.resize((canvas_w, canvas_h), Image.Resampling.LANCZOS)
        img.paste(raw_bg, (0, 0))
    else:
        for y in range(canvas_h):
            ratio = y / canvas_h
            r = int(15 + 40 * ratio)
            g = int(10 + 20 * (1 - ratio))
            b = int(25 + 55 * ratio)
            draw.line([(0, y), (canvas_w, y)], fill=(r, g, b, 255))

    safe_box = (663, 551, 1897, 889)
    safe_w = safe_box[2] - safe_box[0]
    center_x = (safe_box[0] + safe_box[2]) // 2

    overlay = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)

    overlay_draw.rounded_rectangle((safe_box[0] + 10, safe_box[1] + 10, safe_box[2] - 10, safe_box[3] - 10), radius=28, fill=(10, 8, 20, 215), outline=(0, 240, 255, 180), width=3)
    overlay_draw.line([(safe_box[0] + 25, safe_box[1] + 10), (safe_box[2] - 25, safe_box[1] + 10)], fill=(255, 20, 147, 240), width=5)

    img = Image.alpha_composite(img, overlay)
    draw = ImageDraw.Draw(img)

    font_title = get_system_font("impact.ttf", 86)
    font_sub = get_system_font("impact.ttf", 36)
    font_badge = get_system_font("segoeui.ttf", 26)
    font_side = get_system_font("impact.ttf", 28)

    title_text = "PIYUSH MAKHIJA GAMING"
    t_box = font_title.getbbox(title_text)
    t_w = t_box[2] - t_box[0]
    draw_text_with_outline(draw, (center_x - t_w // 2, 575), title_text, font_title, (0, 240, 255, 255), (0, 0, 0, 255), 6)

    sub_text = "GTA 6  •  NEXT-GEN PC & PS5 GAMEPLAY  •  4K 60FPS"
    s_box = font_sub.getbbox(sub_text)
    s_w = s_box[2] - s_box[0]
    draw_text_with_outline(draw, (center_x - s_w // 2, 680), sub_text, font_sub, (255, 255, 255, 255), (0, 0, 0, 255), 4)

    schedule_text = "⚡ NEW 4K SHORT DAILY AT 8:00 PM IST  |  SUBSCRIBE FOR EPIC MISSIONS"
    sch_box = font_badge.getbbox(schedule_text)
    sch_w = sch_box[2] - sch_box[0]

    pill_x1 = center_x - sch_w // 2 - 25
    pill_y1 = 745
    pill_x2 = center_x + sch_w // 2 + 25
    pill_y2 = 795
    draw.rounded_rectangle((pill_x1, pill_y1, pill_x2, pill_y2), radius=25, fill=(255, 20, 147, 230), outline=(255, 255, 255, 220), width=2)
    draw.text((center_x - sch_w // 2, pill_y1 + 10), schedule_text, font=font_badge, fill=(255, 255, 255, 255))

    left_badge_box = (safe_box[0] + 35, 610, safe_box[0] + 165, 830)
    draw.rounded_rectangle(left_badge_box, radius=16, fill=(18, 16, 32, 230), outline=(0, 240, 255, 200), width=2)
    draw.text((safe_box[0] + 55, 640), "PC", font=font_side, fill=(0, 240, 255, 255))
    draw.text((safe_box[0] + 58, 690), "+", font=font_side, fill=(255, 255, 255, 255))
    draw.text((safe_box[0] + 48, 740), "PS5", font=font_side, fill=(255, 20, 147, 255))

    right_badge_box = (safe_box[2] - 165, 610, safe_box[2] - 35, 830)
    draw.rounded_rectangle(right_badge_box, radius=16, fill=(18, 16, 32, 230), outline=(255, 20, 147, 200), width=2)
    draw.text((safe_box[2] - 150, 640), "TRUE", font=font_side, fill=(255, 255, 255, 255))
    draw.text((safe_box[2] - 145, 690), "4K", font=font_side, fill=(255, 215, 0, 255))
    draw.text((safe_box[2] - 158, 740), "60FPS", font=font_side, fill=(0, 240, 255, 255))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG", optimize=True)
    return output_path


def create_video_watermark(output_path: Path) -> Path:
    """Generate 500x500 high-contrast transparent PNG watermark for YouTube player.

    Args:
        output_path: Destination PNG file path.

    Returns:
        Resolved Path to generated watermark image.
    """
    size = (500, 500)
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle((20, 20, 480, 480), radius=60, fill=(18, 18, 24, 240), outline=(255, 0, 0, 255), width=8)

    draw.rounded_rectangle((50, 60, 450, 250), radius=40, fill=(230, 20, 20, 255))
    draw.polygon([(210, 105), (210, 205), (310, 155)], fill=(255, 255, 255, 255))

    font_sub = get_system_font("impact.ttf", 64)
    font_name = get_system_font("impact.ttf", 46)

    sub_text = "SUBSCRIBE"
    sb = font_sub.getbbox(sub_text)
    sw = sb[2] - sb[0]
    draw_text_with_outline(draw, ((500 - sw) // 2, 280), sub_text, font_sub, (255, 255, 255, 255), (0, 0, 0, 255), 4)

    name_text = "PIYUSH GAMING"
    nb = font_name.getbbox(name_text)
    nw = nb[2] - nb[0]
    draw_text_with_outline(draw, ((500 - nw) // 2, 365), name_text, font_name, (0, 240, 255, 255), (0, 0, 0, 255), 3)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG", optimize=True)
    return output_path


def create_ep1_master_thumbnail(output_path: Path, raw_ep1_art_path: Path | None = None) -> Path:
    """Generate 1920x1080 16:9 high-CTR master thumbnail for GTA 6 Episode 1 Walkthrough.

    Args:
        output_path: Destination PNG file path.
        raw_ep1_art_path: Optional path to AI-generated background art.

    Returns:
        Resolved Path to generated thumbnail image.
    """
    size = (1920, 1080)
    img = Image.new("RGBA", size, (15, 12, 24, 255))
    draw = ImageDraw.Draw(img)

    if raw_ep1_art_path and raw_ep1_art_path.exists():
        raw_art = Image.open(raw_ep1_art_path).convert("RGBA")
        raw_art = raw_art.resize(size, Image.Resampling.LANCZOS)
        img.paste(raw_art, (0, 0))
    else:
        for y in range(1080):
            ratio = y / 1080
            r = int(35 + 80 * ratio)
            g = int(15 + 40 * (1 - ratio))
            b = int(50 + 90 * ratio)
            draw.line([(0, y), (1920, y)], fill=(r, g, b, 255))

    vignette = Image.new("RGBA", size, (0, 0, 0, 0))
    v_draw = ImageDraw.Draw(vignette)
    for i in range(180):
        alpha = int(190 * (1 - i / 180))
        v_draw.rectangle([i, i, 1920 - i, 1080 - i], outline=(0, 0, 0, alpha), width=1)
    v_draw.rectangle([0, 0, 1150, 1080], fill=(5, 5, 14, 155))
    img = Image.alpha_composite(img, vignette)
    draw = ImageDraw.Draw(img)

    font_hero_brand = get_system_font("impact.ttf", 150)
    font_hindi_hook = get_system_font("impact.ttf", 110)
    font_badge = get_system_font("impact.ttf", 52)
    font_meta = get_system_font("segoeui.ttf", 36)

    draw.rounded_rectangle((70, 70, 480, 145), radius=18, fill=(230, 20, 20, 240), outline=(255, 255, 255, 220), width=3)
    draw.text((95, 80), "EPISODE 1", font=font_badge, fill=(255, 255, 255, 255))

    draw.rounded_rectangle((510, 70, 920, 145), radius=18, fill=(0, 200, 255, 240), outline=(255, 255, 255, 220), width=3)
    draw.text((535, 80), "HINDI 4K 60FPS", font=font_badge, fill=(0, 0, 0, 255))

    draw_text_with_outline(draw, (70, 180), "GRAND THEFT AUTO VI", font_hero_brand, (0, 240, 255, 255), (0, 0, 0, 255), 8)

    draw_text_with_outline(draw, (70, 370), "BHAI NE BOLA", font_hindi_hook, (255, 235, 50, 255), (0, 0, 0, 255), 7)
    draw_text_with_outline(draw, (70, 500), "MARNE KA TOH", font_hindi_hook, (255, 255, 255, 255), (0, 0, 0, 255), 7)
    draw_text_with_outline(draw, (70, 630), "MARNE KA! 💀", font_hindi_hook, (255, 40, 80, 255), (0, 0, 0, 255), 8)

    bottom_bar = (70, 880, 1050, 990)
    draw.rounded_rectangle(bottom_bar, radius=24, fill=(15, 15, 25, 230), outline=(0, 240, 255, 200), width=3)
    draw.text((105, 910), "🎮 PC & PS5 MAX SETTINGS  •  FULL WALKTHROUGH", font=font_meta, fill=(255, 255, 255, 255))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG", optimize=True)
    return output_path


def main() -> None:
    """Generate all branding assets for Piyush Makhija Gaming."""
    branding_dir = Path("ai-shorts-generator/assets/branding")
    branding_dir.mkdir(parents=True, exist_ok=True)

    def find_raw(prefix: str) -> Path | None:
        for ext in [".jpg", ".png", ".jpeg"]:
            p = branding_dir / f"{prefix}{ext}"
            if p.exists():
                return p
        return None

    raw_avatar = find_raw("raw_avatar_art")
    raw_banner = find_raw("raw_banner_bg")
    raw_ep1 = find_raw("raw_ep1_art")

    avatar_path = branding_dir / "channel_profile_avatar_800x800.png"
    banner_path = branding_dir / "channel_banner_2560x1440.png"
    watermark_path = branding_dir / "video_watermark_500x500.png"
    thumbnail_path = branding_dir / "ep1_master_thumbnail_1080p.png"

    print("Generating Channel Profile Avatar (800x800)...")
    create_profile_avatar(avatar_path, raw_avatar)

    print("Generating Channel Banner (2560x1440, Safe-Zone Compliant)...")
    create_channel_banner(banner_path, raw_banner)

    print("Generating Video Player Watermark (500x500 Transparent PNG)...")
    create_video_watermark(watermark_path)

    print("Generating Episode 1 Master 4K Thumbnail (1920x1080)...")
    create_ep1_master_thumbnail(thumbnail_path, raw_ep1)

    print("All branding assets generated and blended successfully!")


if __name__ == "__main__":
    main()
