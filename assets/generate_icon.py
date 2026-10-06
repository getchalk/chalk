"""
assets/generate_icon.py - Monochrome Geometric AI-Lab Brand Identity Compiler.
Renders the high-order 3-fold (120°) rotational calcite crystal lattice emblem (CaCO3)
inspired by OpenAI's rosette, Claude's sunburst, and DeepSeek's Möbius fin.
Palette: Strict monochrome — Chalk white (#F8FAFC) on deep obsidian slate (#07080B).
Generates:
- assets/app.png (512x512 master brand asset)
- assets/app.ico (16, 24, 32, 48, 64, 128, 256 mipmaps)
- assets/app.icns (macOS Retina bundle icon)
- web/assets/logo.png (512x512)
"""

import os
import math
import shutil
from PIL import Image, ImageDraw


def rotate_point(x: float, y: float, angle_deg: float, cx: float, cy: float) -> tuple:
    """Rotates point (x, y) around (cx, cy) by angle_deg degrees."""
    rad = math.radians(angle_deg)
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)
    nx = cos_a * (x - cx) - sin_a * (y - cy) + cx
    ny = sin_a * (x - cx) + cos_a * (y - cy) + cy
    return (nx, ny)


def rotate_polygon(points: list, angle_deg: float, cx: float, cy: float) -> list:
    return [rotate_point(px, py, angle_deg, cx, cy) for (px, py) in points]


def draw_calcite_triskelion(draw: ImageDraw.ImageDraw, cx: float, cy: float, scale: float = 1.0):
    """
    Renders 3-fold rotational calcite crystal lattice with precision facets.
    Pure monochrome tones: #FFFFFF, #E2E8F0, #94A3B8, #475569.
    """
    # Base branch polygon definitions relative to center (0, 0)
    # 1. Primary Highlight Blade (Chalk White)
    blade_poly = [
        (0 * scale, -280 * scale),
        (70 * scale, -156 * scale),
        (0 * scale, -118 * scale),
        (-70 * scale, -156 * scale),
    ]

    # 2. Outer Chamfered Bevel Arm (Calcite Mid-tone)
    bevel_poly = [
        (70 * scale, -156 * scale),
        (180 * scale, 34 * scale),
        (110 * scale, 74 * scale),
        (0 * scale, -118 * scale),
    ]

    # 3. Inner Calcite Cleavage Edge (Shadow Depth)
    cleavage_poly = [
        (0 * scale, -118 * scale),
        (110 * scale, 74 * scale),
        (40 * scale, 114 * scale),
        (-38 * scale, -24 * scale),
    ]

    # 4. Terminal Apex Facet (Specular Chalk)
    apex_poly = [
        (0 * scale, -280 * scale),
        (22 * scale, -315 * scale),
        (52 * scale, -298 * scale),
        (70 * scale, -156 * scale),
    ]

    colors = {
        "apex": (255, 255, 255, 255),       # Specular pure white #FFFFFF
        "blade": (248, 250, 252, 250),      # Chalk white #F8FAFC
        "bevel": (180, 192, 206, 245),      # Light graphite/calcite
        "cleavage": (65, 75, 95, 240),      # Deep obsidian shadow
        "stroke": (20, 24, 32, 255),        # Precision hairline incision
    }

    # Render each facet rotated across 3 rotational symmetry axes: 0°, 120°, 240°
    for angle in (0.0, 120.0, 240.0):
        # Cleavage depth
        c_poly = [(cx + px, cy + py) for (px, py) in cleavage_poly]
        draw.polygon(rotate_polygon(c_poly, angle, cx, cy), fill=colors["cleavage"])

        # Bevel arm
        b_poly = [(cx + px, cy + py) for (px, py) in bevel_poly]
        draw.polygon(rotate_polygon(b_poly, angle, cx, cy), fill=colors["bevel"])

        # Highlight blade
        h_poly = [(cx + px, cy + py) for (px, py) in blade_poly]
        draw.polygon(rotate_polygon(h_poly, angle, cx, cy), fill=colors["blade"])

        # Apex facet
        a_poly = [(cx + px, cy + py) for (px, py) in apex_poly]
        draw.polygon(rotate_polygon(a_poly, angle, cx, cy), fill=colors["apex"])

    # Hairline incision wireframe pass for razor-sharp micro-contrast
    for angle in (0.0, 120.0, 240.0):
        for p in (blade_poly, bevel_poly, apex_poly):
            world_p = [(cx + px, cy + py) for (px, py) in p]
            draw.polygon(rotate_polygon(world_p, angle, cx, cy), outline=colors["stroke"], width=max(1, int(2 * scale)))

    # Central negative crystal aperture (Inverted triangle core)
    core_r = 42 * scale
    core_points = [
        (cx, cy - core_r),
        (cx + core_r * math.cos(math.radians(30)), cy + core_r * math.sin(math.radians(30))),
        (cx - core_r * math.cos(math.radians(30)), cy + core_r * math.sin(math.radians(30))),
    ]
    draw.polygon(core_points, fill=(7, 8, 11, 255), outline=(50, 60, 75, 255), width=max(1, int(2 * scale)))

    # Sub-pixel white centroid point
    pt_r = max(2, int(4 * scale))
    draw.ellipse([cx - pt_r, cy - pt_r, cx + pt_r, cy + pt_r], fill=(248, 250, 252, 230))


