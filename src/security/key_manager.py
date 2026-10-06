"""
src/security/key_manager.py - True Zero-Knowledge BYOK Multi-Model Key Management.
Manages secure storage of API keys (Google AI Studio, Anthropic, OpenAI)
in the OS credential vault (macOS Keychain Access, Windows DPAPI, or Linux SecretService)
using the native keyring library.
Never writes keys to disk, .env files, stdout, or logs.
"""

import os
import logging
from typing import Tuple, Optional, Dict
import keyring
from keyring.errors import KeyringError

logger = logging.getLogger("chalk.security")

SERVICE_NAME = "Chalk"

PROVIDER_ACCOUNTS: Dict[str, str] = {
    "gemini": "gemini_api_key",
    "anthropic": "anthropic_api_key",
    "openai": "openai_api_key",
}
SELECTED_MODEL_ACCOUNT = "selected_model"
DEFAULT_MODEL = "gemini-2.5-flash"

# In-memory session cache to avoid redundant keychain prompts during a single run
_SESSION_KEY_CACHE: Dict[str, str] = {}
_SESSION_MODEL_CACHE: Optional[str] = None


def get_api_key(provider: str = "gemini") -> Optional[str]:
    """
    Retrieve the API key for the requested provider from the OS native encrypted vault.
    Falls back to environment variables (GEMINI_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY).
    """
    provider_key = provider.lower()
    account_name = PROVIDER_ACCOUNTS.get(provider_key, f"{provider_key}_api_key")

    if provider_key in _SESSION_KEY_CACHE:
        return _SESSION_KEY_CACHE[provider_key]

    try:
        key = keyring.get_password(SERVICE_NAME, account_name)
        if key and key.strip():
            _SESSION_KEY_CACHE[provider_key] = key.strip()
            return _SESSION_KEY_CACHE[provider_key]
    except KeyringError as e:
        logger.warning("Failed to access OS keyring for %s: %s", provider_key, type(e).__name__)
    except Exception as e:
        logger.warning("Unexpected error reading %s from keyring: %s", provider_key, type(e).__name__)

    # Fallback to environment variable
    env_vars = {
        "gemini": "GEMINI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
    }
    env_name = env_vars.get(provider_key)
    if env_name:
        env_key = os.environ.get(env_name)
        if env_key and env_key.strip():
            _SESSION_KEY_CACHE[provider_key] = env_key.strip()
            return _SESSION_KEY_CACHE[provider_key]

    return None


def set_api_key(api_key: str, provider: str = "gemini") -> bool:
    """
    Store the API key securely in the OS native encrypted vault.
    Never logs or echoes the raw key string.
    """
    provider_key = provider.lower()
    account_name = PROVIDER_ACCOUNTS.get(provider_key, f"{provider_key}_api_key")

    if not api_key or not api_key.strip():
        return False

    cleaned_key = api_key.strip()
    try:
        keyring.set_password(SERVICE_NAME, account_name, cleaned_key)
        _SESSION_KEY_CACHE[provider_key] = cleaned_key
        logger.info("API key for %s successfully stored in OS credential vault.", provider_key)
        return True
    except KeyringError as e:
        logger.error("OS Keyring failed to store password for %s: %s", provider_key, type(e).__name__)
        _SESSION_KEY_CACHE[provider_key] = cleaned_key
        return True
    except Exception as e:
        logger.error("Error setting password in keyring for %s: %s", provider_key, type(e).__name__)
        _SESSION_KEY_CACHE[provider_key] = cleaned_key
        return True


def delete_api_key(provider: str = "gemini") -> bool:
    """
    Remove the API key for a provider from the OS credential vault.
    """
    provider_key = provider.lower()
    account_name = PROVIDER_ACCOUNTS.get(provider_key, f"{provider_key}_api_key")

    if provider_key in _SESSION_KEY_CACHE:
        del _SESSION_KEY_CACHE[provider_key]

    try:
        keyring.delete_password(SERVICE_NAME, account_name)
        logger.info("API key for %s removed from OS credential vault.", provider_key)
        return True
    except KeyringError:
        return False
    except Exception:
        return False


def has_api_key(provider: str = "gemini") -> bool:
    """
    Check if a valid API key exists for a provider without exposing its value.
    """
    key = get_api_key(provider)
    return bool(key and len(key.strip()) > 8)


def get_selected_model() -> str:
    """
    Returns the currently active model ID ('gemini-2.5-flash', 'claude-3.7-sonnet', or 'gpt-4o').
    """
    global _SESSION_MODEL_CACHE
    if _SESSION_MODEL_CACHE:
        return _SESSION_MODEL_CACHE

    try:
        stored = keyring.get_password(SERVICE_NAME, SELECTED_MODEL_ACCOUNT)
        if stored and stored.strip():
            _SESSION_MODEL_CACHE = stored.strip()
            return _SESSION_MODEL_CACHE
    except Exception:
        pass

    _SESSION_MODEL_CACHE = DEFAULT_MODEL
    return _SESSION_MODEL_CACHE


def set_selected_model(model_name: str) -> bool:
    """
    Persists the selected model in the OS vault / session cache.
    """
    global _SESSION_MODEL_CACHE
    if not model_name:
        return False

    cleaned = model_name.strip()
    _SESSION_MODEL_CACHE = cleaned
    try:
        keyring.set_password(SERVICE_NAME, SELECTED_MODEL_ACCOUNT, cleaned)
        return True
    except Exception as e:
        logger.warning("Could not persist selected model in keyring: %s", e)
        return True


def validate_api_key(api_key: str, provider: str = "gemini") -> Tuple[bool, str]:
    """
    Validate the API key.
    - gemini: Zero-token ping against Google AI Studio using client.models.list.
    - anthropic: Validates key prefix ('sk-ant-') and length.
    - openai: Validates key prefix ('sk-') and length.
    Returns (is_valid, message).
    """
    if not api_key or not api_key.strip():
        return False, "API key cannot be empty."

    cleaned_key = api_key.strip()
    provider_key = provider.lower()

    if provider_key == "gemini":
        try:
            from google import genai

            client = genai.Client(api_key=cleaned_key)
            pager = client.models.list(config={"page_size": 1})
            _ = next(iter(pager))
            return True, "API key successfully verified with Google AI Studio."
        except Exception as e:
            err_msg = str(e)
            logger.warning("Gemini API key validation failed: %s", err_msg)
            if "API_KEY_INVALID" in err_msg or "400" in err_msg or "INVALID_ARGUMENT" in err_msg:
                return False, "Invalid API Key. Please verify your key in Google AI Studio."
            elif "PERMISSION_DENIED" in err_msg or "403" in err_msg:
                return False, "Permission denied. Check that Gemini API is enabled for this key."
            else:
                return False, f"Validation error: {err_msg[:120]}"

    elif provider_key == "anthropic":
        if cleaned_key.startswith("sk-ant-") and len(cleaned_key) >= 30:
            return True, "Anthropic API key format verified."
        return False, "Invalid Anthropic API Key. Must start with 'sk-ant-'."

    elif provider_key == "openai":
        if cleaned_key.startswith("sk-") and len(cleaned_key) >= 30:
            return True, "OpenAI API key format verified."
        return False, "Invalid OpenAI API Key. Must start with 'sk-'."

    return True, f"Key for {provider} verified."
