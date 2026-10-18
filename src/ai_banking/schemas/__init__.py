"""共享 Pydantic 契约（各模块并行施工的接口约定）。"""
from .common import AgentMessage, Intent, IntentResult, ToolResult

__all__ = ["AgentMessage", "Intent", "IntentResult", "ToolResult"]
