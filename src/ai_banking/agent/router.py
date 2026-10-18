"""确定性意图路由：意图 + 实体 -> (工具名, 入参)。

工具名是各场景模块的契约，场景工具实现时必须使用相同名称注册。
"""
from __future__ import annotations

from typing import Any

from ..schemas.common import Intent


def route(intent: Intent, entities: dict[str, Any], message: str) -> tuple[str | None, dict[str, Any]]:
    if intent == Intent.transfer:
        return _route_transfer(entities, message)
    if intent == Intent.bill_analysis:
        return _route_bill(message)
    if intent == Intent.wealth:
        return _route_wealth(message)
    if intent == Intent.card:
        return _route_card(message, entities)
    if intent == Intent.subscription:
        return _route_subscription(message)
    if intent == Intent.cross_scenario:
        args: dict[str, Any] = {}
        if "days_before" in entities:
            args["days_before"] = entities["days_before"]
        if "amount" in entities:
            args["amount"] = entities["amount"]
        return "check_birthday_plan", args
    return None, {}


def _route_transfer(entities: dict[str, Any], message: str) -> tuple[str | None, dict[str, Any]]:
    args: dict[str, Any] = {}
    for key in ("amount", "to_name", "to_phone", "note", "date_expr"):
        if key in entities:
            args[key] = entities[key]
    if "AA" in message or "分摊" in message or "收款" in message:
        return "create_aa_collection", args
    if "date_expr" in entities or "定时" in message or "明天" in message or "每月" in message:
        return "schedule_transfer", args
    return "transfer_money", args


def _route_bill(message: str) -> tuple[str | None, dict[str, Any]]:
    if "异常" in message:
        return "detect_anomalies", {}
    if "年度" in message or "年报" in message:
        return "generate_report", {"period": "annual"}
    if "月度" in message or "月报" in message or "月" in message:
        return "generate_report", {"period": "monthly"}
    return "analyze_spending", {}


def _route_wealth(message: str) -> tuple[str | None, dict[str, Any]]:
    if "风险" in message:
        return "assess_risk", {}
    if "对比" in message:
        return "compare_products", {}
    if "赎回" in message:
        return "redeem_fund", {}
    if "申购" in message or "购买" in message or "买入" in message:
        return "subscribe_fund", {}
    return "recommend_products", {}


def _route_card(message: str, entities: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    args: dict[str, Any] = {}
    if "card_last4" in entities:
        args["card_last4"] = entities["card_last4"]
    if "amount" in entities:
        args["new_limit"] = entities["amount"]
    if "挂失" in message:
        return "report_card_loss", args
    if "额度" in message:
        return "adjust_card_limit", args
    if "解锁" in message:
        return "unlock_card", args
    if "限制" in message or "冻结" in message or "锁卡" in message:
        return "restrict_card", args
    return "apply_card", args


def _route_subscription(message: str) -> tuple[str | None, dict[str, Any]]:
    if "取消" in message:
        import re
        m = re.search(r"取消(.+?)(?:的)?(?:订阅|会员|自动续费)", message)
        return "cancel_subscription", {"merchant": m.group(1).strip() if m else None}
    if "提醒" in message or "续费" in message:
        return "remind_renewals", {}
    if "识别" in message or "检测" in message or "扣费" in message:
        return "detect_subscriptions", {}
    return "list_subscriptions", {}
