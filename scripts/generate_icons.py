"""
Icon Generator for Audio Visualizer.
Rebuilds the ICO from the checked-in PNG, preserving its tile and emblem.
If the PNG is absent, transforms raw high-res artwork into a Squircle icon:
- Clean transparent margins (no black corners on desktop)
- Soft ambient drop shadow for depth on any wallpaper
- 7-layer .ico container (16, 24, 32, 48, 64, 128, 256) via Lanczos supersampling
- Windows 11 / macOS fluent squircle geometry
"""

import os
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter, ImageDraw

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
SOURCE_IMAGE = ASSETS_DIR / "Helvior_Logo_alt2.png"
OUTPUT_ICO = ASSETS_DIR / "icon.ico"
OUTPUT_PNG = ASSETS_DIR / "icon.png"

TARGET_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def generate_squircle_master(src_path: Path, canvas_size: int = 1024) -> Image.Image:
    print(f"Loading source artwork from: {src_path}")
    if not src_path.exists():
        raise FileNotFoundError(f"Source artwork not found at: {src_path}")

    src_logo = Image.open(src_path)

    TILE_SIZE = int(canvas_size * 0.80)       # 820px on 1024 canvas
    OFFSET_Y = int(-canvas_size * 0.014)     # -14px slight upward lift for shadow room
    RADIUS = int(TILE_SIZE * 0.225)          # Squircle corner radius
    SS = 2                                   # 2x Supersampling for ultra-crisp edges

    C_SS = canvas_size * SS
    T_SS = TILE_SIZE * SS
    R_SS = RADIUS * SS
    OFF_SS = OFFSET_Y * SS

    # 1. Base Squircle Mask with 2x supersampling
    cx, cy = C_SS // 2, C_SS // 2 + OFF_SS
    x0, y0 = cx - T_SS // 2, cy - T_SS // 2
    x1, y1 = x0 + T_SS, y0 + T_SS

    mask_ss = Image.new("L", (C_SS, C_SS), 0)
    d_mask = ImageDraw.Draw(mask_ss)
    d_mask.rounded_rectangle([x0, y0, x1, y1], radius=R_SS, fill=255)
    tile_mask = mask_ss.resize((canvas_size, canvas_size), Image.Resampling.LANCZOS)

    # 2. Ambient Drop Shadow
    shadow_broad = tile_mask.filter(ImageFilter.GaussianBlur(radius=int(canvas_size * 0.045)))
    contact_mask = Image.new("L", (canvas_size, canvas_size), 0)
    contact_mask.paste(tile_mask, (0, int(canvas_size * 0.026)))
    shadow_contact = contact_mask.filter(ImageFilter.GaussianBlur(radius=int(canvas_size * 0.021)))

    arr_broad = np.array(shadow_broad, dtype=np.float32) / 255.0 * 0.38
    arr_contact = np.array(shadow_contact, dtype=np.float32) / 255.0 * 0.52
    arr_comb = np.clip(arr_broad + arr_contact, 0.0, 0.90)

    sh_rgba = np.zeros((canvas_size, canvas_size, 4), dtype=np.uint8)
    sh_rgba[:, :, 3] = (arr_comb * 255).astype(np.uint8)
    canvas = Image.fromarray(sh_rgba, "RGBA")

    # 3. Tile Surface (Premium Dark Gradient: #1C1C24 -> #101014)
    gradient = np.zeros((canvas_size, canvas_size, 4), dtype=np.uint8)
    for row in range(canvas_size):
        t = row / canvas_size
        r = int(28 * (1 - t) + 14 * t)
        g = int(28 * (1 - t) + 14 * t)
        b = int(36 * (1 - t) + 18 * t)
        gradient[row, :, 0] = r
        gradient[row, :, 1] = g
        gradient[row, :, 2] = b
        gradient[row, :, 3] = 255
    grad_img = Image.fromarray(gradient, "RGBA")

    # 4. Extract Logo and apply alpha matte
    box_rad = 2500
    crop_logo = src_logo.crop((3125 - box_rad, 3125 - box_rad, 3125 + box_rad, 3125 + box_rad))
    target_logo_size = int(TILE_SIZE * 0.70)
    resized_logo = crop_logo.resize((target_logo_size, target_logo_size), Image.Resampling.LANCZOS)

    l_arr = np.array(resized_logo, dtype=np.float32)
    r_chan = l_arr[:, :, 0]
    alpha_chan = np.clip((r_chan - 2) / 180.0 * 255.0, 0, 255).astype(np.uint8)

    clean_logo_arr = np.zeros_like(l_arr, dtype=np.uint8)
    clean_logo_arr[:, :, :3] = l_arr[:, :, :3].astype(np.uint8)
    clean_logo_arr[:, :, 3] = alpha_chan
    clean_logo = Image.fromarray(clean_logo_arr, "RGBA")

    # Subtle neon crimson ambient glow behind emblem
    glow_mask = clean_logo.split()[3].filter(ImageFilter.GaussianBlur(radius=int(target_logo_size * 0.03)))
    glow_rgba = np.zeros((target_logo_size, target_logo_size, 4), dtype=np.uint8)
    glow_arr = np.array(glow_mask, dtype=np.float32) / 255.0 * 0.35
    glow_rgba[:, :, 0] = 220
    glow_rgba[:, :, 1] = 60
    glow_rgba[:, :, 2] = 70
    glow_rgba[:, :, 3] = (glow_arr * 255).astype(np.uint8)
    glow_img = Image.fromarray(glow_rgba, "RGBA")

    lx = (canvas_size - target_logo_size) // 2
    ly = (canvas_size - target_logo_size) // 2 + OFFSET_Y
    grad_img.paste(glow_img, (lx, ly), glow_img)
    grad_img.paste(clean_logo, (lx, ly), clean_logo)

    # 5. Subtle Fluent rim light
    border_ss = Image.new("RGBA", (C_SS, C_SS), (0, 0, 0, 0))
    d_b = ImageDraw.Draw(border_ss)
    d_b.rounded_rectangle([x0, y0, x1, y1], radius=R_SS, outline=(70, 70, 95, 160), width=3 * SS)
    border_img = border_ss.resize((canvas_size, canvas_size), Image.Resampling.LANCZOS)
    grad_img.alpha_composite(border_img)

    # Apply squircle mask to tile surface
    grad_img.putalpha(tile_mask)
    canvas.alpha_composite(grad_img)

    return canvas


def build_icons():
    # The checked-in PNG is the canonical artwork; keep its styling when rebuilding the ICO.
    if OUTPUT_PNG.exists():
        master = Image.open(OUTPUT_PNG).convert("RGBA")
        master.save(OUTPUT_ICO, format="ICO", sizes=TARGET_SIZES)
        print(f"[OK] Rebuilt ICO from {OUTPUT_PNG}")
        return

    master = generate_squircle_master(SOURCE_IMAGE, canvas_size=1024)

    # Save 256x256 PNG
    png_256 = master.resize((256, 256), Image.Resampling.LANCZOS)
    png_256.save(OUTPUT_PNG, "PNG")
    print(f"[OK] Saved high-res PNG to: {OUTPUT_PNG}")

    # Generate multi-layer ICO with all 7 sizes
    master.save(OUTPUT_ICO, format="ICO", sizes=TARGET_SIZES)
    print(f"[OK] Saved multi-layer ICO ({len(TARGET_SIZES)} layers: {TARGET_SIZES}) to: {OUTPUT_ICO}")


if __name__ == "__main__":
    build_icons()
