"""卡片管理场景工具：开卡、额度调整、交易限制、解锁、挂失。"""
from __future__ import annotations

import random
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import select

from ...core.models import Card
from ...core.tooling import Tool, registry
from ...safety.guardrails import mask_card_no
from ...schemas.common import ToolResult


class ApplyCardArgs(BaseModel):
    card_type: Optional[str] = None


class AdjustCardLimitArgs(BaseModel):
    card_last4: Optional[str] = None
    new_limit: Optional[float] = None
    confirmed: Optional[bool] = None


class RestrictCardArgs(BaseModel):
    card_last4: Optional[str] = None


class UnlockCardArgs(BaseModel):
    card_last4: Optional[str] = None


class ReportCardLossArgs(BaseModel):
    card_last4: Optional[str] = None
    confirmed: Optional[bool] = None


def _resolve_user_id(args: dict):
    user_id = args.get("user_id")
    if user_id is None:
        return None
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return None


def _find_card(db, user_id: int, card_last4: Optional[str]) -> Card:
    cards = list(
        db.execute(select(Card).where(Card.user_id == user_id)).scalars().all()
    )
    if not cards:
        raise ValueError("未找到该用户的卡片")
    if card_last4:
        matched = [c for c in cards if c.card_no.endswith(card_last4)]
        if not matched:
            raise ValueError(f"未找到尾号为 {card_last4} 的卡片")
        return matched[0]
    return cards[0]


def _generate_card_no(db) -> str:
    for _ in range(10):
        card_no = "622202" + "".join(
            random.choice("0123456789") for _ in range(10)
        )
        existing = db.execute(
            select(Card).where(Card.card_no == card_no)
        ).scalar_one_or_none()
        if existing is None:
            return card_no
    raise ValueError("生成卡号失败，请重试")


def apply_card(db, args: dict) -> ToolResult:
    """申请开卡：生成唯一卡号并创建卡片，返回脱敏卡号与额度。"""
    user_id = _resolve_user_id(args)
    if user_id is None:
        return ToolResult(success=False, message="缺少用户标识")

    card_type = args.get("card_type") or "credit"
    is_credit = card_type == "credit"
    credit_limit = 20000.0 if is_credit else 0.0

    try:
        card = Card(
            user_id=user_id,
            card_no=_generate_card_no(db),
            card_type=card_type,
            credit_limit=credit_limit,
            daily_limit=50000.0,
            status="active",
        )
        db.add(card)
        db.commit()
        db.refresh(card)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return ToolResult(success=False, message=f"开卡失败: {exc}")

    masked = mask_card_no(card.card_no)
    message = (
        f"开卡成功：{masked}，信用额度 {card.credit_limit:.2f} 元，"
        f"单日限额 {card.daily_limit:.2f} 元。"
    )
    return ToolResult(
        success=True,
        message=message,
        data={"card_id": card.id, "masked_no": masked},
    )


def adjust_card_limit(db, args: dict) -> ToolResult:
    """调整卡片额度：默认按尾号定位卡片，确认后修改信用额度。"""
    user_id = _resolve_user_id(args)
    if user_id is None:
        return ToolResult(success=False, message="缺少用户标识")

    card_last4 = args.get("card_last4")
    if card_last4 is not None:
        card_last4 = str(card_last4).strip() or None

    new_limit = args.get("new_limit")
    if new_limit is None:
        return ToolResult(success=False, message="缺少调整后的额度")

    try:
        new_limit = float(new_limit)
    except (TypeError, ValueError):
        return ToolResult(success=False, message="额度无效")

    try:
        card = _find_card(db, user_id, card_last4)
    except Exception as exc:  # noqa: BLE001
        return ToolResult(success=False, message=str(exc))

    last4 = card.card_no[-4:]
    if not args.get("confirmed"):
        prompt = (
            f"确认将尾号 {last4} 的卡片额度调整为 {new_limit:.2f} 元？"
            "回复“确认”执行，回复“取消”放弃。"
        )
        return ToolResult(
            success=True, requires_confirmation=True, confirmation_prompt=prompt
        )

    try:
        card.credit_limit = new_limit
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return ToolResult(success=False, message=f"额度调整失败: {exc}")

    return ToolResult(
        success=True,
        message=f"额度调整成功：尾号 {last4} 的卡片额度已调整为 {new_limit:.2f} 元。",
        data={"card_id": card.id, "credit_limit": new_limit},
    )


