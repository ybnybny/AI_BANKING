"""订阅/代扣管理场景工具：订阅查询、订阅检测、续费提醒、取消订阅。"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import select

from ...core.errors import BankingError
from ...core.models import Subscription, Transaction
from ...core.tooling import Tool, registry
from ...core.timeutil import utcnow
from ...domain.accounts import get_user, list_transactions
from ...domain.scheduler import register_handler
from ...schemas.common import ToolResult

logger = logging.getLogger(__name__)


class ListSubscriptionsArgs(BaseModel):
    pass


class DetectSubscriptionsArgs(BaseModel):
    pass


class RemindRenewalsArgs(BaseModel):
    pass


class CancelSubscriptionArgs(BaseModel):
    merchant: Optional[str] = None
    subscription_id: Optional[int] = None
    confirmed: Optional[bool] = None


def _parse_user_id(args: dict) -> int | None:
    """解析并校验 user_id，返回 None 表示缺失或无效。"""
    user_id = args.get("user_id")
    if user_id is None:
        return None
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return -1


def _guess_category(merchant: str) -> str:
    name = merchant or ""
    if "视频" in name or "影视" in name:
        return "视频会员"
    if "云" in name:
        return "云服务"
    return "其他"


def _typical_amount(txns: list[Transaction]) -> float:
    """取出现频次最高的金额（四舍五入到分），空时返回 0。"""
    amounts = [round(abs(t.amount), 2) for t in txns]
    if not amounts:
        return 0.0
    counter = Counter(amounts)
    return counter.most_common(1)[0][0]


def _sub_to_dict(s: Subscription) -> dict:
    return {
        "id": s.id,
        "merchant": s.merchant,
        "amount": round(float(s.amount), 2),
        "cycle": s.cycle,
        "next_renewal": s.next_renewal.isoformat() if s.next_renewal else None,
        "category": s.category,
        "status": s.status,
    }


def list_subscriptions(db, args: dict) -> ToolResult:
    """查询用户当前生效中的订阅。"""
    user_id = _parse_user_id(args)
    if user_id is None:
        return ToolResult(success=False, message="缺少用户标识")
    if user_id < 0:
        return ToolResult(success=False, message="用户标识无效")

    try:
        subs = list(
            db.execute(
                select(Subscription)
                .where(Subscription.user_id == user_id, Subscription.status == "active")
                .order_by(Subscription.id)
            )
            .scalars()
            .all()
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(success=False, message=f"查询订阅失败: {exc}")

    if not subs:
        return ToolResult(success=True, message="暂无订阅", data={"subscriptions": []})

    data = [_sub_to_dict(s) for s in subs]
    names = "、".join(s.merchant for s in subs)
    message = f"您当前有 {len(subs)} 个订阅：{names}"
    return ToolResult(success=True, message=message, data={"subscriptions": data})


def detect_subscriptions(db, args: dict) -> ToolResult:
    """扫描交易流水，识别疑似订阅并自动建档。"""
    user_id = _parse_user_id(args)
    if user_id is None:
        return ToolResult(success=False, message="缺少用户标识")
    if user_id < 0:
        return ToolResult(success=False, message="用户标识无效")

    try:
        get_user(db, user_id)
    except BankingError as exc:
        return ToolResult(success=False, message=str(exc))

    txns = list_transactions(db, user_id)
    now = utcnow()
    cutoff = now - timedelta(days=90)

    grouped: dict[str, list[Transaction]] = {}
    for t in txns:
        merchant = (t.merchant or "").strip()
        if not merchant:
            continue
        grouped.setdefault(merchant, []).append(t)

    try:
        existing = {
            s.merchant
            for s in db.execute(
                select(Subscription).where(
                    Subscription.user_id == user_id, Subscription.status == "active"
                )
            )
            .scalars()
            .all()
        }
    except Exception as exc:  # noqa: BLE001
        return ToolResult(success=False, message=f"查询订阅失败: {exc}")

    detected: list[Subscription] = []
    for merchant, items in grouped.items():
        in_90 = sum(1 for t in items if t.txn_time is not None and t.txn_time >= cutoff)
        any_sub = any(t.is_subscription for t in items)
        if not (in_90 >= 2 or any_sub):
            continue
        if merchant in existing:
            continue
        sub = Subscription(
            user_id=user_id,
            merchant=merchant,
            amount=_typical_amount(items),
            cycle="monthly",
            next_renewal=now + timedelta(days=30),
            category=_guess_category(merchant),
            status="active",
        )
        db.add(sub)
        detected.append(sub)
        existing.add(merchant)

    try:
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return ToolResult(success=False, message=f"保存订阅失败: {exc}")

    if not detected:
        return ToolResult(success=True, message="未发现新的订阅", data={"detected": []})

    data = [_sub_to_dict(s) for s in detected]
    names = "、".join(s.merchant for s in detected)
    message = f"检测到 {len(detected)} 个新订阅：{names}"
    return ToolResult(success=True, message=message, data={"detected": data})


def _scan_due_renewals(db, user_id: int | None = None) -> list[Subscription]:
    """查找 30 天内到期或已逾期的有效订阅。"""
    now = utcnow()
    horizon = now + timedelta(days=30)
    stmt = select(Subscription).where(
        Subscription.status == "active",
        Subscription.next_renewal.is_not(None),
        Subscription.next_renewal <= horizon,
    )
    if user_id is not None:
        stmt = stmt.where(Subscription.user_id == user_id)
    return list(db.execute(stmt.order_by(Subscription.next_renewal)).scalars().all())


def _renewal_reminder_handler(db, job) -> None:
    """续费提醒调度处理器：扫描全量到期订阅并记录日志。"""
    try:
        subs = _scan_due_renewals(db)
    except Exception as exc:  # noqa: BLE001
        logger.warning("续费提醒扫描失败: %s", exc)
        return
    logger.info("续费提醒任务 %s：发现 %d 个待续费订阅", getattr(job, "id", "-"), len(subs))


def remind_renewals(db, args: dict) -> ToolResult:
    """提醒用户未来 30 天内即将续费或已逾期的订阅。"""
    user_id = _parse_user_id(args)
    if user_id is None:
        return ToolResult(success=False, message="缺少用户标识")
    if user_id < 0:
        return ToolResult(success=False, message="用户标识无效")

    now = utcnow()
    try:
        due = _scan_due_renewals(db, user_id)
    except Exception as exc:  # noqa: BLE001
        return ToolResult(success=False, message=f"查询续费失败: {exc}")

    renewals = []
    for s in due:
        days = (s.next_renewal - now).days
        renewals.append(
            {
                "merchant": s.merchant,
                "amount": round(float(s.amount), 2),
                "cycle": s.cycle,
                "category": s.category,
                "next_renewal": s.next_renewal.isoformat() if s.next_renewal else None,
                "days_until": days,
            }
        )

    if not renewals:
        message = "未来 30 天内没有需要续费的订阅"
    else:
        message = f"有 {len(renewals)} 个订阅即将续费或已逾期，请注意"
    return ToolResult(success=True, message=message, data={"renewals": renewals})


def cancel_subscription(db, args: dict) -> ToolResult:
    """取消订阅（支持按 id 或按商户名模糊匹配，需二次确认）。"""
    user_id = _parse_user_id(args)
    if user_id is None:
        return ToolResult(success=False, message="缺少用户标识")
    if user_id < 0:
        return ToolResult(success=False, message="用户标识无效")

    try:
        get_user(db, user_id)
    except BankingError as exc:
        return ToolResult(success=False, message=str(exc))

    sub: Subscription | None = None
    sub_id = args.get("subscription_id")
    merchant = args.get("merchant")

    if sub_id is not None:
        try:
            sub_id = int(sub_id)
        except (TypeError, ValueError):
            return ToolResult(success=False, message="订阅编号无效")
        sub = db.execute(
            select(Subscription).where(
                Subscription.id == sub_id, Subscription.user_id == user_id
            )
        ).scalar_one_or_none()
    elif merchant:
        sub = (
            db.execute(
                select(Subscription)
                .where(
                    Subscription.user_id == user_id,
                    Subscription.merchant.contains(str(merchant)),
                )
                .order_by(Subscription.id)
            )
            .scalars()
            .first()
        )

    if sub is None:
        return ToolResult(success=False, message=f"未找到订阅：{merchant or sub_id}")

    if sub.status != "active":
        return ToolResult(success=False, message=f"订阅 {sub.merchant} 已取消")

    if not args.get("confirmed"):
        return ToolResult(
            success=True,
            requires_confirmation=True,
            confirmation_prompt=f"确认取消订阅 {sub.merchant}？",
            message=f"请确认是否取消订阅 {sub.merchant}",
            data={"subscription_id": sub.id, "merchant": sub.merchant},
        )

    sub.status = "cancelled"
    try:
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return ToolResult(success=False, message=f"取消订阅失败: {exc}")

    return ToolResult(
        success=True,
        message=f"已取消订阅 {sub.merchant}",
        data={"subscription_id": sub.id, "merchant": sub.merchant, "status": sub.status},
    )


registry.register(
    Tool(
        name="list_subscriptions",
        description="订阅查询：列出用户当前生效中的订阅（商户、金额、周期、下次续费、类目、状态）。",
        args_schema=ListSubscriptionsArgs,
        func=list_subscriptions,
    )
)
registry.register(
    Tool(
        name="detect_subscriptions",
        description="订阅检测：扫描交易流水识别疑似订阅（近 90 天同商户出现 2 次及以上或标记为订阅），自动建档。",
        args_schema=DetectSubscriptionsArgs,
        func=detect_subscriptions,
    )
)
registry.register(
    Tool(
        name="remind_renewals",
        description="续费提醒：查找未来 30 天内到期或已逾期的有效订阅并生成提醒。",
        args_schema=RemindRenewalsArgs,
        func=remind_renewals,
    )
)
registry.register(
    Tool(
        name="cancel_subscription",
        description="取消订阅：按订阅编号或商户名（模糊匹配）取消订阅，需二次确认。",
        args_schema=CancelSubscriptionArgs,
        func=cancel_subscription,
    )
)

register_handler("renewal_reminder", _renewal_reminder_handler)
