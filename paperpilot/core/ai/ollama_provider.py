"""
paperpilot/core/ai/ollama_provider.py
本地 Ollama 提供商（POST /api/chat，stream=False）
"""
from __future__ import annotations

import httpx

from .base import AIMessage, AIResponse, BaseProvider


class OllamaProvider(BaseProvider):
    name = "ollama"

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3",
    ):
        self.base_url = base_url.rstrip("/")
        self.default_model = model

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=120.0)  # 本地模型推理可能较慢

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
        """POST /api/chat，stream=False"""
        effective_model = model or self.default_model
        payload = {
            "model": effective_model,
            "messages": self._messages_to_payload(messages),
            "stream": False,
            **kwargs,
        }
        with self._client() as client:
            resp = client.post(
                f"{self.base_url}/api/chat",
                json=payload,
            )
            resp.raise_for_status()
            data: dict = resp.json()

        message = data.get("message", {})
        usage_raw = data.get("usage", {})
        # Ollama 的 token 计数字段名称
        prompt_tokens = data.get("prompt_eval_count", usage_raw.get("prompt_tokens", 0))
        completion_tokens = data.get("eval_count", usage_raw.get("completion_tokens", 0))

        return AIResponse(
            content=message.get("content", ""),
            model=data.get("model", effective_model),
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            },
            raw=data,
        )

    def list_models(self) -> list[str]:
        """GET /api/tags，返回本地已拉取的模型名称列表"""
        with self._client() as client:
            resp = client.get(f"{self.base_url}/api/tags")
            resp.raise_for_status()
            data: dict = resp.json()

        models = [m["name"] for m in data.get("models", [])]
        return sorted(models)

    def test_connection(self) -> tuple[bool, str]:
        """发送简单消息测试 Ollama 是否可达"""
        try:
            response = self.chat(
                messages=[AIMessage(role="user", content="Hi")],
                model=self.default_model,
            )
            return True, f"OK — model={response.model}"
        except httpx.HTTPStatusError as exc:
            return False, f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
        except httpx.RequestError as exc:
            return False, f"Network error: {exc}"
        except Exception as exc:  # noqa: BLE001
            return False, f"Unexpected error: {exc}"
