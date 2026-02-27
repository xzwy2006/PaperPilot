"""
paperpilot/core/ai/base.py
AI Provider 抽象基类定义
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class AIMessage:
    role: str        # "user" | "assistant" | "system"
    content: str


@dataclass
class AIResponse:
    content: str
    model: str
    usage: dict      # {"prompt_tokens": int, "completion_tokens": int}
    raw: dict = field(default_factory=dict)   # 原始响应 JSON


class BaseProvider(ABC):
    name: str = ""

    @abstractmethod
    def chat(self, messages: list[AIMessage], model: str = None, **kwargs) -> AIResponse:
        """发送对话请求，返回 AIResponse"""
        ...

    @abstractmethod
    def list_models(self) -> list[str]:
        """返回该 Provider 可用的模型名称列表"""
        ...

    @abstractmethod
    def test_connection(self) -> tuple[bool, str]:
        """测试连接是否正常，返回 (ok, message)"""
        ...