def restrict_card(db, args: dict) -> ToolResult:
    """限制卡片交易：将卡片标记为交易受限。"""
    user_id = _resolve_user_id(args)
    if user_id is None:
        return ToolResult(success=False, message="缺少用户标识")

    card_last4 = args.get("card_last4")
    if card_last4 is not None:
        card_last4 = str(card_last4).strip() or None

    try:
        card = _find_card(db, user_id, card_last4)
    except Exception as exc:  # noqa: BLE001
        return ToolResult(success=False, message=str(exc))

    try:
        card.transaction_restricted = True
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return ToolResult(success=False, message=f"操作失败: {exc}")

    return ToolResult(
        success=True,
        message=f"交易限制已开启：尾号 {card.card_no[-4:]} 的卡片已限制交易。",
        data={"card_id": card.id, "masked_no": mask_card_no(card.card_no)},
    )


def unlock_card(db, args: dict) -> ToolResult:
    """解锁卡片：解除交易限制并恢复为活跃状态。"""
    user_id = _resolve_user_id(args)
    if user_id is None:
        return ToolResult(success=False, message="缺少用户标识")

    card_last4 = args.get("card_last4")
    if card_last4 is not None:
        card_last4 = str(card_last4).strip() or None

    try:
        card = _find_card(db, user_id, card_last4)
    except Exception as exc:  # noqa: BLE001
        return ToolResult(success=False, message=str(exc))

    try:
        card.transaction_restricted = False
        card.status = "active"
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return ToolResult(success=False, message=f"解锁失败: {exc}")

    return ToolResult(
        success=True,
        message=f"卡片已解锁：尾号 {card.card_no[-4:]} 的卡片已恢复可用。",
        data={"card_id": card.id, "masked_no": mask_card_no(card.card_no)},
    )


def report_card_loss(db, args: dict) -> ToolResult:
    """挂失卡片：确认后把卡片状态置为 lost（不可撤销）。"""
    user_id = _resolve_user_id(args)
    if user_id is None:
        return ToolResult(success=False, message="缺少用户标识")

    card_last4 = args.get("card_last4")
    if card_last4 is not None:
        card_last4 = str(card_last4).strip() or None

    try:
        card = _find_card(db, user_id, card_last4)
    except Exception as exc:  # noqa: BLE001
        return ToolResult(success=False, message=str(exc))

    last4 = card.card_no[-4:]
    if not args.get("confirmed"):
        prompt = (
            f"挂失不可撤销：确认挂失尾号 {last4} 的卡片？"
            "回复“确认”执行，回复“取消”放弃。"
        )
        return ToolResult(
            success=True, requires_confirmation=True, confirmation_prompt=prompt
        )

    try:
        card.status = "lost"
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return ToolResult(success=False, message=f"挂失失败: {exc}")

    return ToolResult(
        success=True,
        message=f"挂失成功：尾号 {last4} 的卡片已挂失（{mask_card_no(card.card_no)}）。",
        data={"card_id": card.id, "masked_no": mask_card_no(card.card_no)},
    )


registry.register(
    Tool(
        name="apply_card",
        description="申请开卡：为用户生成一张新卡片，返回脱敏卡号与额度。",
        args_schema=ApplyCardArgs,
        func=apply_card,
    )
)
registry.register(
    Tool(
        name="adjust_card_limit",
        description="调整卡片额度：修改卡片信用额度，需二次确认。",
        args_schema=AdjustCardLimitArgs,
        func=adjust_card_limit,
    )
)
registry.register(
    Tool(
        name="restrict_card",
        description="限制卡片交易：将卡片标记为交易受限。",
        args_schema=RestrictCardArgs,
        func=restrict_card,
    )
)
registry.register(
    Tool(
        name="unlock_card",
        description="解锁卡片：解除交易限制并恢复卡片为活跃状态。",
        args_schema=UnlockCardArgs,
        func=unlock_card,
    )
)
registry.register(
    Tool(
        name="report_card_loss",
        description="挂失卡片：将卡片状态置为挂失，不可撤销，需二次确认。",
        args_schema=ReportCardLossArgs,
        func=report_card_loss,
    )
)
