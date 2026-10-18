"""共享 Pydantic 契约：意图枚举、工具结果、Agent 消息。"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Intent(str, Enum):
    transfer = "transfer"
    bill_analysis = "bill_analysis"
    wealth = "wealth"
    card = "card"
    subscription = "subscription"
    cross_scenario = "cross_scenario"
    confirm = "confirm"  # 用户对确认请求的答复（同意/取消）
    chitchat = "chitchat"
    unknown = "unknown"


class ToolResult(BaseModel):
    """工具统一返回结构。"""

    success: bool = True
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    requires_confirmation: bool = False
    confirmation_prompt: str | None = None


class AgentMessage(BaseModel):
    role: str  # user/assistant
    content: str


class IntentResult(BaseModel):
    intent: Intent
    entities: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0
    raw: str = ""
