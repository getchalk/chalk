"""
src/ui/settings_dialog.py - BYOK API Key Configuration & Multi-Model Selection Modal.
Presents a sleek monochrome dark-mode PyQt6 dialog for configuring AI credentials.
Supports Google AI Studio (default), Anthropic Claude 3.7, and OpenAI GPT-4o runtimes.
Performs non-blocking validation and stores credentials in the OS native vault.
Full 5-language internationalization parity (EN, DE, FR, ES, ZH).
"""

import sys
import os
from typing import Optional, List, Dict, Any
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
    QFileDialog,
)

from src.security.key_manager import (
    get_api_key,
    set_api_key,
    validate_api_key,
    has_api_key,
    get_selected_model,
    set_selected_model,
)
from src.engine.config import (
    get_obsidian_vault_path,
    set_obsidian_vault_path,
    get_output_language,
    set_output_language,
)
from src.ui.i18n import (
    tr,
    get_ui_language,
    set_ui_language,
    SUPPORTED_LANGUAGES,
)

MONOCHROME_STYLESHEET = """
QDialog {
    background-color: #121317;
    color: #F8FAFC;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, sans-serif;
}
QLabel {
    color: #94A3B8;
    font-size: 12px;
}
QLabel#titleLabel {
    color: #F8FAFC;
    font-size: 16px;
    font-weight: 700;
}
QLabel#subtitleLabel {
    color: #64748B;
    font-size: 11.5px;
}
QLineEdit, QComboBox {
    background-color: #15161B;
    color: #F8FAFC;
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 7px;
    padding: 7px 11px;
    font-size: 12.5px;
}
QLineEdit:focus, QComboBox:focus {
    border: 1px solid rgba(255, 255, 255, 0.3);
    background-color: #1A1C23;
}
QComboBox::drop-down {
    border: none;
    padding-right: 8px;
}
QComboBox QAbstractItemView {
    background-color: #15161B;
    color: #F8FAFC;
    border: 1px solid rgba(255, 255, 255, 0.15);
    selection-background-color: rgba(255, 255, 255, 0.1);
}
QPushButton#primaryButton {
    background-color: #FFFFFF;
    color: #121317;
    font-weight: 600;
    font-size: 12.5px;
    border-radius: 7px;
    padding: 8px 16px;
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
    background-color: #1A1C23;
    color: #CBD5E1;
    font-size: 12px;
    border-radius: 7px;
    padding: 7px 14px;
    border: 1px solid rgba(255, 255, 255, 0.1);
}
QPushButton#secondaryButton:hover {
    background-color: #22252F;
    color: #FFFFFF;
    border-color: rgba(255, 255, 255, 0.2);
}
QPushButton#linkButton {
    background: transparent;
    color: #94A3B8;
    text-align: left;
    border: none;
    font-size: 11.5px;
    text-decoration: underline;
    padding: 0;
}
QPushButton#linkButton:hover {
    color: #FFFFFF;
}
QFrame#bannerCard {
    background-color: #1A1C23;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 9px;
}
QFrame#guideCard {
    background-color: #15161B;
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 7px;
}
"""

COUPLED_PRESET_ITEMS = [
    # (preset_id, i18n_key, default_label, optgroup_key)
    ("gemini-max", "model_preset_gemini_max", "Gemini Maximum: Gemini 3.5 Flash (Operational) + Gemini 3.1 Pro (Synthesis)", "optgroup_free"),
    ("gemini-medium", "model_preset_gemini_medium", "Gemini Medium: Gemini 3.5 Flash-Lite (Operational) + Gemini 3.5 Flash (Synthesis)", "optgroup_free"),
    ("gemini-min", "model_preset_gemini_min", "Gemini Minimum: Gemini 3.1 Flash-Lite (Operational) + Gemini 3.5 Flash-Lite (Synthesis)", "optgroup_free"),
    ("paid-gemini", "model_preset_paid_gemini", "Gemini 3.8 Flash (Operational & Synthesis)", "optgroup_premium"),
    ("paid-claude", "model_preset_paid_claude", "Claude 5.5 Sonnet (Operational & Synthesis)", "optgroup_premium"),
    ("paid-openai", "model_preset_paid_openai", "GPT-6.1 Sol (Operational & Synthesis)", "optgroup_premium"),
]
SUPPORTED_MODELS = [(item[0], item[1], item[2]) for item in COUPLED_PRESET_ITEMS]


