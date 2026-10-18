"""LangGraph Agent 状态机：understand -> plan -> act -> respond。"""
from __future__ import annotations

import contextvars
import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from ..core.tooling import registry
from ..llm import get_llm_provider
from ..safety.audit import log_audit
from ..safety.guardrails import classify_risk
from ..schemas.common import Intent
from .memory import clear_pending, get_history, get_pending, save_message, set_pending
from .router import route
from .state import AgentState

logger = logging.getLogger(__name__)

# 通过 contextvar 在节点间传递当前请求的数据库会话
_db_ctx: contextvars.ContextVar[Any] = contextvars.ContextVar("db", default=None)

_CHITCHAT_REPLY = (
    "您好！我是 AI 银行助手 🤖，可以帮您：\n"
    "· 智能转账（按姓名/手机号/定时/AA 收款）\n"
    "· 账单分析（分类统计/异常识别/月报年报）\n"
    "· 理财操作（风险评估/推荐对比/申购赎回）\n"
    "· 卡片管理（申请/额度/限制/挂失）\n"
    "· 订阅管理（识别扣费/续费提醒/取消）\n"
    "· 跨场景联动（爱人生日自动安排礼物）\n"
    "请问有什么可以帮您？"
)

_UNKNOWN_REPLY = (
    "抱歉，我没有完全理解您的意思。您可以试试：\n"
    "· “转 500 元给张三，备注聚餐”\n"
    "· “分析我上个月的账单”\n"
    "· “推荐一款稳健理财”\n"
    "· “帮我挂失尾号 8888 的卡”\n"
    "· “取消我的视频会员订阅”"
)


def understand_node(state: AgentState) -> dict:
    db = _db_ctx.get()
    provider = get_llm_provider()
    history = get_history(db, state["user_id"], state["session_id"])
    result = provider.classify_intent(state["user_message"], history)
    return {"intent": result.intent.value, "entities": result.entities}


def plan_node(state: AgentState) -> dict:
    session_id = state["session_id"]
    intent = Intent(state["intent"])
    entities = state.get("entities", {})
    pending = get_pending(session_id)

    if pending is not None:
        if intent == Intent.confirm:
            action = entities.get("action", "confirm")
            if action == "cancel":
                clear_pending(session_id)
                return {
                    "tool_name": None,
                    "tool_args": {},
                    "response": "好的，已取消该操作。",
                    "intent": "confirm",
                }
        args = dict(pending["args"])
        args["confirmed"] = True
        return {"tool_name": pending["tool"], "tool_args": args, "intent": "confirm"}
        # 用户提出新请求，作废旧的待确认操作
        clear_pending(session_id)

    tool_name, args = route(intent, entities, state["user_message"])
    return {"tool_name": tool_name, "tool_args": args}


def act_node(state: AgentState) -> dict:
    tool_name = state.get("tool_name")
    if not tool_name:
        return {}
    db = _db_ctx.get()
    args = dict(state.get("tool_args", {}) or {})
    args["user_id"] = state["user_id"]
    result = registry.invoke(db, tool_name, args)
    risk = classify_risk(tool_name, args)
    try:
        log_audit(
            db, state["user_id"], tool_name, args,
            risk=risk.value, status="success" if result.success else "failed",
        )
    except Exception:  # noqa: BLE001
        logger.exception("审计写入失败")
    return {"tool_result": result.model_dump()}


def respond_node(state: AgentState) -> dict:
    session_id = state["session_id"]
    if state.get("response"):
        return {}
    tool_name = state.get("tool_name")
    result = state.get("tool_result")
    if result is None:
        return {"response": _CHITCHAT_REPLY if state["intent"] == "chitchat" else _UNKNOWN_REPLY}
    if result.get("requires_confirmation"):
        set_pending(
            session_id,
            {
                "tool": tool_name,
                "args": state.get("tool_args", {}),
                "prompt": result.get("confirmation_prompt"),
            },
        )
        return {"response": result.get("confirmation_prompt") or "请确认是否继续该操作？"}
    return {"response": result.get("message", "操作完成")}


def _router_after_plan(state: AgentState) -> str:
    return "act" if state.get("tool_name") else "respond"


_graph = None


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("understand", understand_node)
    g.add_node("plan", plan_node)
    g.add_node("act", act_node)
    g.add_node("respond", respond_node)
    g.add_edge(START, "understand")
    g.add_edge("understand", "plan")
    g.add_conditional_edges("plan", _router_after_plan, {"act": "act", "respond": "respond"})
    g.add_edge("act", "respond")
    g.add_edge("respond", END)
    return g.compile()


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def run_agent(db: Any, user_id: int, session_id: str, user_message: str) -> dict:
    """执行一轮对话，返回 {response, intent, tool_used, data, requires_confirmation}。"""
    save_message(db, user_id, session_id, "user", user_message)
    token = _db_ctx.set(db)
    try:
        result = get_graph().invoke(
            {
                "user_id": user_id,
                "session_id": session_id,
                "user_message": user_message,
                "intent": "",
                "entities": {},
                "tool_name": None,
                "tool_args": {},
                "tool_result": None,
                "response": "",
            }
        )
    finally:
        _db_ctx.reset(token)
    response = result.get("response") or "抱歉，我暂时无法处理该请求。"
    save_message(db, user_id, session_id, "assistant", response)
    tool_result = result.get("tool_result") or {}
    return {
        "response": response,
        "intent": result.get("intent"),
        "tool_used": result.get("tool_name"),
        "data": tool_result.get("data", {}),
        "requires_confirmation": bool(tool_result.get("requires_confirmation")),
    }
