"""
src/security/key_manager.py - True Zero-Knowledge BYOK Key Management.
Manages secure storage of Google AI Studio API keys in the OS credential vault
(Windows Credential Locker via DPAPI, macOS Keychain Access, or SecretService on Linux)
using the native keyring library.
Never writes keys to disk, .env files, stdout, or logs.
"""

import os
import logging
from typing import Tuple, Optional
import keyring
from keyring.errors import KeyringError

logger = logging.getLogger("chalk.security")

SERVICE_NAME = "Chalk"
ACCOUNT_NAME = "gemini_api_key"

# In-memory session cache to avoid redundant keychain prompts during a single run
_SESSION_KEY_CACHE: Optional[str] = None


def get_api_key() -> Optional[str]:
    """
    Retrieve the Gemini API key from the OS native encrypted vault.
    Falls back to environment variable GEMINI_API_KEY if OS vault is empty or unavailable.
    """
    global _SESSION_KEY_CACHE
    if _SESSION_KEY_CACHE:
        return _SESSION_KEY_CACHE

    try:
        key = keyring.get_password(SERVICE_NAME, ACCOUNT_NAME)
        if key and key.strip():
            _SESSION_KEY_CACHE = key.strip()
            return _SESSION_KEY_CACHE
    except KeyringError as e:
        logger.warning("Failed to access OS keyring: %s", type(e).__name__)
    except Exception as e:
        logger.warning("Unexpected error reading from keyring: %s", type(e).__name__)

    # Fallback to environment variable (useful in containerized/CI environments)
    env_key = os.environ.get("GEMINI_API_KEY")
    if env_key and env_key.strip():
        _SESSION_KEY_CACHE = env_key.strip()
        return _SESSION_KEY_CACHE

    return None


def set_api_key(api_key: str) -> bool:
    """
    Store the Gemini API key securely in the OS native encrypted vault.
    Never logs or echoes the raw key string.
    """
    global _SESSION_KEY_CACHE
    if not api_key or not api_key.strip():
        return False

    cleaned_key = api_key.strip()
    try:
        keyring.set_password(SERVICE_NAME, ACCOUNT_NAME, cleaned_key)
        _SESSION_KEY_CACHE = cleaned_key
        logger.info("API key successfully stored in OS credential vault.")
        return True
    except KeyringError as e:
        logger.error("OS Keyring failed to store password: %s", type(e).__name__)
        # Fallback to session cache so user can still proceed during this app lifecycle
        _SESSION_KEY_CACHE = cleaned_key
        return True
    except Exception as e:
        logger.error("Error setting password in keyring: %s", type(e).__name__)
        _SESSION_KEY_CACHE = cleaned_key
        return True


def delete_api_key() -> bool:
    """
    Remove the Gemini API key from the OS credential vault.
    """
    global _SESSION_KEY_CACHE
    _SESSION_KEY_CACHE = None
    try:
        keyring.delete_password(SERVICE_NAME, ACCOUNT_NAME)
        logger.info("API key removed from OS credential vault.")
        return True
    except KeyringError:
        return False
    except Exception:
        return False


def has_api_key() -> bool:
    """
    Check if a valid API key exists without exposing its value.
    """
    key = get_api_key()
    return bool(key and len(key.strip()) > 8)


def validate_api_key(api_key: str) -> Tuple[bool, str]:
    """
    Validate the Gemini API key against Google AI Studio using a zero-token ping:
    client.models.list(config={"page_size": 1}).
    Returns (is_valid, message).
    """
    if not api_key or not api_key.strip():
        return False, "API key cannot be empty."

    cleaned_key = api_key.strip()
    try:
        from google import genai

        client = genai.Client(api_key=cleaned_key)
        pager = client.models.list(config={"page_size": 1})
        # Force generator evaluation to trigger network authentication
        _ = next(iter(pager))
        return True, "API key successfully verified with Google AI Studio."
    except Exception as e:
        err_msg = str(e)
        logger.warning("API key validation failed: %s", err_msg)
        if "API_KEY_INVALID" in err_msg or "400" in err_msg or "INVALID_ARGUMENT" in err_msg:
            return False, "Invalid API Key. Please verify your key in Google AI Studio."
        elif "PERMISSION_DENIED" in err_msg or "403" in err_msg:
            return False, "Permission denied. Check that Gemini API is enabled for this key."
        else:
            return False, f"Validation error: {err_msg[:120]}"