def populate_preset_combobox(combo: QComboBox, active_lang: str):
    """Populates a QComboBox with coupled dual-stage model presets organized by category."""
    combo.clear()
    last_grp = None
    for pid, key, default_label, grp_key in COUPLED_PRESET_ITEMS:
        if grp_key != last_grp:
            last_grp = grp_key
            grp_label = tr(grp_key, lang=active_lang) or ("Gemini Free Tier (Direct BYOK)" if grp_key == "optgroup_free" else "Paid Models (Direct BYOK)")
            combo.addItem(f"── {grp_label} ──", "")
            header_idx = combo.count() - 1
            model = combo.model()
            if hasattr(model, "item"):
                item = model.item(header_idx)
                if item:
                    item.setEnabled(False)
        combo.addItem(tr(key, lang=active_lang) or default_label, pid)


def select_preset_in_combobox(combo: QComboBox, target_id: Optional[str]):
    """Selects the matching preset in combobox, gracefully resolving legacy model names."""
    from src.engine.config import resolve_model_preset
    preset = resolve_model_preset(target_id)
    resolved_id = preset["id"]
    for i in range(combo.count()):
        if combo.itemData(i) == resolved_id:
            combo.setCurrentIndex(i)
            return
    for i in range(combo.count()):
        if combo.itemData(i):
            combo.setCurrentIndex(i)
            return


class ValidationWorker(QThread):
    validation_finished = pyqtSignal(bool, str)

    def __init__(self, api_key: str, provider: str = "gemini"):
        super().__init__()
        self.api_key = api_key
        self.provider = provider

    def run(self):
        is_valid, msg = validate_api_key(self.api_key, provider=self.provider)
        self.validation_finished.emit(is_valid, msg)


