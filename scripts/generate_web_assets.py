"""
scripts/generate_web_assets.py - Generates editorial dark titanium WebP images for Chalk Web Portal.
Creates:
1. web/assets/img/obsidian_preview.webp (Obsidian Step 3 Integration Preview)
2. web/assets/img/usecase_lecture.webp (University Lectures & Seminars)
3. web/assets/img/usecase_architecture.webp (Architecture Walkthroughs & ADRs)
4. web/assets/img/usecase_boardroom.webp (Executive Strategy & Board Meetings)
5. web/assets/img/usecase_webinar.webp (Webinars & Virtual Conferences)
6. web/assets/img/hero_desk_atmosphere.webp (Subtle Studio / Desk Atmosphere Accent)
"""

import os
from PIL import Image, ImageDraw, ImageFont

ASSETS_IMG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "assets", "img")
os.makedirs(ASSETS_IMG_DIR, exist_ok=True)


def get_font(size=14):
    try:
        return ImageFont.truetype("/System/Library/Fonts/SFProText-Regular.otf", size)
    except Exception:
        try:
            return ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size)
        except Exception:
            return ImageFont.load_default()


def get_bold_font(size=14):
    try:
        return ImageFont.truetype("/System/Library/Fonts/SFProText-Bold.otf", size)
    except Exception:
        try:
            return ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size)
        except Exception:
            return ImageFont.load_default()


def create_obsidian_preview():
    w, h = 800, 480
    img = Image.new("RGBA", (w, h), (18, 19, 23, 255))  # #121317
    draw = ImageDraw.Draw(img)

    # Window Card
    draw.rounded_rectangle([20, 20, w - 20, h - 20], radius=14, fill=(26, 28, 35, 255), outline=(255, 255, 255, 24), width=1)

    # Top Window Bar
    draw.rectangle([20, 20, w - 20, 60], fill=(21, 22, 27, 255))
    draw.line([(20, 60), (w - 20, 60)], fill=(255, 255, 255, 18), width=1)

    # Window dots
    draw.ellipse([36, 36, 46, 46], fill=(255, 255, 255, 40))
    draw.ellipse([54, 36, 64, 46], fill=(255, 255, 255, 40))
    draw.ellipse([72, 36, 82, 46], fill=(255, 255, 255, 40))

    # Tab title
    f_title = get_bold_font(12)
    f_body = get_font(13)
    f_small = get_font(11)
    f_mono = get_font(12)

    draw.text((100, 34), "obsidian://open/vault/Chalk/finance_capm_derivation.md", fill=(148, 163, 184, 255), font=f_small)

    # Note Content
    draw.text((45, 80), "# Financial Markets & Capital Asset Pricing Model", fill=(248, 250, 252, 255), font=get_bold_font(18))
    draw.text((45, 115), "Tags: #academic #finance #capm #lecture-notes  •  Synthesized by Chalk", fill=(100, 116, 139, 255), font=f_small)

    # Callout Box (Theorem)
    draw.rounded_rectangle([45, 140, w - 45, 240], radius=8, fill=(21, 22, 27, 255), outline=(255, 255, 255, 20), width=1)
    draw.rectangle([45, 140, 49, 240], fill=(96, 165, 250, 255))  # Blue accent
    draw.text((60, 150), "THEOREM: Security Market Line & Beta Sensitivity", fill=(147, 197, 253, 255), font=get_bold_font(12))

    # Formula display inside callout
    draw.text((70, 180), "E(R_i) = R_f + β_i [ E(R_m) - R_f ]", fill=(248, 250, 252, 255), font=get_bold_font(15))
    draw.text((70, 210), "where β_i = Cov(R_i, R_m) / Var(R_m)  •  Audio Anchor: [00:14:15]  ∎", fill=(148, 163, 184, 255), font=f_mono)

    # Bullet Points
    bullets = [
        "• Systematic risk cannot be diversified away; only covariance with market risk earns premium.",
        "• Arbitrage Pricing Theory (APT) generalizes single-factor CAPM into macroeconomic multifactor exposures.",
        "• Exam Alert: Instructor emphasized derivation of beta from first principles of quadratic utility.",
    ]
    y = 265
    for b in bullets:
        draw.text((45, y), b, fill=(203, 213, 225, 255), font=f_body)
        y += 28

    # Bottom status bar
    draw.line([(20, h - 55), (w - 20, h - 55)], fill=(255, 255, 255, 18), width=1)
    draw.text((45, h - 42), "✓ Verified KaTeX Math Syntax  •  Local Vault Linked  •  100% In-Place BYOK", fill=(100, 116, 139, 255), font=f_small)

    out_path = os.path.join(ASSETS_IMG_DIR, "obsidian_preview.webp")
    img.save(out_path, "WEBP", quality=90)
    print(f"Generated: {out_path}")


