"""
src/ui/settings_dialog.py - BYOK API Key Configuration & Validation Modal.
Presents a sleek dark-mode PyQt6 dialog for configuring Google AI Studio credentials.
Performs non-blocking zero-token API validation and stores credentials in the OS native vault.
"""

import sys
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl
from PyQt6.QtGui import QFont, QIcon, QDesktopServices, QColor
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QProgressBar,
    QFrame,
    QMessageBox,
    QWidget,
)

from src.security.key_manager import get_api_key, set_api_key, validate_api_key, has_api_key


DARK_STYLESHEET = """
QDialog {
    background-color: #0c0d12;
    color: #f3f4f6;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}
QLabel {
    color: #d1d5db;
    font-size: 13px;
}
QLabel#titleLabel {
    color: #ffffff;
    font-size: 18px;
    font-weight: 700;
}
QLabel#subtitleLabel {
    color: #9ca3af;
    font-size: 12px;
}
QLineEdit {
    background-color: #161822;
    color: #f3f4f6;
    border: 1px solid #2e3346;
    border-radius: 8px;
    padding: 10px 14px;
    font-size: 13px;
    selection-background-color: #6366f1;
}
QLineEdit:focus {
    border: 1px solid #818cf8;
    background-color: #1a1d29;
}
QPushButton#primaryButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4f46e5, stop:1 #7c3aed);
    color: #ffffff;
    font-weight: 600;
    font-size: 13px;
    border-radius: 8px;
    padding: 10px 18px;
    border: none;
}
QPushButton#primaryButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6366f1, stop:1 #8b5cf6);
}
QPushButton#primaryButton:disabled {
    background-color: #374151;
    color: #9ca3af;
}
QPushButton#secondaryButton {
    background-color: #1f2333;
    color: #d1d5db;
    font-size: 13px;
    border-radius: 8px;
    padding: 10px 16px;
    border: 1px solid #374151;
}
QPushButton#secondaryButton:hover {
    background-color: #282d42;
    color: #ffffff;
}
QPushButton#linkButton {
    background: transparent;
    color: #818cf8;
    text-align: left;
    border: none;
    font-size: 12px;
    text-decoration: underline;
    padding: 0;
}
QPushButton#linkButton:hover {
    color: #a5b4fc;
}
QFrame#bannerCard {
    background-color: #13151f;
    border: 1px solid #24283b;
    border-radius: 10px;
}
"""


class ValidationWorker(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, api_key: str):
        super().__init__()
        self.api_key = api_key

    def run(self):
        is_valid, msg = validate_api_key(self.api_key)
        self.finished.emit(is_valid, msg)


