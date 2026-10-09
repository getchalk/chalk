"""
src/ui/hud_window.py - Frameless PyQt6 Floating Agent HUD (Alt+Space).
Translucent dark-mode palette, stays on top without stealing focus.
Features:
- User Scratchpad shorthand centerpiece (authoritative outline anchor)
- 1-Click Obsidian & Default Editor integration with local vault scanner
- Interactive Audio-Scrubbing player for 'chalk-audio://' timestamp links
- Quick Actions: Attach Slides, Snip Screen (Alt+S), Rewind 90s, Copy Notes, Obsidian, Editor, Finish (F9)
- Copilot agent query interface
"""

import os
import sys
import time
import subprocess
import logging
import re
import html
from typing import Optional, List, Dict, Any, Tuple, Union
from PIL import Image

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QPoint, QUrl
from PyQt6.QtGui import QFont, QIcon, QColor, QPainter, QBrush, QPen, QPixmap, QDesktopServices, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QTextBrowser,
    QLineEdit,
    QFileDialog,
    QFrame,
    QScrollArea,
    QSplitter,
    QGraphicsDropShadowEffect,
    QSlider,
    QStackedWidget,
    QComboBox,
)

from src.ui.snip_overlay import SnipOverlayWidget
from src.api.tools import read_local_file
from src.companion.bridge import CompanionBridge
from src.companion.server import CompanionDaemon
from src.companion.qr_generator import QRCode
from src.export.pdf_exporter import export_notes_to_pdf
from src.api.synthesis_pipeline import export_flashcards_to_tsv, extract_flashcards_from_markdown
from src.ui.search_dialog import SessionArchiveSearchDialog
from src.ui.i18n import tr, get_ui_language, set_ui_language
from src.security.key_manager import (
    get_api_key,
    set_api_key,
    validate_api_key,
    get_selected_model,
    set_selected_model,
)
from src.engine.config import (
    get_obsidian_vault_path,
    set_obsidian_vault_path,
    resolve_model_preset,
)
from src.ui.settings_dialog import (
    populate_preset_combobox,
    select_preset_in_combobox,
)

logger = logging.getLogger("chalk.ui.hud")



HUD_STYLESHEET_DARK = """
QWidget#hudRoot {
    background-color: rgba(18, 19, 23, 0.98);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 16px;
    color: #F8FAFC;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, sans-serif;
}
QFrame#cardFrame {
    background-color: rgba(26, 28, 35, 0.92);
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 12px;
}
QFrame#dockFrame {
    background-color: rgba(21, 22, 27, 0.95);
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 10px;
}
QLabel {
    color: #E2E8F0;
}
QPushButton {
    background-color: rgba(30, 32, 40, 0.85);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 7px;
    color: #CBD5E1;
    padding: 5px 10px;
    font-size: 11px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: rgba(45, 48, 60, 0.95);
    color: #FFFFFF;
    border-color: rgba(255, 255, 255, 0.25);
}
QPushButton#primaryAction {
    background-color: #F8FAFC;
    color: #07080B;
    font-weight: 600;
    border: 1px solid rgba(255, 255, 255, 0.3);
}
QPushButton#primaryAction:hover {
    background-color: #FFFFFF;
    color: #000000;
}
QPushButton#tabActive {
    background-color: rgba(255, 255, 255, 0.16);
    color: #FFFFFF;
    font-weight: 600;
    border: 1px solid rgba(255, 255, 255, 0.22);
}
QPushButton#tabInactive {
    background-color: transparent;
    color: #94A3B8;
    font-weight: 500;
    border: 1px solid transparent;
}
QPushButton#tabInactive:hover {
    background-color: rgba(255, 255, 255, 0.06);
    color: #F8FAFC;
}
QPushButton#chipBtn {
    background-color: rgba(21, 22, 27, 0.9);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 12px;
    color: #E2E8F0;
    padding: 2px 9px;
    font-size: 10.5px;
    font-weight: 500;
}
QPushButton#chipBtn:hover {
    background-color: rgba(255, 255, 255, 0.12);
    color: #FFFFFF;
    border-color: rgba(255, 255, 255, 0.25);
}
QTextEdit, QTextBrowser, QLineEdit, QComboBox {
    background-color: rgba(21, 22, 27, 0.95);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 8px;
    color: #F8FAFC;
    padding: 6px 10px;
    font-size: 12px;
}
QTextEdit:focus, QTextBrowser:focus, QLineEdit:focus, QComboBox:focus {
    border: 1px solid rgba(255, 255, 255, 0.35);
}
QComboBox QAbstractItemView {
    background-color: #15161B;
    color: #F8FAFC;
    border: 1px solid rgba(255, 255, 255, 0.15);
    selection-background-color: rgba(255, 255, 255, 0.15);
}
QFrame#playerPill {
    background-color: rgba(22, 24, 30, 0.95);
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 12px;
    padding: 3px 8px;
}
QPushButton#pillBtn {
    background-color: rgba(35, 38, 48, 0.9);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 6px;
    color: #F8FAFC;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: 600;
}
QPushButton#pillCloseBtn {
    background: transparent;
    border: none;
    color: #94A3B8;
    font-size: 13px;
    font-weight: 700;
}
"""

HUD_STYLESHEET_LIGHT = """
QWidget#hudRoot {
    background-color: rgba(248, 250, 252, 0.98);
    border: 1px solid rgba(15, 23, 42, 0.15);
    border-radius: 16px;
    color: #0F172A;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, sans-serif;
}
QFrame#cardFrame {
    background-color: #FFFFFF;
    border: 1px solid rgba(15, 23, 42, 0.12);
    border-radius: 12px;
}
QFrame#dockFrame {
    background-color: #F1F5F9;
    border: 1px solid rgba(15, 23, 42, 0.12);
    border-radius: 10px;
}
QLabel {
    color: #334155;
}
QPushButton {
    background-color: #F8FAFC;
    border: 1px solid rgba(15, 23, 42, 0.15);
    border-radius: 7px;
    color: #334155;
    padding: 5px 10px;
    font-size: 11px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #E2E8F0;
    color: #0F172A;
    border-color: rgba(15, 23, 42, 0.25);
}
QPushButton#primaryAction {
    background-color: #0F172A;
    color: #FFFFFF;
    font-weight: 600;
    border: 1px solid #0F172A;
}
QPushButton#primaryAction:hover {
    background-color: #000000;
    color: #FFFFFF;
}
QPushButton#tabActive {
    background-color: #0F172A;
    color: #FFFFFF;
    font-weight: 600;
    border: 1px solid #0F172A;
}
QPushButton#tabInactive {
    background-color: transparent;
    color: #64748B;
    font-weight: 500;
    border: 1px solid transparent;
}
QPushButton#tabInactive:hover {
    background-color: rgba(15, 23, 42, 0.06);
    color: #0F172A;
}
QPushButton#chipBtn {
    background-color: #FFFFFF;
    border: 1px solid rgba(15, 23, 42, 0.15);
    border-radius: 12px;
    color: #334155;
    padding: 2px 9px;
    font-size: 10.5px;
    font-weight: 500;
}
QPushButton#chipBtn:hover {
    background-color: #E2E8F0;
    color: #0F172A;
}
QTextEdit, QTextBrowser, QLineEdit, QComboBox {
    background-color: #FFFFFF;
    border: 1px solid rgba(15, 23, 42, 0.15);
    border-radius: 8px;
    color: #0F172A;
    padding: 6px 10px;
    font-size: 12px;
}
QTextEdit:focus, QTextBrowser:focus, QLineEdit:focus, QComboBox:focus {
    border: 1px solid rgba(15, 23, 42, 0.4);
}
QComboBox QAbstractItemView {
    background-color: #FFFFFF;
    color: #0F172A;
    border: 1px solid rgba(15, 23, 42, 0.15);
    selection-background-color: #E2E8F0;
}
QFrame#playerPill {
    background-color: #FFFFFF;
    border: 1px solid rgba(15, 23, 42, 0.15);
    border-radius: 12px;
    padding: 3px 8px;
}
QPushButton#pillBtn {
    background-color: #F1F5F9;
    border: 1px solid rgba(15, 23, 42, 0.15);
    border-radius: 6px;
    color: #0F172A;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: 600;
}
QPushButton#pillCloseBtn {
    background: transparent;
    border: none;
    color: #64748B;
    font-size: 13px;
    font-weight: 700;
}
"""

HUD_STYLESHEET = HUD_STYLESHEET_DARK


def parse_audio_timestamp(url_or_str: str) -> float:
    """
    Parses 'chalk-audio://01:24:15', 'chalk-audio://24:15', 'chalk-audio://5055',
    or raw timestamp strings into seconds as a float.
    """
    s = str(url_or_str).strip()
    if s.lower().startswith("chalk-audio://"):
        s = s[len("chalk-audio://"):]
    s = s.strip("/")
    if not s:
        return 0.0

    if ":" in s:
        parts = s.split(":")
        try:
            if len(parts) == 3:
                return float(int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2]))
            elif len(parts) == 2:
                return float(int(parts[0]) * 60 + float(parts[1]))
            elif len(parts) == 1:
                return float(parts[0])
        except ValueError:
            return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def format_timestamp(seconds: float) -> str:
    """Formats seconds into HH:MM:SS or MM:SS."""
    total_sec = max(0, int(round(seconds)))
    h = total_sec // 3600
    m = (total_sec % 3600) // 60
    s = total_sec % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def find_local_obsidian_vault() -> Optional[str]:
    """
    Scans system and Obsidian app registry for local Obsidian vaults.
    """
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, "Library", "Application Support", "obsidian", "obsidian.json"),
        os.path.join(home, "AppData", "Roaming", "obsidian", "obsidian.json"),
        os.path.join(home, ".config", "obsidian", "obsidian.json"),
    ]
    for cfg in candidates:
        if os.path.exists(cfg):
            try:
                import json
                with open(cfg, "r", encoding="utf-8") as f:
                    data = json.load(f)
                vaults = data.get("vaults", {})
                for v in vaults.values():
                    p = v.get("path")
                    if p and os.path.exists(p):
                        return p
            except Exception:
                pass

    search_dirs = [
        os.path.join(home, "Documents"),
        os.path.join(home, "Obsidian"),
        os.path.join(home, "Notes"),
        home,
    ]
    for base in search_dirs:
        if not os.path.exists(base):
            continue
        try:
            for entry in os.scandir(base):
                if entry.is_dir() and os.path.exists(os.path.join(entry.path, ".obsidian")):
                    return entry.path
        except Exception:
            pass
    return None


