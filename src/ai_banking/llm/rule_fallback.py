"""规则回退引擎：正则/关键词实现意图识别与实体抽取，保证无 Key 离线可演示。"""
from __future__ import annotations

import re

from ..schemas.common import AgentMessage, Intent, IntentResult

_AMOUNT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(万|千|百)?\s*(?:元|块|块钱|人民币)?")
_PHONE_RE = re.compile(r"1[3-9]\d{9}")
_CARD_TAIL_RE = re.compile(r"尾号\s*(\d{4})")
_FULL_CARD_RE = re.compile(r"\d{4}\s*\d{4}\s*\d{4}\s*\d{4}")

# 意图关键词（按优先级排序：靠前的意图优先命中）
_INTENT_RULES: list[tuple[Intent, list[str]]] = [
    (Intent.cross_scenario, ["生日", "鲜花", "蛋糕", "礼物", "锁定", "跨场景"]),
    (Intent.subscription, ["订阅", "会员", "代扣", "续费", "扣费", "取消订阅", "自动扣"]),
    (Intent.bill_analysis, ["账单", "消费分析", "报表", "异常", "月度", "年度", "分类", "支出统计"]),
    (Intent.wealth, ["理财", "基金", "申购", "赎回", "风险", "推荐", "对比", "收益", "投资"]),
    (Intent.card, ["挂失", "额度", "限制", "解锁", "卡片", "银行卡", "办卡", "申请卡"]),
    (Intent.transfer, ["转账", "转给", "转", "汇款", "打钱", "打款", "AA", "分摊", "收款", "定时转", "定时汇款"]),
    (Intent.confirm, ["确认", "好的", "可以", "同意", "执行", "取消", "算了", "不转", "先不"]),
    (Intent.chitchat, ["你好", "您好", "在吗", "谢谢", "hi", "hello", "帮助", "你能做什么"]),
]


def _extract_amount(text: str) -> float | None:
    m = _AMOUNT_RE.search(text)
    if not m:
        return None
    value = float(m.group(1))
    unit = m.group(2)
    if unit == "万":
        value *= 10000
    elif unit == "千":
        value *= 1000
    elif unit == "百":
        value *= 100
    return value


def _extract_name(text: str) -> str | None:
    for pat in (r"转给\s*([\u4e00-\u9fa5A-Za-z]{2,10})", r"给\s*([\u4e00-\u9fa5A-Za-z]{2,10})"):
        m = re.search(pat, text)
        if m:
            return m.group(1)
    return None


def _extract_note(text: str) -> str | None:
    m = re.search(r"备注[：:]?\s*(.+?)(?:[，。,.；;]|$)", text)
    if m:
        return m.group(1).strip()
    m = re.search(r"说明[：:]?\s*(.+?)(?:[，。,.；;]|$)", text)
    return m.group(1).strip() if m else None


def _extract_days_before(text: str) -> int | None:
    m = re.search(r"前\s*(\d+)\s*天", text)
    return int(m.group(1)) if m else None


def _extract_action(text: str) -> str | None:
    if re.search(r"取消|算了|先不|不要|拒绝", text):
        return "cancel"
    if re.search(r"确认|好的|可以|同意|执行|没问题", text):
        return "confirm"
    return None


class RuleFallbackProvider:
    """离线规则引擎。"""

    @property
    def available(self) -> bool:
        return True

    def classify_intent(
        self, user_message: str, history: list[AgentMessage]
    ) -> IntentResult:
        text = user_message.strip()
        entities: dict = {}

        amount = _extract_amount(text)
        if amount is not None:
            entities["amount"] = amount
        name = _extract_name(text)
        if name:
            entities["to_name"] = name
        phone = _PHONE_RE.search(text)
        if phone:
            entities["to_phone"] = phone.group(0)
        card_tail = _CARD_TAIL_RE.search(text)
        if card_tail:
            entities["card_last4"] = card_tail.group(1)
        elif _FULL_CARD_RE.search(text):
            entities["card_no"] = _FULL_CARD_RE.search(text).group(0).replace(" ", "")
        note = _extract_note(text)
        if note:
            entities["note"] = note
        days_before = _extract_days_before(text)
        if days_before is not None:
            entities["days_before"] = days_before

        # 日期表达
        date_expr = re.search(
            r"(明天|后天|下周一|下周二|下周三|下周四|下周五|周末|月底|月初|每月\d{1,2}号|每月|今天|今晚)",
            text,
        )
        if date_expr:
            entities["date_expr"] = date_expr.group(1)

        action = _extract_action(text)
        if action:
            entities["action"] = action

        # 确认类答复优先识别（短句且含动作词）
        for intent, keywords in _INTENT_RULES:
            if any(k in text for k in keywords):
                return IntentResult(
                    intent=intent, entities=entities, confidence=0.85, raw=text
                )
        return IntentResult(intent=Intent.unknown, entities=entities, confidence=0.0, raw=text)

    def generate_response(self, messages: list[dict]) -> str:
        # 规则引擎的兜底回复；正常流程由 Agent 依据工具结果生成回复。
        last = messages[-1]["content"] if messages else ""
        return f"收到您的消息：{last}。请问还有其他可以帮您的吗？"
