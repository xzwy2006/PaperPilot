"""
tests/test_ai_providers.py — Phase 7.3: AI Provider test suite for PaperPilot.

Covers:
- BaseProvider interface (inheritance, abstract methods)
- OpenAIProvider  (mock HTTP via unittest.mock.patch)
    * normal chat response → AIResponse.content correct, usage populated
    * HTTP 401 → test_connection returns (False, "...")
    * TimeoutException → test_connection returns (False, "...")
    * list_models → sorted list of model-id strings
- OllamaProvider  (mock HTTP via unittest.mock.patch)
    * normal /api/chat response → AIResponse correct
    * ConnectError → test_connection returns (False, "...")
    * list_models → parses /api/tags response
- ProviderConfig
    * load() on missing file → empty dict, no exception
    * save() + load() round-trip consistent
    * get_provider() returns correct Provider instance type
    * tempfile isolation (does not touch ~/.paperpilot/)
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from paperpilot.core.ai.providers import (
    AIResponse,
    AIUsage,
    BaseProvider,
    OllamaProvider,
    OpenAIProvider,
    ProviderConfig,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_httpx_response(status_code: int, body: Any) -> MagicMock:
    """Build a MagicMock that mimics an httpx.Response."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.text = json.dumps(body) if not isinstance(body, str) else body
    mock_resp.json.return_value = body if isinstance(body, dict) else json.loads(body)
    if status_code >= 400:
        mock_resp.raise_for_status.side_effect = Exception(
            f"HTTP Error {status_code}"
        )
    else:
        mock_resp.raise_for_status.return_value = None
    return mock_resp


def _openai_chat_body(
    content: str = "Hello, world!",
    model: str = "gpt-4o-mini",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
) -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def _openai_models_body(model_ids: list) -> dict:
    return {
        "object": "list",
        "data": [{"id": mid, "object": "model"} for mid in model_ids],
    }


def _ollama_chat_body(
    content: str = "Bonjour!",
    model: str = "llama3",
) -> dict:
    return {
        "model": model,
        "message": {"role": "assistant", "content": content},
        "done": True,
    }


