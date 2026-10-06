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
)

from src.ui.snip_overlay import SnipOverlayWidget
from src.api.tools import read_local_file

logger = logging.getLogger("chalk.ui.hud")

HUD_STYLESHEET = """
QWidget#hudRoot {
    background-color: rgba(10, 11, 16, 0.96);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 16px;
    color: #F8FAFC;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, sans-serif;
}
QLabel {
    color: #E2E8F0;
}
QPushButton {
    background-color: rgba(22, 24, 32, 0.85);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 8px;
    color: #CBD5E1;
    padding: 6px 12px;
    font-size: 12px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: rgba(35, 38, 50, 0.95);
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
    background-color: rgba(18, 20, 28, 0.95);
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
    background-color: rgba(18, 20, 28, 0.8);
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
"""


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

        # Attachments
        self.attached_document_text: Optional[str] = None
        self.attached_document_name: Optional[str] = None
        self.attached_snip_image: Optional[Image.Image] = None

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
        hide_btn.setToolTip("HUD ausblenden (Alt+Space zum Einblenden)")
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

        self.snip_btn = QPushButton("✂️ Snip (Alt+S)")
        self.snip_btn.setToolTip("Bildschirmbereich zuschneiden und an Prompt anhängen")
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

        copilot_label = QLabel("💬 Chalk Copilot & Audio-Scrubbing:")
        copilot_label.setStyleSheet("font-size: 11px; font-weight: 600; color: #94A3B8;")
        right_layout.addWidget(copilot_label)

        self.chat_history = QTextBrowser()
        self.chat_history.setReadOnly(True)
        self.chat_history.setOpenExternalLinks(False)
        self.chat_history.setOpenLinks(False)
        self.chat_history.anchorClicked.connect(self._on_anchor_clicked)
        self.chat_history.setPlaceholderText("Antworten, Rewind-Transkripte und klickbare Zeitstempel [HH:MM:SS] erscheinen hier...")
        right_layout.addWidget(self.chat_history)

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

        # Mini-Audio Player Bar
        player_frame = QFrame()
        player_frame.setObjectName("playerBar")
        player_layout = QHBoxLayout(player_frame)
        player_layout.setContentsMargins(8, 4, 8, 4)
        player_layout.setSpacing(10)

        self.player_play_btn = QPushButton("▶ Play")
        self.player_play_btn.setFixedSize(68, 28)
        self.player_play_btn.clicked.connect(self._toggle_audio_playback)
        player_layout.addWidget(self.player_play_btn)

        self.player_status_lbl = QLabel("Audio-Scrubber: Bereit (Klicke auf Zeitstempel wie [01:14:20])")
        self.player_status_lbl.setStyleSheet("font-size: 11px; color: #94A3B8;")
        player_layout.addWidget(self.player_status_lbl)

        player_layout.addStretch()

        self.player_slider = QSlider(Qt.Orientation.Horizontal)
        self.player_slider.setRange(0, 100)
        self.player_slider.setValue(0)
        self.player_slider.setFixedWidth(120)
        self.player_slider.sliderMoved.connect(self._on_slider_moved)
        player_layout.addWidget(self.player_slider)

        self.player_time_lbl = QLabel("00:00")
        self.player_time_lbl.setStyleSheet("font-size: 11px; font-family: ui-monospace, monospace; color: #CBD5E1;")
        player_layout.addWidget(self.player_time_lbl)

        main_layout.addWidget(player_frame)

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
        text = read_local_file(path)
        self.attached_document_text = text
        self.attached_document_name = os.path.basename(path)
        self._update_attachment_banner()

    def _update_attachment_banner(self):
        tags = []
        if self.attached_document_name:
            tags.append(f"📄 {self.attached_document_name}")
        if self.attached_snip_image:
            tags.append(f"✂️ Screen Snip ({self.attached_snip_image.width}x{self.attached_snip_image.height})")

        if tags:
            self.attachment_label.setText("Angehängt: " + " | ".join(tags))
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
        self.chat_history.append(f"<b>[Rewind 90s Transkript]:</b>\n{transcript}\n")

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
        self.chat_history.append(f"<b>Chalk:</b>\n{response}\n")

    # Audio Scrubbing & Playback
    def _on_anchor_clicked(self, url: QUrl):
        url_str = url.toString()
        if url_str.startswith("chalk-audio://"):
            time_str = url_str.replace("chalk-audio://", "").strip("/")
            parts = time_str.split(":")
            sec = 0
            if len(parts) == 3:
                sec = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 2:
                sec = int(parts[0]) * 60 + int(parts[1])
            self.play_audio_scrub(offset_seconds=float(sec), duration=30.0)
            self.chat_history.append(f"<i>[Audio-Scrubbing zu Zeitstempel {time_str}]</i>")
        else:
            QDesktopServices.openUrl(url)

    def play_audio_scrub(self, offset_seconds: float = 0.0, duration: float = 30.0):
        """Plays audio at given offset using sounddevice."""
        try:
            import sounddevice as sd
            import numpy as np

            audio = None
            if self.recorder:
                audio = self.recorder.get_rewind_audio(seconds=int(duration + 10))

            if audio is not None and len(audio) > 0:
                sd.stop()
                sd.play(audio, 16000)
                self.is_playing_audio = True
                self.player_status_lbl.setText(f"▶ Wiedergabe @ {int(offset_seconds)}s (30s Snippet)")
                self.player_status_lbl.setStyleSheet("color: #FFFFFF; font-size: 11px; font-weight: 600;")
                self.player_play_btn.setText("■ Stop")
            else:
                self.player_status_lbl.setText("Kein Audio-Puffer verfügbar")
        except Exception as e:
            logger.warning("Audio playback error: %s", e)

    def stop_audio_scrub(self):
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass
        self.is_playing_audio = False
        self.player_status_lbl.setText("Wiedergabe angehalten")
        self.player_play_btn.setText("▶ Play")

    def _toggle_audio_playback(self):
        if self.is_playing_audio:
            self.stop_audio_scrub()
        else:
            self.play_audio_scrub(offset_seconds=0.0, duration=30.0)

    def _on_slider_moved(self, value: int):
        mins = int((time.time() - self.session_start_time) // 60)
        target_sec = int((value / 100.0) * max(1, mins * 60))
        self.play_audio_scrub(offset_seconds=float(target_sec), duration=20.0)

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
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if file_path.lower().endswith((".pdf", ".pptx", ".ppt", ".txt", ".md")):
                self.load_reference_document(file_path)
                break

    # Window drag handling
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()
