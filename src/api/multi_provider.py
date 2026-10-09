"""
src/api/multi_provider.py - Resilient Multi-Provider LLM Engine for Chalk.
Provides unified exponential backoff with jitter, circuit breaking, and emergency disk dump
for Anthropic Claude, OpenAI, and Google Gemini runtimes.
"""

import os
import time
import json
import random
import logging
from typing import Optional, Dict, Any, List, Tuple

from src.security.key_manager import get_api_key
from src.api.gemini_client import GeminiLecturePipeline

logger = logging.getLogger("chalk.api.multi_provider")


class ResilientLLMAdapter:
    """
    Base class providing resilient HTTP request handling, exponential backoff with jitter,
    and zero-data-loss emergency persistence.
    """

    def __init__(self, provider_name: str, api_key: Optional[str] = None):
        self.provider_name = provider_name
        self.api_key = api_key or get_api_key(provider_name)
        self.max_retries = 3

    def _execute_with_backoff(self, func, *args, **kwargs):
        last_exception = None
        for attempt in range(self.max_retries + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                err_str = str(e).lower()
                is_transient = (
                    "429" in err_str
                    or "rate limit" in err_str
                    or "overloaded" in err_str
                    or "500" in err_str
                    or "502" in err_str
                    or "503" in err_str
                    or "504" in err_str
                    or "timeout" in err_str
                    or "connection" in err_str
                )
                if attempt < self.max_retries and is_transient:
                    jitter = random.uniform(0.1, 0.8)
                    backoff = min(8.0, (2 ** attempt) + jitter)
                    logger.warning(
                        "[%s] Transient error (attempt %d/%d): %s. Retrying in %.2fs...",
                        self.provider_name, attempt + 1, self.max_retries, e, backoff
                    )
                    time.sleep(backoff)
                else:
                    break
        if last_exception:
            raise last_exception

    def emergency_dump(self, session_id: Optional[str], payload: Dict[str, Any], error_msg: str) -> str:
        return GeminiLecturePipeline.emergency_dump_session(session_id, payload, error_msg)


FALLBACK_CLAUDE_MODEL = "claude-3-7-sonnet-20250219"
FALLBACK_OPENAI_MODEL = "gpt-4o"


class AnthropicClaudeAdapter(ResilientLLMAdapter):
    """
    Adapter for Anthropic Claude Frontier BYOK execution.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-5-5-sonnet"):
        super().__init__("anthropic", api_key)
        self.model = model

    def synthesize(self, prompt: str, system_prompt: str, session_id: Optional[str] = None) -> str:
        if not self.api_key:
            raise ValueError("No Anthropic API key found in OS credential vault.")

        def _call_model(target_model: str):
            import urllib.request
            url = "https://api.anthropic.com/v1/messages"
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            body = {
                "model": target_model,
                "max_tokens": 4096,
                "system": system_prompt,
                "messages": [{"role": "user", "content": prompt}],
            }
            req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                contents = data.get("content", [])
                text_parts = [c.get("text", "") for c in contents if c.get("type") == "text"]
                return "".join(text_parts)

        def _call():
            try:
                return _call_model(self.model)
            except Exception as e:
                err_str = str(e).lower()
                if ("404" in err_str or "not_found" in err_str or "model" in err_str) and self.model != FALLBACK_CLAUDE_MODEL:
                    logger.warning("Anthropic model '%s' unavailable, falling back to %s", self.model, FALLBACK_CLAUDE_MODEL)
                    return _call_model(FALLBACK_CLAUDE_MODEL)
                raise

        try:
            return self._execute_with_backoff(_call)
        except Exception as e:
            self.emergency_dump(session_id, {"prompt": prompt, "system": system_prompt}, str(e))
            raise


class OpenAIAdapter(ResilientLLMAdapter):
    """
    Adapter for OpenAI GPT-4o / Sol / o3 BYOK execution.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-6-1-sol"):
        super().__init__("openai", api_key)
        self.model = model

    def synthesize(self, prompt: str, system_prompt: str, session_id: Optional[str] = None) -> str:
        if not self.api_key:
            raise ValueError("No OpenAI API key found in OS credential vault.")

        def _call_model(target_model: str):
            import urllib.request
            url = "https://api.openai.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            body = {
                "model": target_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
            }
            req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "")
                return ""

        def _call():
            try:
                return _call_model(self.model)
            except Exception as e:
                err_str = str(e).lower()
                if ("404" in err_str or "model_not_found" in err_str or "does not exist" in err_str) and self.model != FALLBACK_OPENAI_MODEL:
                    logger.warning("OpenAI model '%s' unavailable, falling back to %s", self.model, FALLBACK_OPENAI_MODEL)
                    return _call_model(FALLBACK_OPENAI_MODEL)
                raise

        try:
            return self._execute_with_backoff(_call)
        except Exception as e:
            self.emergency_dump(session_id, {"prompt": prompt, "system": system_prompt}, str(e))
            raise
