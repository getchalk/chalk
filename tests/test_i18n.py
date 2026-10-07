"""
tests/test_i18n.py - Unit Tests for Desktop i18n Parity Engine (EN, DE, FR, ES, ZH).
Enforces 100% complete dictionaries, fallback behaviors, and zero unicode emojis.
"""

import unittest
import re
from src.ui.i18n import (
    I18nManager,
    tr,
    get_i18n,
    set_ui_language,
    get_ui_language,
    SUPPORTED_LANGUAGES,
    TRANSLATIONS,
)
from src.engine.config import load_chalk_config, set_ui_language as cfg_set_ui


class TestI18nEngine(unittest.TestCase):

    def setUp(self):
        # Reset to English before tests
        self.i18n = I18nManager("en")
        I18nManager._instance = self.i18n

    def test_all_supported_languages_present(self):
        expected_langs = {"en", "de", "fr", "es", "zh"}
        self.assertEqual(set(SUPPORTED_LANGUAGES.keys()), expected_langs)

    def test_complete_translations_parity(self):
        """Every single key in TRANSLATIONS must have a non-empty string in all 5 languages."""
        missing = []
        for key, lang_dict in TRANSLATIONS.items():
            for lang in ("en", "de", "fr", "es", "zh"):
                val = lang_dict.get(lang)
                if not val or not isinstance(val, str) or not val.strip():
                    missing.append((key, lang))

        self.assertEqual(
            missing,
            [],
            f"Missing or empty translations detected: {missing}"
        )

    def test_zero_emojis_in_translations(self):
        """No translation string may contain unicode emojis."""
        emoji_pattern = re.compile(
            r"[\U00010000-\U0010ffff"
            r"\u2600-\u26FF"
            r"\u2700-\u27BF"
            r"\uFE00-\uFE0F"
            r"\u200D"
            r"\u2300-\u23FF"
            r"\u2B50-\u2B55]"
        )
        violations = []
        for key, lang_dict in TRANSLATIONS.items():
            for lang, text in lang_dict.items():
                if emoji_pattern.search(text):
                    violations.append((key, lang, text))

        self.assertEqual(
            violations,
            [],
            f"Found forbidden emoji in translations: {violations}"
        )

    def test_fallback_behavior(self):
        # Missing language code should fallback to English
        val_fallback = self.i18n.tr("status_standby", lang="unknown_lang")
        self.assertEqual(val_fallback, "STANDBY")

        # Unknown key returns the key itself
        val_unknown_key = self.i18n.tr("completely_nonexistent_key_xyz")
        self.assertEqual(val_unknown_key, "completely_nonexistent_key_xyz")

    def test_parameter_interpolation(self):
        res_en = self.i18n.tr("status_slides_ready", lang="en", count=42)
        self.assertEqual(res_en, "Slides attached: 42 pages")

        res_de = self.i18n.tr("status_slides_ready", lang="de", count=42)
        self.assertEqual(res_de, "Folien angehängt: 42 Seiten")

        res_fr = self.i18n.tr("status_slides_ready", lang="fr", count=42)
        self.assertEqual(res_fr, "Diapositives attachées : 42 pages")

        res_es = self.i18n.tr("status_slides_ready", lang="es", count=42)
        self.assertEqual(res_es, "Diapositivas adjuntas: 42 páginas")

        res_zh = self.i18n.tr("status_slides_ready", lang="zh", count=42)
        self.assertEqual(res_zh, "已附加幻灯片：42 页")

    def test_language_switching_and_persistence(self):
        set_ui_language("fr")
        self.assertEqual(get_ui_language(), "fr")
        self.assertEqual(tr("status_standby"), "EN VEILLE")

        set_ui_language("de")
        self.assertEqual(get_ui_language(), "de")
        self.assertEqual(tr("status_standby"), "BEREIT")

        set_ui_language("zh")
        self.assertEqual(get_ui_language(), "zh")
        self.assertEqual(tr("status_standby"), "待机")

        set_ui_language("en")
        self.assertEqual(get_ui_language(), "en")
        self.assertEqual(tr("status_standby"), "STANDBY")

    def test_ui_components_retranslate(self):
        """Validates that HUD, Search Modal, and Settings Dialog dynamically update text."""
        from PyQt6.QtWidgets import QApplication
        import sys

        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)

        from src.ui.hud_window import FloatingHUDWindow
        from src.ui.search_dialog import SessionArchiveSearchDialog
        from src.ui.settings_dialog import SettingsDialog
        from src.ui.tray import ChalkSystemTray

        # Test HUD
        hud = FloatingHUDWindow()
        set_ui_language("de")
        hud.retranslate_ui()
        self.assertEqual(hud.attach_doc_btn.text(), "Folien anhängen")
        self.assertEqual(hud.synth_btn.text(), "Beenden [F9]")

        set_ui_language("fr")
        hud.retranslate_ui()
        self.assertEqual(hud.attach_doc_btn.text(), "Joindre diapositives")
        self.assertEqual(hud.synth_btn.text(), "Terminer [F9]")

        set_ui_language("es")
        hud.retranslate_ui()
        self.assertEqual(hud.attach_doc_btn.text(), "Adjuntar diapositivas")
        self.assertEqual(hud.synth_btn.text(), "Finalizar [F9]")

        set_ui_language("zh")
        hud.retranslate_ui()
        self.assertEqual(hud.attach_doc_btn.text(), "附加幻灯片")
        self.assertEqual(hud.synth_btn.text(), "完成 [F9]")

        set_ui_language("en")
        hud.retranslate_ui()
        self.assertEqual(hud.attach_doc_btn.text(), "Attach Slides")
        self.assertEqual(hud.synth_btn.text(), "Finish [F9]")

        # Test Search Dialog
        search_dlg = SessionArchiveSearchDialog()
        set_ui_language("de")
        search_dlg.retranslate_ui()
        self.assertEqual(search_dlg.title_lbl.text(), "Archiv- & Formelsuche")

        set_ui_language("fr")
        search_dlg.retranslate_ui()
        self.assertEqual(search_dlg.title_lbl.text(), "Recherche d'archives et formules")

        set_ui_language("zh")
        search_dlg.retranslate_ui()
        self.assertEqual(search_dlg.title_lbl.text(), "归档与公式搜索")

        # Test Settings Dialog
        settings_dlg = SettingsDialog()
        set_ui_language("fr")
        settings_dlg.retranslate_ui("fr")
        self.assertEqual(settings_dlg.save_btn.text(), "Enregistrer & Valider")

        set_ui_language("de")
        settings_dlg.retranslate_ui("de")
        self.assertEqual(settings_dlg.save_btn.text(), "Speichern & Prüfen")

        # Test Tray Menu Retranslate
        tray = ChalkSystemTray()
        set_ui_language("fr")
        menu = tray._build_menu()
        self.assertIsNotNone(menu)

        # Reset to en
        set_ui_language("en")


if __name__ == "__main__":
    unittest.main()