def _ollama_tags_body(model_names: list) -> dict:
    return {
        "models": [{"name": name} for name in model_names]
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. BaseProvider interface
# ─────────────────────────────────────────────────────────────────────────────

class TestBaseProviderInterface:
    """Verify the inheritance hierarchy and abstract method contract."""

    def test_openai_provider_inherits_base(self):
        assert issubclass(OpenAIProvider, BaseProvider)

    def test_ollama_provider_inherits_base(self):
        assert issubclass(OllamaProvider, BaseProvider)

    def test_base_provider_is_abstract(self):
        """BaseProvider cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseProvider()  # type: ignore[abstract]

    def test_openai_provider_has_chat(self):
        assert callable(getattr(OpenAIProvider, "chat", None))

    def test_openai_provider_has_list_models(self):
        assert callable(getattr(OpenAIProvider, "list_models", None))

    def test_openai_provider_has_test_connection(self):
        assert callable(getattr(OpenAIProvider, "test_connection", None))

    def test_ollama_provider_has_chat(self):
        assert callable(getattr(OllamaProvider, "chat", None))

    def test_ollama_provider_has_list_models(self):
        assert callable(getattr(OllamaProvider, "list_models", None))

    def test_ollama_provider_has_test_connection(self):
        assert callable(getattr(OllamaProvider, "test_connection", None))

    def test_airesponse_has_content(self):
        resp = AIResponse(content="test")
        assert resp.content == "test"

    def test_aiusage_fields(self):
        usage = AIUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        assert usage.prompt_tokens == 10
        assert usage.completion_tokens == 5
        assert usage.total_tokens == 15


# ─────────────────────────────────────────────────────────────────────────────
# 2. OpenAIProvider — mock HTTP
# ─────────────────────────────────────────────────────────────────────────────

class TestOpenAIProviderChat:
    """OpenAIProvider.chat() with mocked httpx.Client.post."""

    def _provider(self) -> OpenAIProvider:
        return OpenAIProvider(api_key="sk-test-key")

    @patch("httpx.Client.post")
    def test_chat_normal_response_content(self, mock_post):
        """Normal 200 response → AIResponse.content matches assistant message."""
        body = _openai_chat_body(content="Paris is the capital of France.")
        mock_post.return_value = _make_httpx_response(200, body)

        provider = self._provider()
        messages = [{"role": "user", "content": "What is the capital of France?"}]
        resp = provider.chat(messages=messages, model="gpt-4o-mini")

        assert isinstance(resp, AIResponse)
        assert resp.content == "Paris is the capital of France."

    @patch("httpx.Client.post")
    def test_chat_normal_response_usage_prompt_tokens(self, mock_post):
        """Normal response → usage.prompt_tokens is populated."""
        body = _openai_chat_body(prompt_tokens=42, completion_tokens=8)
        mock_post.return_value = _make_httpx_response(200, body)

        provider = self._provider()
        resp = provider.chat(
            messages=[{"role": "user", "content": "Summarize this paper."}],
            model="gpt-4o-mini",
        )

        assert isinstance(resp.usage, AIUsage)
        assert resp.usage.prompt_tokens == 42
        assert resp.usage.completion_tokens == 8
        assert resp.usage.total_tokens == 50

    @patch("httpx.Client.post")
    def test_chat_normal_response_model(self, mock_post):
        """Normal response → AIResponse.model echoes the model field."""
        body = _openai_chat_body(model="gpt-4-turbo")
        mock_post.return_value = _make_httpx_response(200, body)

        provider = self._provider()
        resp = provider.chat(
            messages=[{"role": "user", "content": "ping"}],
            model="gpt-4-turbo",
        )

        assert resp.model == "gpt-4-turbo"

    @patch("httpx.Client.post")
    def test_chat_passes_messages_to_post(self, mock_post):
        """chat() must forward the messages list to httpx.Client.post."""
        body = _openai_chat_body()
        mock_post.return_value = _make_httpx_response(200, body)

        provider = self._provider()
        messages = [
            {"role": "system", "content": "You are a research assistant."},
            {"role": "user", "content": "Summarize."},
        ]
        provider.chat(messages=messages, model="gpt-4o-mini")

        call_kwargs = mock_post.call_args.kwargs
        sent_json = call_kwargs.get("json", {})
        assert sent_json["messages"] == messages


class TestOpenAIProviderTestConnection:
    """OpenAIProvider.test_connection() with mocked httpx.Client.post."""

    def _provider(self) -> OpenAIProvider:
        return OpenAIProvider(api_key="sk-test-key")

    @patch("httpx.Client.post")
    def test_connection_success(self, mock_post):
        """200 → test_connection returns (True, '')."""
        body = _openai_chat_body()
        mock_post.return_value = _make_httpx_response(200, body)

        ok, msg = self._provider().test_connection()

        assert ok is True
        assert msg == ""

    @patch("httpx.Client.post")
    def test_connection_http_401(self, mock_post):
        """HTTP 401 → test_connection returns (False, non-empty message)."""
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        ok, msg = self._provider().test_connection()

        assert ok is False
        assert isinstance(msg, str)
        assert len(msg) > 0
        # Message should mention auth failure or 401
        assert any(kw in msg.lower() for kw in ("401", "auth", "key", "unauthorized"))

    @patch("httpx.Client.post")
    def test_connection_http_500(self, mock_post):
        """HTTP 5xx → test_connection returns (False, non-empty message)."""
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        ok, msg = self._provider().test_connection()

        assert ok is False
        assert len(msg) > 0

    @patch("httpx.Client.post")
    def test_connection_timeout(self, mock_post):
        """TimeoutException → test_connection returns (False, non-empty message)."""
        import httpx as _httpx
        mock_post.side_effect = _httpx.TimeoutException("timed out")

        ok, msg = self._provider().test_connection()

        assert ok is False
        assert isinstance(msg, str)
        assert len(msg) > 0

    @patch("httpx.Client.post")
    def test_connection_connect_error(self, mock_post):
        """ConnectError → test_connection returns (False, non-empty message)."""
        import httpx as _httpx
        mock_post.side_effect = _httpx.ConnectError("connection refused")

        ok, msg = self._provider().test_connection()

        assert ok is False
        assert len(msg) > 0


class TestOpenAIProviderListModels:
    """OpenAIProvider.list_models() with mocked httpx.Client.get."""

    def _provider(self) -> OpenAIProvider:
        return OpenAIProvider(api_key="sk-test-key")

    @patch("httpx.Client.get")
    def test_list_models_returns_sorted_list(self, mock_get):
        """list_models() returns a sorted list of string model IDs."""
        ids = ["gpt-4o", "gpt-3.5-turbo", "gpt-4o-mini", "gpt-4-turbo"]
        body = _openai_models_body(ids)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = body
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        models = self._provider().list_models()

        assert isinstance(models, list)
        assert all(isinstance(m, str) for m in models)
        assert models == sorted(models)

    @patch("httpx.Client.get")
    def test_list_models_correct_ids(self, mock_get):
        """list_models() returns exactly the model IDs from the response."""
        ids = ["gpt-4o", "gpt-3.5-turbo"]
        body = _openai_models_body(ids)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = body
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        models = self._provider().list_models()

        assert set(models) == set(ids)

    @patch("httpx.Client.get")
    def test_list_models_empty_when_no_data(self, mock_get):
        """list_models() returns [] when 'data' key is absent."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"object": "list"}
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        models = self._provider().list_models()

        assert models == []


# ─────────────────────────────────────────────────────────────────────────────
# 3. OllamaProvider — mock HTTP
# ─────────────────────────────────────────────────────────────────────────────

class TestOllamaProviderChat:
    """OllamaProvider.chat() with mocked httpx.Client.post."""

    def _provider(self) -> OllamaProvider:
        return OllamaProvider()

    @patch("httpx.Client.post")
    def test_chat_normal_response_content(self, mock_post):
        """Normal /api/chat 200 → AIResponse.content matches message.content."""
        body = _ollama_chat_body(content="The mitochondria is the powerhouse.")
        mock_post.return_value = _make_httpx_response(200, body)

        resp = self._provider().chat(
            messages=[{"role": "user", "content": "Explain cells."}],
            model="llama3",
        )

        assert isinstance(resp, AIResponse)
        assert resp.content == "The mitochondria is the powerhouse."

    @patch("httpx.Client.post")
    def test_chat_normal_response_model(self, mock_post):
        """Normal response → AIResponse.model echoes the model field."""
        body = _ollama_chat_body(model="mistral")
        mock_post.return_value = _make_httpx_response(200, body)

        resp = self._provider().chat(
            messages=[{"role": "user", "content": "ping"}],
            model="mistral",
        )

        assert resp.model == "mistral"

    @patch("httpx.Client.post")
    def test_chat_posts_to_api_chat(self, mock_post):
        """chat() must call /api/chat endpoint."""
        body = _ollama_chat_body()
        mock_post.return_value = _make_httpx_response(200, body)

        self._provider().chat(
            messages=[{"role": "user", "content": "hi"}],
            model="llama3",
        )

        call_args = mock_post.call_args
        url = (
            call_args.args[0]
            if call_args.args
            else call_args.kwargs.get("url", "")
        )
        assert "/api/chat" in url

    @patch("httpx.Client.post")
    def test_chat_sets_stream_false(self, mock_post):
        """chat() must request stream=False to get a single JSON response."""
        body = _ollama_chat_body()
        mock_post.return_value = _make_httpx_response(200, body)

        self._provider().chat(
            messages=[{"role": "user", "content": "hi"}],
            model="llama3",
        )

        sent_json = mock_post.call_args.kwargs.get("json", {})
        assert sent_json.get("stream") is False


class TestOllamaProviderTestConnection:
    """OllamaProvider.test_connection() with mocked httpx.Client.post."""

    def _provider(self) -> OllamaProvider:
        return OllamaProvider()

    @patch("httpx.Client.post")
    def test_connection_success(self, mock_post):
        """200 → test_connection returns (True, '')."""
        body = _ollama_chat_body()
        mock_post.return_value = _make_httpx_response(200, body)

        ok, msg = self._provider().test_connection()

        assert ok is True
        assert msg == ""

    @patch("httpx.Client.post")
    def test_connection_connect_error(self, mock_post):
        """ConnectError → test_connection returns (False, non-empty message)."""
        import httpx as _httpx
        mock_post.side_effect = _httpx.ConnectError("connection refused")

        ok, msg = self._provider().test_connection()

        assert ok is False
        assert isinstance(msg, str)
        assert len(msg) > 0

    @patch("httpx.Client.post")
    def test_connection_std_connection_error(self, mock_post):
        """Standard ConnectionRefusedError → test_connection returns (False, ...)."""
        mock_post.side_effect = ConnectionRefusedError("refused")

        ok, msg = self._provider().test_connection()

        assert ok is False
        assert len(msg) > 0

    @patch("httpx.Client.post")
    def test_connection_timeout(self, mock_post):
        """TimeoutException → test_connection returns (False, non-empty message)."""
        import httpx as _httpx
        mock_post.side_effect = _httpx.TimeoutException("timeout")

        ok, msg = self._provider().test_connection()

        assert ok is False
        assert len(msg) > 0

    @patch("httpx.Client.post")
    def test_connection_http_error(self, mock_post):
        """HTTP 4xx → test_connection returns (False, non-empty message)."""
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not Found"
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        ok, msg = self._provider().test_connection()

        assert ok is False
        assert len(msg) > 0


class TestOllamaProviderListModels:
    """OllamaProvider.list_models() with mocked httpx.Client.get."""

    def _provider(self) -> OllamaProvider:
        return OllamaProvider()

    @patch("httpx.Client.get")
    def test_list_models_returns_sorted_list(self, mock_get):
        """list_models() returns a sorted list of model name strings."""
        names = ["mistral:latest", "llama3:8b", "codellama:latest"]
        body = _ollama_tags_body(names)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = body
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        models = self._provider().list_models()

        assert isinstance(models, list)
        assert all(isinstance(m, str) for m in models)
        assert models == sorted(models)

    @patch("httpx.Client.get")
    def test_list_models_correct_names(self, mock_get):
        """list_models() returns exactly the names from /api/tags."""
        names = ["llama3:latest", "gemma:7b"]
        body = _ollama_tags_body(names)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = body
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        models = self._provider().list_models()

        assert set(models) == set(names)

    @patch("httpx.Client.get")
    def test_list_models_empty_when_no_models(self, mock_get):
        """list_models() returns [] when 'models' key is absent."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        models = self._provider().list_models()

        assert models == []

    @patch("httpx.Client.get")
    def test_list_models_calls_api_tags(self, mock_get):
        """list_models() must call /api/tags endpoint."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _ollama_tags_body(["llama3"])
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        self._provider().list_models()

        call_args = mock_get.call_args
        url = (
            call_args.args[0]
            if call_args.args
            else call_args.kwargs.get("url", "")
        )
        assert "/api/tags" in url


# ─────────────────────────────────────────────────────────────────────────────
# 4. ProviderConfig
# ─────────────────────────────────────────────────────────────────────────────

class TestProviderConfig:
    """ProviderConfig: load, save, round-trip, get_provider, isolation."""

    def _config(self, tmpdir: str) -> ProviderConfig:
        """Return a ProviderConfig pointing to an isolated temp directory."""
        return ProviderConfig(config_dir=tmpdir)

    # ── load() on missing file ────────────────────────────────────────────────

    def test_load_missing_file_returns_empty_dict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pc = self._config(tmpdir)
            assert not pc.config_path.exists()
            result = pc.load()
            assert result == {}

    def test_load_missing_file_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pc = self._config(tmpdir)
            try:
                pc.load()
            except Exception as exc:
                pytest.fail(f"load() raised unexpectedly: {exc}")

    def test_load_returns_dict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pc = self._config(tmpdir)
            result = pc.load()
            assert isinstance(result, dict)

    # ── save() + load() round-trip ────────────────────────────────────────────

    def test_save_then_load_roundtrip(self):
        """save() followed by load() returns an identical dict."""
        config = {
            "active": "openai",
            "openai": {
                "api_key": "sk-roundtrip-test",
                "base_url": "https://api.openai.com/v1",
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            pc = self._config(tmpdir)
            pc.save(config)
            loaded = pc.load()
            assert loaded == config

    def test_save_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pc = self._config(tmpdir)
            pc.save({"active": "openai", "openai": {"api_key": "x"}})
            assert pc.config_path.exists()

    def test_save_writes_valid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pc = self._config(tmpdir)
            pc.save({"active": "ollama", "ollama": {"base_url": "http://localhost:11434"}})
            raw = pc.config_path.read_text(encoding="utf-8")
            parsed = json.loads(raw)
            assert isinstance(parsed, dict)

    def test_save_then_load_preserves_nested_values(self):
        """Nested config values survive the round-trip unchanged."""
        config = {
            "active": "ollama",
            "ollama": {"base_url": "http://127.0.0.1:11434"},
            "openai": {"api_key": "sk-abc", "base_url": "https://custom.api/v1"},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            pc = self._config(tmpdir)
            pc.save(config)
            loaded = pc.load()
            assert loaded["ollama"]["base_url"] == "http://127.0.0.1:11434"
            assert loaded["openai"]["api_key"] == "sk-abc"

    def test_multiple_save_overrides_previous(self):
        """Calling save() twice keeps only the latest config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pc = self._config(tmpdir)
            pc.save({"active": "openai", "openai": {"api_key": "old-key"}})
            pc.save({"active": "ollama", "ollama": {"base_url": "http://localhost:11434"}})
            loaded = pc.load()
            assert loaded["active"] == "ollama"
            assert "ollama" in loaded

    # ── get_provider() ────────────────────────────────────────────────────────

    def test_get_provider_openai_returns_openai_instance(self):
        """active='openai' → get_provider() returns an OpenAIProvider."""
        config = {"active": "openai", "openai": {"api_key": "sk-test"}}
        with tempfile.TemporaryDirectory() as tmpdir:
            pc = self._config(tmpdir)
            provider = pc.get_provider(config)
            assert isinstance(provider, OpenAIProvider)

    def test_get_provider_ollama_returns_ollama_instance(self):
        """active='ollama' → get_provider() returns an OllamaProvider."""
        config = {"active": "ollama", "ollama": {"base_url": "http://localhost:11434"}}
        with tempfile.TemporaryDirectory() as tmpdir:
            pc = self._config(tmpdir)
            provider = pc.get_provider(config)
            assert isinstance(provider, OllamaProvider)

    def test_get_provider_is_base_provider(self):
        """Returned provider must be a BaseProvider subclass instance."""
        config = {"active": "openai", "openai": {"api_key": "sk-test"}}
        with tempfile.TemporaryDirectory() as tmpdir:
            pc = self._config(tmpdir)
            provider = pc.get_provider(config)
            assert isinstance(provider, BaseProvider)

    def test_get_provider_openai_sets_api_key(self):
        """get_provider() passes the api_key to the OpenAIProvider."""
        config = {"active": "openai", "openai": {"api_key": "sk-unique-key"}}
        with tempfile.TemporaryDirectory() as tmpdir:
            pc = self._config(tmpdir)
            provider = pc.get_provider(config)
            assert isinstance(provider, OpenAIProvider)
            assert provider.api_key == "sk-unique-key"

    def test_get_provider_openai_sets_base_url(self):
        """get_provider() passes custom base_url to OpenAIProvider."""
        config = {
            "active": "openai",
            "openai": {"api_key": "sk-x", "base_url": "https://custom.llm/v1"},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            pc = self._config(tmpdir)
            provider = pc.get_provider(config)
            assert isinstance(provider, OpenAIProvider)
            assert "custom.llm" in provider.base_url

    def test_get_provider_ollama_sets_base_url(self):
        """get_provider() passes base_url to OllamaProvider."""
        config = {
            "active": "ollama",
            "ollama": {"base_url": "http://10.0.0.5:11434"},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            pc = self._config(tmpdir)
            provider = pc.get_provider(config)
            assert isinstance(provider, OllamaProvider)
            assert "10.0.0.5" in provider.base_url

    def test_get_provider_unknown_raises(self):
        """Unknown provider name → ValueError raised."""
        config = {"active": "unknown_provider"}
        with tempfile.TemporaryDirectory() as tmpdir:
            pc = self._config(tmpdir)
            with pytest.raises((ValueError, KeyError)):
                pc.get_provider(config)

    def test_get_provider_loads_from_disk_when_no_config_arg(self):
        """get_provider() without explicit config loads from saved file."""
        config = {"active": "ollama", "ollama": {"base_url": "http://localhost:11434"}}
        with tempfile.TemporaryDirectory() as tmpdir:
            pc = self._config(tmpdir)
            pc.save(config)
            provider = pc.get_provider()
            assert isinstance(provider, OllamaProvider)

    # ── isolation (does NOT touch ~/.paperpilot/) ─────────────────────────────

    def test_does_not_write_to_home_directory(self):
        """ProviderConfig with custom dir must not write to ~/.paperpilot/."""
        home_config = Path.home() / ".paperpilot" / "ai_providers.json"
        existed_before = home_config.exists()

        with tempfile.TemporaryDirectory() as tmpdir:
            pc = self._config(tmpdir)
            pc.save({"active": "openai", "openai": {"api_key": "sk-isolation-test"}})

        # After context manager exits, check home dir was not affected
        if not existed_before:
            assert not home_config.exists(), (
                "ProviderConfig wrote to ~/.paperpilot/ despite custom config_dir!"
            )

    def test_config_path_is_inside_tmpdir(self):
        """Config path must be within the specified config_dir, not ~/.paperpilot."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pc = self._config(tmpdir)
            assert str(pc.config_path).startswith(tmpdir)
            assert str(Path.home() / ".paperpilot") not in str(pc.config_path)
