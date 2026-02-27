"""
paperpilot/core/ai/openai_provider.py
OpenAI / 兼容 API 提供商（支持自定义 base_url，兼容 DeepSeek、月之暗面等）
"""
from __future__ import annotations

import httpx

from .base import AIMessage, AIResponse, BaseProvider


class OpenAIProvider(BaseProvider):
    name = "openai"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.default_model = model
        self._headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=60.0)

    def _messages_to_payload(self, messages: list[AIMessage]) -> list[dict]:
        return [{"role": m.role, "content": m.content} for m in messages]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: list[AIMessage],
        model: str = None,
        **kwargs,
    ) -> AIResponse:
        """POST /chat/completions，超时 60s"""
        effective_model = model or self.default_model
        payload = {
            "model": effective_model,
            "messages": self._messages_to_payload(messages),
            **kwargs,
        }
        with self._client() as client:
            resp = client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers,
                json=payload,
            )
            resp.raise_for_status()
            data: dict = resp.json()

        choice = data["choices"][0]["message"]
        usage_raw = data.get("usage", {})
        return AIResponse(
            content=choice.get("content", ""),
            model=data.get("model", effective_model),
            usage={
                "prompt_tokens": usage_raw.get("prompt_tokens", 0),
                "completion_tokens": usage_raw.get("completion_tokens", 0),
            },
            raw=data,
        )

    def list_models(self) -> list[str]:
        """GET /models，返回 id 列表，按名称排序"""
        with self._client() as client:
            resp = client.get(
                f"{self.base_url}/models",
                headers=self._headers,
            )
            resp.raise_for_status()
            data: dict = resp.json()

        models = [m["id"] for m in data.get("data", [])]
        return sorted(models)

    def test_connection(self) -> tuple[bool, str]:
        """发送最简单的 chat 消息，捕获所有异常"""
        try:
            response = self.chat(
                messages=[AIMessage(role="user", content="Hi")],
                model=self.default_model,
                max_tokens=5,
            )
            return True, f"OK — model={response.model}"
        except httpx.HTTPStatusError as exc:
            return False, f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
        except httpx.RequestError as exc:
            return False, f"Network error: {exc}"
        except Exception as exc:  # noqa: BLE001
            return False, f"Unexpected error: {exc}"
