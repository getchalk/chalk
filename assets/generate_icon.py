"""
assets/generate_icon.py - Literal Chalk on Slate Brand Identity Compiler.
Renders an authentic, architectural chalk stick on chalkboard slate:
- Deep obsidian chalkboard slate bed (#07080B) with subtle border (rgba(255,255,255,0.12)).
- An angled 45° cylindrical chalk stick with chamfered writing tip and matte gradation.
- A tactile chalk stroke line across the slate bed.
Generates:
- assets/app.png (512x512 master brand asset)
- assets/app.ico (16, 24, 32, 48, 64, 128, 256 mipmaps)
- assets/app.icns (macOS Retina bundle icon)
- web/assets/logo.png (512x512 web asset)
"""

import os
import math
import shutil
from PIL import Image, ImageDraw, ImageFilter


def draw_literal_chalk(draw: ImageDraw.ImageDraw, cx: float, cy: float, scale: float = 1.0):
    """
    Renders the literal chalk stick and chalk stroke line on slate.
    Coordinates are scaled relative to (cx, cy).
    """
    # 1. Tactile Chalk Dust Stroke beneath the stick
    # Horizontal stroke from x_start to x_end
    stroke_y = cy + (120.0 * scale)
    x_start = cx - (110.0 * scale)
    x_end = cx + (140.0 * scale)
    stroke_w = max(2, int(14.0 * scale))

    # Multiple passes for chalk texture and dust feathering
    draw.line([(x_start, stroke_y), (x_end, stroke_y)], fill=(248, 250, 252, 235), width=stroke_w)
    draw.line([(x_start + 12 * scale, stroke_y + 10 * scale), (x_end - 30 * scale, stroke_y + 10 * scale)],
              fill=(226, 232, 240, 100), width=max(1, int(4.0 * scale)))

    # 2. Geometry of 45-degree Angled Chalk Cylinder
    # Center of chalk stick
    stick_angle = 45.0  # degrees
    rad = math.radians(stick_angle)
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)

    def to_world(lx, ly):
        """Converts local coordinate (lx along axis, ly perp) to world (wx, wy)."""
        wx = cx + (lx * cos_a - ly * sin_a)
        wy = cy + (lx * sin_a + ly * cos_a)
        return (wx, wy)

    half_w = 26.0 * scale
    half_len = 110.0 * scale
    tip_len = 45.0 * scale

    # 3. Drop Shadow under chalk stick
    shadow_offset_x = -8.0 * scale
    shadow_offset_y = 14.0 * scale
    shadow_body = [
        (cx + shadow_offset_x + (-half_len * cos_a - (-half_w) * sin_a), cy + shadow_offset_y + (-half_len * sin_a + (-half_w) * cos_a)),
        (cx + shadow_offset_x + (half_len * cos_a - (-half_w) * sin_a), cy + shadow_offset_y + (half_len * sin_a + (-half_w) * cos_a)),
        (cx + shadow_offset_x + ((half_len + tip_len) * cos_a), cy + shadow_offset_y + ((half_len + tip_len) * sin_a)),
        (cx + shadow_offset_x + (half_len * cos_a - half_w * sin_a), cy + shadow_offset_y + (half_len * sin_a + half_w * cos_a)),
        (cx + shadow_offset_x + (-half_len * cos_a - half_w * sin_a), cy + shadow_offset_y + (-half_len * sin_a + half_w * cos_a)),
    ]
    draw.polygon(shadow_body, fill=(3, 4, 6, 180))

    # 4. Chalk Shaft - Cylindrical Gradation Panels
    # We draw slices along the width to simulate cylindrical shading
    num_bands = 8
    for i in range(num_bands):
        t1 = -1.0 + (2.0 * i / num_bands)
        t2 = -1.0 + (2.0 * (i + 1) / num_bands)
        y1 = t1 * half_w
        y2 = t2 * half_w

        # Shading: highlight on upper flank, shadow on lower flank
        shade = int(248 - (i * 9))
        shade = max(195, min(255, shade))
        band_col = (shade, shade + 2, shade + 5, 255)

        band_pts = [
            to_world(-half_len, y1),
            to_world(half_len, y1),
            to_world(half_len, y2),
            to_world(-half_len, y2),
        ]
        draw.polygon(band_pts, fill=band_col)

    # 5. Top Back End-Cap Ellipse (Base of chalk stick)
    back_center = to_world(-half_len, 0)
    rx = half_w
    ry = half_w * 0.5
    # Render back cap polygon approximation
    cap_pts = []
    for deg in range(0, 360, 15):
        rad_cap = math.radians(deg)
        lx = -half_len + ry * math.cos(rad_cap)
        ly = rx * math.sin(rad_cap)
        cap_pts.append(to_world(lx, ly))
    draw.polygon(cap_pts, fill=(203, 213, 225, 255), outline=(148, 163, 184, 255))

    # 6. Chamfered Chisel Writing Tip
    # Left bevel face (shaded)
    left_bevel = [
        to_world(half_len, -half_w),
        to_world(half_len + tip_len, 0),
        to_world(half_len, 0),
    ]
    draw.polygon(left_bevel, fill=(226, 232, 240, 255))

    # Right chisel writing face (bright chalk plane)
    right_bevel = [
        to_world(half_len, 0),
        to_world(half_len + tip_len, 0),
        to_world(half_len, half_w),
    ]
    draw.polygon(right_bevel, fill=(255, 255, 255, 255))

    # 7. Razor-Sharp Specular Highlight Ridge
    ridge_p1 = to_world(-half_len + (4 * scale), -half_w + (2 * scale))
    ridge_p2 = to_world(half_len, -half_w + (2 * scale))
    draw.line([ridge_p1, ridge_p2], fill=(255, 255, 255, 255), width=max(1, int(3.0 * scale)))

    # Tip chisel vertex highlight
    apex = to_world(half_len + tip_len, 0)
    draw.ellipse([apex[0] - 2 * scale, apex[1] - 2 * scale, apex[0] + 2 * scale, apex[1] + 2 * scale],
                 fill=(255, 255, 255, 255))