def _extract_braced_arg(s: str, idx: int):
    """Extracts balanced {content} starting at idx."""
    if idx >= len(s) or s[idx] != "{":
        return None, idx
    depth = 0
    start = idx + 1
    for i in range(idx, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return s[start:i], i + 1
    return s[start:], len(s)


def latex_to_katex_html(formula: str) -> str:
    """
    Converts raw LaTeX mathematical expressions into lightweight KaTeX-styled HTML
    compatible with Qt's QTextBrowser engine (roots, fractions, Greek symbols, superscripts).
    """
    # 1. Square roots first with balanced braces (supports nested fractions)
    while True:
        pos = formula.find(r"\sqrt{")
        if pos == -1:
            break
        inner, next_pos = _extract_braced_arg(formula, pos + len(r"\sqrt"))
        if inner is None:
            break
        inner_html = latex_to_katex_html(inner)
        sqrt_html = f'&radic;<span style="border-top:1px solid #F8FAFC; padding-top:1px; margin-left:1px;">{inner_html}</span>'
        formula = formula[:pos] + sqrt_html + formula[next_pos:]

    # 2. Fractions with balanced braces (supports nested numerators/denominators)
    for cmd in [r"\frac", r"\dfrac", r"\tfrac", r"\cfrac"]:
        while True:
            pos = formula.find(cmd + "{")
            if pos == -1:
                break
            num, next_pos = _extract_braced_arg(formula, pos + len(cmd))
            if num is None:
                break
            while next_pos < len(formula) and formula[next_pos].isspace():
                next_pos += 1
            if next_pos < len(formula) and formula[next_pos] == "{":
                den, end_pos = _extract_braced_arg(formula, next_pos)
            else:
                den, end_pos = "", next_pos
            num_html = latex_to_katex_html(num)
            den_html = latex_to_katex_html(den)
            tbl = (
                f'<table style="display:inline-table; vertical-align:middle; text-align:center; border-collapse:collapse; margin:0 3px; font-size:0.92em;">'
                f'<tr><td style="border-bottom:1px solid #F8FAFC; padding:0 3px; line-height:1.15;">{num_html}</td></tr>'
                f'<tr><td style="padding:0 3px; line-height:1.15;">{den_html}</td></tr>'
                f'</table>'
            )
            formula = formula[:pos] + tbl + formula[end_pos:]

    # 3. Greek letters (replace backslash Greek with HTML entities)
    greek = {
        "alpha": "&alpha;", "beta": "&beta;", "gamma": "&gamma;", "delta": "&delta;",
        "epsilon": "&epsilon;", "varepsilon": "&epsilon;", "zeta": "&zeta;", "eta": "&eta;",
        "theta": "&theta;", "vartheta": "&theta;", "iota": "&iota;", "kappa": "&kappa;",
        "lambda": "&lambda;", "mu": "&mu;", "nu": "&nu;", "xi": "&xi;", "pi": "&pi;",
        "rho": "&rho;", "sigma": "&sigma;", "tau": "&tau;", "upsilon": "&upsilon;",
        "phi": "&phi;", "varphi": "&phi;", "chi": "&chi;", "psi": "&psi;", "omega": "&omega;",
        "Gamma": "&Gamma;", "Delta": "&Delta;", "Theta": "&Theta;", "Lambda": "&Lambda;",
        "Xi": "&Xi;", "Pi": "&Pi;", "Sigma": "&Sigma;", "Upsilon": "&Upsilon;",
        "Phi": "&Phi;", "Psi": "&Psi;", "Omega": "&Omega;"
    }
    for g, entity in greek.items():
        pattern = r"\\" + g + r"(?![a-zA-Z])"
        formula = re.sub(pattern, entity, formula)

    # 4. Operators & math symbols
    symbols = {
        "sum": '<span style="font-size:1.3em; line-height:1;">&sum;</span>',
        "prod": '<span style="font-size:1.3em; line-height:1;">&prod;</span>',
        "int": '<span style="font-size:1.3em; line-height:1;">&int;</span>',
        "oint": '<span style="font-size:1.3em; line-height:1;">&#8750;</span>',
        "infty": "&infin;", "approx": "&asymp;", "equiv": "&equiv;",
        "leq": "&le;", "le": "&le;", "geq": "&ge;", "ge": "&ge;",
        "neq": "&ne;", "ne": "&ne;", "times": "&times;", "cdot": "&middot;",
        "pm": "&plusmn;", "mp": "&#8723;", "in": "&isin;", "notin": "&#8713;",
        "subset": "&sub;", "subseteq": "&#8838;", "cup": "&cup;", "cap": "&cap;",
        "forall": "&forall;", "exists": "&exist;", "partial": "&part;", "nabla": "&nabla;",
        "to": "&rarr;", "rightarrow": "&rarr;", "Rightarrow": "&rArr;",
        "leftarrow": "&larr;", "Leftarrow": "&lArr;", "leftrightarrow": "&harr;",
        "quad": "&nbsp;&nbsp;", "qquad": "&nbsp;&nbsp;&nbsp;&nbsp;",
        "mathbb{R}": "&#x211D;", "mathbb{N}": "&#x2115;", "mathbb{Z}": "&#x2124;",
        "mathbb{C}": "&#x2102;", "mathbb{Q}": "&#x211A;", "dots": "&hellip;",
        "cdots": "&hellip;", "ldots": "&hellip;",
    }
    for s, entity in symbols.items():
        formula = formula.replace(f"\\{s}", entity)

    # 5. Superscripts and Subscripts
    formula = re.sub(r"\^\{([^{}]+)\}", r"<sup>\1</sup>", formula)
    formula = re.sub(r"\^([a-zA-Z0-9])", r"<sup>\1</sup>", formula)
    formula = re.sub(r"_\{([^{}]+)\}", r"<sub>\1</sub>", formula)
    formula = re.sub(r"_([a-zA-Z0-9])", r"<sub>\1</sub>", formula)

    # 6. Delimiters
    formula = formula.replace(r"\left(", "(").replace(r"\right)", ")")
    formula = formula.replace(r"\left[", "[").replace(r"\right]", "]")
    formula = formula.replace(r"\left\{", "{").replace(r"\right\}", "}")
    formula = formula.replace(r"\left|", "|").replace(r"\right|", "|")

    # 7. Font styles
    formula = re.sub(r"\\(?:text|mathbf|mathrm)\{([^{}]+)\}", r"<b>\1</b>", formula)
    formula = re.sub(r"\\(?:mathit)\{([^{}]+)\}", r"<i>\1</i>", formula)

    return formula


def render_markdown_with_katex(md_text: str) -> str:
    """
    Renders Markdown notes containing display ($$...$$) and inline ($...$) LaTeX formulas,
    Obsidian callouts (> [!type]), audio scrubbing links (chalk-audio://), and Q.E.D. marks
    into beautiful KaTeX-styled HTML formatted for QTextBrowser on a Dark Titanium background.
    """
    if not md_text or not md_text.strip():
        return ""

    # Protect display formulas $$...$$
    blocks = []
    def repl_display(m):
        raw = m.group(1).strip()
        rendered = latex_to_katex_html(raw)
        idx = len(blocks)
        card = (
            f'<div style="background:#1A1C23; border:1px solid rgba(255,255,255,0.14); '
            f'border-radius:8px; padding:10px 14px; margin:8px 0; text-align:center; '
            f'font-family:\'Cambria Math\',\'KaTeX_Main\',\'Times New Roman\',serif; '
            f'font-size:15px; color:#F8FAFC;">{rendered}</div>'
        )
        blocks.append(card)
        return f"__CHALK_MATH_BLOCK_{idx}__"

    text = re.sub(r"\$\$(.*?)\$\$", repl_display, md_text, flags=re.DOTALL)

    # Protect inline formulas $...$
    inlines = []
    def repl_inline(m):
        raw = m.group(1).strip()
        rendered = latex_to_katex_html(raw)
        idx = len(inlines)
        span = (
            f'<span style="font-family:\'Cambria Math\',\'KaTeX_Math\',\'Times New Roman\',serif; '
            f'font-style:italic; color:#F8FAFC; padding:0 2px;">{rendered}</span>'
        )
        inlines.append(span)
        return f"__CHALK_MATH_INLINE_{idx}__"

    text = re.sub(r"(?<!\\)\$(.+?)(?<!\\)\$", repl_inline, text)

    # Escape HTML to prevent arbitrary tag/script injection
    text = html.escape(text)

    # Convert audio timestamp links [HH:MM:SS](chalk-audio://HH:MM:SS)
    text = re.sub(
        r"\[([0-9:]+)\]\(chalk-audio://([0-9:]+)\)",
        r'<a href="chalk-audio://\2" style="color:#60A5FA; text-decoration:none; '
        r'font-weight:600; font-family:monospace; background:rgba(255,255,255,0.08); '
        r'padding:1px 5px; border-radius:4px;">[\1]</a>',
        text
    )

    # Convert headers
    text = re.sub(r"^###\s+(.*)$", r'<h3 style="color:#F8FAFC; font-size:14px; margin:8px 0 4px;">\1</h3>', text, flags=re.MULTILINE)
    text = re.sub(r"^##\s+(.*)$", r'<h2 style="color:#F8FAFC; font-size:16px; margin:12px 0 6px;">\1</h2>', text, flags=re.MULTILINE)
    text = re.sub(r"^#\s+(.*)$", r'<h1 style="color:#F8FAFC; font-size:18px; margin:14px 0 8px;">\1</h1>', text, flags=re.MULTILINE)

    # Bold & Italic
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)

    # Obsidian callouts > [!type] Title
    callout_colors = {
        "theorem": ("#60A5FA", "THEOREM"),
        "definition": ("#94A3B8", "DEFINITION"),
        "proof": ("#A78BFA", "BEWEIS / PROOF"),
        "remark": ("#FBBF24", "HINWEIS / REMARK"),
        "example": ("#38BDF8", "BEISPIEL / EXAMPLE"),
    }
    for ctype, (color, label) in callout_colors.items():
        pat = re.compile(rf"^(?:&gt;|>)\s*\[!{ctype}\]\s*(.*?)$", flags=re.MULTILINE | re.IGNORECASE)
        text = pat.sub(
            rf'<div style="background:#1A1C23; border:1px solid rgba(255,255,255,0.12); '
            rf'border-left:4px solid {color}; border-radius:6px; padding:8px 12px; margin:8px 0;">'
            rf'<div style="font-weight:700; color:{color}; font-size:11px; margin-bottom:4px; font-family:sans-serif;">{label}: \1</div>',
            text
        )

    text = re.sub(r"\n(?:&gt;|>)\s?", "\n<br>", text)
    text = text.replace("∎", '<span style="float:right; color:#94A3B8; font-size:14px;">&#8718;</span><div style="clear:both;"></div>')

    # Convert newlines to breaks
    text = text.replace("\n\n", "<p style='margin:6px 0;'>").replace("\n", "<br>")

    # Restore inlines & blocks
    for i, b in enumerate(inlines):
        text = text.replace(f"__CHALK_MATH_INLINE_{i}__", b)
    for i, b in enumerate(blocks):
        text = text.replace(f"__CHALK_MATH_BLOCK_{i}__", b)

    return f'<div style="color:#CBD5E1; font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',sans-serif; font-size:13px; line-height:1.5;">{text}</div>'


class CopilotWorker(QThread):
    finished = pyqtSignal(str)

    def __init__(self, pipeline, prompt: str, image: Optional[Image.Image], doc_text: Optional[str]):
        super().__init__()
        self.pipeline = pipeline
        self.prompt = prompt
        self.image = image
        self.doc_text = doc_text

    def run(self):
        try:
            res = self.pipeline.execute_copilot_query(
                prompt=self.prompt,
                attached_image=self.image,
                attached_file_text=self.doc_text,
            )
            self.finished.emit(res)
        except Exception as e:
            self.finished.emit(f"Copilot query failed: {str(e)}")


class RewindWorker(QThread):
    finished = pyqtSignal(str)

    def __init__(self, recorder, pipeline, seconds: int = 90):
        super().__init__()
        self.recorder = recorder
        self.pipeline = pipeline
        self.seconds = seconds

    def run(self):
        try:
            audio = self.recorder.get_rewind_audio(self.seconds)
            res = self.pipeline.transcribe_audio_buffer(audio, duration_sec=self.seconds)
            self.finished.emit(res)
        except Exception as e:
            self.finished.emit(f"Rewind transcription error: {str(e)}")


