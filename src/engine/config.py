"""
src/engine/config.py - Persistent Configuration Manager for Chalk (~/.chalk/config.json).
Stores user preferences such as Obsidian Vault directory, preferred audio settings,
and export configurations.
"""

import os
import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("chalk.engine.config")

CONFIG_DIR = os.path.expanduser("~/.chalk")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")


def load_chalk_config() -> Dict[str, Any]:
    """Reads ~/.chalk/config.json, returning empty dict if missing or malformed."""
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning("Failed to load config from %s: %s", CONFIG_FILE, e)
        return {}


def save_chalk_config(cfg: Dict[str, Any]) -> bool:
    """Saves dictionary to ~/.chalk/config.json atomically."""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp_file = f"{CONFIG_FILE}.tmp.{os.getpid()}"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_file, CONFIG_FILE)
        return True
    except Exception as e:
        logger.error("Failed to write config to %s: %s", CONFIG_FILE, e)
        return False


def get_obsidian_vault_path() -> Optional[str]:
    """Retrieves the configured Obsidian vault path if present and valid."""
    cfg = load_chalk_config()
    val = cfg.get("obsidian_vault_path")
    if val and isinstance(val, str) and val.strip():
        return os.path.abspath(os.path.expanduser(val.strip()))
    return None


def set_obsidian_vault_path(path: Optional[str]) -> bool:
    """Updates the Obsidian vault path in ~/.chalk/config.json."""
    cfg = load_chalk_config()
    if path and path.strip():
        cfg["obsidian_vault_path"] = os.path.abspath(os.path.expanduser(path.strip()))
    else:
        cfg.pop("obsidian_vault_path", None)
    return save_chalk_config(cfg)


def get_output_language() -> str:
    """Retrieves configured target synthesis output language (default 'auto')."""
    cfg = load_chalk_config()
    lang = cfg.get("output_language", "auto")
    if isinstance(lang, str) and lang.strip():
        return lang.strip().lower()
    return "auto"


def set_output_language(language_code: Optional[str]) -> bool:
    """Sets target synthesis output language ('auto', 'de', 'en', 'fr', 'es', 'zh')."""
    cfg = load_chalk_config()
    clean_code = (language_code or "auto").strip().lower()
    if clean_code in ("auto", "original", "none"):
        cfg["output_language"] = "auto"
    else:
        cfg["output_language"] = clean_code
    return save_chalk_config(cfg)


def get_configured_ui_language() -> Optional[str]:
    """Retrieves explicitly configured UI language, or None if not set."""
    cfg = load_chalk_config()
    lang = cfg.get("ui_language")
    if isinstance(lang, str) and lang.strip().lower() in ("en", "de", "fr", "es", "zh"):
        return lang.strip().lower()
    return None


def get_ui_language() -> str:
    """Retrieves UI language ('en', 'de', 'fr', 'es', 'zh'). Defaults to system language or 'en'."""
    configured = get_configured_ui_language()
    if configured:
        return configured
    # Fallback to system locale detection
    try:
        from PyQt6.QtCore import QLocale
        loc_name = QLocale.system().name().lower()
    except Exception:
        loc_name = os.environ.get("LANG", "en").lower()

    if loc_name.startswith("de"):
        return "de"
    elif loc_name.startswith("fr"):
        return "fr"
    elif loc_name.startswith("es"):
        return "es"
    elif loc_name.startswith("zh"):
        return "zh"
    return "en"


def set_ui_language(language_code: Optional[str]) -> bool:
    """Persists chosen UI language in ~/.chalk/config.json."""
    cfg = load_chalk_config()
    clean_code = (language_code or "en").strip().lower()
    if clean_code in ("en", "de", "fr", "es", "zh"):
        cfg["ui_language"] = clean_code
    else:
        cfg["ui_language"] = "en"
    return save_chalk_config(cfg)


# ==============================================================================
# Coupled Dual-Stage Model Selection Presets (Phase 28)
# Separates Daily Live-Chunking (Flash) vs. High-Yield Master Synthesis (Pro)
# ==============================================================================

