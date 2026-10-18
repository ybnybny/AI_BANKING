"""可插拔 LLM 提供层：OpenAI 兼容接口 + 规则回退引擎。"""
from .base import INTENT_TAXONOMY, LLMProvider, get_llm_provider

__all__ = ["INTENT_TAXONOMY", "LLMProvider", "get_llm_provider"]
