"""
paperpilot/core/ai/provider_config.py
AI Provider 配置持久化（读写 ~/.paperpilot/ai_providers.json）
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .base import BaseProvider


class ProviderConfig:
    """读写 ~/.paperpilot/ai_providers.json，并按需实例化 Provider。

    配置文件格式示例::

        {
            "openai": {
                "api_key": "sk-...",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4o-mini"
            },
            "deepseek": {
                "provider": "openai",
                "api_key": "ds-...",
                "base_url": "https://api.deepseek.com/v1",
                "model": "deepseek-chat"
            },
            "ollama": {
                "base_url": "http://localhost:11434",
                "model": "llama3"
            }
        }
    """

    CONFIG_DIR = Path.home() / ".paperpilot"
    CONFIG_FILE = CONFIG_DIR / "ai_providers.json"

    # ------------------------------------------------------------------
    # Load / Save
    # ------------------------------------------------------------------

    def load(self) -> dict:
        """从磁盘读取配置，若文件不存在则返回空字典。"""
        if not self.CONFIG_FILE.exists():
            return {}
        try:
            with self.CONFIG_FILE.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return {}

    def save(self, config: dict) -> None:
        """将配置写入磁盘，自动创建目录。"""
        self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with self.CONFIG_FILE.open("w", encoding="utf-8") as fh:
            json.dump(config, fh, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    def get_provider(self, name: str) -> BaseProvider | None:
        """根据配置实例化并返回指定名称的 Provider，不存在则返回 None。"""
        # 延迟导入，避免循环依赖
        from .ollama_provider import OllamaProvider
        from .openai_provider import OpenAIProvider

        config = self.load()
        entry: dict | None = config.get(name)
        if not entry:
            return None

        # 支持用 "provider" 字段覆盖底层实现（如 deepseek 用 openai 兼容层）
        provider_type = entry.get("provider", name)

        if provider_type == "openai":
            return OpenAIProvider(
                api_key=entry.get("api_key", os.environ.get("OPENAI_API_KEY", "")),
                base_url=entry.get("base_url", "https://api.openai.com/v1"),
                model=entry.get("model", "gpt-4o-mini"),
            )
        elif provider_type == "ollama":
            return OllamaProvider(
                base_url=entry.get("base_url", "http://localhost:11434"),
                model=entry.get("model", "llama3"),
            )
        else:
            raise ValueError(f"Unknown provider type: {provider_type!r}")
