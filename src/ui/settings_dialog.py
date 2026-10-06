"""
src/ui/settings_dialog.py - BYOK API Key Configuration & Multi-Model Selection Modal.
Presents a sleek monochrome dark-mode PyQt6 dialog for configuring AI credentials.
Supports Google AI Studio (default), Anthropic Claude 3.7, and OpenAI GPT-4o runtimes.
Performs non-blocking validation and stores credentials in the OS native vault.
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
    QComboBox,
)

from src.security.key_manager import (
    get_api_key,
    set_api_key,
    validate_api_key,
    has_api_key,
    get_selected_model,
    set_selected_model,
)

MONOCHROME_STYLESHEET = """
QDialog {
    background-color: #0A0A0C;
    color: #F8FAFC;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, sans-serif;
}
QLabel {
    color: #94A3B8;
    font-size: 13px;
}
QLabel#titleLabel {
    color: #FFFFFF;
    font-size: 17px;
    font-weight: 700;
}
QLabel#subtitleLabel {
    color: #64748B;
    font-size: 12px;
}
QLineEdit, QComboBox {
    background-color: #121318;
    color: #F8FAFC;
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 8px;
    padding: 9px 12px;
    font-size: 13px;
}
QLineEdit:focus, QComboBox:focus {
    border: 1px solid rgba(255, 255, 255, 0.3);
    background-color: #181920;
}
QComboBox::drop-down {
    border: none;
    padding-right: 8px;
}
QComboBox QAbstractItemView {
    background-color: #121318;
    color: #F8FAFC;
    border: 1px solid rgba(255, 255, 255, 0.15);
    selection-background-color: rgba(255, 255, 255, 0.1);
}
QPushButton#primaryButton {
    background-color: #FFFFFF;
    color: #0A0A0C;
    font-weight: 600;
    font-size: 13px;
    border-radius: 8px;
    padding: 9px 18px;
    border: none;
}
QPushButton#primaryButton:hover {
    background-color: #E2E8F0;
}
QPushButton#primaryButton:disabled {
    background-color: #27272A;
    color: #71717A;
}
QPushButton#secondaryButton {
    background-color: #181920;
    color: #CBD5E1;
    font-size: 13px;
    border-radius: 8px;
    padding: 9px 16px;
    border: 1px solid rgba(255, 255, 255, 0.1);
}
QPushButton#secondaryButton:hover {
    background-color: #22232B;
    color: #FFFFFF;
    border-color: rgba(255, 255, 255, 0.2);
}
QPushButton#linkButton {
    background: transparent;
    color: #94A3B8;
    text-align: left;
    border: none;
    font-size: 12px;
    text-decoration: underline;
    padding: 0;
}
QPushButton#linkButton:hover {
    color: #FFFFFF;
}
QFrame#bannerCard {
    background-color: #121318;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 10px;
}
"""


class ValidationWorker(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, api_key: str, provider: str = "gemini"):
        super().__init__()
        self.api_key = api_key
        self.provider = provider

    def run(self):
        is_valid, msg = validate_api_key(self.api_key, provider=self.provider)
        self.finished.emit(is_valid, msg)


class SettingsDialog(QDialog):
    def __init__(self, parent=None, is_initial_setup=False):
        super().__init__(parent)
        self.is_initial_setup = is_initial_setup
        self.setWindowTitle("Chalk — Settings & BYOK Security")
        self.setFixedSize(560, 560)
        self.setStyleSheet(MONOCHROME_STYLESHEET)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        self._setup_ui()
        self._load_existing_settings()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.setSpacing(14)

        # Header Section
        header_layout = QHBoxLayout()
        logo_label = QLabel("CHALK")
        logo_label.setStyleSheet(
            "background-color: #181920; border: 1px solid rgba(255,255,255,0.1);"
            "border-radius: 8px; font-weight: 700; font-size: 11px; padding: 6px 10px; color: #FFFFFF;"
        )
        header_layout.addWidget(logo_label)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        self.title_label = QLabel("Model & BYOK Security")
        self.title_label.setObjectName("titleLabel")
        title_box.addWidget(self.title_label)

        self.subtitle_label = QLabel("Zero-knowledge: Credentials live exclusively in your local OS vault.")
        self.subtitle_label.setObjectName("subtitleLabel")
        title_box.addWidget(self.subtitle_label)

        header_layout.addLayout(title_box)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # 1. Model Selection
        model_box = QVBoxLayout()
        model_box.setSpacing(6)
        model_label = QLabel("Active Synthesis Model:")
        model_label.setStyleSheet("font-weight: 600; color: #F8FAFC; font-size: 12px;")
        model_box.addWidget(model_label)

        self.model_combo = QComboBox()
        self.model_combo.addItem("Gemini 2.5 Flash (1M Token Context, Empfohlen)", "gemini-2.5-flash")
        self.model_combo.addItem("Claude 3.7 Sonnet (Anthropic BYOK)", "claude-3.7-sonnet")
        self.model_combo.addItem("GPT-4o (OpenAI BYOK)", "gpt-4o")
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        model_box.addWidget(self.model_combo)
        layout.addLayout(model_box)

        # Info Card
        card = QFrame()
        card.setObjectName("bannerCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(6)

        info_text = QLabel(
            "Chalk verbindet sich direkt von Ihrem Laptop mit den offiziellen APIs des gewählten Anbieters. "
            "Keine Zwischenserver, keine Relays, keine Telemetrie."
        )
        info_text.setWordWrap(True)
        info_text.setStyleSheet("color: #94A3B8; font-size: 12px; line-height: 1.4;")
        card_layout.addWidget(info_text)

        link_btn = QPushButton("Kostenlosen Gemini API-Schlüssel bei aistudio.google.com erstellen →")
        link_btn.setObjectName("linkButton")
        link_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        link_btn.clicked.connect(self._open_ai_studio)
        card_layout.addWidget(link_btn)

        layout.addWidget(card)

        # 2. Key Input: Google AI Studio (Primary)
        gemini_label = QLabel("Google AI Studio API-Schlüssel (Gemini):")
        gemini_label.setStyleSheet("font-weight: 600; color: #E2E8F0; font-size: 12px;")
        layout.addWidget(gemini_label)

        gemini_row = QHBoxLayout()
        self.gemini_input = QLineEdit()
        self.gemini_input.setPlaceholderText("AIzaSy...")
        self.gemini_input.setEchoMode(QLineEdit.EchoMode.Password)
        gemini_row.addWidget(self.gemini_input)

        self.toggle_gemini_eye = QPushButton("👁️")
        self.toggle_gemini_eye.setFixedSize(36, 36)
        self.toggle_gemini_eye.setObjectName("secondaryButton")
        self.toggle_gemini_eye.clicked.connect(lambda: self._toggle_echo(self.gemini_input, self.toggle_gemini_eye))
        gemini_row.addWidget(self.toggle_gemini_eye)
        layout.addLayout(gemini_row)

        # 3. Key Input: Anthropic (Optional)
        anthropic_label = QLabel("Anthropic API-Schlüssel (Optional für Claude 3.7):")
        anthropic_label.setStyleSheet("font-weight: 500; color: #94A3B8; font-size: 12px;")
        layout.addWidget(anthropic_label)

        anthropic_row = QHBoxLayout()
        self.anthropic_input = QLineEdit()
        self.anthropic_input.setPlaceholderText("sk-ant-api03-...")
        self.anthropic_input.setEchoMode(QLineEdit.EchoMode.Password)
        anthropic_row.addWidget(self.anthropic_input)

        self.toggle_ant_eye = QPushButton("👁️")
        self.toggle_ant_eye.setFixedSize(36, 36)
        self.toggle_ant_eye.setObjectName("secondaryButton")
        self.toggle_ant_eye.clicked.connect(lambda: self._toggle_echo(self.anthropic_input, self.toggle_ant_eye))
        anthropic_row.addWidget(self.toggle_ant_eye)
        layout.addLayout(anthropic_row)

        # 4. Key Input: OpenAI (Optional)
        openai_label = QLabel("OpenAI API-Schlüssel (Optional für GPT-4o):")
        openai_label.setStyleSheet("font-weight: 500; color: #94A3B8; font-size: 12px;")
        layout.addWidget(openai_label)

        openai_row = QHBoxLayout()
        self.openai_input = QLineEdit()
        self.openai_input.setPlaceholderText("sk-proj-...")
        self.openai_input.setEchoMode(QLineEdit.EchoMode.Password)
        openai_row.addWidget(self.openai_input)

        self.toggle_oai_eye = QPushButton("👁️")
        self.toggle_oai_eye.setFixedSize(36, 36)
        self.toggle_oai_eye.setObjectName("secondaryButton")
        self.toggle_oai_eye.clicked.connect(lambda: self._toggle_echo(self.openai_input, self.toggle_oai_eye))
        openai_row.addWidget(self.toggle_oai_eye)
        layout.addLayout(openai_row)

        # Status Label
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-size: 12px; color: #94A3B8;")
        layout.addWidget(self.status_label)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(3)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setStyleSheet(
            "QProgressBar { background-color: #181920; border: none; border-radius: 1px; }"
            "QProgressBar::chunk { background-color: #FFFFFF; border-radius: 1px; }"
        )
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        layout.addStretch()

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        if not self.is_initial_setup:
            self.cancel_btn = QPushButton("Abbrechen")
            self.cancel_btn.setObjectName("secondaryButton")
            self.cancel_btn.clicked.connect(self.reject)
            btn_layout.addWidget(self.cancel_btn)
        else:
            self.exit_btn = QPushButton("Beenden")
            self.exit_btn.setObjectName("secondaryButton")
            self.exit_btn.clicked.connect(self._quit_application)
            btn_layout.addWidget(self.exit_btn)

        self.save_btn = QPushButton("Speichern & Prüfen")
        self.save_btn.setObjectName("primaryButton")
        self.save_btn.clicked.connect(self._validate_and_save)
        btn_layout.addWidget(self.save_btn)

        layout.addLayout(btn_layout)

    def _load_existing_settings(self):
        # Load active model
        active_model = get_selected_model()
        idx = self.model_combo.findData(active_model)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)

        # Load keys
        gemini_key = get_api_key("gemini")
        if gemini_key:
            self.gemini_input.setText(gemini_key)

        ant_key = get_api_key("anthropic")
        if ant_key:
            self.anthropic_input.setText(ant_key)

        oai_key = get_api_key("openai")
        if oai_key:
            self.openai_input.setText(oai_key)

        if gemini_key or ant_key or oai_key:
            self.status_label.setText("Schlüssel im Betriebssystem-Tresor geladen.")
            self.status_label.setStyleSheet("color: #FFFFFF; font-size: 12px;")

    def _on_model_changed(self):
        self.status_label.setText("")

    def _toggle_echo(self, line_edit: QLineEdit, button: QPushButton):
        if line_edit.echoMode() == QLineEdit.EchoMode.Password:
            line_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            button.setText("🔒")
        else:
            line_edit.setEchoMode(QLineEdit.EchoMode.Password)
            button.setText("👁️")

    def _open_ai_studio(self):
        QDesktopServices.openUrl(QUrl("https://aistudio.google.com/app/apikey"))

    def _validate_and_save(self):
        selected_model = self.model_combo.currentData()
        gemini_key = self.gemini_input.text().strip()
        ant_key = self.anthropic_input.text().strip()
        oai_key = self.openai_input.text().strip()

        # Save keys
        if gemini_key:
            set_api_key(gemini_key, "gemini")
        if ant_key:
            set_api_key(ant_key, "anthropic")
        if oai_key:
            set_api_key(oai_key, "openai")

        set_selected_model(selected_model)

        # Determine which key to validate based on selected model
        if "claude" in selected_model:
            target_key = ant_key
            provider = "anthropic"
        elif "gpt" in selected_model:
            target_key = oai_key
            provider = "openai"
        else:
            target_key = gemini_key
            provider = "gemini"

        if not target_key:
            self.status_label.setText(f"Bitte hinterlegen Sie einen Schlüssel für {provider.capitalize()}.")
            self.status_label.setStyleSheet("color: #F87171; font-size: 12px;")
            return

        self.save_btn.setEnabled(False)
        self.progress_bar.show()
        self.status_label.setText(f"Prüfe {provider.capitalize()} API-Schlüssel...")
        self.status_label.setStyleSheet("color: #94A3B8; font-size: 12px;")

        self.worker = ValidationWorker(target_key, provider=provider)
        self.worker.finished.connect(self._on_validation_result)
        self.worker.start()

    def _on_validation_result(self, is_valid: bool, message: str):
        self.progress_bar.hide()
        self.save_btn.setEnabled(True)

        if is_valid:
            self.status_label.setText("✓ " + message)
            self.status_label.setStyleSheet("color: #FFFFFF; font-weight: 600; font-size: 12px;")
            self.accept()
        else:
            self.status_label.setText("✗ " + message)
            self.status_label.setStyleSheet("color: #F87171; font-size: 12px;")

    def _quit_application(self):
        self.reject()
        sys.exit(0)


def ensure_api_key_configured(parent=None) -> bool:
    """
    Checks if an API key exists. If not, blocks execution and prompts the user
    via SettingsDialog. Returns True if a valid key is present or set.
    """
    if has_api_key("gemini") or has_api_key("anthropic") or has_api_key("openai"):
        return True

    dialog = SettingsDialog(parent=parent, is_initial_setup=True)
    result = dialog.exec()
    return result == QDialog.DialogCode.Accepted and (
        has_api_key("gemini") or has_api_key("anthropic") or has_api_key("openai")
    )