def create_usecase_card(filename, title, tag, accent_color=(96, 165, 250)):
    w, h = 640, 360
    img = Image.new("RGBA", (w, h), (18, 19, 23, 255))  # #121317
    draw = ImageDraw.Draw(img)

    # Outer border
    draw.rounded_rectangle([0, 0, w - 1, h - 1], radius=12, fill=(26, 28, 35, 255), outline=(255, 255, 255, 20), width=1)

    # Top header bar
    draw.rectangle([0, 0, w, 44], fill=(21, 22, 27, 255))
    draw.line([(0, 44), (w, 44)], fill=(255, 255, 255, 15), width=1)

    f_bold = get_bold_font(13)
    f_tag = get_bold_font(10)
    f_body = get_font(12)
    f_small = get_font(11)
    f_mono = get_font(11)

    draw.text((18, 14), tag, fill=accent_color + (255,), font=f_tag)
    draw.text((w - 180, 14), "CHALK DESKTOP ENGINE", fill=(100, 116, 139, 255), font=f_tag)

    # Graphic schematic based on use case
    if "lecture" in filename:
        # Math & Blackboard schematic
        draw.rounded_rectangle([25, 60, w - 25, 290], radius=8, fill=(21, 22, 27, 255), outline=(255, 255, 255, 15), width=1)
        # Coordinate axes
        draw.line([(60, 250), (320, 250)], fill=(148, 163, 184, 180), width=2)
        draw.line([(60, 250), (60, 90)], fill=(148, 163, 184, 180), width=2)
        # SML curve
        draw.line([(60, 210), (300, 110)], fill=(248, 250, 252, 220), width=2)
        draw.text((70, 100), "SML: E(R) = R_f + β(R_m - R_f)", fill=(248, 250, 252, 255), font=f_mono)
        draw.text((310, 245), "Beta", fill=(148, 163, 184, 255), font=f_mono)
        draw.text((45, 75), "Return", fill=(148, 163, 184, 255), font=f_mono)

        # Right side notes
        draw.text((360, 80), "• Whiteboard derivations", fill=(203, 213, 225, 255), font=f_body)
        draw.text((360, 110), "• Synchronized slide transitions", fill=(203, 213, 225, 255), font=f_body)
        draw.text((360, 140), "• KaTeX formula synthesis", fill=(203, 213, 225, 255), font=f_body)
        draw.text((360, 170), "• Auto-break detection >180s", fill=(203, 213, 225, 255), font=f_body)
        draw.text((360, 210), "Active Slide 14/48 • 16kHz Stereo", fill=(100, 116, 139, 255), font=f_mono)

    elif "architecture" in filename:
        # Architectural System DAG
        draw.rounded_rectangle([25, 60, w - 25, 290], radius=8, fill=(21, 22, 27, 255), outline=(255, 255, 255, 15), width=1)
        # Boxes
        draw.rounded_rectangle([50, 80, 170, 130], radius=6, fill=(34, 37, 47, 255), outline=(255, 255, 255, 30), width=1)
        draw.text((65, 95), "Ingress Edge", fill=(248, 250, 252, 255), font=f_bold)
        draw.text((65, 110), "gRPC / HTTP/2", fill=(148, 163, 184, 255), font=f_mono)

        draw.rounded_rectangle([240, 80, 380, 130], radius=6, fill=(34, 37, 47, 255), outline=(255, 255, 255, 30), width=1)
        draw.text((255, 95), "Worker Swarm", fill=(248, 250, 252, 255), font=f_bold)
        draw.text((255, 110), "Async Chunker", fill=(148, 163, 184, 255), font=f_mono)

        draw.rounded_rectangle([450, 80, 590, 130], radius=6, fill=(34, 37, 47, 255), outline=(255, 255, 255, 30), width=1)
        draw.text((465, 95), "Disk Journal", fill=(248, 250, 252, 255), font=f_bold)
        draw.text((465, 110), "Atomic Manifest", fill=(148, 163, 184, 255), font=f_mono)

        # Connector lines
        draw.line([(170, 105), (240, 105)], fill=(255, 255, 255, 80), width=2)
        draw.line([(380, 105), (450, 105)], fill=(255, 255, 255, 80), width=2)

        # ADR Decision Record Card
        draw.rounded_rectangle([50, 160, 590, 260], radius=6, fill=(26, 28, 35, 255), outline=(255, 255, 255, 25), width=1)
        draw.text((65, 175), "ADR-004: Zero-Permission WindowServer Hotkeys", fill=(147, 197, 253, 255), font=f_bold)
        draw.text((65, 198), "Decision: Migrate from pynput to Carbon RegisterEventHotKey to eliminate macOS warning.", fill=(203, 213, 225, 255), font=f_body)
        draw.text((65, 222), "Status: Accepted & Validated  •  Payload Limit: <20MB AAC  •  Disk-First Queue", fill=(100, 116, 139, 255), font=f_mono)

    elif "boardroom" in filename:
        # Executive Strategy & Board Call
        draw.rounded_rectangle([25, 60, w - 25, 290], radius=8, fill=(21, 22, 27, 255), outline=(255, 255, 255, 15), width=1)
        # KPI Cards
        draw.rounded_rectangle([50, 80, 200, 150], radius=6, fill=(34, 37, 47, 255), outline=(255, 255, 255, 30), width=1)
        draw.text((65, 92), "ARR Growth", fill=(148, 163, 184, 255), font=f_small)
        draw.text((65, 112), "+142% YoY", fill=(248, 250, 252, 255), font=get_bold_font(18))

        draw.rounded_rectangle([220, 80, 370, 150], radius=6, fill=(34, 37, 47, 255), outline=(255, 255, 255, 30), width=1)
        draw.text((235, 92), "Net Retention", fill=(148, 163, 184, 255), font=f_small)
        draw.text((235, 112), "128.4%", fill=(248, 250, 252, 255), font=get_bold_font(18))

        draw.rounded_rectangle([390, 80, 590, 150], radius=6, fill=(34, 37, 47, 255), outline=(255, 255, 255, 30), width=1)
        draw.text((405, 92), "Cash Runway", fill=(148, 163, 184, 255), font=f_small)
        draw.text((405, 112), "34 Months", fill=(248, 250, 252, 255), font=get_bold_font(18))

        # Action Items Box
        draw.text((50, 175), "EXECUTIVE SUMMARY & ACTION ITEMS:", fill=(248, 250, 252, 255), font=f_bold)
        draw.text((50, 202), "1. Q3 Expansion: Product team commits to EU sovereign cloud compliance by Nov 15.", fill=(203, 213, 225, 255), font=f_body)
        draw.text((50, 228), "2. Capital Allocation: Reallocate 18% reserve budget to low-latency edge deployment.", fill=(203, 213, 225, 255), font=f_body)
        draw.text((50, 254), "All board metrics captured verbatim from presenter deck • Zero note-taking lag.", fill=(100, 116, 139, 255), font=f_mono)

    elif "webinar" in filename:
        # Webinar / Keynote Livestream Split View
        draw.rounded_rectangle([25, 60, w - 25, 290], radius=8, fill=(21, 22, 27, 255), outline=(255, 255, 255, 15), width=1)
        # Left video stream box
        draw.rounded_rectangle([45, 80, 280, 220], radius=6, fill=(15, 16, 20, 255), outline=(255, 255, 255, 25), width=1)
        draw.text((60, 95), "Keynote Stream (Zoom/Teams)", fill=(148, 163, 184, 255), font=f_small)
        # Audio wave lines
        for i in range(12):
            x = 65 + i * 16
            h_bar = 8 + (i % 5) * 8
            draw.line([(x, 150 - h_bar), (x, 150 + h_bar)], fill=(96, 165, 250, 200), width=3)
        draw.text((60, 190), "Loopback Audio: Active (32 kbps AAC)", fill=(100, 116, 139, 255), font=f_mono)

        # Right notes stream
        draw.text((310, 85), "LIVE NOTIZ-EXTRAKTION:", fill=(248, 250, 252, 255), font=f_bold)
        draw.text((310, 112), "• Speaker: Dr. Elena Vance (MIT AI Lab)", fill=(203, 213, 225, 255), font=f_body)
        draw.text((310, 138), "• Topic: Multimodal Context Chaining", fill=(203, 213, 225, 255), font=f_body)
        draw.text((310, 164), "• Live Q&A [00:42:10]: Latency vs compute", fill=(203, 213, 225, 255), font=f_body)
        draw.text((310, 190), "• Automatic slide OCR attached to chunk", fill=(203, 213, 225, 255), font=f_body)
        draw.text((310, 230), "Continuous 7-Hour Session Resilience • Auto Disk Journal", fill=(100, 116, 139, 255), font=f_mono)

    out_path = os.path.join(ASSETS_IMG_DIR, filename)
    img.save(out_path, "WEBP", quality=90)
    print(f"Generated: {out_path}")


