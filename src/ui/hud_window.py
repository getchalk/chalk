"""
src/ui/hud_window.py - Frameless PyQt6 Floating Agent HUD (Alt+Space).
Translucent dark-mode palette (rgba(15, 17, 23, 0.95)), stays on top without stealing focus.
Displays live session duration, daemon status indicator, remaining RPD budget,
drag-and-drop file target for lecture slides (.pdf, .pptx), scratchpad shorthand anchor,
Action buttons (Attach Document, Snip Screen Alt+S, Rewind 90s), and Copilot agent tools.
"""

import os
import time
from typing import Optional
from PIL import Image

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QPoint
from PyQt6.QtGui import QFont, QIcon, QColor, QPainter, QBrush, QPen, QPixmap
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QLineEdit,
    QFileDialog,
    QFrame,
    QScrollArea,
    QSplitter,
    QGraphicsDropShadowEffect,
)

from src.ui.snip_overlay import SnipOverlayWidget
from src.api.tools import read_local_file

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
QTextEdit, QLineEdit {
    background-color: rgba(18, 20, 28, 0.95);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 8px;
    color: #F8FAFC;
    padding: 8px;
    font-size: 12px;
}
QTextEdit:focus, QLineEdit:focus {
    border: 1px solid rgba(255, 255, 255, 0.4);
}
QFrame#cardFrame {
    background-color: rgba(18, 20, 28, 0.6);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 10px;
}
"""


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

    def __init__(self, recorder=None, pipeline=None, quota_manager=None, parent=None):
        super().__init__(parent)
        self.recorder = recorder
        self.pipeline = pipeline
        self.quota_manager = quota_manager

        # Attachments
        self.attached_document_text: Optional[str] = None
        self.attached_document_name: Optional[str] = None
        self.attached_snip_image: Optional[Image.Image] = None

        # State
        self.session_start_time = time.time()
        self.drag_position = QPoint()

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
        self.resize(720, 520)
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

        # Logo & App Title with Calcite Emblem
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

        # Recording Status Pill (Emerald Pulse on Monochrome Slate)
        self.status_pill = QLabel("🟢 RECORDING (00:00)")
        self.status_pill.setStyleSheet(
            "background-color: rgba(16, 185, 129, 0.12); border: 1px solid rgba(16, 185, 129, 0.25);"
            "color: #34d399; font-size: 11px; font-weight: 600; padding: 4px 10px; border-radius: 12px;"
        )
        header.addWidget(self.status_pill)

        # RPD Budget Pill (Pure Slate Monochrome)
        self.quota_pill = QLabel("Quota: 50 RPD")
        self.quota_pill.setStyleSheet(
            "background-color: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.12);"
            "color: #94A3B8; font-size: 11px; font-weight: 500; padding: 4px 10px; border-radius: 12px;"
        )
        header.addWidget(self.quota_pill)

        header.addStretch()

        # Minimize / Hide button
        hide_btn = QPushButton("✕")
        hide_btn.setFixedSize(28, 28)
        hide_btn.setToolTip("Hide HUD (Alt+Space to toggle)")
        hide_btn.clicked.connect(self.hide)
        header.addWidget(hide_btn)

        main_layout.addLayout(header)

        # Quick Actions Bar
        actions_bar = QHBoxLayout()
        actions_bar.setSpacing(8)

        self.attach_doc_btn = QPushButton("📎 Attach Document")
        self.attach_doc_btn.setToolTip("Ground session with lecture slides (.pdf, .pptx)")
        self.attach_doc_btn.clicked.connect(self._open_document_dialog)
        actions_bar.addWidget(self.attach_doc_btn)

        self.snip_btn = QPushButton("✂️ Snip Screen (Alt+S)")
        self.snip_btn.setToolTip("Freeze and marquee crop screen to attach to prompt")
        self.snip_btn.clicked.connect(self.trigger_screen_snip)
        actions_bar.addWidget(self.snip_btn)

        self.rewind_btn = QPushButton("⏮️ Rewind 90s")
        self.rewind_btn.setToolTip("Instantly fetch & transcribe the trailing 90-second audio buffer")
        self.rewind_btn.clicked.connect(self._trigger_audio_rewind)
        actions_bar.addWidget(self.rewind_btn)

        self.flush_btn = QPushButton("⏳ Flush Chunk (F10)")
        self.flush_btn.setToolTip("Force active chunk to synthesize immediately")
        self.flush_btn.clicked.connect(lambda: self.request_force_flush.emit())
        actions_bar.addWidget(self.flush_btn)

        actions_bar.addStretch()

        self.synth_btn = QPushButton("🎓 End & Synthesize (F9)")
        self.synth_btn.setObjectName("primaryAction")
        self.synth_btn.setToolTip("Finish lecture and run Gemini Pro Master Synthesis")
        self.synth_btn.clicked.connect(lambda: self.request_master_synthesis.emit())
        actions_bar.addWidget(self.synth_btn)

        main_layout.addLayout(actions_bar)

        # Attachments Banner (if doc or snip attached)
        self.attachment_label = QLabel("")
        self.attachment_label.setStyleSheet("color: #a78bfa; font-size: 11px;")
        self.attachment_label.hide()
        main_layout.addWidget(self.attachment_label)

        # Splitter: Left = Scratchpad (Primary Outline Anchor), Right = Copilot Q&A
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background-color: rgba(255, 255, 255, 0.08); width: 2px; }")

        # Left Column: Student Scratchpad
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 6, 0)
        left_layout.setSpacing(6)

        scratchpad_label = QLabel("📝 Student Scratchpad (Primary Outline Anchor):")
        scratchpad_label.setStyleSheet("font-size: 11px; font-weight: 600; color: #9ca3af;")
        left_layout.addWidget(scratchpad_label)

        self.scratchpad_text = QTextEdit()
        self.scratchpad_text.setPlaceholderText(
            "- Jot shorthand formulas or topics here...\n"
            "- Anchors section hierarchy in live chunks\n"
            "- Drag & drop .pdf or .pptx slides onto HUD"
        )
        left_layout.addWidget(self.scratchpad_text)
        splitter.addWidget(left_widget)

        # Right Column: Interactive Copilot
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(6, 0, 0, 0)
        right_layout.setSpacing(6)

        copilot_label = QLabel("💬 Chalk Copilot & Tool Executor:")
        copilot_label.setStyleSheet("font-size: 11px; font-weight: 600; color: #9ca3af;")
        right_layout.addWidget(copilot_label)

        self.chat_history = QTextEdit()
        self.chat_history.setReadOnly(True)
        self.chat_history.setPlaceholderText("Answers, tool calls, and 90s rewind transcripts appear here...")
        right_layout.addWidget(self.chat_history)

        prompt_row = QHBoxLayout()
        prompt_row.setSpacing(8)
        self.prompt_input = QLineEdit()
        self.prompt_input.setPlaceholderText("Ask question, explain formula, or execute tool...")
        self.prompt_input.returnPressed.connect(self._send_copilot_prompt)
        prompt_row.addWidget(self.prompt_input)

        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self._send_copilot_prompt)
        prompt_row.addWidget(self.send_btn)

        right_layout.addLayout(prompt_row)
        splitter.addWidget(right_widget)

        splitter.setSizes([320, 360])
        main_layout.addWidget(splitter)

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
        """
        Updates HUD status pill:
        'recording' -> Green
        'paused' | 'standby' -> Yellow
        'processing' -> Blue
        """
        mins = int((time.time() - self.session_start_time) // 60)
        secs = int((time.time() - self.session_start_time) % 60)
        time_str = f"{mins:02d}:{secs:02d}"

        if state == "recording":
            self.status_pill.setText(f"🟢 RECORDING ({time_str})")
            self.status_pill.setStyleSheet(
                "background-color: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.3);"
                "color: #34d399; font-size: 11px; font-weight: 600; padding: 4px 10px; border-radius: 12px;"
            )
        elif state in ("paused", "standby"):
            lbl = f"🟡 STANDBY ({message})" if message else f"🟡 PAUSED ({time_str})"
            self.status_pill.setText(lbl)
            self.status_pill.setStyleSheet(
                "background-color: rgba(245, 158, 11, 0.15); border: 1px solid rgba(245, 158, 11, 0.3);"
                "color: #fbbf24; font-size: 11px; font-weight: 600; padding: 4px 10px; border-radius: 12px;"
            )
        elif state == "processing":
            self.status_pill.setText(f"🔵 PROCESSING CHUNK...")
            self.status_pill.setStyleSheet(
                "background-color: rgba(59, 130, 246, 0.15); border: 1px solid rgba(59, 130, 246, 0.3);"
                "color: #60a5fa; font-size: 11px; font-weight: 600; padding: 4px 10px; border-radius: 12px;"
            )

    def _update_hud_status(self):
        """Periodic status update."""
        if self.quota_manager:
            rpd = self.quota_manager.safe_remaining_rpd
            tokens = self.quota_manager.total_tokens_today
            self.quota_pill.setText(f"Budget: {rpd} RPD ({tokens // 1000}k tok)")

        if self.recorder and self.recorder.is_recording:
            if self.recorder.is_paused:
                self.set_daemon_status("paused")
            else:
                self.set_daemon_status("recording")

    def trigger_screen_snip(self):
        """Freezes screen and displays marquee snip tool (Alt+S)."""
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
            "Attach Lecture Deck or Syllabus",
            "",
            "Lecture Documents (*.pdf *.pptx *.ppt *.txt *.md)",
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
            self.attachment_label.setText("Attached: " + " | ".join(tags))
            self.attachment_label.show()
        else:
            self.attachment_label.hide()

    def _trigger_audio_rewind(self):
        if not self.recorder or not self.pipeline:
            self.chat_history.append("<i>[Audio recorder / API pipeline not initialized]</i>")
            return

        self.chat_history.append("<b>⏮️ Fetching trailing 90-second audio buffer...</b>")
        self.rewind_worker = RewindWorker(self.recorder, self.pipeline, seconds=90)
        self.rewind_worker.finished.connect(self._on_rewind_finished)
        self.rewind_worker.start()

    def _on_rewind_finished(self, transcript: str):
        self.chat_history.append(f"<b>[Rewind 90s Transcript]:</b>\n{transcript}\n")

    def _send_copilot_prompt(self):
        prompt = self.prompt_input.text().strip()
        if not prompt or not self.pipeline:
            return

        self.chat_history.append(f"<b>You:</b> {prompt}")
        self.prompt_input.clear()
        self.send_btn.setEnabled(False)

        img = self.attached_snip_image
        doc = self.attached_document_text
        self.attached_snip_image = None  # Consume single snip
        self._update_attachment_banner()

        self.copilot_worker = CopilotWorker(self.pipeline, prompt, img, doc)
        self.copilot_worker.finished.connect(self._on_copilot_finished)
        self.copilot_worker.start()

    def _on_copilot_finished(self, response: str):
        self.send_btn.setEnabled(True)
        self.chat_history.append(f"<b>Chalk Copilot:</b>\n{response}\n")

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
