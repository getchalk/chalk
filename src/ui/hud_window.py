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
from typing import Optional
from PIL import Image

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QPoint, QUrl
from PyQt6.QtGui import QFont, QIcon, QColor, QPainter, QBrush, QPen, QPixmap, QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
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
)

from src.ui.snip_overlay import SnipOverlayWidget
from src.api.tools import read_local_file

logger = logging.getLogger("chalk.ui.hud")

HUD_STYLESHEET = """
QWidget#hudRoot {
    background-color: rgba(18, 19, 23, 0.96);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 16px;
    color: #F8FAFC;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, sans-serif;
}
QLabel {
    color: #E2E8F0;
}
QPushButton {
    background-color: rgba(26, 28, 35, 0.85);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 8px;
    color: #CBD5E1;
    padding: 6px 12px;
    font-size: 12px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: rgba(38, 41, 52, 0.95);
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
QTextEdit, QTextBrowser, QLineEdit {
    background-color: rgba(21, 22, 27, 0.95);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 8px;
    color: #F8FAFC;
    padding: 8px;
    font-size: 12px;
}
QTextEdit:focus, QTextBrowser:focus, QLineEdit:focus {
    border: 1px solid rgba(255, 255, 255, 0.4);
}
QFrame#playerBar {
    background-color: rgba(26, 28, 35, 0.9);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 10px;
    padding: 4px 10px;
}
QSlider::groove:horizontal {
    border: none;
    height: 4px;
    background: rgba(255, 255, 255, 0.15);
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: #FFFFFF;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #FFFFFF;
    border: none;
    width: 10px;
    height: 10px;
    margin: -3px 0;
    border-radius: 5px;
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
QPushButton#pillBtn:hover {
    background-color: rgba(55, 60, 75, 0.95);
    color: #FFFFFF;
    border-color: rgba(255, 255, 255, 0.3);
}
QPushButton#pillCloseBtn {
    background: transparent;
    border: none;
    color: #94A3B8;
    font-size: 13px;
    font-weight: 700;
    padding: 2px 6px;
}
QPushButton#pillCloseBtn:hover {
    color: #FFFFFF;
}
"""


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

    # Convert audio timestamp links [HH:MM:SS](chalk-audio://HH:MM:SS)
    text = re.sub(
        r"\[([0-9:]+)\]\(chalk-audio://([0-9:]+)\)",
        r'<a href="chalk-audio://\2" style="color:#60A5FA; text-decoration:none; '
        r'font-weight:600; font-family:monospace; background:rgba(255,255,255,0.08); '
        r'padding:1px 5px; border-radius:4px;">⏱️ [\1]</a>',
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
        "definition": ("#34D399", "DEFINITION"),
        "proof": ("#A78BFA", "BEWEIS / PROOF"),
        "remark": ("#FBBF24", "HINWEIS / REMARK"),
        "example": ("#38BDF8", "BEISPIEL / EXAMPLE"),
    }
    for ctype, (color, label) in callout_colors.items():
        pat = re.compile(rf"^>\s*\[!{ctype}\]\s*(.*?)$", flags=re.MULTILINE | re.IGNORECASE)
        text = pat.sub(
            rf'<div style="background:#1A1C23; border:1px solid rgba(255,255,255,0.12); '
            rf'border-left:4px solid {color}; border-radius:6px; padding:8px 12px; margin:8px 0;">'
            rf'<div style="font-weight:700; color:{color}; font-size:11px; margin-bottom:4px; font-family:sans-serif;">{label}: \1</div>',
            text
        )

    text = text.replace("\n> ", "\n<br>")
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


