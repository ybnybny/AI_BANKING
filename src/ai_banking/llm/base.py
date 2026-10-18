"""LLM 提供层协议与工厂。"""
from __future__ import annotations

from typing import Protocol

from ..config import settings
from ..schemas.common import AgentMessage, IntentResult

# 意图分类体系（OpenAI 与规则引擎共用）
INTENT_TAXONOMY = """\
intent 可选值：
- transfer: 转账、汇款、打钱、定时转账、AA 收款/分摊
- bill_analysis: 账单、消费分析、分类统计、异常交易、月报/年报
- wealth: 理财、基金、申购、赎回、风险评估、产品推荐/对比
- card: 银行卡管理、申请、额度调整、交易限制/解锁、挂失
- subscription: 订阅、会员、自动扣费、续费提醒、取消订阅
- cross_scenario: 生日、礼物、鲜花、蛋糕、锁定资金（跨场景联动）
- confirm: 用户对确认请求的答复（同意/确认 或 取消/拒绝）
- chitchat: 寒暄、问候、其他闲聊
- unknown: 无法识别
"""


class LLMProvider(Protocol):
    @property
    def available(self) -> bool: ...

    def classify_intent(
        self, user_message: str, history: list[AgentMessage]
    ) -> IntentResult: ...

    def generate_response(self, messages: list[dict]) -> str: ...


def get_llm_provider() -> LLMProvider:
    """工厂：配置了 API Key 则用 OpenAI 兼容实现，否则回退规则引擎。"""
    if settings.llm_configured:
        from .openai_provider import OpenAIProvider

        return OpenAIProvider()
    from .rule_fallback import RuleFallbackProvider

    return RuleFallbackProvider()
