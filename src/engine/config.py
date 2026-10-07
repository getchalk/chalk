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