class SettingsDialog(QDialog):
    def __init__(self, parent=None, is_initial_setup=False):
        super().__init__(parent)
        self.is_initial_setup = is_initial_setup
        self.setWindowTitle("Chalk — Settings & BYOK Security")
        self.setFixedSize(540, 480)
        self.setStyleSheet(DARK_STYLESHEET)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        self._setup_ui()
        self._load_existing_key()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(18)

        # Header Section
        header_layout = QHBoxLayout()
        logo_label = QLabel("⚡")
        logo_label.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #6366f1, stop:1 #9333ea);"
            "border-radius: 8px; font-size: 18px; padding: 6px 10px; color: white;"
        )
        logo_label.setFixedSize(38, 38)
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(logo_label)

        title_box = QVBoxLayout()
        title_box.setSpacing(3)
        self.title_label = QLabel("Chalk BYOK Authentication")
        self.title_label.setObjectName("titleLabel")
        title_box.addWidget(self.title_label)

        self.subtitle_label = QLabel("Zero-knowledge: Credentials live exclusively in your OS vault.")
        self.subtitle_label.setObjectName("subtitleLabel")
        title_box.addWidget(self.subtitle_label)

        header_layout.addLayout(title_box)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # Info Card
        card = QFrame()
        card.setObjectName("bannerCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(8)

        info_text = QLabel(
            "Chalk requires a <b>Google AI Studio API Key</b>. "
            "Your machine connects directly to Google's official API servers "
            "with zero intermediaries, proxy relays, or tracking."
        )
        info_text.setWordWrap(True)
        info_text.setStyleSheet("color: #9ca3af; font-size: 12px; line-height: 1.4;")
        card_layout.addWidget(info_text)

        link_btn = QPushButton("🔑 Get a Free Gemini API Key at aistudio.google.com →")
        link_btn.setObjectName("linkButton")
        link_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        link_btn.clicked.connect(self._open_ai_studio)
        card_layout.addWidget(link_btn)

        layout.addWidget(card)

        # Input Section
        input_label = QLabel("Google AI Studio API Key:")
        input_label.setStyleSheet("font-weight: 600; color: #e5e7eb;")
        layout.addWidget(input_label)

        input_row = QHBoxLayout()
        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("AIzaSy...")
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.textChanged.connect(self._on_text_changed)
        input_row.addWidget(self.key_input)

        self.toggle_eye_btn = QPushButton("👁️")
        self.toggle_eye_btn.setFixedSize(38, 38)
        self.toggle_eye_btn.setObjectName("secondaryButton")
        self.toggle_eye_btn.setToolTip("Show / Hide Key")
        self.toggle_eye_btn.clicked.connect(self._toggle_echo_mode)
        input_row.addWidget(self.toggle_eye_btn)

        layout.addLayout(input_row)

        # Status / Feedback Banner
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-size: 12px; color: #9ca3af;")
        layout.addWidget(self.status_label)

        # Progress bar (Indeterminate during verification)
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setStyleSheet(
            "QProgressBar { background-color: #1f2333; border: none; border-radius: 2px; }"
            "QProgressBar::chunk { background-color: #6366f1; border-radius: 2px; }"
        )
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        layout.addStretch()

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        if not self.is_initial_setup:
            self.cancel_btn = QPushButton("Cancel")
            self.cancel_btn.setObjectName("secondaryButton")
            self.cancel_btn.clicked.connect(self.reject)
            btn_layout.addWidget(self.cancel_btn)
        else:
            self.exit_btn = QPushButton("Quit Chalk")
            self.exit_btn.setObjectName("secondaryButton")
            self.exit_btn.clicked.connect(self._quit_application)
            btn_layout.addWidget(self.exit_btn)

        self.save_btn = QPushButton("Validate & Save to Vault")
        self.save_btn.setObjectName("primaryButton")
        self.save_btn.clicked.connect(self._validate_and_save)
        btn_layout.addWidget(self.save_btn)

        layout.addLayout(btn_layout)

    def _load_existing_key(self):
        existing_key = get_api_key()
        if existing_key:
            self.key_input.setText(existing_key)
            self.status_label.setText("✓ Active key loaded from OS native encrypted vault.")
            self.status_label.setStyleSheet("color: #34d399; font-size: 12px;")

    def _toggle_echo_mode(self):
        if self.key_input.echoMode() == QLineEdit.EchoMode.Password:
            self.key_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self.toggle_eye_btn.setText("🔒")
        else:
            self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.toggle_eye_btn.setText("👁️")

    def _open_ai_studio(self):
        QDesktopServices.openUrl(QUrl("https://aistudio.google.com/app/apikey"))

    def _on_text_changed(self):
        text = self.key_input.text().strip()
        self.save_btn.setEnabled(bool(text))
        self.status_label.setText("")

    def _validate_and_save(self):
        key = self.key_input.text().strip()
        if not key:
            self.status_label.setText("Please enter an API key.")
            self.status_label.setStyleSheet("color: #f87171; font-size: 12px;")
            return

        self.save_btn.setEnabled(False)
        self.progress_bar.show()
        self.status_label.setText("Verifying with Google AI Studio (zero-token ping)...")
        self.status_label.setStyleSheet("color: #93c5fd; font-size: 12px;")

        self.worker = ValidationWorker(key)
        self.worker.finished.connect(self._on_validation_result)
        self.worker.start()

    def _on_validation_result(self, is_valid: bool, message: str):
        self.progress_bar.hide()
        self.save_btn.setEnabled(True)

        if is_valid:
            key = self.key_input.text().strip()
            set_api_key(key)
            self.status_label.setText("✓ " + message)
            self.status_label.setStyleSheet("color: #34d399; font-weight: 600; font-size: 12px;")
            self.accept()
        else:
            self.status_label.setText("✗ " + message)
            self.status_label.setStyleSheet("color: #f87171; font-size: 12px;")

    def _quit_application(self):
        self.reject()
        sys.exit(0)


def ensure_api_key_configured(parent=None) -> bool:
    """
    Checks if an API key exists. If not, blocks execution and prompts the user
    via SettingsDialog. Returns True if a valid key is present or set.
    """
    if has_api_key():
        return True

    dialog = SettingsDialog(parent=parent, is_initial_setup=True)
    result = dialog.exec()
    return result == QDialog.DialogCode.Accepted and has_api_key()
