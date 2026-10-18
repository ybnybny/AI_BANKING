"""OpenAI 兼容 LLM 实现（httpx 直连，无需 langchain-openai）。"""
from __future__ import annotations

import json
import logging

import httpx

from ..config import settings
from ..schemas.common import AgentMessage, Intent, IntentResult
from .base import INTENT_TAXONOMY
from .rule_fallback import RuleFallbackProvider

logger = logging.getLogger(__name__)


class OpenAIProvider:
    def __init__(self) -> None:
        self.base_url = settings.llm_base_url.rstrip("/")
        self.api_key = settings.llm_api_key
        self.model = settings.llm_model
        self._fallback = RuleFallbackProvider()

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _chat(self, messages: list[dict], json_mode: bool = False) -> str:
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    def classify_intent(
        self, user_message: str, history: list[AgentMessage]
    ) -> IntentResult:
        if not self.available:
            return self._fallback.classify_intent(user_message, history)
        system = (
            "你是银行智能助手，负责理解用户金融意图并抽取实体。\n"
            + INTENT_TAXONOMY
            + "\n只返回 JSON：{\"intent\": <intent>,\"entities\": {..},\"confidence\": 0.0~1.0}"
            + "\n实体字段按需抽取，例如：amount(数字), to_name(收款人), to_phone(手机号), "
            "note(备注), card_last4(卡尾号), merchant(商户), product_name(产品名), "
            "date_expr(时间表达), days_before(天数), action(确认/取消)。"
        )
        try:
            content = self._chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_message},
                ],
                json_mode=True,
            )
            data = json.loads(content)
            intent = data.get("intent", "unknown")
            return IntentResult(
                intent=Intent(intent) if intent in Intent._value2member_map_ else Intent.unknown,
                entities=data.get("entities", {}),
                confidence=float(data.get("confidence", 0.5)),
                raw=content,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM classify_intent 失败，回退规则引擎: %s", exc)
            return self._fallback.classify_intent(user_message, history)

    def generate_response(self, messages: list[dict]) -> str:
        if not self.available:
            return self._fallback.generate_response(messages)
        try:
            return self._chat(messages)
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM generate_response 失败，回退规则引擎: %s", exc)
            return self._fallback.generate_response(messages)