def create_chalk_icon(output_dir: str = None):
    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(__file__))

    os.makedirs(output_dir, exist_ok=True)
    master_size = 1024

    # 1. 1024x1024 Master High-Resolution Canvas
    master = Image.new("RGBA", (master_size, master_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(master)

    # 2. Deep Obsidian Matte Squircle (#07080B)
    margin = 56
    squircle_rect = [margin, margin, master_size - margin, master_size - margin]
    radius = 224

    # Outer Squircle fill
    draw.rounded_rectangle(
        squircle_rect,
        radius=radius,
        fill=(7, 8, 11, 255),  # Deep obsidian #07080B
    )

    # Hairline Graphite Border
    draw.rounded_rectangle(
        squircle_rect,
        radius=radius,
        outline=(255, 255, 255, 20),
        width=4,
    )

    # Subtle inner bevel boundary
    inner_m = margin + 4
    draw.rounded_rectangle(
        [inner_m, inner_m, master_size - inner_m, master_size - inner_m],
        radius=radius - 4,
        outline=(255, 255, 255, 8),
        width=2,
    )

    # 3. Draw Rotational Calcite Emblem
    cx, cy = master_size / 2.0, master_size / 2.0 + 8.0
    draw_calcite_triskelion(draw, cx, cy, scale=1.0)

    # 4. Lanczos Downsampled Export
    # 512x512 Master PNG
    png_512 = master.resize((512, 512), resample=Image.Resampling.LANCZOS)
    png_path = os.path.join(output_dir, "app.png")
    png_512.save(png_path, "PNG", optimize=True)

    # Copy to web/assets/logo.png as well
    web_assets_dir = os.path.join(os.path.dirname(output_dir), "web", "assets")
    os.makedirs(web_assets_dir, exist_ok=True)
    web_logo_path = os.path.join(web_assets_dir, "logo.png")
    png_512.save(web_logo_path, "PNG", optimize=True)

    # Multi-resolution Windows ICO (16, 24, 32, 48, 64, 128, 256)
    ico_path = os.path.join(output_dir, "app.ico")
    icon_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    master.save(ico_path, format="ICO", sizes=icon_sizes)

    # macOS Retina ICNS Bundle Icon
    icns_path = os.path.join(output_dir, "app.icns")
    try:
        png_512.save(icns_path, format="ICNS")
    except Exception as e:
        print(f"ICNS export notice: {e}")

    print(f"Monochrome Calcite AI-Lab Emblem compiled:")
    print(f"  - {png_path} (512x512)")
    print(f"  - {web_logo_path} (Web logo)")
    print(f"  - {ico_path} (Multi-res ICO)")
    print(f"  - {icns_path} (macOS ICNS)")
    return ico_path, png_path, icns_path


def render_tray_icon_base(size: int = 24, status_color: str = "green") -> Image.Image:
    """
    Renders the monochrome calcite emblem with status indicator dot for the OS menu bar.
    Supersampled at 4x and downsampled via Lanczos for pixel-perfect sharpness at 16x16 / 24x24.
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
        outline=(255, 255, 255, 30),
        width=max(1, scale),
    )

    # Draw Calcite Emblem in center
    cx, cy = canvas_size / 2.0 - (1.5 * scale), canvas_size / 2.0 + (1.5 * scale)
    emblem_scale = (canvas_size / 1024.0) * 1.35
    draw_calcite_triskelion(draw, cx, cy, scale=emblem_scale)

    # Status dot in top-right
    palette = {
        "green": ((34, 197, 94, 255), (134, 239, 172, 255)),
        "yellow": ((245, 158, 11, 255), (253, 224, 71, 255)),
        "blue": ((59, 130, 246, 255), (147, 197, 253, 255)),
    }
    fill_col, glow_col = palette.get(status_color.lower(), palette["green"])

    dot_cx = canvas_size - 4.5 * scale
    dot_cy = 4.5 * scale
    dot_r = max(2 * scale, canvas_size // 9)

    # Dark halo ring around dot
    draw.ellipse([dot_cx - dot_r - scale, dot_cy - dot_r - scale, dot_cx + dot_r + scale, dot_cy + dot_r + scale], fill=(7, 8, 11, 255))
    draw.ellipse([dot_cx - dot_r, dot_cy - dot_r, dot_cx + dot_r, dot_cy + dot_r], fill=fill_col)
    hl_r = max(1, dot_r // 2)
    draw.ellipse([dot_cx - hl_r + 1, dot_cy - hl_r + 1, dot_cx + 1, dot_cy + 1], fill=glow_col)

    return img.resize((size, size), resample=Image.Resampling.LANCZOS)


if __name__ == "__main__":
    create_chalk_icon()
