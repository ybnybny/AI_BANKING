"""Agent 状态定义。"""
from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    user_id: int
    session_id: str
    user_message: str
    intent: str
    entities: dict[str, Any]
    tool_name: str | None
    tool_args: dict[str, Any]
    tool_result: dict[str, Any] | None
    response: str
    history: list
