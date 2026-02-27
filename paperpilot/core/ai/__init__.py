"""
paperpilot/core/ai/__init__.py
AI Provider 公共接口导出
"""
from __future__ import annotations

from .base import AIMessage, AIResponse, BaseProvider
from .ollama_provider import OllamaProvider
from .openai_provider import OpenAIProvider
from .provider_config import ProviderConfig

__all__ = [
    "AIMessage",
    "AIResponse",
    "BaseProvider",
    "OpenAIProvider",
    "OllamaProvider",
    "ProviderConfig",
    "get_provider",
]

_config = ProviderConfig()


def get_provider(name: str) -> BaseProvider:
    """根据持久化配置实例化并返回指定名称的 Provider。

    Args:
        name: Provider 名称，如 "openai"、"ollama"、"deepseek"。

    Returns:
        对应的 :class:`BaseProvider` 实例。

    Raises:
        KeyError: 若配置文件中不存在该 Provider 的配置。
        ValueError: 若配置中指定了未知的 provider 类型。
    """
    provider = _config.get_provider(name)
    if provider is None:
        raise KeyError(
            f"Provider {name!r} is not configured. "
            f"Please add it to {_config.CONFIG_FILE}."
        )
    return provider