def create_chalk_icon(output_dir: str = None):
    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(__file__))

    os.makedirs(output_dir, exist_ok=True)
    master_size = 2048  # 4x Super-Sampling for 512x512 Lanczos downsampling

    master = Image.new("RGBA", (master_size, master_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(master)

    # Deep Obsidian Slate Squircle
    margin = 112
    squircle_rect = [margin, margin, master_size - margin, master_size - margin]
    radius = 448

    # Slate Bed Fill (#07080B)
    draw.rounded_rectangle(
        squircle_rect,
        radius=radius,
        fill=(7, 8, 11, 255),
    )

    # Hairline Slate Border
    draw.rounded_rectangle(
        squircle_rect,
        radius=radius,
        outline=(255, 255, 255, 28),
        width=8,
    )

    # Inner Subtle Bevel Border
    inner_m = margin + 12
    draw.rounded_rectangle(
        [inner_m, inner_m, master_size - inner_m, master_size - inner_m],
        radius=radius - 12,
        outline=(255, 255, 255, 12),
        width=4,
    )

    # Render Literal Chalk Stick and Chalk Stroke at scale 2.0 (for 2048 canvas)
    cx, cy = master_size / 2.0, master_size / 2.0 - 20.0
    draw_literal_chalk(draw, cx, cy, scale=2.1)

    # Downsample to 512x512 via Lanczos
    png_512 = master.resize((512, 512), resample=Image.Resampling.LANCZOS)
    png_path = os.path.join(output_dir, "app.png")
    png_512.save(png_path, "PNG", optimize=True)

    # Copy to web/assets/logo.png
    web_assets_dir = os.path.join(os.path.dirname(output_dir), "web", "assets")
    os.makedirs(web_assets_dir, exist_ok=True)
    web_logo_path = os.path.join(web_assets_dir, "logo.png")
    png_512.save(web_logo_path, "PNG", optimize=True)

    # Multi-resolution ICO
    ico_path = os.path.join(output_dir, "app.ico")
    icon_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    master.save(ico_path, format="ICO", sizes=icon_sizes)

    # macOS Retina ICNS Bundle
    icns_path = os.path.join(output_dir, "app.icns")
    try:
        png_512.save(icns_path, format="ICNS")
    except Exception as e:
        print(f"ICNS export note: {e}")

    print(f"Literal Chalk on Slate icon compiled successfully:")
    print(f"  - {png_path} (512x512 master)")
    print(f"  - {web_logo_path} (512x512 web)")
    print(f"  - {ico_path} (Multi-res ICO)")
    print(f"  - {icns_path} (macOS ICNS)")
    return ico_path, png_path, icns_path


def render_tray_icon_base(size: int = 24, status_color: str = "green") -> Image.Image:
    """
    Renders literal chalk mark on slate for the OS menu bar at 16x16 / 24x24.
    Highly legible angled chalk stick with crisp stroke and status indicator pip.
    """
    scale = 4
    canvas_size = size * scale
    img = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Base squircle
    pad = 2 * scale
    draw.rounded_rectangle(
        [pad, pad, canvas_size - pad, canvas_size - pad],
        radius=max(3 * scale, canvas_size // 4),
        fill=(7, 8, 11, 255),
        outline=(255, 255, 255, 36),
        width=max(1, scale),
    )

    # Draw scaled chalk stick & stroke
    cx, cy = canvas_size / 2.0 - (1.5 * scale), canvas_size / 2.0 + (1.0 * scale)
    emblem_scale = (canvas_size / 512.0) * 0.82
    draw_literal_chalk(draw, cx, cy, scale=emblem_scale)

    # Status pip in top-right
    palette = {
        "green": ((34, 197, 94, 255), (134, 239, 172, 255)),
        "yellow": ((245, 158, 11, 255), (253, 224, 71, 255)),
        "blue": ((59, 130, 246, 255), (147, 197, 253, 255)),
    }
    fill_col, glow_col = palette.get(status_color.lower(), palette["green"])

    dot_cx = canvas_size - 4.5 * scale
    dot_cy = 4.5 * scale
    dot_r = max(2 * scale, canvas_size // 9)

    draw.ellipse([dot_cx - dot_r - scale, dot_cy - dot_r - scale, dot_cx + dot_r + scale, dot_cy + dot_r + scale], fill=(7, 8, 11, 255))
    draw.ellipse([dot_cx - dot_r, dot_cy - dot_r, dot_cx + dot_r, dot_cy + dot_r], fill=fill_col)
    hl_r = max(1, dot_r // 2)
    draw.ellipse([dot_cx - hl_r + 1, dot_cy - hl_r + 1, dot_cx + 1, dot_cy + 1], fill=glow_col)

    return img.resize((size, size), resample=Image.Resampling.LANCZOS)


if __name__ == "__main__":
    create_chalk_icon()