class FloatingHUDWindow(QWidget):
    """
    Floating Agent HUD window triggered via Alt + Space.
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

        # State
        self.session_start_time = time.time()
        self.drag_position = QPoint()
        self.is_playing_audio = False

        # Snip overlay tool
        self.snip_overlay = SnipOverlayWidget()
        self.snip_overlay.snip_captured.connect(self._on_snip_received)

        self._setup_window_properties()
        self._setup_ui()

        # Update timer for HUD status and session duration
        self.hud_timer = QTimer(self)
        self.hud_timer.timeout.connect(self._update_hud_status)
        self.hud_timer.start(1000)

    def _setup_window_properties(self):
        self.setObjectName("hudRoot")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAcceptDrops(True)
        self.resize(780, 560)
        self.setStyleSheet(HUD_STYLESHEET)

        # Center on upper part of primary screen
        screen = self.screen().geometry()
        x = (screen.width() - self.width()) // 2
        y = max(40, (screen.height() - self.height()) // 4)
        self.move(x, y)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 16, 18, 16)
        main_layout.setSpacing(12)

        # Header Row (Window Drag Handle & Status)
        header = QHBoxLayout()
        header.setSpacing(10)

        # Logo & App Title
        logo_layout = QHBoxLayout()
        logo_layout.setSpacing(6)

        logo_icon_lbl = QLabel()
        icon_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "assets", "app.png"))
        if os.path.exists(icon_path):
            pix = QPixmap(icon_path).scaled(18, 18, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            logo_icon_lbl.setPixmap(pix)
            logo_layout.addWidget(logo_icon_lbl)

        app_badge = QLabel("CHALK")
        app_badge.setStyleSheet("font-weight: 700; font-size: 13px; letter-spacing: 1.5px; color: #F8FAFC;")
        logo_layout.addWidget(app_badge)
        header.addLayout(logo_layout)

        # Recording Status Pill
        self.status_pill = QLabel("AUFNAHME AKTIV (00:00)")
        self.status_pill.setStyleSheet(
            "background-color: rgba(255, 255, 255, 0.08); border: 1px solid rgba(255, 255, 255, 0.18);"
            "color: #FFFFFF; font-size: 11px; font-weight: 600; padding: 4px 10px; border-radius: 12px;"
        )
        header.addWidget(self.status_pill)

        header.addStretch()

        # Minimize / Hide button
        hide_btn = QPushButton("✕")
        hide_btn.setFixedSize(28, 28)
        hud_shortcut = "Cmd+Shift+Space" if sys.platform == "darwin" else "Ctrl+Shift+Space"
        hide_btn.setToolTip(f"HUD ausblenden ({hud_shortcut} zum Einblenden)")
        hide_btn.clicked.connect(self.hide)
        header.addWidget(hide_btn)

        main_layout.addLayout(header)

        # Quick Actions Bar
        actions_bar = QHBoxLayout()
        actions_bar.setSpacing(8)

        self.attach_doc_btn = QPushButton("📎 Folien anhängen")
        self.attach_doc_btn.setToolTip("Folien oder Skript einbinden (.pdf, .pptx)")
        self.attach_doc_btn.clicked.connect(self._open_document_dialog)
        actions_bar.addWidget(self.attach_doc_btn)

        snip_shortcut = "Cmd+Shift+S" if sys.platform == "darwin" else "Ctrl+Shift+S"
        self.snip_btn = QPushButton(f"✂️ Snip ({snip_shortcut})")
        self.snip_btn.setToolTip(f"Bildschirmbereich zuschneiden ({snip_shortcut} / Alt+S)")
        self.snip_btn.clicked.connect(self.trigger_screen_snip)
        actions_bar.addWidget(self.snip_btn)

        self.rewind_btn = QPushButton("⏮️ Rewind 90s")
        self.rewind_btn.setToolTip("Letzte 90 Sekunden Audio abrufen, abspielen und transkribieren")
        self.rewind_btn.clicked.connect(self._trigger_audio_rewind)
        actions_bar.addWidget(self.rewind_btn)

        self.copy_notes_btn = QPushButton("📋 Notizen kopieren")
        self.copy_notes_btn.setToolTip("Notizen und Gliederung in Zwischenablage kopieren")
        self.copy_notes_btn.clicked.connect(self._copy_notes_to_clipboard)
        actions_bar.addWidget(self.copy_notes_btn)

        self.obsidian_btn = QPushButton("📓 Obsidian")
        self.obsidian_btn.setToolTip("Notizen direkt in Obsidian öffnen")
        self.obsidian_btn.clicked.connect(self._open_in_obsidian)
        actions_bar.addWidget(self.obsidian_btn)

        self.editor_btn = QPushButton("↗️ Editor")
        self.editor_btn.setToolTip("Notizen im Standard-Markdown-Editor öffnen")
        self.editor_btn.clicked.connect(self._open_in_default_editor)
        actions_bar.addWidget(self.editor_btn)

        actions_bar.addStretch()

        self.synth_btn = QPushButton("Beenden (F9)")
        self.synth_btn.setObjectName("primaryAction")
        self.synth_btn.setToolTip("Sitzung beenden und finale Notizen synthetisieren")
        self.synth_btn.clicked.connect(lambda: self.request_master_synthesis.emit())
        actions_bar.addWidget(self.synth_btn)

        main_layout.addLayout(actions_bar)

        # Attachments Banner (if doc or snip attached)
        self.attachment_label = QLabel("")
        self.attachment_label.setStyleSheet("color: #E2E8F0; font-size: 11px;")
        self.attachment_label.hide()
        main_layout.addWidget(self.attachment_label)

        # Splitter: Left = User Scratchpad, Right = Copilot & Scrub Transcript
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background-color: rgba(255, 255, 255, 0.08); width: 2px; }")

        # Left Column: User Scratchpad
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 6, 0)
        left_layout.setSpacing(6)

        scratchpad_label = QLabel("📝 User Scratchpad (Shorthand & Outline Anchor):")
        scratchpad_label.setStyleSheet("font-size: 11px; font-weight: 600; color: #94A3B8;")
        left_layout.addWidget(scratchpad_label)

        self.scratchpad_text = QTextEdit()
        self.scratchpad_text.setPlaceholderText(
            "- Jot shorthand bullets or quick thoughts here...\n"
            "- Chalk weaves your bullets into the structured synthesis\n"
            "- Scrubbable audio timestamp links created automatically\n"
            "- Drag & drop slides (.pdf, .pptx) anywhere onto HUD"
        )
        left_layout.addWidget(self.scratchpad_text)
        splitter.addWidget(left_widget)

        # Right Column: Interactive Copilot & Scrub Transcript
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(6, 0, 0, 0)
        right_layout.setSpacing(6)

        # Right Column Header Switcher: [💬 Copilot & Verlauf] [📐 Live KaTeX Notizen]
        switcher_row = QHBoxLayout()
        switcher_row.setSpacing(6)

        self.btn_view_chat = QPushButton("💬 Copilot & Verlauf")
        self.btn_view_chat.setStyleSheet("background-color: rgba(255, 255, 255, 0.16); color: #FFFFFF; font-weight: 600; padding: 4px 10px; font-size: 11px;")
        self.btn_view_chat.clicked.connect(self._show_chat_view)
        switcher_row.addWidget(self.btn_view_chat)

        self.btn_view_notes = QPushButton("📐 Live KaTeX Notizen")
        self.btn_view_notes.setStyleSheet("background-color: rgba(26, 28, 35, 0.85); color: #94A3B8; font-weight: 500; padding: 4px 10px; font-size: 11px;")
        self.btn_view_notes.clicked.connect(self._show_notes_view)
        switcher_row.addWidget(self.btn_view_notes)

        switcher_row.addStretch()
        right_layout.addLayout(switcher_row)

        # Stacked viewer: 0 = Chat & Scrubber, 1 = Live KaTeX Notes
        self.right_stack = QStackedWidget()

        self.chat_history = QTextBrowser()
        self.chat_history.setReadOnly(True)
        self.chat_history.setOpenExternalLinks(False)
        self.chat_history.setOpenLinks(False)
        self.chat_history.anchorClicked.connect(self._on_anchor_clicked)
        self.chat_history.setPlaceholderText("Antworten, Rewind-Transkripte und klickbare Zeitstempel [HH:MM:SS] erscheinen hier...")
        self.right_stack.addWidget(self.chat_history)

        self.notes_browser = QTextBrowser()
        self.notes_browser.setReadOnly(True)
        self.notes_browser.setOpenExternalLinks(False)
        self.notes_browser.setOpenLinks(False)
        self.notes_browser.anchorClicked.connect(self._on_anchor_clicked)
        self.notes_browser.setPlaceholderText("Live KaTeX gerenderte Notizen mit echten mathematischen Formeln erscheinen hier...")
        self.right_stack.addWidget(self.notes_browser)

        right_layout.addWidget(self.right_stack)

        prompt_row = QHBoxLayout()
        prompt_row.setSpacing(8)
        self.prompt_input = QLineEdit()
        self.prompt_input.setPlaceholderText("Frage stellen oder Folie erklären lassen...")
        self.prompt_input.returnPressed.connect(self._send_copilot_prompt)
        prompt_row.addWidget(self.prompt_input)

        self.send_btn = QPushButton("Senden")
        self.send_btn.clicked.connect(self._send_copilot_prompt)
        prompt_row.addWidget(self.send_btn)

        right_layout.addLayout(prompt_row)
        splitter.addWidget(right_widget)

        splitter.setSizes([330, 410])
        main_layout.addWidget(splitter)

        # Floating Mini-Player Pill ([⏮ -5s] [▶/⏸] [⏭ +5s] [01:24:15] ✕)
        self.player_pill = QFrame()
        self.player_pill.setObjectName("playerPill")
        pill_layout = QHBoxLayout(self.player_pill)
        pill_layout.setContentsMargins(10, 4, 10, 4)
        pill_layout.setSpacing(8)

        self.player_rewind_btn = QPushButton("⏮ -5s")
        self.player_rewind_btn.setObjectName("pillBtn")
        self.player_rewind_btn.setToolTip("5 Sekunden zurückspringen")
        self.player_rewind_btn.clicked.connect(self._step_backward_5s)
        pill_layout.addWidget(self.player_rewind_btn)

        self.player_play_btn = QPushButton("▶")
        self.player_play_btn.setObjectName("pillBtn")
        self.player_play_btn.setFixedSize(36, 26)
        self.player_play_btn.setToolTip("Wiedergabe starten/anhalten")
        self.player_play_btn.clicked.connect(self._toggle_audio_playback)
        pill_layout.addWidget(self.player_play_btn)

        self.player_forward_btn = QPushButton("⏭ +5s")
        self.player_forward_btn.setObjectName("pillBtn")
        self.player_forward_btn.setToolTip("5 Sekunden vorwärtsspringen")
        self.player_forward_btn.clicked.connect(self._step_forward_5s)
        pill_layout.addWidget(self.player_forward_btn)

        self.player_time_badge = QLabel("[00:00]")
        self.player_time_badge.setStyleSheet(
            "color: #FFFFFF; font-weight: 700; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px;"
        )
        pill_layout.addWidget(self.player_time_badge)

        self.player_status_lbl = QLabel("20s Audio-Ausschnitt")
        self.player_status_lbl.setStyleSheet("color: #94A3B8; font-size: 11px;")
        pill_layout.addWidget(self.player_status_lbl)

        pill_layout.addStretch()

        self.player_close_btn = QPushButton("✕")
        self.player_close_btn.setObjectName("pillCloseBtn")
        self.player_close_btn.setToolTip("Mini-Player schließen")
        self.player_close_btn.clicked.connect(self.hide_audio_player_pill)
        pill_layout.addWidget(self.player_close_btn)

        main_layout.addWidget(self.player_pill)
        self.player_pill.hide()

    def get_scratchpad_content(self) -> str:
        """Returns the current student scratchpad text."""
        return self.scratchpad_text.toPlainText()

    def toggle_visibility(self):
        """Toggle HUD window visibility (Alt+Space)."""
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def set_daemon_status(self, state: str, message: str = ""):
        mins = int((time.time() - self.session_start_time) // 60)
        secs = int((time.time() - self.session_start_time) % 60)
        time_str = f"{mins:02d}:{secs:02d}"

        if state == "recording":
            self.status_pill.setText(f"AUFNAHME AKTIV ({time_str})")
            self.status_pill.setStyleSheet(
                "background-color: rgba(255, 255, 255, 0.08); border: 1px solid rgba(255, 255, 255, 0.2);"
                "color: #FFFFFF; font-size: 11px; font-weight: 600; padding: 4px 10px; border-radius: 12px;"
            )
        elif state in ("paused", "standby"):
            lbl = f"STANDBY ({message})" if message else f"PAUSIERT ({time_str})"
            self.status_pill.setText(lbl)
            self.status_pill.setStyleSheet(
                "background-color: rgba(255, 255, 255, 0.04); border: 1px solid rgba(255, 255, 255, 0.1);"
                "color: #94A3B8; font-size: 11px; font-weight: 500; padding: 4px 10px; border-radius: 12px;"
            )
        elif state == "processing":
            self.status_pill.setText("VERARBEITE NOTIZEN...")
            self.status_pill.setStyleSheet(
                "background-color: rgba(255, 255, 255, 0.12); border: 1px solid rgba(255, 255, 255, 0.25);"
                "color: #FFFFFF; font-size: 11px; font-weight: 600; padding: 4px 10px; border-radius: 12px;"
            )

    def _update_hud_status(self):
        if self.recorder and self.recorder.is_recording:
            if self.recorder.is_paused:
                self.set_daemon_status("paused")
            else:
                self.set_daemon_status("recording")

        mins = int((time.time() - self.session_start_time) // 60)
        secs = int((time.time() - self.session_start_time) % 60)
        self.player_time_lbl.setText(f"{mins:02d}:{secs:02d}")

    def trigger_screen_snip(self):
        self.snip_overlay.start_snip()

    def _on_snip_received(self, pil_image: Image.Image):
        self.attached_snip_image = pil_image
        self._update_attachment_banner()
        self.show()
        self.raise_()
        self.activateWindow()
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

                # Build full structured slide deck markdown with page markers
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
                    f"<b>📚 Folien bereit: {total_pages} Seiten ({self.imported_pdf_name})</b><br>"
                    "<i>In-Person Vorlesungsmodus: Gesprochene Inhalte werden automatisch den Folienseiten zugeordnet.</i>\n"
                )
                logger.info("Pre-imported %d PDF slide pages from '%s'", total_pages, clean_path)
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
        """
        Returns relevant reference text for live chunk synthesis.
        If PDF slides are imported, formats the relevant slide pages (or all if under max_chars)
        so that live audio maps directly to the correct PDF slide page during in-person lectures.
        """
        if not self.attached_document_text and not self.imported_pdf_slides:
            return None

        if not self.imported_pdf_slides:
            return self.attached_document_text

        # If total text fits within max_chars, return full attached_document_text
        if len(self.attached_document_text) <= max_chars:
            return self.attached_document_text

        # For large slide decks (>max_chars): prioritize matching pages
        tokens = set(t.lower() for t in query_hint.split() if len(t) >= 4)
        scored_pages = []
        for s in self.imported_pdf_slides:
            score = 0
            text_lower = s["text"].lower()
            for token in tokens:
                if token in text_lower:
                    score += 1
            scored_pages.append((score, s["page"], s["text"]))

        # Sort by score descending, preserving page order for ties
        scored_pages.sort(key=lambda x: (x[0], -x[1]), reverse=True)

        selected_pages = {}
        # Pick top scoring pages (or first pages if score == 0)
        for _, p_num, p_text in scored_pages[:25]:
            selected_pages[p_num] = p_text

        # Format selected pages in ascending page order
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
            deck_name = self.imported_pdf_name or "Vorlesungsskript"
            tags.append(f"📚 Folien bereit: {total_pages} Seiten ({deck_name})")
        elif self.attached_document_name:
            tags.append(f"📄 {self.attached_document_name}")
        if self.attached_snip_image:
            tags.append(f"✂️ Screen Snip ({self.attached_snip_image.width}x{self.attached_snip_image.height})")

        if tags:
            self.attachment_label.setText(" | ".join(tags))
            self.attachment_label.setStyleSheet(
                "background-color: rgba(255, 255, 255, 0.08); "
                "border: 1px solid rgba(255, 255, 255, 0.2); "
                "color: #F8FAFC; font-size: 11px; padding: 4px 10px; "
                "border-radius: 8px; font-weight: 600;"
            )
            self.attachment_label.show()
        else:
            self.attachment_label.hide()

    def _trigger_audio_rewind(self):
        if not self.recorder or not self.pipeline:
            self.chat_history.append("<i>[Audio-Aufnahme nicht aktiv]</i>")
            return

        self.chat_history.append("<b>⏮️ Rufe letzte 90 Sekunden Audio ab...</b>")
        self.play_audio_scrub(offset_seconds=0.0, duration=90.0)

        self.rewind_worker = RewindWorker(self.recorder, self.pipeline, seconds=90)
        self.rewind_worker.finished.connect(self._on_rewind_finished)
        self.rewind_worker.start()

    def _on_rewind_finished(self, transcript: str):
        rendered_html = render_markdown_with_katex(transcript)
        self.chat_history.append(f"<b>[Rewind 90s Transkript]:</b><div style='margin-top:4px;'>{rendered_html}</div><br>")
        self.refresh_live_notes_view()

    def _send_copilot_prompt(self):
        prompt = self.prompt_input.text().strip()
        if not prompt or not self.pipeline:
            return

        self.chat_history.append(f"<b>Du:</b> {prompt}")
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

    def _show_chat_view(self):
        """Switches right pane to Copilot & Audio-Scrubbing history."""
        self.right_stack.setCurrentIndex(0)
        self.btn_view_chat.setStyleSheet("background-color: rgba(255, 255, 255, 0.16); color: #FFFFFF; font-weight: 600; padding: 4px 10px; font-size: 11px;")
        self.btn_view_notes.setStyleSheet("background-color: rgba(26, 28, 35, 0.85); color: #94A3B8; font-weight: 500; padding: 4px 10px; font-size: 11px;")

    def _show_notes_view(self):
        """Switches right pane to Live KaTeX mathematical notes browser."""
        self.right_stack.setCurrentIndex(1)
        self.btn_view_notes.setStyleSheet("background-color: rgba(255, 255, 255, 0.16); color: #FFFFFF; font-weight: 600; padding: 4px 10px; font-size: 11px;")
        self.btn_view_chat.setStyleSheet("background-color: rgba(26, 28, 35, 0.85); color: #94A3B8; font-weight: 500; padding: 4px 10px; font-size: 11px;")
        self.refresh_live_notes_view()

    def refresh_live_notes_view(self):
        """Loads and live-renders active lecture notes with KaTeX equations."""
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
                content = f"# Aktueller Notizen-Entwurf\n\n{scratchpad}"
            else:
                content = (
                    "# Chalk Live Notizen\n\n"
                    "> [!theorem] KaTeX Mathematical Live-Rendering Aktiv\n"
                    "> Mathematische Formeln wie $$E(R_i) = R_f + \\beta_i [E(R_m) - R_f]$$ "
                    "oder $$P(A|B) = \\frac{P(B|A)P(A)}{P(B)}$$ werden live mit echten "
                    "Wurzeln, Brüchen und Summenzeichen gerendert. ∎\n\n"
                    "Sobald der Dozent spricht oder Folien wechseln, wachsen deine Notizen hier synchron mit."
                )

        rendered_html = render_markdown_with_katex(content)
        self.notes_browser.setHtml(rendered_html)

    def display_live_notes(self, markdown_notes: str):
        """Explicitly sets and updates the live KaTeX rendered notes."""
        rendered_html = render_markdown_with_katex(markdown_notes)
        self.notes_browser.setHtml(rendered_html)

    # Audio Scrubbing & Floating Mini-Player Playback
    def _on_anchor_clicked(self, url: QUrl):
        url_str = url.toString()
        if url_str.startswith("chalk-audio://"):
            self.open_audio_url(url_str)
            sec = parse_audio_timestamp(url_str)
            self.chat_history.append(f"<i>[Audio-Scrubbing @ {format_timestamp(sec)}]</i>")
        else:
            QDesktopServices.openUrl(url)

    def open_audio_url(self, url_or_str: str):
        """Called when a chalk-audio:// URL is triggered via custom scheme or anchor click."""
        sec = parse_audio_timestamp(url_or_str)
        self.current_playback_offset = sec
        self.player_time_badge.setText(f"[{format_timestamp(sec)}]")
        self.player_pill.show()
        self.play_audio_slice(offset_seconds=sec, duration=20.0)

    def play_audio_slice(self, offset_seconds: float = 0.0, duration: float = 20.0):
        """Plays a 20-second audio slice around offset_seconds via sounddevice/journal without freezing UI."""
        try:
            import sounddevice as sd
            import numpy as np

            audio = None
            sr = 16000

            # 1. Try disk journal if available
            if self.recorder and hasattr(self.recorder, "journal") and self.recorder.journal:
                audio, seg_sr = self.recorder.journal.get_audio_slice(
                    target_timestamp_sec=offset_seconds, slice_duration=duration
                )
                if len(audio) > 0:
                    sr = seg_sr

            # 2. Fallback to recorder rewind buffer
            if (audio is None or len(audio) == 0) and self.recorder:
                audio = self.recorder.get_rewind_audio(seconds=int(duration + 10))

            if audio is not None and len(audio) > 0:
                sd.stop()
                sd.play(audio, sr)
                self.is_playing_audio = True
                self.player_play_btn.setText("⏸")
                self.player_status_lbl.setText("▶ Spielt 20s Ausschnitt")
                self.player_status_lbl.setStyleSheet("color: #38BDF8; font-size: 11px;")

                if hasattr(self, "_play_timer") and self._play_timer:
                    self._play_timer.stop()
                self._play_timer = QTimer(self)
                self._play_timer.setSingleShot(True)
                self._play_timer.timeout.connect(self._on_playback_completed)
                self._play_timer.start(int((len(audio) / sr) * 1000) + 200)
            else:
                self.player_status_lbl.setText("Kein Audio-Puffer verfügbar")
                self.player_status_lbl.setStyleSheet("color: #F87171; font-size: 11px;")
                self.player_play_btn.setText("▶")
                self.is_playing_audio = False
        except Exception as e:
            logger.warning("Audio playback error: %s", e)
            self.player_status_lbl.setText("Wiedergabefehler")
            self.player_play_btn.setText("▶")
            self.is_playing_audio = False

    def play_audio_scrub(self, offset_seconds: float = 0.0, duration: float = 20.0):
        """Backward-compatible alias for play_audio_slice."""
        self.current_playback_offset = offset_seconds
        self.player_time_badge.setText(f"[{format_timestamp(offset_seconds)}]")
        self.player_pill.show()
        self.play_audio_slice(offset_seconds=offset_seconds, duration=duration)

    def _on_playback_completed(self):
        self.is_playing_audio = False
        self.player_play_btn.setText("▶")
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

    # Note Export & Open Handlers
    def _get_active_notes_path(self) -> Optional[str]:
        """Resolves the active session notes markdown path."""
        if self.notes_manager and hasattr(self.notes_manager, "session_file"):
            if os.path.exists(self.notes_manager.session_file):
                return self.notes_manager.session_file

        notes_dir = os.path.abspath("Notes")
        if os.path.exists(notes_dir):
            md_files = [
                os.path.join(notes_dir, f)
                for f in os.listdir(notes_dir)
                if f.endswith(".md")
            ]
            if md_files:
                md_files.sort(key=os.path.getmtime, reverse=True)
                return md_files[0]
        return None

    def _copy_notes_to_clipboard(self):
        """Copies session notes (or scratchpad shorthand) to system clipboard."""
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
            self.copy_notes_btn.setText("✓ Kopiert!")
            QTimer.singleShot(2000, lambda: self.copy_notes_btn.setText(orig_text))

    def _open_in_obsidian(self):
        """Opens active session notes inside Obsidian via obsidian:// URI scheme."""
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

        # Check for local Obsidian vault
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
        """Opens active notes markdown file in the system default editor."""
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

    # Drag and Drop support for slide decks (.pdf, .pptx)
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

    # Window drag handling
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()
