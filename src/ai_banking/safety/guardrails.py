"""安全护栏：操作风险分级与确认判定、金额阈值、PII 脱敏。"""
from __future__ import annotations

import re
from enum import Enum
from typing import Any

from ..config import settings


class Risk(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


# 高风险操作名（返回 requires_confirmation 时或名称命中即判高风险）
_HIGH_RISK_ACTIONS = {
    "report_card_loss", "card_loss", "cancel_subscription",
    "redeem_fund", "redeem", "unlock_card",
}
_MEDIUM_RISK_ACTIONS = {"transfer", "schedule_transfer", "adjust_card_limit", "subscribe_fund"}


def classify_risk(action: str, args: dict[str, Any]) -> Risk:
    if action in _HIGH_RISK_ACTIONS:
        return Risk.high
    if action in _MEDIUM_RISK_ACTIONS:
        amount = float(args.get("amount") or 0)
        if amount >= settings.transfer_confirm_threshold:
            return Risk.high
        return Risk.medium
    return Risk.low


def needs_confirmation(action: str, args: dict[str, Any]) -> bool:
    return classify_risk(action, args) in (Risk.medium, Risk.high)


def mask_phone(phone: str) -> str:
    if len(phone) == 11:
        return f"{phone[:3]}****{phone[7:]}"
    return phone


def mask_card_no(card_no: str) -> str:
    digits = re.sub(r"\D", "", card_no)
    if len(digits) >= 8:
        return f"{digits[:4]} **** **** {digits[-4:]}"
    return card_no


def mask_name(name: str) -> str:
    if not name:
        return name
    if len(name) <= 1:
        return name
    return name[0] + "*" * (len(name) - 1)