def create_hero_atmosphere():
    w, h = 960, 420
    img = Image.new("RGBA", (w, h), (18, 19, 23, 255))  # #121317
    draw = ImageDraw.Draw(img)

    # Gradient subtle desk lighting
    draw.rounded_rectangle([10, 10, w - 10, h - 10], radius=16, fill=(26, 28, 35, 255), outline=(255, 255, 255, 24), width=1)

    # Ambient studio card
    draw.rounded_rectangle([30, 30, w - 30, h - 30], radius=12, fill=(21, 22, 27, 255), outline=(255, 255, 255, 14), width=1)

    f_bold = get_bold_font(16)
    f_body = get_font(13)
    f_mono = get_font(12)

    # Visual minimalist laptop representation
    draw.rounded_rectangle([60, 60, 480, 320], radius=10, fill=(18, 19, 23, 255), outline=(255, 255, 255, 30), width=1)
    # Menu bar
    draw.rectangle([60, 60, 480, 86], fill=(26, 28, 35, 255))
    draw.text((75, 68), "Chalk  01:14:20  •  Recording  •  Cmd+Shift+Space", fill=(248, 250, 252, 255), font=f_mono)

    # Laptop screen interior
    draw.text((80, 110), "# Real-Time Multimodal Lecture Stream", fill=(248, 250, 252, 255), font=f_bold)
    draw.text((80, 140), "Left Channel (Physical Mic)  |  Right Channel (Loopback Audio)", fill=(100, 116, 139, 255), font=f_mono)
    draw.rounded_rectangle([80, 165, 460, 245], radius=6, fill=(26, 28, 35, 255), outline=(255, 255, 255, 18), width=1)
    draw.text((95, 180), "E(R_i) = R_f + β_i [ E(R_m) - R_f ]", fill=(248, 250, 252, 255), font=get_bold_font(14))
    draw.text((95, 210), "Structured Obsidian Note Synced (30s Disk Segments)  ∎", fill=(148, 163, 184, 255), font=f_mono)

    # Right side: Studio Atmosphere Highlights
    draw.text((520, 80), "CALM COGNITIVE PRESENCE", fill=(148, 163, 184, 255), font=get_bold_font(11))
    draw.text((520, 105), "Zero frantic typing. Total recall.", fill=(248, 250, 252, 255), font=get_bold_font(20))
    draw.text((520, 145), "Be fully present in lectures, architecture reviews, and high-stakes strategy sessions while Chalk handles the nuance silently in the background.", fill=(148, 163, 184, 255), font=f_body)

    metrics = [
        ("100% Local-First", "OS Encrypted Keyring, Zero Cloud Proxy"),
        ("< 20 MB Audio Payloads", "Native AAC Compression (32 kbps)"),
        ("7-Hour Resilience", "Atomic Disk-Journal & Crash-Recovery"),
    ]
    y = 220
    for label, sub in metrics:
        draw.text((520, y), label, fill=(248, 250, 252, 255), font=get_bold_font(13))
        draw.text((520, y + 18), sub, fill=(100, 116, 139, 255), font=f_mono)
        y += 44

    out_path = os.path.join(ASSETS_IMG_DIR, "hero_desk_atmosphere.webp")
    img.save(out_path, "WEBP", quality=90)
    print(f"Generated: {out_path}")


if __name__ == "__main__":
    create_obsidian_preview()
    create_usecase_card("usecase_lecture.webp", "University Lectures", "ACADEMIC SEMINAR", (96, 165, 250))
    create_usecase_card("usecase_architecture.webp", "Technical Walkthroughs", "SYSTEM ARCHITECTURE", (52, 211, 153))
    create_usecase_card("usecase_boardroom.webp", "Executive Strategy", "STRATEGY & BOARD", (251, 191, 36))
    create_usecase_card("usecase_webinar.webp", "Webinars & Keynotes", "VIRTUAL KEYNOTE", (167, 139, 250))
    create_hero_atmosphere()
    print("All editorial visual assets generated successfully!")
