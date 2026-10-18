"""工具契约：Tool 基类与 ToolRegistry。

这是所有场景模块并行施工的“接口合同”：
- 各场景模块实现工具函数并暴露 `register(registry)`；
- Agent 框架通过 ToolRegistry 查询、执行工具。
"""
from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel

from ..schemas.common import ToolResult


class Tool:
    """银行业务工具。

    - name / description：供 LLM 规划与工具选择使用；
    - args_schema：Pydantic 模型类，定义入参；
    - func：可调用对象，签名 func(db, args) -> ToolResult。
    """

    def __init__(
        self,
        name: str,
        description: str,
        args_schema: type[BaseModel],
        func: Callable[[Any, dict], ToolResult],
    ) -> None:
        self.name = name
        self.description = description
        self.args_schema = args_schema
        self.func = func

    def run(self, db: Any, args: dict) -> ToolResult:
        return self.func(db, args)

    def to_spec(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.args_schema.model_json_schema(),
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def describe(self) -> list[dict]:
        return [t.to_spec() for t in self._tools.values()]

    def invoke(self, db: Any, name: str, args: dict) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(success=False, message=f"未知工具: {name}")
        try:
            return tool.run(db, args)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, message=f"工具执行失败: {exc}")


registry = ToolRegistry()