class WhiteboardCamDialog(QDialog):
    """
    Modal dialog displaying the Whiteboard Camera QR code and pairing info.
    Allows students/attendees to scan the QR code and snap physical chalkboards.
    """

    def __init__(self, parent=None, daemon: Optional[CompanionDaemon] = None):
        super().__init__(parent)
        self.daemon = daemon
        self.setWindowTitle("Chalk — Tafel-Kamera via QR-Code")
        self.setFixedSize(420, 540)
        self.setStyleSheet("""
            QDialog {
                background-color: #121317;
                color: #F8FAFC;
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 16px;
            }
            QLabel {
                color: #F8FAFC;
            }
            QPushButton {
                background-color: #1A1C23;
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 8px;
                color: #F8FAFC;
                padding: 8px 14px;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #22252F;
                border-color: rgba(255, 255, 255, 0.3);
            }
            QPushButton#doneBtn {
                background-color: #2A2E3B;
                padding: 10px;
                font-size: 13px;
            }
            QPushButton#doneBtn:hover {
                background-color: #373C4D;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # Header Title
        self.title_lbl = QLabel()
        self.title_lbl.setStyleSheet("font-size: 16px; font-weight: 700; color: #FFFFFF;")
        self.title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_lbl)

        self.sub_lbl = QLabel()
        self.sub_lbl.setStyleSheet("font-size: 12px; color: #94A3B8; line-height: 1.4;")
        self.sub_lbl.setWordWrap(True)
        self.sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.sub_lbl)

        # QR Code Display
        qr_frame = QFrame()
        qr_frame.setStyleSheet("background-color: #FFFFFF; border-radius: 14px; padding: 12px;")
        qr_inner_layout = QVBoxLayout(qr_frame)
        qr_inner_layout.setContentsMargins(8, 8, 8, 8)
        qr_inner_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        url = self.daemon.get_url() if self.daemon else "http://127.0.0.1:8765"
        if self.daemon:
            qr = self.daemon.get_qr_code()
            if qr:
                pix = qr.to_qpixmap(border=2, scale=5)
                self.qr_label.setPixmap(pix)
        qr_inner_layout.addWidget(self.qr_label)
        layout.addWidget(qr_frame, alignment=Qt.AlignmentFlag.AlignCenter)

        # URL Input & Copy Button
        url_layout = QHBoxLayout()
        url_layout.setSpacing(6)
        self.url_edit = QLineEdit(url)
        self.url_edit.setReadOnly(True)
        self.url_edit.setStyleSheet("""
            QLineEdit {
                background-color: #1A1C23;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 8px;
                color: #94A3B8;
                padding: 6px 10px;
                font-family: ui-monospace, Menlo, monospace;
                font-size: 11px;
            }
        """)
        url_layout.addWidget(self.url_edit)

        self.copy_btn = QPushButton()
        self.copy_btn.clicked.connect(self._copy_link)
        url_layout.addWidget(self.copy_btn)
        layout.addLayout(url_layout)

        # Live Status
        self.live_status = QLabel()
        self.live_status.setStyleSheet("font-size: 11px; color: #F8FAFC; font-weight: 600;")
        self.live_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.live_status)

        # Info bullet
        self.info_lbl = QLabel()
        self.info_lbl.setStyleSheet("font-size: 10px; color: #64748B;")
        self.info_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.info_lbl)

        # Done button
        self.done_btn = QPushButton()
        self.done_btn.setObjectName("doneBtn")
        self.done_btn.clicked.connect(self.accept)
        layout.addWidget(self.done_btn)

        self._photos_count = 0
        self.retranslate_ui()

        if self.daemon and self.daemon.bridge:
            self.daemon.bridge.photo_received.connect(self._on_photo_received)
            self.daemon.bridge.client_connected.connect(self._on_client_connected)

    def retranslate_ui(self):
        self.setWindowTitle(tr("wb_dialog_title"))
        self.title_lbl.setText(tr("wb_dialog_title"))
        self.sub_lbl.setText(tr("wb_subtitle"))
        self.copy_btn.setText(tr("btn_copy_link"))
        self.info_lbl.setText(tr("wb_info_footer"))
        self.done_btn.setText(tr("btn_close"))
        if self._photos_count == 0:
            self.live_status.setText(tr("wb_waiting"))
        else:
            self.live_status.setText(f"[OK] {tr('wb_connected', count=self._photos_count)}")

    def _copy_link(self):
        QApplication.clipboard().setText(self.url_edit.text())
        self.copy_btn.setText("[OK]")
        QTimer.singleShot(2000, lambda: self.copy_btn.setText(tr("btn_copy_link")))

    def _on_photo_received(self, path: str, ts: str):
        count = self.daemon.bridge.upload_count if self.daemon and self.daemon.bridge else 1
        self._photos_count = count
        self.live_status.setText(f"[OK] {tr('wb_connected', count=count)} ({ts})")

    def _on_client_connected(self, ip: str):
        self.live_status.setText(f"{tr('wb_connected', count=self._photos_count)} ({ip})")




class FloatingHUDWindow(QWidget):
    """
    1:1 Desktop HUD Window matching the Chalk Web Simulation experience.
    Frameless, floating (Alt+Space / Cmd+Shift+Space), dual-column layout:
    - Left Column:
        * Card 1: SCREEN CAPTURE (with slide navigation, topic, heading, KaTeX math preview)
        * Card 2: LIVE AUDIO & CAPTURE (speaker status, live transcribed speech, Snap Photo, Pair QR)
    - Right Column:
        * Navigation Tabs: [Live Notes] [AI Chat] [Settings] + filename + [Copy notes]
        * Tab 0: Live KaTeX Notes + Bottom Directive Dock (+ chips, input, attach)
        * Tab 1: AI Chat (grounded Copilot + prompt chips)
        * Tab 2: Integrated Settings (BYOK Gemini key, model dropdown, vault path, Dark/Light, EN/DE/FR/ES/ZH)
    - Top Window Bar:
        * macOS Traffic Lights (red/yellow/green), Lecture Title, Live Recording Status Pill
    - Bottom Footer:
        * Real-time Duration Timer (hours/mins/secs live counter) + Secondary Quick Tools
    """
    request_toggle_recording = pyqtSignal()
    request_force_flush = pyqtSignal()
    request_master_synthesis = pyqtSignal()

    def __init__(self, recorder=None, pipeline=None, quota_manager=None, notes_manager=None, parent=None):
        super().__init__(parent)
        self.recorder = recorder
        self.pipeline = pipeline
        self.quota_manager = quota_manager
        self.notes_manager = notes_manager

        # Attachments & In-Person Lecture Slides
        self.attached_document_text: Optional[str] = None
        self.attached_document_name: Optional[str] = None
        self.attached_snip_image: Optional[Image.Image] = None
        self.imported_pdf_slides = []  # List of dicts: {"page": int, "text": str}
        self.imported_pdf_name: Optional[str] = None
        self.current_slide_idx = 0

        # Sample / Demo Slide keyframes for pristine initial presentation
        self.sample_slides = [
            {
                "file": "Asset_Pricing_Lecture_04.pdf (p. 12/42)",
                "topic": "Portfolio Theory & Risk Modeling",
                "heading": "Capital Asset Pricing Model (CAPM)",
                "math": "$$E(R_i) = R_f + \\beta_i [E(R_m) - R_f]$$",
            },
            {
                "file": "Asset_Pricing_Lecture_04.pdf (p. 18/42)",
                "topic": "Performance Attribution & Alpha",
                "heading": "Security Market Line & Jensen's Alpha",
                "math": "$$\\alpha_i = R_i - [R_f + \\beta_i (E(R_m) - R_f)]$$",
            },
            {
                "file": "Asset_Pricing_Lecture_04.pdf (p. 25/42)",
                "topic": "Arbitrage Pricing & Multi-Factor",
                "heading": "Fama-French Three-Factor Model",
                "math": "$$E(R_i) - R_f = \\beta_{i1}(R_m - R_f) + \\beta_{i2}SMB + \\beta_{i3}HML$$",
            },
        ]

        # Whiteboard Camera & Mobile Companion
        self.whiteboard_photos: List[str] = []
        self.companion_bridge = CompanionBridge(self)
        self.companion_bridge.photo_received.connect(self._on_whiteboard_photo_received)
        sess_id = getattr(self.notes_manager, "session_id", None) or f"sess_{int(time.time())}"
        self.companion_daemon = CompanionDaemon(
            bridge=self.companion_bridge,
            session_id=sess_id,
        )

        # State
        self.session_start_time = time.time()
        self.drag_position = QPoint()
        self.is_playing_audio = False
        self._current_daemon_state = "recording"
        self._current_daemon_msg = ""
        self.current_theme = "dark"
        self.pinned_directives = []

        # Snip overlay tool
        self.snip_overlay = SnipOverlayWidget()
        self.snip_overlay.snip_captured.connect(self._on_snip_received)

        self._setup_window_properties()
        self._setup_ui()

        # Update timer for HUD status and session duration
        self.hud_timer = QTimer(self)
        self.hud_timer.timeout.connect(self._update_hud_status)
        self.hud_timer.start(1000)

        # Periodic live screen mirror sampler
        self.screen_mirror_timer = QTimer(self)
        self.screen_mirror_timer.timeout.connect(self.grab_live_screen_preview)
        self.screen_mirror_timer.start(2500)
        QTimer.singleShot(200, self.grab_live_screen_preview)

    def _setup_window_properties(self):
        self.setObjectName("hudRoot")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAcceptDrops(True)
        self.resize(860, 580)
        self.setStyleSheet(HUD_STYLESHEET_DARK)

        # Center on upper part of primary screen
        screen = self.screen().geometry()
        x = max(20, (screen.width() - self.width()) // 2)
        y = max(40, (screen.height() - self.height()) // 5)
        self.move(x, y)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 12, 14, 12)
        main_layout.setSpacing(8)

        # ------------------------------------------------------------------
        # 1. TOP HEADER: Window Chrome (macOS traffic lights, title, status)
        # ------------------------------------------------------------------
        header_bar = QHBoxLayout()
        header_bar.setSpacing(10)

        # Traffic Lights
        lights_layout = QHBoxLayout()
        lights_layout.setSpacing(7)

        self.mac_close_btn = QPushButton()
        self.mac_close_btn.setFixedSize(12, 12)
        self.mac_close_btn.setStyleSheet("background-color: #FF5F56; border-radius: 6px; border: 1px solid rgba(0,0,0,0.2);")
        self.mac_close_btn.setToolTip("HUD ausblenden (Cmd+Shift+Space / Ctrl+Shift+Space)")
        self.mac_close_btn.clicked.connect(self.hide)
        self.hide_btn = self.mac_close_btn  # Backward compat alias

        self.mac_min_btn = QPushButton()
        self.mac_min_btn.setFixedSize(12, 12)
        self.mac_min_btn.setStyleSheet("background-color: #FFBD2E; border-radius: 6px; border: 1px solid rgba(0,0,0,0.2);")
        self.mac_min_btn.setToolTip("Minimieren")
        self.mac_min_btn.clicked.connect(self.showMinimized)

        self.mac_expand_btn = QPushButton()
        self.mac_expand_btn.setFixedSize(12, 12)
        self.mac_expand_btn.setStyleSheet("background-color: #27C93F; border-radius: 6px; border: 1px solid rgba(0,0,0,0.2);")
        self.mac_expand_btn.setToolTip("Fenstergröße anpassen")
        self.mac_expand_btn.clicked.connect(self.toggle_expand)

        lights_layout.addWidget(self.mac_close_btn)
        lights_layout.addWidget(self.mac_min_btn)
        lights_layout.addWidget(self.mac_expand_btn)
        header_bar.addLayout(lights_layout)

        # Title
        topic_title = getattr(self.notes_manager, "topic", "") if self.notes_manager else ""
        if not topic_title:
            topic_title = "Financial Markets & Risk"
        self.window_title_label = QLabel(f"Lecture: {topic_title} — Chalk")
        self.window_title_label.setStyleSheet("font-size: 12px; font-weight: 600; color: #F8FAFC;")
        header_bar.addWidget(self.window_title_label)

        header_bar.addStretch()

        # Attachment Banner
        self.attachment_label = QLabel("")
        self.attachment_label.setStyleSheet(
            "background-color: rgba(255, 255, 255, 0.08); border: 1px solid rgba(255, 255, 255, 0.18);"
            "color: #CBD5E1; font-size: 10.5px; font-weight: 500; padding: 2px 8px; border-radius: 10px;"
        )
        self.attachment_label.hide()
        header_bar.addWidget(self.attachment_label)

        # Recording Status Pill
        self.status_pill = QLabel("● Recording active (00:00)")
        self.status_pill.setStyleSheet(
            "background-color: rgba(255, 255, 255, 0.08); border: 1px solid rgba(255, 255, 255, 0.18);"
            "color: #FFFFFF; font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 12px;"
        )
        header_bar.addWidget(self.status_pill)

        main_layout.addLayout(header_bar)

        # ------------------------------------------------------------------
        # 2. MAIN 2-COLUMN BODY LAYOUT
        # ------------------------------------------------------------------
        body_layout = QHBoxLayout()
        body_layout.setSpacing(10)

        # LEFT COLUMN (340px)
        left_col = QVBoxLayout()
        left_col.setSpacing(10)

        # Card 1: SCREEN CAPTURE
        self.screen_capture_card = QFrame()
        self.screen_capture_card.setObjectName("cardFrame")
        sc_layout = QVBoxLayout(self.screen_capture_card)
        sc_layout.setContentsMargins(12, 10, 12, 10)
        sc_layout.setSpacing(6)

        sc_head = QHBoxLayout()
        self.screen_title_lbl = QLabel(tr("hud_screen_mirror"))
        self.screen_title_lbl.setStyleSheet("font-size: 10px; font-weight: 700; letter-spacing: 1px; color: #94A3B8;")
        sc_head.addWidget(self.screen_title_lbl)
        sc_head.addStretch()

        self.screen_badge_lbl = QLabel("")
        self.screen_badge_lbl.hide()
        sc_head.addWidget(self.screen_badge_lbl)

        # Legacy backward-compat widgets (hidden)
        self.prev_slide_btn = QPushButton("‹")
        self.prev_slide_btn.hide()
        self.next_slide_btn = QPushButton("›")
        self.next_slide_btn.hide()
        self.slide_counter_lbl = QLabel("1/1")
        self.slide_counter_lbl.hide()
        self.slide_file_lbl = QLabel("")
        self.slide_file_lbl.hide()
        self.slide_topic_lbl = QLabel("")
        self.slide_topic_lbl.hide()
        self.slide_heading_lbl = QLabel("")
        self.slide_heading_lbl.hide()
        self.slide_math_view = QTextBrowser()
        self.slide_math_view.hide()

        sc_layout.addLayout(sc_head)

        self.screen_source_lbl = QLabel("")
        self.screen_source_lbl.setStyleSheet("font-size: 10px; font-family: monospace; color: #64748B;")
        self.screen_source_lbl.hide()
        sc_layout.addWidget(self.screen_source_lbl)

        # Real Live Screen Preview Label
        self.screen_preview_lbl = QLabel("")
        self.screen_preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.screen_preview_lbl.setStyleSheet(
            "background-color: rgba(21, 22, 27, 0.85); "
            "border: 1px solid rgba(255, 255, 255, 0.08); "
            "border-radius: 6px; color: #64748B; font-size: 11px; font-family: monospace;"
        )
        self.screen_preview_lbl.setFixedHeight(120)
        self.screen_preview_lbl.setScaledContents(False)
        sc_layout.addWidget(self.screen_preview_lbl)

        self.screen_details_lbl = QLabel("")
        self.screen_details_lbl.hide()
        sc_layout.addWidget(self.screen_details_lbl)

        left_col.addWidget(self.screen_capture_card)

        # Card 2: LIVE AUDIO & CAPTURE
        self.live_audio_card = QFrame()
        self.live_audio_card.setObjectName("cardFrame")
        la_layout = QVBoxLayout(self.live_audio_card)
        la_layout.setContentsMargins(12, 10, 12, 10)
        la_layout.setSpacing(6)

        la_head = QHBoxLayout()
        la_title_lbl = QLabel("● LIVE AUDIO & CAPTURE")
        la_title_lbl.setStyleSheet("font-size: 10px; font-weight: 700; letter-spacing: 1px; color: #94A3B8;")
        la_head.addWidget(la_title_lbl)
        la_head.addStretch()
        la_layout.addLayout(la_head)

        self.speaker_badge_lbl = QLabel("Speaker Active    @ 00:00")
        self.speaker_badge_lbl.setStyleSheet("font-size: 10.5px; font-family: monospace; color: #CBD5E1;")
        la_layout.addWidget(self.speaker_badge_lbl)

        self.live_speech_lbl = QLabel(tr("hud_listening_speech"))
        self.live_speech_lbl.setStyleSheet(
            "font-size: 11.5px; font-style: italic; color: #94A3B8; "
            "background-color: rgba(21, 22, 27, 0.7); padding: 8px 10px; border-radius: 6px; border: 1px solid rgba(255, 255, 255, 0.06);"
        )
        self.live_speech_lbl.setWordWrap(True)
        la_layout.addWidget(self.live_speech_lbl)

        # Snap & QR Bar
        audio_btn_row = QHBoxLayout()
        audio_btn_row.setSpacing(8)

        self.snap_photo_btn = QPushButton("Snap Photo")
        self.snap_photo_btn.setStyleSheet("font-weight: 600; padding: 6px 12px;")
        self.snap_photo_btn.clicked.connect(self.trigger_screen_snip)
        self.snip_btn = self.snap_photo_btn  # Backward compat alias
        audio_btn_row.addWidget(self.snap_photo_btn, stretch=2)

        self.cam_btn = QPushButton("Pair QR")
        self.cam_btn.setStyleSheet("font-weight: 500; padding: 6px 10px;")
        self.cam_btn.clicked.connect(self._open_whiteboard_cam_dialog)
        audio_btn_row.addWidget(self.cam_btn, stretch=1)

        la_layout.addLayout(audio_btn_row)
        left_col.addWidget(self.live_audio_card)

        body_layout.addLayout(left_col, stretch=4)

        # RIGHT COLUMN: Main Workspace (Notes, Chat, Settings)
        self.workspace_card = QFrame()
        self.workspace_card.setObjectName("cardFrame")
        ws_layout = QVBoxLayout(self.workspace_card)
        ws_layout.setContentsMargins(12, 10, 12, 10)
        ws_layout.setSpacing(8)

        # Tab bar
        tab_bar = QHBoxLayout()
        tab_bar.setSpacing(6)

        self.tab_btn_notes = QPushButton("Live Notes")
        self.tab_btn_notes.setObjectName("tabActive")
        self.tab_btn_notes.clicked.connect(lambda: self.switch_tab(0))
        tab_bar.addWidget(self.tab_btn_notes)
        self.btn_view_notes = self.tab_btn_notes  # Alias

        self.tab_btn_chat = QPushButton("AI Chat")
        self.tab_btn_chat.setObjectName("tabInactive")
        self.tab_btn_chat.clicked.connect(lambda: self.switch_tab(1))
        tab_bar.addWidget(self.tab_btn_chat)
        self.btn_view_chat = self.tab_btn_chat  # Alias

        self.tab_btn_settings = QPushButton("Settings")
        self.tab_btn_settings.setObjectName("tabInactive")
        self.tab_btn_settings.clicked.connect(lambda: self.switch_tab(2))
        tab_bar.addWidget(self.tab_btn_settings)
        self.settings_btn = self.tab_btn_settings  # Alias

        tab_bar.addStretch()

        self.note_filename_lbl = QLabel("financial_markets_ch3.md")
        self.note_filename_lbl.setStyleSheet("font-size: 11px; font-family: monospace; color: #64748B;")
        tab_bar.addWidget(self.note_filename_lbl)

        self.copy_notes_btn = QPushButton("Copy notes")
        self.copy_notes_btn.clicked.connect(self._copy_notes_to_clipboard)
        tab_bar.addWidget(self.copy_notes_btn)

        ws_layout.addLayout(tab_bar)

        # Stacked Widget
        self.right_stack = QStackedWidget()

        # ---------------- PAGE 0: Live Notes ----------------
        self.notes_tab_widget = QWidget()
        n_tab_layout = QVBoxLayout(self.notes_tab_widget)
        n_tab_layout.setContentsMargins(0, 0, 0, 0)
        n_tab_layout.setSpacing(6)

        self.notes_browser = QTextBrowser()
        self.notes_browser.setOpenExternalLinks(False)
        self.notes_browser.setOpenLinks(False)
        self.notes_browser.anchorClicked.connect(self._on_anchor_clicked)
        n_tab_layout.addWidget(self.notes_browser)

        # Directive Dock Frame
        self.directive_dock_card = QFrame()
        self.directive_dock_card.setObjectName("dockFrame")
        dd_layout = QVBoxLayout(self.directive_dock_card)
        dd_layout.setContentsMargins(10, 8, 10, 8)
        dd_layout.setSpacing(5)

        dd_head = QHBoxLayout()
        dd_title_lbl = QLabel("✍ Note or Directive to AI")
        dd_title_lbl.setStyleSheet("font-size: 11px; font-weight: 600; color: #E2E8F0;")
        dd_head.addWidget(dd_title_lbl)
        dd_head.addStretch()
        dd_sub_lbl = QLabel("Synced with audio & summary")
        dd_sub_lbl.setStyleSheet("font-size: 9.5px; color: #64748B;")
        dd_head.addWidget(dd_sub_lbl)
        dd_layout.addLayout(dd_head)

        chips_row = QHBoxLayout()
        chips_row.setSpacing(6)

        self.chip_exam_btn = QPushButton("+ Exam Hint")
        self.chip_exam_btn.setObjectName("chipBtn")
        self.chip_exam_btn.clicked.connect(lambda: self._insert_directive_chip("Exam Hint: Key calculation step"))
        chips_row.addWidget(self.chip_exam_btn)

        self.chip_proof_btn = QPushButton("+ Detail Proof")
        self.chip_proof_btn.setObjectName("chipBtn")
        self.chip_proof_btn.clicked.connect(lambda: self._insert_directive_chip("Detail Proof: Expand covariance derivation step-by-step"))
        chips_row.addWidget(self.chip_proof_btn)

        self.chip_note_btn = QPushButton("+ Side Note")
        self.chip_note_btn.setObjectName("chipBtn")
        self.chip_note_btn.clicked.connect(lambda: self._insert_directive_chip("Side Note: Connect to Sharpe Ratio"))
        chips_row.addWidget(self.chip_note_btn)
        chips_row.addStretch()
        dd_layout.addLayout(chips_row)

        dir_input_row = QHBoxLayout()
        dir_input_row.setSpacing(6)
        self.directive_input = QLineEdit()
        self.directive_input.setPlaceholderText("Add note or instruction for the AI summary...")
        self.directive_input.returnPressed.connect(self._on_pin_user_directive)
        dir_input_row.addWidget(self.directive_input)

        self.attach_directive_btn = QPushButton("Attach ✈")
        self.attach_directive_btn.setStyleSheet("font-weight: 600; padding: 6px 12px;")
        self.attach_directive_btn.clicked.connect(self._on_pin_user_directive)
        self.pin_directive_btn = self.attach_directive_btn  # Alias
        dir_input_row.addWidget(self.attach_directive_btn)
        dd_layout.addLayout(dir_input_row)

        self.pinned_directive_lbl = QLabel("")
        self.pinned_directive_lbl.setStyleSheet("font-size: 10px; color: #38BDF8; font-style: italic;")
        self.pinned_directive_lbl.hide()
        dd_layout.addWidget(self.pinned_directive_lbl)

        n_tab_layout.addWidget(self.directive_dock_card)
        self.right_stack.addWidget(self.notes_tab_widget)

        # ---------------- PAGE 1: AI Chat ----------------
        self.chat_tab_widget = QWidget()
        c_tab_layout = QVBoxLayout(self.chat_tab_widget)
        c_tab_layout.setContentsMargins(0, 0, 0, 0)
        c_tab_layout.setSpacing(6)

        c_header_row = QHBoxLayout()
        c_header_row.setContentsMargins(0, 0, 0, 0)
        c_info_lbl = QLabel(tr("preview_chat_grounded") or "AI grounded in live audio, slides & photos")
        c_info_lbl.setStyleSheet("font-size: 10.5px; color: #64748B; padding-left: 2px;")
        c_header_row.addWidget(c_info_lbl)
        c_header_row.addStretch()

        self.chat_model_badge = QLabel("Gemini 2.5 Flash")
        self.chat_model_badge.setStyleSheet(
            "font-size: 10px; font-family: monospace; color: #94A3B8; "
            "background-color: #15161B; border: 1px solid rgba(255, 255, 255, 0.1); "
            "border-radius: 4px; padding: 2px 6px;"
        )
        c_header_row.addWidget(self.chat_model_badge)
        c_tab_layout.addLayout(c_header_row)

        self.chat_history = QTextBrowser()
        self.chat_history.setOpenExternalLinks(False)
        self.chat_history.setOpenLinks(False)
        self.chat_history.anchorClicked.connect(self._on_anchor_clicked)
        c_tab_layout.addWidget(self.chat_history)

        chat_chips_row = QHBoxLayout()
        chat_chips_row.setSpacing(6)

        self.chat_chip_summary = QPushButton("Summarize Takeaways")
        self.chat_chip_summary.setObjectName("chipBtn")
        self.chat_chip_summary.clicked.connect(lambda: self._send_quick_chat("Summarize the key takeaways and core formulas from this lecture so far."))
        chat_chips_row.addWidget(self.chat_chip_summary)

        self.chat_chip_intuition = QPushButton("Explain Intuition")
        self.chat_chip_intuition.setObjectName("chipBtn")
        self.chat_chip_intuition.clicked.connect(lambda: self._send_quick_chat("Explain the intuitive economic rationale behind CAPM risk-pricing."))
        chat_chips_row.addWidget(self.chat_chip_intuition)

        self.chat_chip_proof = QPushButton("Step-by-Step Proof")
        self.chat_chip_proof.setObjectName("chipBtn")
        self.chat_chip_proof.clicked.connect(lambda: self._send_quick_chat("Provide the step-by-step mathematical derivation of the CAPM formula."))
        chat_chips_row.addWidget(self.chat_chip_proof)
        chat_chips_row.addStretch()
        c_tab_layout.addLayout(chat_chips_row)

        c_input_row = QHBoxLayout()
        c_input_row.setSpacing(6)
        self.prompt_input = QLineEdit()
        self.prompt_input.setPlaceholderText("Ask AI about this lecture...")
        self.prompt_input.returnPressed.connect(self._send_copilot_prompt)
        c_input_row.addWidget(self.prompt_input)

        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self._send_copilot_prompt)
        c_input_row.addWidget(self.send_btn)
        c_tab_layout.addLayout(c_input_row)

        self.right_stack.addWidget(self.chat_tab_widget)

        # ---------------- PAGE 2: Settings ----------------
        self.settings_tab_widget = QWidget()
        s_tab_layout = QVBoxLayout(self.settings_tab_widget)
        s_tab_layout.setContentsMargins(6, 6, 6, 6)
        s_tab_layout.setSpacing(10)

        # 1. API Key
        key_head = QHBoxLayout()
        key_lbl = QLabel(tr("preview_key_label") or "API Key (BYOK):")
        key_lbl.setStyleSheet("font-size: 11px; font-weight: 600; color: #F8FAFC;")
        key_head.addWidget(key_lbl)
        key_head.addStretch()
        free_key_link = QPushButton("Get Free Key ↗")
        free_key_link.setStyleSheet(
            "QPushButton { background-color: #22252F; border: 1px solid rgba(255, 255, 255, 0.12); "
            "color: #F8FAFC; font-size: 10.5px; font-weight: 600; padding: 2px 8px; border-radius: 5px; } "
            "QPushButton:hover { border-color: #94A3B8; background-color: #2A2D37; }"
        )
        free_key_link.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://aistudio.google.com/app/apikey")))
        key_head.addWidget(free_key_link)
        s_tab_layout.addLayout(key_head)

        key_row = QHBoxLayout()
        key_row.setSpacing(6)
        self.settings_key_input = QLineEdit()
        self.settings_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.settings_key_input.setPlaceholderText("AIzaSy... (Enter your key to test)")
        saved_key = get_api_key("gemini") or ""
        if saved_key:
            self.settings_key_input.setText(saved_key)
        key_row.addWidget(self.settings_key_input)

        self.settings_test_key_btn = QPushButton("Test Key")
        self.settings_test_key_btn.clicked.connect(self._test_settings_key)
        key_row.addWidget(self.settings_test_key_btn)

        self.settings_save_key_btn = QPushButton("Save Key")
        self.settings_save_key_btn.setObjectName("primaryAction")
        self.settings_save_key_btn.clicked.connect(self._save_settings_key)
        key_row.addWidget(self.settings_save_key_btn)
        s_tab_layout.addLayout(key_row)

        self.settings_key_feedback = QLabel("")
        self.settings_key_feedback.setStyleSheet("font-size: 10.5px; font-family: monospace;")
        s_tab_layout.addWidget(self.settings_key_feedback)

        # 2. Model
        self.settings_model_label = QLabel("AI Synthesis Model:")
        s_tab_layout.addWidget(self.settings_model_label)
        self.settings_model_combo = QComboBox()
        populate_preset_combobox(self.settings_model_combo, get_ui_language())
        cur_model = get_selected_model()
        select_preset_in_combobox(self.settings_model_combo, cur_model)
        self.settings_model_combo.currentIndexChanged.connect(self._on_settings_model_changed)
        s_tab_layout.addWidget(self.settings_model_combo)
        if hasattr(self, "chat_model_badge"):
            active_p = resolve_model_preset(self.settings_model_combo.currentData() or cur_model)
            self.chat_model_badge.setText(active_p.get("short_name", "Gemini Maximum"))

        # 3. Notes Vault Directory
        s_tab_layout.addWidget(QLabel("Notes Vault Directory:"))
        vault_row = QHBoxLayout()
        vault_row.setSpacing(6)
        self.settings_vault_input = QLineEdit()
        v_path = get_obsidian_vault_path() or find_local_obsidian_vault() or os.path.expanduser("~/Documents/Notes")
        self.settings_vault_input.setText(v_path)
        vault_row.addWidget(self.settings_vault_input)
        self.settings_vault_browse_btn = QPushButton("Browse")
        self.settings_vault_browse_btn.clicked.connect(self._browse_vault_path)
        vault_row.addWidget(self.settings_vault_browse_btn)
        s_tab_layout.addLayout(vault_row)

        # 4. Appearance Mode
        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("Appearance Mode (This Window):"))
        theme_row.addStretch()
        self.theme_dark_btn = QPushButton("Dark")
        self.theme_dark_btn.setObjectName("tabActive")
        self.theme_dark_btn.clicked.connect(lambda: self.apply_theme("dark"))
        theme_row.addWidget(self.theme_dark_btn)

        self.theme_light_btn = QPushButton("Light")
        self.theme_light_btn.setObjectName("tabInactive")
        self.theme_light_btn.clicked.connect(lambda: self.apply_theme("light"))
        theme_row.addWidget(self.theme_light_btn)
        s_tab_layout.addLayout(theme_row)

        # 5. Interface Language Switcher (EN, DE, FR, ES, ZH)
        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel("Interface Language:"))
        lang_row.addStretch()

        self.lang_en_btn = QPushButton("EN")
        self.lang_en_btn.clicked.connect(lambda: self.change_language("en"))
        lang_row.addWidget(self.lang_en_btn)

        self.lang_de_btn = QPushButton("DE")
        self.lang_de_btn.clicked.connect(lambda: self.change_language("de"))
        lang_row.addWidget(self.lang_de_btn)

        self.lang_fr_btn = QPushButton("FR")
        self.lang_fr_btn.clicked.connect(lambda: self.change_language("fr"))
        lang_row.addWidget(self.lang_fr_btn)

        self.lang_es_btn = QPushButton("ES")
        self.lang_es_btn.clicked.connect(lambda: self.change_language("es"))
        lang_row.addWidget(self.lang_es_btn)

        self.lang_zh_btn = QPushButton("ZH")
        self.lang_zh_btn.clicked.connect(lambda: self.change_language("zh"))
        lang_row.addWidget(self.lang_zh_btn)
        s_tab_layout.addLayout(lang_row)

        # 6. Disclaimer Box
        disclaimer_box = QFrame()
        disclaimer_box.setObjectName("dockFrame")
        d_layout = QVBoxLayout(disclaimer_box)
        d_layout.setContentsMargins(10, 8, 10, 8)
        d_head = QLabel("Direct Connection & Local Storage")
        d_head.setStyleSheet("font-size: 11px; font-weight: 600; color: #F8FAFC;")
        d_layout.addWidget(d_head)
        d_body = QLabel(
            "Your API key is saved locally in your system keychain. "
            "Synthesis requests connect directly from localhost to the AI provider with zero middleman servers."
        )
        d_body.setStyleSheet("font-size: 10px; color: #94A3B8;")
        d_body.setWordWrap(True)
        d_layout.addWidget(d_body)
        s_tab_layout.addWidget(disclaimer_box)

        s_tab_layout.addStretch()
        self.right_stack.addWidget(self.settings_tab_widget)

        ws_layout.addWidget(self.right_stack)
        body_layout.addWidget(self.workspace_card, stretch=6)

        main_layout.addLayout(body_layout)

        # ------------------------------------------------------------------
        # 3. FOOTER ROW: Live Duration Counter & Quick Actions
        # ------------------------------------------------------------------
        footer_bar = QHBoxLayout()
        footer_bar.setContentsMargins(4, 2, 4, 2)
        footer_bar.setSpacing(8)

        self.footer_duration_lbl = QLabel("Duration: 1h 42m 45s")
        self.footer_duration_lbl.setStyleSheet("font-size: 11px; font-family: monospace; color: #94A3B8;")
        footer_bar.addWidget(self.footer_duration_lbl)

        footer_bar.addStretch()

        self.attach_doc_btn = QPushButton(tr("btn_attach_slides"))
        self.attach_doc_btn.clicked.connect(self._open_document_dialog)
        footer_bar.addWidget(self.attach_doc_btn)

        self.pdf_export_btn = QPushButton(tr("btn_pdf_export"))
        self.pdf_export_btn.clicked.connect(self._export_notes_pdf)
        footer_bar.addWidget(self.pdf_export_btn)

        self.obsidian_btn = QPushButton(tr("btn_obsidian"))
        self.obsidian_btn.clicked.connect(self._open_in_obsidian)
        footer_bar.addWidget(self.obsidian_btn)

        self.synth_btn = QPushButton(tr("btn_finish"))
        self.synth_btn.setObjectName("primaryAction")
        self.synth_btn.clicked.connect(lambda: self.request_master_synthesis.emit())
        footer_bar.addWidget(self.synth_btn)

        main_layout.addLayout(footer_bar)

        # Hidden & backward-compatibility widgets
        self.rewind_btn = QPushButton("Rewind 90s")
        self.rewind_btn.clicked.connect(self._trigger_audio_rewind)
        self.search_btn = QPushButton("Suche (Alt+F)")
        self.search_btn.clicked.connect(self._open_archive_search)
        self.anki_export_btn = QPushButton("Export Anki")
        self.anki_export_btn.clicked.connect(self._export_anki_flashcards)
        self.editor_btn = QPushButton("System Editor")
        self.editor_btn.clicked.connect(self._open_in_default_editor)
        self.scratchpad_text = QTextEdit()  # For legacy test compat

        # Floating Mini-Player Pill
        self.player_pill = QFrame()
        self.player_pill.setObjectName("playerPill")
        pill_layout = QHBoxLayout(self.player_pill)
        pill_layout.setContentsMargins(10, 4, 10, 4)
        pill_layout.setSpacing(8)

        self.player_rewind_btn = QPushButton("-5s")
        self.player_rewind_btn.setObjectName("pillBtn")
        self.player_rewind_btn.clicked.connect(self._step_backward_5s)
        pill_layout.addWidget(self.player_rewind_btn)

        self.player_play_btn = QPushButton("Play")
        self.player_play_btn.setObjectName("pillBtn")
        self.player_play_btn.setFixedSize(50, 26)
        self.player_play_btn.clicked.connect(self._toggle_audio_playback)
        pill_layout.addWidget(self.player_play_btn)

        self.player_forward_btn = QPushButton("+5s")
        self.player_forward_btn.setObjectName("pillBtn")
        self.player_forward_btn.clicked.connect(self._step_forward_5s)
        pill_layout.addWidget(self.player_forward_btn)

        self.player_time_badge = QLabel("[00:00]")
        self.player_time_badge.setStyleSheet("color: #FFFFFF; font-weight: 700; font-family: monospace; font-size: 11px;")
        pill_layout.addWidget(self.player_time_badge)

        self.player_status_lbl = QLabel("20s Audio-Ausschnitt")
        self.player_status_lbl.setStyleSheet("color: #94A3B8; font-size: 11px;")
        pill_layout.addWidget(self.player_status_lbl)

        self.player_speed = 1.0
        self.player_speed_btn = QPushButton("1.0x")
        self.player_speed_btn.setObjectName("pillBtn")
        self.player_speed_btn.setFixedSize(42, 26)
        self.player_speed_btn.clicked.connect(self._cycle_playback_speed)
        pill_layout.addWidget(self.player_speed_btn)
        pill_layout.addStretch()

        self.player_close_btn = QPushButton("X")
        self.player_close_btn.setObjectName("pillCloseBtn")
        self.player_close_btn.clicked.connect(self.hide_audio_player_pill)
        pill_layout.addWidget(self.player_close_btn)

        main_layout.addWidget(self.player_pill)
        self.player_pill.hide()

        # Keyboard shortcuts
        self.search_shortcut = QShortcut(QKeySequence("Alt+F"), self)
        self.search_shortcut.activated.connect(self._open_archive_search)
        self.search_shortcut_cmd = QShortcut(QKeySequence("Ctrl+F"), self)
        self.search_shortcut_cmd.activated.connect(self._open_archive_search)

        # Initial view population
        self._navigate_slide(0)
        self.refresh_live_notes_view()
        self.retranslate_ui()

    def switch_tab(self, index: int):
        self.right_stack.setCurrentIndex(index)
        buttons = [self.tab_btn_notes, self.tab_btn_chat, self.tab_btn_settings]
        for idx, btn in enumerate(buttons):
            if idx == index:
                btn.setObjectName("tabActive")
            else:
                btn.setObjectName("tabInactive")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        is_settings = (index == 2)
        is_notes = (index == 0)
        if hasattr(self, "note_filename_lbl"):
            self.note_filename_lbl.setVisible(is_notes)
        if hasattr(self, "copy_notes_btn"):
            self.copy_notes_btn.setVisible(is_notes)
        if hasattr(self, "attach_doc_btn"):
            self.attach_doc_btn.setVisible(not is_settings)
        if hasattr(self, "pdf_export_btn"):
            self.pdf_export_btn.setVisible(not is_settings)
        if hasattr(self, "obsidian_btn"):
            self.obsidian_btn.setVisible(not is_settings)
        if hasattr(self, "synth_btn"):
            self.synth_btn.setVisible(not is_settings)

        if index == 0:
            self.refresh_live_notes_view()

    def _show_notes_view(self):
        self.switch_tab(0)

    def _show_chat_view(self):
        self.switch_tab(1)

    def _show_settings_view(self):
        self.switch_tab(2)

    def toggle_expand(self):
        if self.width() > 950:
            self.resize(860, 580)
        else:
            self.resize(1040, 680)

    def _navigate_slide(self, step: int):
        if self.imported_pdf_slides:
            total = len(self.imported_pdf_slides)
            self.current_slide_idx = (self.current_slide_idx + step) % total
            slide = self.imported_pdf_slides[self.current_slide_idx]
            self.slide_counter_lbl.setText(f"{self.current_slide_idx + 1}/{total}")
            deck_name = self.imported_pdf_name or "Presentation.pdf"
            self.slide_file_lbl.setText(f"{deck_name} (p. {slide['page']}/{total})")
            p_text = slide.get("text", "")
            lines = [l for l in p_text.splitlines() if l.strip()]
            first_line = lines[0] if lines else "Slide content"
            self.slide_heading_lbl.setText(first_line[:40])
            self.slide_topic_lbl.setText(f"Page {slide['page']}")
            self.slide_math_view.setHtml(render_markdown_with_katex(p_text[:300]))
        else:
            total = len(self.sample_slides)
            self.current_slide_idx = (self.current_slide_idx + step) % total
            slide = self.sample_slides[self.current_slide_idx]
            self.slide_counter_lbl.setText(f"{self.current_slide_idx + 1}/{total}")
            self.slide_file_lbl.setText(slide["file"])
            self.slide_topic_lbl.setText(slide["topic"])
            self.slide_heading_lbl.setText(slide["heading"])
            self.slide_math_view.setHtml(render_markdown_with_katex(slide["math"]))

    def grab_live_screen_preview(self):
        """Captures a real scaled thumbnail of the primary display without lag."""
        if not self.isVisible():
            return
        if self.imported_pdf_slides:
            return  # If user explicitly attached slide deck, keep slide deck context active
        try:
            screen = QApplication.primaryScreen()
            if screen:
                pix = screen.grabWindow(0)
                if not pix.isNull():
                    target_w = self.screen_preview_lbl.width() or 316
                    target_h = self.screen_preview_lbl.height() or 120
                    scaled = pix.scaled(
                        target_w, target_h,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    self.screen_preview_lbl.setPixmap(scaled)
        except Exception as e:
            logger.debug("Live screen preview capture failed: %s", e)

    def update_screen_preview(self, image_data: Union[Image.Image, QPixmap, str]):
        """Updates the HUD screen preview widget with a new keyframe, snip or photo."""
        try:
            if isinstance(image_data, Image.Image):
                from PIL.ImageQt import ImageQt
                qimg = ImageQt(image_data)
                pix = QPixmap.fromImage(qimg)
            elif isinstance(image_data, str) and os.path.exists(image_data):
                pix = QPixmap(image_data)
            elif isinstance(image_data, QPixmap):
                pix = image_data
            else:
                return

            if not pix.isNull():
                target_w = self.screen_preview_lbl.width() or 316
                target_h = self.screen_preview_lbl.height() or 120
                scaled = pix.scaled(
                    target_w, target_h,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.screen_preview_lbl.setPixmap(scaled)
        except Exception as e:
            logger.debug("Failed to set screen preview pixmap: %s", e)

    def update_live_speech(self, text: str, speaker: str = "", timestamp: str = ""):
        """Updates the live spoken audio quote and speaker badge dynamically."""
        if text:
            clean_text = text.strip()
            if not clean_text.startswith('"') and not clean_text.startswith('“'):
                clean_text = f'"{clean_text}"'
            self.live_speech_lbl.setText(clean_text)
        if speaker or timestamp:
            spk = speaker or "Speaker Active"
            ts = timestamp or format_timestamp(time.time() - self.session_start_time)
            self.speaker_badge_lbl.setText(f"{spk}    @ {ts}")

    def _on_pin_user_directive(self):
        text = self.directive_input.text().strip()
        if not text:
            text = self.scratchpad_text.toPlainText().strip()
        if not text:
            return

        now_sec = time.time() - self.session_start_time
        time_str = format_timestamp(now_sec)
        self.pinned_directives.append({"text": text, "time": time_str})

        # Append to active session notes
        if self.notes_manager and hasattr(self.notes_manager, "append_user_directive"):
            self.notes_manager.append_user_directive(text, time_str)

        count = len(self.pinned_directives)
        count_suffix = f" ({count} active notes recorded)" if count > 1 else ""
        self.pinned_directive_lbl.setText(f'Active Directive: "{text}" [{time_str}] - Synced with AI summary{count_suffix}')
        self.pinned_directive_lbl.show()
        self.directive_input.clear()

        # Acknowledge in chat history
        self.chat_history.append(
            f"<div style='background:rgba(255,255,255,0.06); padding:6px 10px; border-radius:6px; margin:4px 0;'>"
            f"<b>[SYNC] Synchronized note:</b> <em>'{text}'</em> ({time_str}) with live audio & AI summary.</div>"
        )
        self.refresh_live_notes_view()

    def _insert_directive_chip(self, chip_text: str):
        self.directive_input.setText(chip_text)
        self.directive_input.setFocus()

    def _send_quick_chat(self, prompt: str):
        self.prompt_input.setText(prompt)
        self._send_copilot_prompt()

    def _test_settings_key(self):
        key = self.settings_key_input.text().strip()
        if not key:
            self.settings_key_feedback.setText("Please enter an API key.")
            self.settings_key_feedback.setStyleSheet("color: #F87171;")
            return
        self.settings_key_feedback.setText("Testing key...")
        self.settings_key_feedback.setStyleSheet("color: #94A3B8;")

        valid, msg = validate_api_key(key)
        if valid:
            self.settings_key_feedback.setText("✓ API key is valid and working.")
            self.settings_key_feedback.setStyleSheet("color: #F8FAFC; font-weight: 600;")
        else:
            self.settings_key_feedback.setText(f"✗ Validation failed: {msg[:60]}")
            self.settings_key_feedback.setStyleSheet("color: #F87171;")

    def _save_settings_key(self):
        key = self.settings_key_input.text().strip()
        if not key:
            self.settings_key_feedback.setText("Key cannot be empty.")
            self.settings_key_feedback.setStyleSheet("color: #F87171;")
            return
        set_api_key(key, "gemini")
        self.settings_key_feedback.setText("✓ API key saved securely to OS Vault.")
        self.settings_key_feedback.setStyleSheet("color: #F8FAFC; font-weight: 600;")

    def _on_settings_model_changed(self, idx: int):
        preset_id = self.settings_model_combo.currentData()
        if not preset_id:
            return
        set_selected_model(preset_id)
        preset = resolve_model_preset(preset_id)
        if self.pipeline and hasattr(self.pipeline, "apply_preset"):
            try:
                preset = self.pipeline.apply_preset(preset_id)
            except Exception as e:
                logger.warning("Pipeline apply_preset failed: %s", e)

        short_name = preset.get("short_name", preset_id)
        flash_m = preset.get("flash_model", "gemini-2.5-flash")
        pro_m = preset.get("pro_model", "gemini-2.5-pro")

        if hasattr(self, "chat_model_badge"):
            self.chat_model_badge.setText(short_name)
        if hasattr(self, "chat_history"):
            if preset.get("category") == "premium" or flash_m == pro_m:
                arch_desc = f"• Model: <span style='color:#F8FAFC;'>{flash_m}</span> (Operational & Synthesis)"
            else:
                arch_desc = f"• Operational: <span style='color:#F8FAFC;'>{flash_m}</span><br>• Synthesis: <span style='color:#F8FAFC;'>{pro_m}</span>"
            self.chat_history.append(
                f"<div style='font-size:10px; font-family:monospace; color:#94A3B8; "
                f"background:#15161B; border:1px solid rgba(255,255,255,0.1); border-radius:4px; padding:6px 10px; margin:4px 0;'>"
                f"<b style='color:#F8FAFC;'>[Model Setup Active]:</b><br>"
                f"{arch_desc}</div>"
            )

    def _browse_vault_path(self):
        d = QFileDialog.getExistingDirectory(self, "Select Obsidian Vault Directory", self.settings_vault_input.text())
        if d:
            self.settings_vault_input.setText(d)
            set_obsidian_vault_path(d)

    def apply_theme(self, theme: str):
        self.current_theme = theme
        if theme == "light":
            self.setStyleSheet(HUD_STYLESHEET_LIGHT)
            self.theme_light_btn.setObjectName("tabActive")
            self.theme_dark_btn.setObjectName("tabInactive")
        else:
            self.setStyleSheet(HUD_STYLESHEET_DARK)
            self.theme_dark_btn.setObjectName("tabActive")
            self.theme_light_btn.setObjectName("tabInactive")
        for b in [self.theme_dark_btn, self.theme_light_btn]:
            b.style().unpolish(b)
            b.style().polish(b)
        self.refresh_live_notes_view()
        self._navigate_slide(0)

    def change_language(self, lang: str):
        set_ui_language(lang)
        self.retranslate_ui()

    def get_scratchpad_content(self) -> str:
        parts = []
        if hasattr(self, "directive_input") and self.directive_input.text().strip():
            parts.append(self.directive_input.text().strip())
        if hasattr(self, "scratchpad_text") and self.scratchpad_text.toPlainText().strip():
            parts.append(self.scratchpad_text.toPlainText().strip())
        for p in self.pinned_directives:
            parts.append(f"[{p['time']}] {p['text']}")
        return "\n".join(parts)

    def toggle_visibility(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def set_daemon_status(self, state: str, message: str = ""):
        self._current_daemon_state = state
        self._current_daemon_msg = message

        if state == "recording":
            self.status_pill.setStyleSheet(
                "background-color: rgba(255, 255, 255, 0.08); border: 1px solid rgba(255, 255, 255, 0.18);"
                "color: #FFFFFF; font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 12px;"
            )
        elif state == "processing":
            self.status_pill.setText("⚡ Processing Chunk...")
            self.status_pill.setStyleSheet(
                "background-color: rgba(56, 189, 248, 0.15); border: 1px solid #38BDF8;"
                "color: #38BDF8; font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 12px;"
            )
        elif state == "paused":
            msg = f" ({message})" if message else ""
            self.status_pill.setText(f"⏸ Paused{msg}")
            self.status_pill.setStyleSheet(
                "background-color: rgba(251, 191, 36, 0.15); border: 1px solid #FBBF24;"
                "color: #FBBF24; font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 12px;"
            )
        elif state == "standby":
            self.status_pill.setText("Standby")
            self.status_pill.setStyleSheet(
                "background-color: rgba(255, 255, 255, 0.08); border: 1px solid rgba(255, 255, 255, 0.15);"
                "color: #94A3B8; font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 12px;"
            )

    def retranslate_ui(self):
        hud_shortcut = "Cmd+Shift+Space" if sys.platform == "darwin" else "Ctrl+Shift+Space"
        snip_shortcut = "Cmd+Shift+S" if sys.platform == "darwin" else "Ctrl+Shift+S"

        # Update language buttons
        cur_lang = get_ui_language()
        lang_btns = {
            "en": getattr(self, "lang_en_btn", None),
            "de": getattr(self, "lang_de_btn", None),
            "fr": getattr(self, "lang_fr_btn", None),
            "es": getattr(self, "lang_es_btn", None),
            "zh": getattr(self, "lang_zh_btn", None),
        }
        for l, btn in lang_btns.items():
            if btn:
                if l == cur_lang:
                    btn.setObjectName("tabActive")
                else:
                    btn.setObjectName("tabInactive")
                btn.style().unpolish(btn)
                btn.style().polish(btn)

        if hasattr(self, "hide_btn"):
            self.hide_btn.setToolTip(f"{tr('tray_hide_hud')} ({hud_shortcut})")
        if hasattr(self, "attach_doc_btn"):
            self.attach_doc_btn.setText(tr("btn_attach_slides"))
            self.attach_doc_btn.setToolTip(tr("btn_attach_slides"))
        if hasattr(self, "synth_btn"):
            self.synth_btn.setText(tr("btn_finish"))
            self.synth_btn.setToolTip(tr("btn_finish"))
        if hasattr(self, "snip_btn"):
            self.snip_btn.setText(tr("btn_snip_screen"))
            self.snip_btn.setToolTip(f"{tr('btn_snip_screen')} ({snip_shortcut})")
        if hasattr(self, "cam_btn"):
            self.cam_btn.setText(tr("btn_cam"))
            self.cam_btn.setToolTip(tr("btn_cam"))
        if hasattr(self, "tab_btn_notes"):
            self.tab_btn_notes.setText(tr("tab_notes"))
        if hasattr(self, "tab_btn_chat"):
            self.tab_btn_chat.setText(tr("tab_copilot"))
        if hasattr(self, "tab_btn_settings"):
            self.tab_btn_settings.setText(tr("btn_settings"))
        if hasattr(self, "copy_notes_btn"):
            self.copy_notes_btn.setText(tr("btn_copy_notes"))
        if hasattr(self, "send_btn"):
            self.send_btn.setText(tr("btn_send"))
        if hasattr(self, "prompt_input"):
            self.prompt_input.setPlaceholderText(tr("prompt_input_placeholder"))
        if hasattr(self, "directive_input"):
            self.directive_input.setPlaceholderText("Add note or instruction for the AI summary...")

        # HUD Settings Tab translations
        if hasattr(self, "settings_guide_btn"):
            is_guide_open = hasattr(self, "settings_guide_frame") and not self.settings_guide_frame.isHidden()
            self.settings_guide_btn.setText(tr("guide_toggle_btn_close" if is_guide_open else "guide_toggle_btn"))
        if hasattr(self, "settings_step1_lbl"):
            self.settings_step1_lbl.setText(f"<b>{tr('guide_step1_title')}</b><br>{tr('guide_step1_desc')}")
        if hasattr(self, "settings_step2_lbl"):
            self.settings_step2_lbl.setText(f"<b>{tr('guide_step2_title')}</b><br>{tr('guide_step2_desc')}")
        if hasattr(self, "settings_step3_lbl"):
            self.settings_step3_lbl.setText(f"<b>{tr('guide_step3_title')}</b><br>{tr('guide_step3_desc')}")
        if hasattr(self, "settings_model_combo"):
            curr_data = self.settings_model_combo.currentData()
            self.settings_model_combo.blockSignals(True)
            populate_preset_combobox(self.settings_model_combo, cur_lang)
            select_preset_in_combobox(self.settings_model_combo, curr_data)
            self.settings_model_combo.blockSignals(False)

        # Secondary actions
        if hasattr(self, "pdf_export_btn"):
            self.pdf_export_btn.setText(tr("btn_pdf_export"))
        if hasattr(self, "obsidian_btn"):
            self.obsidian_btn.setText(tr("btn_obsidian"))
        if hasattr(self, "rewind_btn"):
            self.rewind_btn.setText(tr("btn_rewind_90s"))
        if hasattr(self, "search_btn"):
            self.search_btn.setText(tr("btn_search_archive"))

        if hasattr(self, "screen_title_lbl"):
            self.screen_title_lbl.setText(tr("hud_screen_mirror"))

        self._update_hud_status()

    def _update_hud_status(self):
        if self.recorder and self.recorder.is_recording:
            if self.recorder.is_paused:
                self.set_daemon_status("paused")
            else:
                self.set_daemon_status("recording")

        elapsed_sec = int(time.time() - self.session_start_time)
        hrs = elapsed_sec // 3600
        mins = (elapsed_sec % 3600) // 60
        secs = elapsed_sec % 60

        cur_lang = get_ui_language()
        if self._current_daemon_state == "recording":
            state_text = tr("recording_status") if "recording_status" in tr.__globals__["TRANSLATIONS"].get(cur_lang, {}) else "Recording active"
            self.status_pill.setText(f"● {state_text} ({mins:02d}:{secs:02d})")

        # Live Duration Timer in Footer
        if cur_lang == "de":
            dur_str = f"Dauer: {hrs}h {mins:02d}m {secs:02d}s"
        elif cur_lang == "fr":
            dur_str = f"Durée : {hrs}h {mins:02d}m {secs:02d}s"
        elif cur_lang == "es":
            dur_str = f"Duración: {hrs}h {mins:02d}m {secs:02d}s"
        elif cur_lang == "zh":
            dur_str = f"时长：{hrs}小时{mins:02d}分{secs:02d}秒"
        else:
            dur_str = f"Duration: {hrs}h {mins:02d}m {secs:02d}s"
        self.footer_duration_lbl.setText(dur_str)

    def trigger_screen_snip(self):
        self.snip_overlay.start_snip()

    def _on_snip_received(self, pil_image: Image.Image):
        self.attached_snip_image = pil_image
        self._update_attachment_banner()
        self.show()
        self.raise_()
        self.activateWindow()
        self.switch_tab(1)
        self.prompt_input.setFocus()

    def _open_document_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Folien oder Skript einbinden",
            "",
            "Dokumente (*.pdf *.pptx *.ppt *.txt *.md)",
        )
        if path:
            self.load_reference_document(path)

    def load_reference_document(self, path: str):
        clean_path = os.path.expanduser(os.path.expandvars(path.strip()))
        if not os.path.exists(clean_path):
            logger.warning("Referenced file does not exist: %s", clean_path)
            return

        lower = clean_path.lower()
        if lower.endswith(".pdf"):
            try:
                import pypdf
                reader = pypdf.PdfReader(clean_path)
                slides = []
                for idx, page in enumerate(reader.pages):
                    try:
                        p_text = page.extract_text() or ""
                    except Exception:
                        p_text = ""
                    slides.append({
                        "page": idx + 1,
                        "text": p_text.strip(),
                    })
                self.imported_pdf_slides = slides
                self.imported_pdf_name = os.path.basename(clean_path)
                self.attached_document_name = self.imported_pdf_name

                deck_sections = []
                for s in self.imported_pdf_slides:
                    p_num = s["page"]
                    p_txt = s["text"]
                    if p_txt:
                        deck_sections.append(f"--- [Folie / Page {p_num}] ---\n{p_txt}")
                    else:
                        deck_sections.append(f"--- [Folie / Page {p_num}] ---\n[Abbildung / Folieninhalt]")

                total_pages = len(self.imported_pdf_slides)
                self.attached_document_text = (
                    f"IN-PERSON LECTURE SLIDE DECK: {self.imported_pdf_name} ({total_pages} Folien/Seiten)\n"
                    f"HINWEIS FÜR DIE SYNTHESE: Der Dozent präsentiert diese Folien im Hörsaal. Mappe gesprochenes "
                    f"Audio und studentische Fragen direkt auf die entsprechende Foliennummer (z. B. '[Folie X]').\n\n"
                    + "\n\n".join(deck_sections)
                )

                self.chat_history.append(
                    f"<b>[PDF] Folien bereit: {total_pages} Seiten ({self.imported_pdf_name})</b><br>"
                    "<i>In-Person Vorlesungsmodus: Gesprochene Inhalte werden automatisch den Folienseiten zugeordnet.</i>\n"
                )
                logger.info("Pre-imported %d PDF slide pages from '%s'", total_pages, clean_path)
                self.current_slide_idx = 0
                self._navigate_slide(0)
            except Exception as e:
                logger.error("pypdf extraction failed for '%s': %s", clean_path, e)
                self.imported_pdf_slides = []
                self.imported_pdf_name = None
                self.attached_document_text = read_local_file(clean_path)
                self.attached_document_name = os.path.basename(clean_path)
        else:
            self.imported_pdf_slides = []
            self.imported_pdf_name = None
            self.attached_document_text = read_local_file(clean_path)
            self.attached_document_name = os.path.basename(clean_path)

        self._update_attachment_banner()

    def get_relevant_reference_text(self, query_hint: str = "", max_chars: int = 40000) -> Optional[str]:
        if not self.attached_document_text and not self.imported_pdf_slides:
            return None

        if not self.imported_pdf_slides:
            return self.attached_document_text

        if len(self.attached_document_text) <= max_chars:
            return self.attached_document_text

        tokens = set(t.lower() for t in query_hint.split() if len(t) >= 4)
        scored_pages = []
        for s in self.imported_pdf_slides:
            score = 0
            text_lower = s["text"].lower()
            for token in tokens:
                if token in text_lower:
                    score += 1
            scored_pages.append((score, s["page"], s["text"]))

        scored_pages.sort(key=lambda x: (x[0], -x[1]), reverse=True)
        selected_pages = {}
        for _, p_num, p_text in scored_pages[:25]:
            selected_pages[p_num] = p_text

        total_pages = len(self.imported_pdf_slides)
        sections = [
            f"IN-PERSON LECTURE SLIDE DECK (RELEVANT EXTRACT): {self.imported_pdf_name} ({total_pages} Seiten)\n"
            f"HINWEIS: Ausgewählte Folienseiten passend zum aktuellen Vorlesungsabschnitt. Mappe gesprochene "
            f"Erklärungen direkt auf diese Foliennummern (z. B. '[Folie X]').\n"
        ]
        for p_num in sorted(selected_pages.keys()):
            p_text = selected_pages[p_num]
            if p_text:
                sections.append(f"--- [Folie / Page {p_num}] ---\n{p_text}")
            else:
                sections.append(f"--- [Folie / Page {p_num}] ---\n[Abbildung]")

        result = "\n\n".join(sections)
        return result[:max_chars]

    def _update_attachment_banner(self):
        tags = []
        if self.imported_pdf_slides:
            total_pages = len(self.imported_pdf_slides)
            deck_name = self.imported_pdf_name or "Script"
            tags.append(f"[PDF] {tr('status_slides_ready', count=total_pages)} ({deck_name})")
        elif self.attached_document_name:
            tags.append(f"[DOC] {self.attached_document_name}")
        if self.attached_snip_image:
            tags.append(f"[SNIP] Screen Snip ({self.attached_snip_image.width}x{self.attached_snip_image.height})")
        if self.whiteboard_photos:
            n_wb = len(self.whiteboard_photos)
            tags.append(f"[CAM] {tr('status_photo_ready', count=n_wb)}")

        if tags:
            self.attachment_label.setText(" | ".join(tags))
            self.attachment_label.show()
        else:
            self.attachment_label.hide()

    def _open_whiteboard_cam_dialog(self):
        if not self.companion_daemon.is_running:
            try:
                self.companion_daemon.start()
            except Exception as e:
                logger.error("Could not start CompanionDaemon: %s", e)
        dialog = WhiteboardCamDialog(self, daemon=self.companion_daemon)
        dialog.exec()

    def _open_settings_dialog(self):
        self.switch_tab(2)

    def _on_whiteboard_photo_received(self, image_path: str, timestamp_str: str):
        self.whiteboard_photos.append(image_path)
        logger.info("Whiteboard photo registered in HUD: %s", image_path)

        self.status_pill.setText(f"[CAM] PHOTO CAPTURED ({timestamp_str})")
        self.status_pill.setStyleSheet(
            "background-color: rgba(255, 255, 255, 0.12); border: 1px solid rgba(255, 255, 255, 0.28);"
            "color: #F8FAFC; font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 12px;"
        )
        QTimer.singleShot(3500, self._restore_pill_status)
        self._update_attachment_banner()

        n_photos = len(self.whiteboard_photos)
        self.chat_history.append(
            f"<span style='color:#F8FAFC;'><b>[CAM] Photo #{n_photos} captured ({timestamp_str}).</b> Prioritized in lecture notes.</span><br>"
        )

    def _restore_pill_status(self):
        self.status_pill.setStyleSheet(
            "background-color: rgba(255, 255, 255, 0.08); border: 1px solid rgba(255, 255, 255, 0.18);"
            "color: #FFFFFF; font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 12px;"
        )

    def pop_unprocessed_whiteboard_photos(self) -> List[str]:
        photos = list(self.whiteboard_photos)
        self.whiteboard_photos.clear()
        self._update_attachment_banner()
        return photos

    def _trigger_audio_rewind(self):
        if not self.recorder or not self.pipeline:
            self.chat_history.append("<i>[Audio recording inactive]</i>")
            return

        self.switch_tab(1)
        self.chat_history.append("<b>[REWIND] Fetching last 90s audio...</b>")
        self.play_audio_scrub(offset_seconds=0.0, duration=90.0)

        self.rewind_worker = RewindWorker(self.recorder, self.pipeline, seconds=90)
        self.rewind_worker.finished.connect(self._on_rewind_finished)
        self.rewind_worker.start()

    def _on_rewind_finished(self, transcript: str):
        rendered_html = render_markdown_with_katex(transcript)
        self.chat_history.append(f"<b>[Rewind 90s Transcript]:</b><div style='margin-top:4px;'>{rendered_html}</div><br>")
        self.refresh_live_notes_view()

    def _send_copilot_prompt(self):
        prompt = self.prompt_input.text().strip()
        if not prompt or not self.pipeline:
            return

        escaped_prompt = html.escape(prompt)
        self.chat_history.append(f"<b>You:</b> {escaped_prompt}")
        self.prompt_input.clear()
        self.send_btn.setEnabled(False)

        img = self.attached_snip_image
        doc = self.attached_document_text
        self.attached_snip_image = None
        self._update_attachment_banner()

        self.copilot_worker = CopilotWorker(self.pipeline, prompt, img, doc)
        self.copilot_worker.finished.connect(self._on_copilot_finished)
        self.copilot_worker.start()

    def _on_copilot_finished(self, response: str):
        self.send_btn.setEnabled(True)
        rendered_html = render_markdown_with_katex(response)
        self.chat_history.append(f"<b>Chalk:</b><div style='margin-top:4px;'>{rendered_html}</div><br>")
        self.refresh_live_notes_view()

    def refresh_live_notes_view(self):
        notes_path = self._get_active_notes_path()
        content = ""
        if notes_path and os.path.exists(notes_path):
            try:
                with open(notes_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                pass

        if not content.strip():
            scratchpad = self.get_scratchpad_content().strip()
            if scratchpad:
                content = f"# Active Notes Draft\n\n{scratchpad}"
            else:
                cur_lang = get_ui_language()
                if cur_lang == "de":
                    content = (
                        "# Kapitalmarktlinie & Systematisches Risiko\n\n"
                        "Die erwartete Rendite eines Wertpapiers setzt sich aus dem risikofreien Zins und der marktweiten Risikoprämie zusammen. "
                        "Das unsystematische Einzelrisiko wird durch Portfolio-Diversifikation eliminiert.\n\n"
                        "$$E(R_i) = R_f + \\beta_i \\left[E(R_m) - R_f\\right]$$\n\n"
                        "- **Beta-Faktor (\\beta_i):** Sensitivität der Rendite gegenüber Schwankungen des Gesamtmarktes.\n"
                        "- **Risikofreier Zins (R_f):** Rendite erstklassiger Staatsanleihen als Mindesthürde.\n"
                        "- **[Kernaussage Dozent @ 01:14:20]:** Nur systematisches Risiko wird vom Markt mit einer Prämie vergütet."
                    )
                else:
                    content = (
                        "# Capital Market Line & Systematic Risk\n\n"
                        "The expected return of an asset comprises the risk-free rate plus the market risk premium. "
                        "Unsystematic individual risk is eliminated through portfolio diversification.\n\n"
                        "$$E(R_i) = R_f + \\beta_i \\left[E(R_m) - R_f\\right]$$\n\n"
                        "- **Beta factor (\\beta_i):** Sensitivity of asset return to broad market movements.\n"
                        "- **Risk-free rate (R_f):** Benchmark sovereign bond yield as the hurdle rate.\n"
                        "- **[Lecturer Core Point @ 01:14:20]:** Only systematic risk is compensated by the market with a risk premium."
                    )

        rendered_html = render_markdown_with_katex(content)
        self.notes_browser.setHtml(rendered_html)

    def display_live_notes(self, markdown_notes: str):
        rendered_html = render_markdown_with_katex(markdown_notes)
        self.notes_browser.setHtml(rendered_html)

    # Audio Scrubbing & Floating Mini-Player Playback
    def _on_anchor_clicked(self, url: QUrl):
        url_str = url.toString()
        if url_str.startswith("chalk-audio://"):
            self.open_audio_url(url_str)
            sec = parse_audio_timestamp(url_str)
            self.chat_history.append(f"<i>[Audio-Scrubbing @ {format_timestamp(sec)}]</i>")
        elif url_str.startswith(("http://", "https://")):
            QDesktopServices.openUrl(url)
        else:
            logger.warning("Blocked potentially unsafe URL schema in HUD anchor click: %s", url_str)

    def open_audio_url(self, url_or_str: str):
        sec = parse_audio_timestamp(url_or_str)
        self.current_playback_offset = sec
        self.player_time_badge.setText(f"[{format_timestamp(sec)}]")
        self.player_pill.show()
        self.play_audio_slice(offset_seconds=sec, duration=20.0)

    def play_audio_slice(self, offset_seconds: float = 0.0, duration: float = 20.0):
        try:
            import sounddevice as sd
            import numpy as np

            sd.stop()
            if hasattr(self, "_play_timer") and self._play_timer:
                self._play_timer.stop()

            audio = None
            sr = 16000

            if self.recorder and hasattr(self.recorder, "journal") and self.recorder.journal:
                audio, seg_sr = self.recorder.journal.get_audio_slice(
                    target_timestamp_sec=offset_seconds, slice_duration=duration
                )
                if len(audio) > 0:
                    sr = seg_sr

            if (audio is None or len(audio) == 0) and self.recorder:
                # Only fall back to rewind buffer if offset is within the rolling rewind window
                current_elapsed = getattr(self.recorder, "total_frames_recorded", 0) / max(1, sr)
                if abs(current_elapsed - offset_seconds) <= getattr(self.recorder, "rewind_buffer_seconds", 90):
                    audio = self.recorder.get_rewind_audio(seconds=int(duration + 10))
                else:
                    audio = None

            if audio is not None and len(audio) > 0:
                speed = getattr(self, "player_speed", 1.0)
                playback_sr = int(sr * speed)
                sd.play(audio, playback_sr)
                self.is_playing_audio = True
                self.player_play_btn.setText("Pause")
                status_txt = tr("audio_slice_playing", sec=int(duration))
                self.player_status_lbl.setText(f"{status_txt} ({speed}x)")
                self.player_status_lbl.setStyleSheet("color: #38BDF8; font-size: 11px;")

                if hasattr(self, "_play_timer") and self._play_timer:
                    self._play_timer.stop()
                self._play_timer = QTimer(self)
                self._play_timer.setSingleShot(True)
                self._play_timer.timeout.connect(self._on_playback_completed)
                duration_ms = int(((len(audio) / sr) / speed) * 1000) + 200
                self._play_timer.start(duration_ms)
            else:
                self.player_status_lbl.setText(tr("no_audio_slice", default="Kein Audio-Ausschnitt verfügbar"))
                self.player_status_lbl.setStyleSheet("color: #F87171; font-size: 11px;")
                self.player_play_btn.setText("Play")
                self.is_playing_audio = False
        except Exception as e:
            logger.warning("Audio playback error: %s", e)
            self.player_status_lbl.setText("Wiedergabefehler")
            self.player_play_btn.setText("Play")
            self.is_playing_audio = False

    def play_audio_scrub(self, offset_seconds: float = 0.0, duration: float = 20.0):
        self.current_playback_offset = offset_seconds
        self.player_time_badge.setText(f"[{format_timestamp(offset_seconds)}]")
        self.player_pill.show()
        self.play_audio_slice(offset_seconds=offset_seconds, duration=duration)

    def _on_playback_completed(self):
        self.is_playing_audio = False
        self.player_play_btn.setText("Play")
        self.player_status_lbl.setText("20s Snippet beendet")
        self.player_status_lbl.setStyleSheet("color: #94A3B8; font-size: 11px;")

    def stop_audio_scrub(self):
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass
        if hasattr(self, "_play_timer") and self._play_timer:
            self._play_timer.stop()
        self.is_playing_audio = False
        self.player_play_btn.setText("▶")
        self.player_status_lbl.setText("Wiedergabe angehalten")
        self.player_status_lbl.setStyleSheet("color: #94A3B8; font-size: 11px;")

    def _toggle_audio_playback(self):
        if self.is_playing_audio:
            self.stop_audio_scrub()
        else:
            self.play_audio_slice(offset_seconds=getattr(self, "current_playback_offset", 0.0), duration=20.0)

    def _step_backward_5s(self):
        cur = getattr(self, "current_playback_offset", 0.0)
        self.current_playback_offset = max(0.0, cur - 5.0)
        self.player_time_badge.setText(f"[{format_timestamp(self.current_playback_offset)}]")
        self.play_audio_slice(offset_seconds=self.current_playback_offset, duration=20.0)

    def _step_forward_5s(self):
        cur = getattr(self, "current_playback_offset", 0.0)
        self.current_playback_offset = cur + 5.0
        self.player_time_badge.setText(f"[{format_timestamp(self.current_playback_offset)}]")
        self.play_audio_slice(offset_seconds=self.current_playback_offset, duration=20.0)

    def hide_audio_player_pill(self):
        self.stop_audio_scrub()
        self.player_pill.hide()

    def _cycle_playback_speed(self):
        speeds = [1.0, 1.25, 1.5, 2.0]
        cur = getattr(self, "player_speed", 1.0)
        try:
            next_idx = (speeds.index(cur) + 1) % len(speeds)
        except ValueError:
            next_idx = 0
        self.player_speed = speeds[next_idx]
        self.player_speed_btn.setText(f"{self.player_speed}x")
        if getattr(self, "is_playing_audio", False):
            self.play_audio_slice(offset_seconds=getattr(self, "current_playback_offset", 0.0), duration=20.0)

    def _export_anki_flashcards(self):
        notes_path = self._get_active_notes_path()
        content = ""
        if notes_path and os.path.exists(notes_path):
            try:
                with open(notes_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                content = ""

        if not content.strip():
            content = self.get_scratchpad_content().strip()

        cards = extract_flashcards_from_markdown(content)
        if not cards:
            self.chat_history.append(f"<i>[{tr('no_flashcards')}]</i>")
            return

        export_dir = os.path.expanduser("~/Documents")
        os.makedirs(export_dir, exist_ok=True)
        today_str = time.strftime("%Y%m%d_%H%M%S")
        tsv_path = os.path.join(export_dir, f"Chalk_Flashcards_{today_str}.tsv")

        success = export_flashcards_to_tsv(cards, tsv_path)
        if success:
            orig_text = self.anki_export_btn.text()
            self.anki_export_btn.setText(tr("export_success"))
            QTimer.singleShot(2500, lambda: self.anki_export_btn.setText(orig_text))
            self.chat_history.append(f"<b>[Anki TSV Export]</b> {len(cards)} Flashcards -> <code>{tsv_path}</code>")
        else:
            self.chat_history.append("<span style='color: #F87171;'>Export error.</span>")

    def _export_notes_pdf(self):
        notes_path = self._get_active_notes_path()
        content = ""
        if notes_path and os.path.exists(notes_path):
            try:
                with open(notes_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                content = ""

        if not content.strip():
            content = self.get_scratchpad_content().strip()
            if not content:
                content = "# Chalk Notizen\n\n*(Keine Inhalte zum Exportieren verfügbar)*\n"

        export_dir = os.path.expanduser("~/Documents")
        os.makedirs(export_dir, exist_ok=True)
        today_str = time.strftime("%Y%m%d_%H%M%S")
        pdf_path = os.path.join(export_dir, f"Chalk_Notes_{today_str}.pdf")

        title = "Chalk Vorlesungsnotizen"
        if notes_path:
            title = os.path.splitext(os.path.basename(notes_path))[0].replace("_", " ")

        success = export_notes_to_pdf(content, pdf_path, title=title)
        if success:
            orig_text = self.pdf_export_btn.text()
            self.pdf_export_btn.setText("PDF Fertig [OK]")
            QTimer.singleShot(2500, lambda: self.pdf_export_btn.setText(orig_text))
            self.chat_history.append(f"<b>[PDF Export]</b> Akademisches Skript gespeichert: <code>{pdf_path}</code>")
        else:
            self.chat_history.append("<span style='color: #F87171;'>Fehler beim Generieren des PDFs.</span>")

    def _open_archive_search(self):
        dialog = SessionArchiveSearchDialog(self)
        dialog.result_selected.connect(self._on_search_result_selected)
        dialog.exec()

    def _on_search_result_selected(self, file_path: str, timestamp_sec: float):
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                self.notes_browser.setHtml(f"<div style='font-family: -apple-system, sans-serif; color: #F8FAFC;'><pre>{content}</pre></div>")
                self.switch_tab(0)
                self.chat_history.append(f"<i>[Geladene Notiz aus Archiv: {os.path.basename(file_path)}]</i>")
            except Exception as e:
                logger.warning("Failed to preview search file: %s", e)

        if timestamp_sec > 0:
            self.open_audio_url(f"chalk-audio://{int(timestamp_sec)}")

    def _get_active_notes_path(self) -> Optional[str]:
        if self.notes_manager and hasattr(self.notes_manager, "session_file"):
            if os.path.exists(self.notes_manager.session_file):
                return self.notes_manager.session_file

        # Fallback to configured Chalk notes directory (~/Documents/Chalk)
        docs_dir = getattr(self.notes_manager, "notes_dir", None) or os.path.join(os.path.expanduser("~"), "Documents", "Chalk")
        if os.path.exists(docs_dir):
            md_files = [
                os.path.join(docs_dir, f)
                for f in os.listdir(docs_dir)
                if f.endswith(".md")
            ]
            if md_files:
                md_files.sort(key=os.path.getmtime, reverse=True)
                return md_files[0]
        return None

    def _copy_notes_to_clipboard(self):
        notes_path = self._get_active_notes_path()
        content = ""
        if notes_path and os.path.exists(notes_path):
            try:
                with open(notes_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                content = ""

        if not content.strip():
            scratchpad = self.get_scratchpad_content().strip()
            content = scratchpad if scratchpad else "# Chalk Lecture Notes\n\n*(Session in progress)*\n"

        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(content)
            orig_text = self.copy_notes_btn.text()
            self.copy_notes_btn.setText("Copied [OK]")
            QTimer.singleShot(2000, lambda: self.copy_notes_btn.setText(orig_text))

    def _open_in_obsidian(self):
        notes_path = self._get_active_notes_path()
        if not notes_path:
            notes_dir = os.path.abspath("Notes")
            os.makedirs(notes_dir, exist_ok=True)
            today_str = time.strftime("%Y-%m-%d")
            notes_path = os.path.join(notes_dir, f"Lecture_{today_str}.md")
            if not os.path.exists(notes_path):
                try:
                    with open(notes_path, "w", encoding="utf-8") as f:
                        f.write(f"# Chalk Lecture Notes — {today_str}\n\n")
                except Exception:
                    pass

        vault_path = find_local_obsidian_vault()
        if vault_path and os.path.exists(vault_path) and notes_path:
            if not notes_path.startswith(vault_path):
                vault_chalk_dir = os.path.join(vault_path, "Chalk Notes")
                os.makedirs(vault_chalk_dir, exist_ok=True)
                target_note_in_vault = os.path.join(vault_chalk_dir, os.path.basename(notes_path))
                try:
                    import shutil
                    shutil.copy2(notes_path, target_note_in_vault)
                    notes_path = target_note_in_vault
                except Exception:
                    pass

        if notes_path and os.path.exists(notes_path):
            encoded_path = QUrl.toPercentEncoding(notes_path).data().decode("utf-8")
            obsidian_uri = f"obsidian://open?path={encoded_path}"
            opened = QDesktopServices.openUrl(QUrl(obsidian_uri))
            if not opened:
                self._open_in_default_editor()
            else:
                self.chat_history.append(f"<i>[In Obsidian geöffnet: {os.path.basename(notes_path)}]</i>")

    def _open_in_default_editor(self):
        notes_path = self._get_active_notes_path()
        if not notes_path:
            notes_dir = os.path.abspath("Notes")
            os.makedirs(notes_dir, exist_ok=True)
            today_str = time.strftime("%Y-%m-%d")
            notes_path = os.path.join(notes_dir, f"Lecture_{today_str}.md")
            if not os.path.exists(notes_path):
                try:
                    with open(notes_path, "w", encoding="utf-8") as f:
                        f.write(f"# Chalk Lecture Notes — {today_str}\n\n")
                except Exception:
                    pass

        if notes_path and os.path.exists(notes_path):
            if sys.platform == "darwin":
                subprocess.Popen(["open", notes_path])
            elif sys.platform == "win32":
                os.startfile(notes_path)
            else:
                subprocess.Popen(["xdg-open", notes_path])
            self.chat_history.append(f"<i>[Im Standard-Editor geöffnet: {os.path.basename(notes_path)}]</i>")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    fp = url.toLocalFile().lower()
                    if fp.endswith((".pdf", ".pptx", ".ppt", ".txt", ".md")):
                        event.acceptProposedAction()
                        return
        super().dragEnterEvent(event)

    def dropEvent(self, event):
        handled = False
        for url in event.mimeData().urls():
            if url.isLocalFile():
                file_path = url.toLocalFile()
                if file_path.lower().endswith((".pdf", ".pptx", ".ppt", ".txt", ".md")):
                    self.load_reference_document(file_path)
                    handled = True
                    break
        if handled:
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def show_socratic_debrief(self, source: Union[str, List[str]]):
        questions = []
        if isinstance(source, list):
            questions = [str(q).strip() for q in source if str(q).strip()]
        elif isinstance(source, str):
            pattern = re.compile(
                r">\s*\[!question\]\s*Socratic Active Recall(.*?)(?=\n> \[|\n## |\n<!-- CHUNK_STATE|\Z)",
                re.DOTALL | re.IGNORECASE,
            )
            match = pattern.search(source)
            if match:
                q_block = match.group(1)
                for line in q_block.splitlines():
                    cleaned = re.sub(r"^>\s*(?:\d+\.|\-|\*)\s*", "", line).strip()
                    if cleaned and not cleaned.startswith(">") and not cleaned.startswith("[!"):
                        questions.append(cleaned)

        if not questions:
            questions = [
                tr("debrief_q1"),
                tr("debrief_q2"),
                tr("debrief_q3"),
            ]

        questions = questions[:3]
        qs_html = "".join([f"<li style='margin-bottom: 5px; color: #E2E8F0; line-height: 1.4;'>{html.escape(q)}</li>" for q in questions])
        header_text = tr("debrief_header")
        debrief_card = (
            "<div style='border: 1px solid rgba(255, 255, 255, 0.15); border-radius: 8px; "
            "background-color: #1A1C23; padding: 12px; margin: 10px 0;'>"
            f"<div style='font-size: 11px; font-weight: 700; color: #94A3B8; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 8px;'>"
            f"{header_text}</div>"
            f"<ol style='margin: 0; padding-left: 20px; font-size: 12px;'>{qs_html}</ol>"
            "</div>"
        )

        self.switch_tab(1)
        self.chat_history.append(debrief_card)

        notes_path = self._get_active_notes_path()
        if notes_path and os.path.exists(notes_path):
            try:
                with open(notes_path, "r", encoding="utf-8") as f:
                    current_notes = f.read()
                if "[!question] Socratic Active Recall" not in current_notes:
                    callout_lines = [
                        "\n\n> [!question] Socratic Active Recall",
                    ]
                    for idx, q in enumerate(questions, 1):
                        callout_lines.append(f"> {idx}. {q}")
                    callout_lines.append("\n")
                    with open(notes_path, "a", encoding="utf-8") as f:
                        f.write("\n".join(callout_lines))
                    logger.info("Appended Socratic Active Recall callout to notes: %s", notes_path)
            except Exception as e:
                logger.warning("Could not auto-append socratic callout to notes: %s", e)

    def closeEvent(self, event):
        if hasattr(self, "companion_daemon") and self.companion_daemon:
            self.companion_daemon.stop()
        super().closeEvent(event)
