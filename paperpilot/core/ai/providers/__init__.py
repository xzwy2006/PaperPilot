"""
paperpilot/core/ai/providers/__init__.py

AI Provider abstraction layer for PaperPilot.

Provides:
- BaseProvider     — abstract base class
- AIResponse       — standardised chat response
- AIUsage          — token usage info
- OpenAIProvider   — OpenAI-compatible HTTP provider
- OllamaProvider   — Ollama local HTTP provider
- ProviderConfig   — load/save/get_provider config wrapper
"""
from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx


# ──────────────────────────────────────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class AIUsage:
    """Token-usage info returned alongside an AI response."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class AIResponse:
    """Standardised response from any AI provider."""
    content: str
    model: str = ""
    usage: AIUsage = field(default_factory=AIUsage)
    raw: Any = None  # original parsed JSON for debugging


# ──────────────────────────────────────────────────────────────────────────────
# Base class
# ──────────────────────────────────────────────────────────────────────────────

class BaseProvider(ABC):
    """Abstract base for all AI providers."""

    @abstractmethod
    def chat(
        self,
        messages: List[Dict[str, str]],
        model: str,
        **kwargs: Any,
    ) -> AIResponse:
        """Send a chat request and return an AIResponse."""

    @abstractmethod
    def list_models(self) -> List[str]:
        """Return a sorted list of available model names."""

    @abstractmethod
    def test_connection(self) -> Tuple[bool, str]:
        """
        Check connectivity.
        Returns (True, "") on success or (False, error_message) on failure.
        """


# ──────────────────────────────────────────────────────────────────────────────
# OpenAI-compatible provider
# ──────────────────────────────────────────────────────────────────────────────

class OpenAIProvider(BaseProvider):
    """
    Provider for any OpenAI-compatible API endpoint
    (OpenAI, Azure OpenAI, LM Studio, vLLM, etc.).
    """

    DEFAULT_BASE_URL = "https://api.openai.com/v1"
    DEFAULT_TIMEOUT = 60.0

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ── internal helper ──────────────────────────────────────────────────────

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    # ── BaseProvider interface ───────────────────────────────────────────────

    def chat(
        self,
        messages: List[Dict[str, str]],
        model: str = "gpt-4o-mini",
        temperature: float = 0.2,
        **kwargs: Any,
    ) -> AIResponse:
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            **kwargs,
        }
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]["message"]["content"]
        usage_raw = data.get("usage", {})
        usage = AIUsage(
            prompt_tokens=usage_raw.get("prompt_tokens", 0),
            completion_tokens=usage_raw.get("completion_tokens", 0),
            total_tokens=usage_raw.get("total_tokens", 0),
        )
        return AIResponse(content=choice, model=data.get("model", model), usage=usage, raw=data)

    def list_models(self) -> List[str]:
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(
                f"{self.base_url}/models",
                headers=self._headers(),
            )
        resp.raise_for_status()
        data = resp.json()
        return sorted(item["id"] for item in data.get("data", []))

    def test_connection(self) -> Tuple[bool, str]:
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json={
                        "model": "gpt-4o-mini",
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 1,
                    },
                )
            if resp.status_code == 401:
                return False, f"Authentication failed (HTTP 401): invalid API key"
            if resp.status_code >= 400:
                return False, f"HTTP error {resp.status_code}: {resp.text[:200]}"
            return True, ""
        except httpx.TimeoutException as exc:
            return False, f"Connection timed out: {exc}"
        except httpx.ConnectError as exc:
            return False, f"Connection refused: {exc}"
        except Exception as exc:  # pragma: no cover
            return False, f"Unexpected error: {exc}"


# ──────────────────────────────────────────────────────────────────────────────
# Ollama provider
# ──────────────────────────────────────────────────────────────────────────────

class OllamaProvider(BaseProvider):
    """
    Provider for a locally-running Ollama instance.
    Uses Ollama's native REST API (/api/chat, /api/tags).
    """

    DEFAULT_BASE_URL = "http://localhost:11434"
    DEFAULT_TIMEOUT = 120.0

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ── BaseProvider interface ───────────────────────────────────────────────

    def chat(
        self,
        messages: List[Dict[str, str]],
        model: str = "llama3",
        **kwargs: Any,
    ) -> AIResponse:
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            **kwargs,
        }
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.base_url}/api/chat",
                json=payload,
            )
        resp.raise_for_status()
        data = resp.json()
        content = data["message"]["content"]
        usage_raw = data.get("usage", {})
        usage = AIUsage(
            prompt_tokens=usage_raw.get("prompt_tokens", 0),
            completion_tokens=usage_raw.get("completion_tokens", 0),
            total_tokens=usage_raw.get("total_tokens", 0),
        )
        return AIResponse(content=content, model=data.get("model", model), usage=usage, raw=data)

    def list_models(self) -> List[str]:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(f"{self.base_url}/api/tags")
        resp.raise_for_status()
        data = resp.json()
        return sorted(m["name"] for m in data.get("models", []))

    def test_connection(self) -> Tuple[bool, str]:
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": "llama3",
                        "messages": [{"role": "user", "content": "ping"}],
                        "stream": False,
                    },
                )
            if resp.status_code >= 400:
                return False, f"HTTP error {resp.status_code}: {resp.text[:200]}"
            return True, ""
        except (httpx.ConnectError, ConnectionRefusedError) as exc:
            return False, f"Connection refused: {exc}"
        except httpx.TimeoutException as exc:
            return False, f"Connection timed out: {exc}"
        except Exception as exc:  # pragma: no cover
            return False, f"Unexpected error: {exc}"


# ──────────────────────────────────────────────────────────────────────────────
# Provider config
# ──────────────────────────────────────────────────────────────────────────────

_CONFIG_FILENAME = "ai_providers.json"


class ProviderConfig:
    """
    Manages persisted AI-provider configuration.

    Config format (JSON):
    {
        "active": "openai",          # or "ollama"
        "openai": {
            "api_key": "...",
            "base_url": "https://api.openai.com/v1"
        },
        "ollama": {
            "base_url": "http://localhost:11434"
        }
    }
    """

    def __init__(self, config_dir: Optional[Path | str] = None) -> None:
        if config_dir is None:
            config_dir = Path.home() / ".paperpilot"
        self.config_dir = Path(config_dir)
        self.config_path = self.config_dir / _CONFIG_FILENAME

    # ── persistence ──────────────────────────────────────────────────────────

    def load(self) -> Dict[str, Any]:
        """Load config from disk. Returns empty dict if file does not exist."""
        if not self.config_path.exists():
            return {}
        try:
            return json.loads(self.config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def save(self, config: Dict[str, Any]) -> None:
        """Persist config dict to disk (creates parent dirs as needed)."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(config, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── factory ──────────────────────────────────────────────────────────────

    def get_provider(self, config: Optional[Dict[str, Any]] = None) -> BaseProvider:
        """
        Instantiate the active provider from *config* (or load from disk if None).
        Raises KeyError/ValueError for unknown/missing provider type.
        """
        if config is None:
            config = self.load()

        provider_name: str = config.get("active", "openai")

        if provider_name == "openai":
            cfg = config.get("openai", {})
            return OpenAIProvider(
                api_key=cfg.get("api_key", ""),
                base_url=cfg.get("base_url", OpenAIProvider.DEFAULT_BASE_URL),
            )
        elif provider_name == "ollama":
            cfg = config.get("ollama", {})
            return OllamaProvider(
                base_url=cfg.get("base_url", OllamaProvider.DEFAULT_BASE_URL),
            )
        else:
            raise ValueError(f"Unknown provider: {provider_name!r}")
