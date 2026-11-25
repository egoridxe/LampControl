"""Generate crisp minimalist Google-style lamp icon (.ico + .png)."""

from __future__ import annotations

from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def build_icon() -> None:
    out_dir = Path(__file__).resolve().parent / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)

    size = 1024
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Clean Google-style white rounded squircle tile with subtle shadow/border
    pad = 64
    draw.rounded_rectangle(
        [pad, pad, size - pad, size - pad],
        radius=220,
        fill=(255, 255, 255, 255),
        outline=(224, 227, 235, 255),
        width=12,
    )

    # Soft colorful Google ambient halo behind the minimalist bulb
    glow_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow_layer)
    # 4 subtle Google-hue radiant orbs forming a soft prism glow
    gdraw.ellipse([260, 200, 620, 560], fill=(66, 133, 244, 95))   # Google Blue
    gdraw.ellipse([410, 210, 770, 570], fill=(251, 188, 4, 95))   # Google Yellow
    gdraw.ellipse([330, 310, 690, 670], fill=(52, 168, 83, 80))   # Google Green
    gdraw.ellipse([290, 260, 610, 580], fill=(234, 67, 53, 65))   # Google Red
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=72))

    # Mask glow inside squircle
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([pad, pad, size - pad, size - pad], radius=220, fill=255)
    img.paste(glow_layer, (0, 0), mask)

    # Draw crisp gradient bulb dome using numpy
    yy, xx = np.mgrid[0:size, 0:size]
    cx, cy = size * 0.5, size * 0.43
    bulb_r = 215.0
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)

    # Smooth Google 4-color sweep inside the bulb circle
    ang = (np.degrees(np.arctan2(yy - cy, xx - cx)) + 360.0) % 360.0
    # Blend smoothly across Google Blue -> Green -> Yellow -> Red -> Blue
    t = ang / 360.0
    stops_pos = np.array([0.0, 0.25, 0.50, 0.75, 1.0])
    stops_r = np.array([234, 251, 52, 66, 234], dtype=np.float32)
    stops_g = np.array([67, 188, 168, 133, 67], dtype=np.float32)
    stops_b = np.array([53, 4, 83, 244, 53], dtype=np.float32)

    cr = np.interp(t, stops_pos, stops_r)
    cg = np.interp(t, stops_pos, stops_g)
    cb = np.interp(t, stops_pos, stops_b)

    # Bright luminous core near center-top
    core = np.clip(1.0 - (dist / (bulb_r * 1.05)), 0.0, 1.0) ** 1.5
    cr = cr * (1.0 - 0.55 * core) + 255.0 * (0.55 * core)
    cg = cg * (1.0 - 0.55 * core) + 255.0 * (0.55 * core)
    cb = cb * (1.0 - 0.55 * core) + 255.0 * (0.55 * core)

    # Anti-aliased circle alpha
    alpha = np.clip((bulb_r - dist) * 0.65 + 0.5, 0.0, 1.0) * 255.0
    bulb_rgba = np.stack([cr, cg, cb, alpha], axis=-1).astype(np.uint8)
    bulb_img = Image.fromarray(bulb_rgba, mode="RGBA")
    img = Image.alpha_composite(img, bulb_img)

    # Draw minimalist white inner filament / gleam + clean Material bulb neck & base
    draw = ImageDraw.Draw(img)
    # Soft white center highlight ring
    draw.ellipse([cx - 82, cy - 82, cx + 82, cy + 82], fill=(255, 255, 255, 145))
    draw.ellipse([cx - 46, cy - 46, cx + 46, cy + 46], fill=(255, 255, 255, 235))

    # Minimalist bulb neck & screw base in Google Ink / Slate
    neck_top = int(cy + bulb_r - 36)
    draw.rounded_rectangle(
        [int(cx - 96), neck_top, int(cx + 96), neck_top + 74],
        radius=28,
        fill=(60, 64, 67, 255),
    )
    draw.rounded_rectangle(
        [int(cx - 76), neck_top + 90, int(cx + 76), neck_top + 138],
        radius=24,
        fill=(95, 99, 104, 255),
    )
    draw.rounded_rectangle(
        [int(cx - 44), neck_top + 152, int(cx + 44), neck_top + 186],
        radius=17,
        fill=(128, 134, 139, 255),
    )

    # Save PNG for UI logo and preview
    img.resize((256, 256), Image.Resampling.LANCZOS).save(out_dir / "lamp_logo.png")
    # Save multi-resolution Windows .ico
    icon_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)]
    img.save(out_dir / "lamp.ico", format="ICO", sizes=icon_sizes)
    print(f"Generated {out_dir / 'lamp.ico'} and {out_dir / 'lamp_logo.png'}")


if __name__ == "__main__":
    build_icon()