class SettingsDialog(QDialog):
    language_changed = pyqtSignal(str)

    def __init__(self, parent=None, is_initial_setup=False):
        super().__init__(parent)
        self.is_initial_setup = is_initial_setup
        self.setFixedWidth(580)
        self.resize(580, 720)
        self.setStyleSheet(MONOCHROME_STYLESHEET)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        self._active_ui_lang = get_ui_language()
        self._setup_ui()
        self._load_existing_settings()
        self.retranslate_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 16, 22, 16)
        layout.setSpacing(9)

        # Header Section
        header_layout = QHBoxLayout()
        logo_label = QLabel("CHALK")
        logo_label.setStyleSheet(
            "background-color: #1A1C23; border: 1px solid rgba(255,255,255,0.12);"
            "border-radius: 8px; font-weight: 700; font-size: 11px; padding: 5px 9px; color: #FFFFFF;"
        )
        header_layout.addWidget(logo_label)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        self.title_label = QLabel("Model & BYOK Security")
        self.title_label.setObjectName("titleLabel")
        title_box.addWidget(self.title_label)

        self.subtitle_label = QLabel("Local-First: Credentials live exclusively in your local OS native vault.")
        self.subtitle_label.setObjectName("subtitleLabel")
        title_box.addWidget(self.subtitle_label)

        header_layout.addLayout(title_box)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # 1. Model Selection
        model_box = QVBoxLayout()
        model_box.setSpacing(4)
        self.model_label = QLabel("Active Synthesis Model:")
        self.model_label.setStyleSheet("font-weight: 600; color: #F8FAFC; font-size: 12px;")
        model_box.addWidget(self.model_label)

        self.model_combo = QComboBox()
        populate_preset_combobox(self.model_combo, self._active_ui_lang)
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        model_box.addWidget(self.model_combo)
        layout.addLayout(model_box)

        # Info Card
        card = QFrame()
        card.setObjectName("bannerCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(5)

        self.info_text = QLabel(
            "Chalk connects directly from your laptop to the official APIs of the selected provider. "
            "No middleman servers, no relays, no telemetry."
        )
        self.info_text.setWordWrap(True)
        self.info_text.setStyleSheet("color: #94A3B8; font-size: 11px; line-height: 1.4;")
        card_layout.addWidget(self.info_text)

        link_row = QHBoxLayout()
        self.link_btn = QPushButton("Create free Gemini API key at aistudio.google.com →")
        self.link_btn.setObjectName("linkButton")
        self.link_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.link_btn.clicked.connect(self._open_ai_studio)
        link_row.addWidget(self.link_btn)

        link_row.addStretch()
        self.guide_toggle_btn = QPushButton("How to get your free key (3 steps) ▾")
        self.guide_toggle_btn.setObjectName("linkButton")
        self.guide_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.guide_toggle_btn.clicked.connect(self._toggle_free_guide)
        link_row.addWidget(self.guide_toggle_btn)
        card_layout.addLayout(link_row)

        # Collapsible 3-step guide
        self.guide_frame = QFrame()
        self.guide_frame.setObjectName("guideCard")
        guide_inner = QVBoxLayout(self.guide_frame)
        guide_inner.setContentsMargins(10, 8, 10, 8)
        guide_inner.setSpacing(5)

        self.guide_step1_lbl = QLabel()
        self.guide_step1_lbl.setWordWrap(True)
        self.guide_step1_lbl.setStyleSheet("font-size: 10.5px; color: #CBD5E1; line-height: 1.3;")
        guide_inner.addWidget(self.guide_step1_lbl)

        self.guide_step2_lbl = QLabel()
        self.guide_step2_lbl.setWordWrap(True)
        self.guide_step2_lbl.setStyleSheet("font-size: 10.5px; color: #CBD5E1; line-height: 1.3;")
        guide_inner.addWidget(self.guide_step2_lbl)

        self.guide_step3_lbl = QLabel()
        self.guide_step3_lbl.setWordWrap(True)
        self.guide_step3_lbl.setStyleSheet("font-size: 10.5px; color: #CBD5E1; line-height: 1.3;")
        guide_inner.addWidget(self.guide_step3_lbl)

        guide_action_row = QHBoxLayout()
        guide_action_row.addStretch()
        self.guide_action_btn = QPushButton("Open Google AI Studio ↗")
        self.guide_action_btn.setObjectName("secondaryButton")
        self.guide_action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.guide_action_btn.clicked.connect(self._open_ai_studio)
        guide_action_row.addWidget(self.guide_action_btn)
        guide_inner.addLayout(guide_action_row)

        self.guide_frame.hide()
        card_layout.addWidget(self.guide_frame)

        # Transparent Onboarding Note on Free-Tier vs Paid-Tier
        self.tier_notice = QLabel(
            "<b>Transparency & Privacy:</b><br>"
            "Google AI Studio Free-Tier: Google reserves the right to use prompts for model improvement. "
            "For 100% confidential sessions, we recommend a Paid-Tier (Pay-as-you-go) key from "
            "Google AI Studio, Anthropic, or OpenAI where data is never used for training."
        )
        self.tier_notice.setWordWrap(True)
        self.tier_notice.setStyleSheet(
            "color: #94A3B8; font-size: 10.5px; line-height: 1.4; "
            "padding: 6px 8px; background-color: rgba(255, 255, 255, 0.03); "
            "border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 6px;"
        )
        card_layout.addWidget(self.tier_notice)

        layout.addWidget(card)

        # 2. Key Input: Google AI Studio (Primary)
        gemini_hdr_row = QHBoxLayout()
        self.gemini_label = QLabel("Google AI Studio API Key (Gemini):")
        self.gemini_label.setStyleSheet("font-weight: 600; color: #E2E8F0; font-size: 12px;")
        gemini_hdr_row.addWidget(self.gemini_label)
        gemini_hdr_row.addStretch()

        self.get_free_key_btn = QPushButton("Get Free Key ↗")
        self.get_free_key_btn.setObjectName("linkButton")
        self.get_free_key_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.get_free_key_btn.setStyleSheet("font-size: 11px; padding: 2px 6px; font-weight: 500; color: #E2E8F0;")
        self.get_free_key_btn.clicked.connect(self._open_ai_studio)
        gemini_hdr_row.addWidget(self.get_free_key_btn)
        layout.addLayout(gemini_hdr_row)

        gemini_row = QHBoxLayout()
        self.gemini_input = QLineEdit()
        self.gemini_input.setPlaceholderText("AIzaSy...")
        self.gemini_input.setEchoMode(QLineEdit.EchoMode.Password)
        gemini_row.addWidget(self.gemini_input)

        self.toggle_gemini_eye = QPushButton("Show")
        self.toggle_gemini_eye.setFixedSize(65, 34)
        self.toggle_gemini_eye.setObjectName("secondaryButton")
        self.toggle_gemini_eye.clicked.connect(lambda: self._toggle_echo(self.gemini_input, self.toggle_gemini_eye))
        gemini_row.addWidget(self.toggle_gemini_eye)
        layout.addLayout(gemini_row)

        # 3. Key Input: Anthropic (Optional)
        self.anthropic_label = QLabel("Anthropic API Key (Optional for Claude 3.7):")
        self.anthropic_label.setStyleSheet("font-weight: 500; color: #94A3B8; font-size: 11.5px;")
        layout.addWidget(self.anthropic_label)

        anthropic_row = QHBoxLayout()
        self.anthropic_input = QLineEdit()
        self.anthropic_input.setPlaceholderText("sk-ant-api03-...")
        self.anthropic_input.setEchoMode(QLineEdit.EchoMode.Password)
        anthropic_row.addWidget(self.anthropic_input)

        self.toggle_ant_eye = QPushButton("Show")
        self.toggle_ant_eye.setFixedSize(65, 34)
        self.toggle_ant_eye.setObjectName("secondaryButton")
        self.toggle_ant_eye.clicked.connect(lambda: self._toggle_echo(self.anthropic_input, self.toggle_ant_eye))
        anthropic_row.addWidget(self.toggle_ant_eye)
        layout.addLayout(anthropic_row)

        # 4. Key Input: OpenAI (Optional)
        self.openai_label = QLabel("OpenAI API Key (Optional for GPT-4o):")
        self.openai_label.setStyleSheet("font-weight: 500; color: #94A3B8; font-size: 11.5px;")
        layout.addWidget(self.openai_label)

        openai_row = QHBoxLayout()
        self.openai_input = QLineEdit()
        self.openai_input.setPlaceholderText("sk-proj-...")
        self.openai_input.setEchoMode(QLineEdit.EchoMode.Password)
        openai_row.addWidget(self.openai_input)

        self.toggle_oai_eye = QPushButton("Show")
        self.toggle_oai_eye.setFixedSize(65, 34)
        self.toggle_oai_eye.setObjectName("secondaryButton")
        self.toggle_oai_eye.clicked.connect(lambda: self._toggle_echo(self.openai_input, self.toggle_oai_eye))
        openai_row.addWidget(self.toggle_oai_eye)
        layout.addLayout(openai_row)

        # 5. Obsidian Vault Directory Picker
        self.obsidian_label = QLabel("Obsidian Vault Directory (Optional for auto-sync):")
        self.obsidian_label.setStyleSheet("font-weight: 500; color: #94A3B8; font-size: 11.5px;")
        layout.addWidget(self.obsidian_label)

        obsidian_row = QHBoxLayout()
        self.obsidian_input = QLineEdit()
        self.obsidian_input.setPlaceholderText("Path to Obsidian Vault (e.g. ~/Documents/Obsidian)...")
        obsidian_row.addWidget(self.obsidian_input)

        self.obsidian_browse_btn = QPushButton("Browse...")
        self.obsidian_browse_btn.setObjectName("secondaryButton")
        self.obsidian_browse_btn.clicked.connect(self._browse_obsidian_vault)
        obsidian_row.addWidget(self.obsidian_browse_btn)
        layout.addLayout(obsidian_row)

        # 6. Dual Language Configuration Row
        lang_row = QHBoxLayout()
        lang_row.setSpacing(12)

        # 6A. Interface Language (Desktop App)
        ui_lang_box = QVBoxLayout()
        ui_lang_box.setSpacing(4)
        self.ui_lang_label = QLabel("Interface Language (Desktop UI):")
        self.ui_lang_label.setStyleSheet("font-weight: 500; color: #94A3B8; font-size: 11.5px;")
        ui_lang_box.addWidget(self.ui_lang_label)

        self.ui_lang_combo = QComboBox()
        self.ui_lang_combo.addItem("English", "en")
        self.ui_lang_combo.addItem("Deutsch", "de")
        self.ui_lang_combo.addItem("Français", "fr")
        self.ui_lang_combo.addItem("Español", "es")
        self.ui_lang_combo.addItem("中文", "zh")
        self.ui_lang_combo.currentIndexChanged.connect(self._on_ui_language_selected)
        ui_lang_box.addWidget(self.ui_lang_combo)
        lang_row.addLayout(ui_lang_box)

        # 6B. Output Synthesis Target Language
        output_lang_box = QVBoxLayout()
        output_lang_box.setSpacing(4)
        self.lang_label = QLabel("Synthesis Target Language (Notes):")
        self.lang_label.setStyleSheet("font-weight: 500; color: #94A3B8; font-size: 11.5px;")
        output_lang_box.addWidget(self.lang_label)

        self.lang_combo = QComboBox()
        self.lang_combo.addItem("Auto / Original (Lecture Language)", "auto")
        self.lang_combo.addItem("English (US/UK)", "en")
        self.lang_combo.addItem("Deutsch (German)", "de")
        self.lang_combo.addItem("Français (French)", "fr")
        self.lang_combo.addItem("Español (Spanish)", "es")
        self.lang_combo.addItem("中文 (Mandarin)", "zh")
        output_lang_box.addWidget(self.lang_combo)
        lang_row.addLayout(output_lang_box)

        layout.addLayout(lang_row)

        # Status Label
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-size: 11.5px; color: #94A3B8;")
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
            self.cancel_btn = QPushButton("Cancel")
            self.cancel_btn.setObjectName("secondaryButton")
            self.cancel_btn.clicked.connect(self.reject)
            btn_layout.addWidget(self.cancel_btn)
        else:
            self.exit_btn = QPushButton("Close")
            self.exit_btn.setObjectName("secondaryButton")
            self.exit_btn.clicked.connect(self._quit_application)
            btn_layout.addWidget(self.exit_btn)

        self.save_btn = QPushButton("Save && Validate")
        self.save_btn.setObjectName("primaryButton")
        self.save_btn.clicked.connect(self._validate_and_save)
        btn_layout.addWidget(self.save_btn)

        layout.addLayout(btn_layout)

    def _toggle_free_guide(self):
        is_hidden = self.guide_frame.isHidden()
        self.guide_frame.setVisible(is_hidden)
        if is_hidden:
            self.guide_toggle_btn.setText(tr("guide_toggle_btn_close", lang=self._active_ui_lang))
        else:
            self.guide_toggle_btn.setText(tr("guide_toggle_btn", lang=self._active_ui_lang))
        self.adjustSize()

    def retranslate_ui(self, lang_code: Optional[str] = None):
        """Updates all visible texts in SettingsDialog according to specified or current language."""
        lang = lang_code or self._active_ui_lang

        self.setWindowTitle(tr("settings_dialog_title", lang=lang))
        self.title_label.setText(tr("settings_header_title", lang=lang))
        self.subtitle_label.setText(tr("settings_header_subtitle", lang=lang))
        self.model_label.setText(tr("settings_model_label", lang=lang))

        # Model options
        curr_preset_id = self.model_combo.currentData() or "gemini-max"
        populate_preset_combobox(self.model_combo, lang)
        select_preset_in_combobox(self.model_combo, curr_preset_id)

        self.info_text.setText(tr("settings_info_banner", lang=lang))
        self.link_btn.setText(tr("settings_link_aistudio", lang=lang))

        is_guide_open = hasattr(self, "guide_frame") and not self.guide_frame.isHidden()
        self.guide_toggle_btn.setText(tr("guide_toggle_btn_close" if is_guide_open else "guide_toggle_btn", lang=lang))
        self.guide_step1_lbl.setText(f"<b>{tr('guide_step1_title', lang=lang)}</b><br>{tr('guide_step1_desc', lang=lang)}")
        self.guide_step2_lbl.setText(f"<b>{tr('guide_step2_title', lang=lang)}</b><br>{tr('guide_step2_desc', lang=lang)}")
        self.guide_step3_lbl.setText(f"<b>{tr('guide_step3_title', lang=lang)}</b><br>{tr('guide_step3_desc', lang=lang)}")
        self.guide_action_btn.setText(tr("guide_action_btn", lang=lang))

        self.tier_notice.setText(tr("settings_tier_notice", lang=lang))
        self.gemini_label.setText(tr("settings_gemini_key_label", lang=lang))
        if hasattr(self, "get_free_key_btn"):
            self.get_free_key_btn.setText(tr("preview_free_guide_link", lang=lang))
        self.anthropic_label.setText(tr("settings_anthropic_key_label", lang=lang))
        self.openai_label.setText(tr("settings_openai_key_label", lang=lang))
        self.obsidian_label.setText(tr("settings_vault_label", lang=lang))
        self.obsidian_input.setPlaceholderText(tr("settings_vault_placeholder", lang=lang))
        self.obsidian_browse_btn.setText(tr("btn_browse", lang=lang))

        self.ui_lang_label.setText(tr("settings_ui_lang_label", lang=lang))
        self.lang_label.setText(tr("settings_output_lang_label", lang=lang))

        # Output lang auto label
        curr_out_idx = self.lang_combo.currentIndex()
        self.lang_combo.setItemText(0, tr("settings_output_lang_auto", lang=lang))
        self.lang_combo.setCurrentIndex(curr_out_idx)

        if hasattr(self, "cancel_btn"):
            self.cancel_btn.setText(tr("btn_cancel", lang=lang))
        if hasattr(self, "exit_btn"):
            self.exit_btn.setText(tr("btn_close", lang=lang))
        self.save_btn.setText(tr("btn_save", lang=lang))

    def _on_ui_language_selected(self, index: int):
        new_lang = self.ui_lang_combo.currentData()
        if new_lang and new_lang != self._active_ui_lang:
            self._active_ui_lang = new_lang
            self.retranslate_ui(new_lang)

    def _load_existing_settings(self):
        # Load active model preset
        active_model = get_selected_model()
        select_preset_in_combobox(self.model_combo, active_model)

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

        # Load Obsidian vault path
        vault_path = get_obsidian_vault_path()
        if vault_path:
            self.obsidian_input.setText(vault_path)

        # Load UI language
        ui_lang = get_ui_language()
        ui_idx = self.ui_lang_combo.findData(ui_lang)
        if ui_idx >= 0:
            self.ui_lang_combo.blockSignals(True)
            self.ui_lang_combo.setCurrentIndex(ui_idx)
            self.ui_lang_combo.blockSignals(False)
            self._active_ui_lang = ui_lang

        # Load output synthesis language
        target_lang = get_output_language()
        lang_idx = self.lang_combo.findData(target_lang)
        if lang_idx >= 0:
            self.lang_combo.setCurrentIndex(lang_idx)

        if gemini_key or ant_key or oai_key or vault_path:
            self.status_label.setText(tr("settings_status_loaded", lang=self._active_ui_lang))
            self.status_label.setStyleSheet("color: #FFFFFF; font-size: 11.5px;")

    def _browse_obsidian_vault(self):
        current_val = self.obsidian_input.text().strip()
        start_dir = os.path.expanduser(current_val) if current_val else os.path.expanduser("~/Documents")
        chosen = QFileDialog.getExistingDirectory(
            self,
            tr("settings_vault_label", lang=self._active_ui_lang),
            start_dir,
            QFileDialog.Option.ShowDirsOnly,
        )
        if chosen:
            self.obsidian_input.setText(chosen)

    def _on_model_changed(self):
        self.status_label.setText("")
        preset_id = self.model_combo.currentData()
        if not preset_id:
            return
        from src.engine.config import resolve_model_preset
        preset = resolve_model_preset(preset_id)
        provider = preset["required_provider"]
        if provider == "anthropic" and hasattr(self, "anthropic_input"):
            self.anthropic_input.setFocus()
        elif provider == "openai" and hasattr(self, "openai_input"):
            self.openai_input.setFocus()
        elif hasattr(self, "gemini_input"):
            self.gemini_input.setFocus()

    def _toggle_echo(self, line_edit: QLineEdit, button: QPushButton):
        if line_edit.echoMode() == QLineEdit.EchoMode.Password:
            line_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            button.setText("Hide")
        else:
            line_edit.setEchoMode(QLineEdit.EchoMode.Password)
            button.setText("Show")

    def _open_ai_studio(self):
        QDesktopServices.openUrl(QUrl("https://aistudio.google.com/app/apikey"))

    def _validate_and_save(self):
        selected_model = self.model_combo.currentData() or "gemini-max"
        gemini_key = self.gemini_input.text().strip()
        ant_key = self.anthropic_input.text().strip()
        oai_key = self.openai_input.text().strip()
        obsidian_vault = self.obsidian_input.text().strip()
        selected_output_lang = self.lang_combo.currentData()
        selected_ui_lang = self.ui_lang_combo.currentData()

        # Save Obsidian vault path & output language
        set_obsidian_vault_path(obsidian_vault if obsidian_vault else None)
        set_output_language(selected_output_lang)

        # Check UI language change
        old_ui_lang = get_ui_language()
        if selected_ui_lang and selected_ui_lang != old_ui_lang:
            set_ui_language(selected_ui_lang)
            self._active_ui_lang = selected_ui_lang
            self.language_changed.emit(selected_ui_lang)

        # Store pending keys for atomic persistence after validation succeeds
        self._pending_save_data = {
            "selected_model": selected_model,
            "gemini_key": gemini_key,
            "ant_key": ant_key,
            "oai_key": oai_key,
        }

        # Determine which key to validate based on selected coupled preset
        from src.engine.config import resolve_model_preset
        preset = resolve_model_preset(selected_model)
        provider = preset["required_provider"]
        if provider == "anthropic":
            target_key = ant_key
        elif provider == "openai":
            target_key = oai_key
        else:
            target_key = gemini_key

        if not target_key:
            self.status_label.setText(tr("settings_key_missing", lang=self._active_ui_lang, provider=provider.capitalize()))
            self.status_label.setStyleSheet("color: #F87171; font-size: 11.5px;")
            return

        self.save_btn.setEnabled(False)
        self.progress_bar.show()
        self.status_label.setText(tr("settings_checking_key", lang=self._active_ui_lang, provider=provider.capitalize()))
        self.status_label.setStyleSheet("color: #94A3B8; font-size: 11.5px;")

        self.worker = ValidationWorker(target_key, provider=provider)
        self.worker.validation_finished.connect(self._on_validation_result)
        self.worker.start()

    def _on_validation_result(self, is_valid: bool, message: str):
        self.progress_bar.hide()
        self.save_btn.setEnabled(True)

        if is_valid:
            # Persist credentials to OS native vault ONLY upon successful validation
            if hasattr(self, "_pending_save_data"):
                data = self._pending_save_data
                if data.get("gemini_key"):
                    set_api_key(data["gemini_key"], "gemini")
                if data.get("ant_key"):
                    set_api_key(data["ant_key"], "anthropic")
                if data.get("oai_key"):
                    set_api_key(data["oai_key"], "openai")
                if data.get("selected_model"):
                    set_selected_model(data["selected_model"])

            self.status_label.setText("[OK] " + message)
            self.status_label.setStyleSheet("color: #FFFFFF; font-weight: 600; font-size: 11.5px;")
            self.accept()
        else:
            self.status_label.setText("[ERR] " + message)
            self.status_label.setStyleSheet("color: #F87171; font-size: 11.5px;")

    def _quit_application(self):
        self.reject()
        sys.exit(0)


def ensure_api_key_configured(parent=None) -> bool:
    """
    Checks if an API key exists for the active model provider. If not, blocks execution
    and prompts the user via SettingsDialog. Returns True if a valid key is present or set.
    """
    from src.engine.config import resolve_model_preset
    selected_model = get_selected_model()
    preset = resolve_model_preset(selected_model)
    provider = preset["required_provider"]

    if has_api_key(provider):
        return True

    # If active provider key missing but another valid key exists, permit startup
    if has_api_key("gemini") or has_api_key("anthropic") or has_api_key("openai"):
        return True

    dialog = SettingsDialog(parent=parent, is_initial_setup=True)
    result = dialog.exec()
    return result == QDialog.DialogCode.Accepted and (
        has_api_key("gemini") or has_api_key("anthropic") or has_api_key("openai")
    )