COUPLED_MODEL_PRESETS: Dict[str, Dict[str, Any]] = {
    "gemini-max": {
        "id": "gemini-max",
        "i18n_key": "model_preset_gemini_max",
        "display_name": "Gemini Maximum: Gemini 3.5 Flash (Operational) + Gemini 3.1 Pro (Synthesis)",
        "short_name": "Gemini Maximum",
        "category": "free",
        "flash_model": "gemini-3.5-flash",
        "pro_model": "gemini-3.1-pro",
        "daily_rpd_limit": 50,
        "required_provider": "gemini",
        "description": "High Reasoning Tier • Gemini 3.5 Flash (Operational) + Gemini 3.1 Pro (Synthesis)",
    },
    "gemini-medium": {
        "id": "gemini-medium",
        "i18n_key": "model_preset_gemini_medium",
        "display_name": "Gemini Medium: Gemini 3.5 Flash-Lite (Operational) + Gemini 3.5 Flash (Synthesis)",
        "short_name": "Gemini Medium",
        "category": "free",
        "flash_model": "gemini-3.5-flash-lite",
        "pro_model": "gemini-3.5-flash",
        "daily_rpd_limit": 500,
        "required_provider": "gemini",
        "description": "Balanced Quota Tier • Gemini 3.5 Flash-Lite (Operational) + Gemini 3.5 Flash (Synthesis)",
    },
    "gemini-min": {
        "id": "gemini-min",
        "i18n_key": "model_preset_gemini_min",
        "display_name": "Gemini Minimum: Gemini 3.1 Flash-Lite (Operational) + Gemini 3.5 Flash-Lite (Synthesis)",
        "short_name": "Gemini Minimum",
        "category": "free",
        "flash_model": "gemini-3.1-flash-lite",
        "pro_model": "gemini-3.5-flash-lite",
        "daily_rpd_limit": 1500,
        "required_provider": "gemini",
        "description": "Max Quota Tier • Gemini 3.1 Flash-Lite (Operational) + Gemini 3.5 Flash-Lite (Synthesis)",
    },
    "paid-gemini": {
        "id": "paid-gemini",
        "i18n_key": "model_preset_paid_gemini",
        "display_name": "Gemini 3.8 Flash (Operational & Synthesis)",
        "short_name": "Gemini 3.8 Flash",
        "category": "premium",
        "flash_model": "gemini-3.8-flash",
        "pro_model": "gemini-3.8-flash",
        "daily_rpd_limit": 10000,
        "required_provider": "gemini",
        "description": "Direct BYOK • Gemini 3.8 Flash (Operational & Synthesis)",
    },
    "paid-claude": {
        "id": "paid-claude",
        "i18n_key": "model_preset_paid_claude",
        "display_name": "Claude 5.5 Sonnet (Operational & Synthesis)",
        "short_name": "Claude 5.5 Sonnet",
        "category": "premium",
        "flash_model": "claude-5-5-sonnet",
        "pro_model": "claude-5-5-sonnet",
        "daily_rpd_limit": 10000,
        "required_provider": "anthropic",
        "description": "Direct BYOK • Claude 5.5 Sonnet (Operational & Synthesis)",
    },
    "paid-openai": {
        "id": "paid-openai",
        "i18n_key": "model_preset_paid_openai",
        "display_name": "GPT-6.1 Sol (Operational & Synthesis)",
        "short_name": "GPT-6.1 Sol",
        "category": "premium",
        "flash_model": "gpt-6-1-sol",
        "pro_model": "gpt-6-1-sol",
        "daily_rpd_limit": 10000,
        "required_provider": "openai",
        "description": "Direct BYOK • GPT-6.1 Sol (Operational & Synthesis)",
    },
}

DEFAULT_MODEL_PRESET = "gemini-max"


def resolve_model_preset(preset_or_model_id: Optional[str]) -> Dict[str, Any]:
    """
    Resolves a preset ID or legacy model name into the coupled preset configuration.
    """
    if not preset_or_model_id:
        return COUPLED_MODEL_PRESETS[DEFAULT_MODEL_PRESET]

    key = str(preset_or_model_id).strip()
    if key in COUPLED_MODEL_PRESETS:
        return COUPLED_MODEL_PRESETS[key]

    lower = key.lower()
    if "paid-gemini" in lower or "3.8" in lower or ("paid" in lower and "gemini" in lower):
        return COUPLED_MODEL_PRESETS["paid-gemini"]
    elif "claude" in lower:
        return COUPLED_MODEL_PRESETS["paid-claude"]
    elif "gpt" in lower or "openai" in lower or "sol" in lower or "o3" in lower:
        return COUPLED_MODEL_PRESETS["paid-openai"]
    elif "min" in lower or "lite" in lower or "eco" in lower:
        return COUPLED_MODEL_PRESETS["gemini-min"]
    elif "medium" in lower or "mid" in lower or "2.0" in lower:
        return COUPLED_MODEL_PRESETS["gemini-medium"]
    elif "max" in lower or "pro" in lower:
        return COUPLED_MODEL_PRESETS["gemini-max"]
    else:
        return COUPLED_MODEL_PRESETS[DEFAULT_MODEL_PRESET]

