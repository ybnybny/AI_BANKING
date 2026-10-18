"""智能转账场景工具：即时转账、定时转账、AA 收款。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import select

from ...config import settings
from ...core.errors import BankingError, InvalidOperationError, NotFoundError
from ...core.models import AAMember, AATransfer, ScheduledJob, User
from ...core.tooling import Tool, registry
from ...domain.accounts import get_user, get_user_by_phone, transfer_funds
from ...domain.scheduler import register_handler
from ...safety.guardrails import mask_name, mask_phone
from ...schemas.common import ToolResult


class TransferMoneyArgs(BaseModel):
    amount: Optional[float] = None
    to_name: Optional[str] = None
    to_phone: Optional[str] = None
    note: Optional[str] = None
    confirmed: Optional[bool] = None


class ScheduleTransferArgs(BaseModel):
    amount: Optional[float] = None
    to_name: Optional[str] = None
    to_phone: Optional[str] = None
    note: Optional[str] = None
    date_expr: Optional[str] = None


class AACollectionArgs(BaseModel):
    amount: Optional[float] = None
    to_name: Optional[str] = None
    note: Optional[str] = None


def _resolve_recipient(db, to_phone: Optional[str], to_name: Optional[str]) -> User:
    """按手机号精确匹配，否则按姓名唯一匹配。"""
    if to_phone:
        user = get_user_by_phone(db, to_phone)
        if user is None:
            raise NotFoundError(f"未找到手机号为 {to_phone} 的用户")
        return user
    if to_name:
        matches = list(
            db.execute(select(User).where(User.name == to_name)).scalars().all()
        )
        if not matches:
            raise NotFoundError(f"未找到姓名为 {to_name} 的用户")
        if len(matches) > 1:
            raise InvalidOperationError(f"存在多个姓名为 {to_name} 的用户，请补充手机号")
        return matches[0]
    raise InvalidOperationError("请提供收款人姓名或手机号")


def _mask_recipient(recipient: User, by_phone: bool) -> str:
    if by_phone:
        return mask_phone(recipient.phone or "")
    return mask_name(recipient.name)


def transfer_money(db, args: dict) -> ToolResult:
    """即时转账（金额达到阈值需二次确认）。"""
    user_id = args.get("user_id")
    if user_id is None:
        return ToolResult(success=False, message="缺少用户标识")
    try:
        user_id = int(user_id)
        amount = float(args.get("amount"))
    except (TypeError, ValueError):
        return ToolResult(success=False, message="转账金额或用户标识无效")

    try:
        recipient = _resolve_recipient(db, args.get("to_phone"), args.get("to_name"))
        get_user(db, user_id)
    except BankingError as exc:
        return ToolResult(success=False, message=str(exc))

    by_phone = bool(args.get("to_phone"))
    masked = _mask_recipient(recipient, by_phone)

    if amount >= settings.transfer_confirm_threshold and not args.get("confirmed"):
        prompt = (
            f"确认转账 {amount:.2f} 元给 {masked}？"
            "回复“确认”执行，回复“取消”放弃。"
        )
        return ToolResult(
            success=True, requires_confirmation=True, confirmation_prompt=prompt
        )

    try:
        from_acct, _to_acct = transfer_funds(
            db, user_id, recipient.id, amount, args.get("note")
        )
        db.commit()
    except BankingError as exc:
        db.rollback()
        return ToolResult(success=False, message=str(exc))

    message = (
        f"转账成功：已向 {masked} 转账 {amount:.2f} 元，"
        f"当前余额 {from_acct.balance:.2f} 元。"
    )
    return ToolResult(
        success=True,
        message=message,
        data={"from_balance": from_acct.balance, "to_user_id": recipient.id},
    )


def _parse_run_at(date_expr: Optional[str]) -> datetime:
    """解析日期表达式：明天 -> 明天 09:00；每月/含月 -> +30 天 09:00；默认明天 09:00。"""
    now = datetime.now()
    if date_expr and "月" in date_expr:
        run = now + timedelta(days=30)
    else:
        run = now + timedelta(days=1)
    return run.replace(hour=9, minute=0, second=0, microsecond=0)


def schedule_transfer(db, args: dict) -> ToolResult:
    """创建定时转账任务。"""
    user_id = args.get("user_id")
    if user_id is None:
        return ToolResult(success=False, message="缺少用户标识")
    try:
        user_id = int(user_id)
        amount = float(args.get("amount"))
    except (TypeError, ValueError):
        return ToolResult(success=False, message="转账金额或用户标识无效")
    if amount <= 0:
        return ToolResult(success=False, message="转账金额必须大于 0")

    try:
        recipient = _resolve_recipient(db, args.get("to_phone"), args.get("to_name"))
        get_user(db, user_id)
    except BankingError as exc:
        return ToolResult(success=False, message=str(exc))

    masked = _mask_recipient(recipient, bool(args.get("to_phone")))
    run_at = _parse_run_at(args.get("date_expr"))
    payload = {
        "amount": amount,
        "to_name": args.get("to_name"),
        "to_phone": args.get("to_phone"),
        "note": args.get("note"),
        "from_user_id": user_id,
    }
    job = ScheduledJob(
        job_type="scheduled_transfer",
        user_id=user_id,
        payload=json.dumps(payload, ensure_ascii=False),
        run_at=run_at,
        status="pending",
    )
    db.add(job)
    db.commit()

    message = (
        f"已创建定时转账：{amount:.2f} 元给 {masked}，"
        f"计划执行时间 {run_at:%Y-%m-%d %H:%M}。"
    )
    return ToolResult(
        success=True,
        message=message,
        data={"job_id": job.id, "run_at": run_at.isoformat()},
    )


def _run_scheduled_transfer(db, job: ScheduledJob) -> None:
    """定时转账处理器：到期后按 payload 执行实际转账（视为已确认）。"""
    payload = json.loads(job.payload or "{}")
    args = {
        "user_id": payload.get("from_user_id", job.user_id),
        "amount": payload.get("amount"),
        "to_name": payload.get("to_name"),
        "to_phone": payload.get("to_phone"),
        "note": payload.get("note"),
        "confirmed": True,
    }
    result = transfer_money(db, args)
    if not result.success:
        raise BankingError(result.message)


def create_aa_collection(db, args: dict) -> ToolResult:
    """创建 AA 收款单（发起人已付一半，另一位待付）。"""
    user_id = args.get("user_id")
    if user_id is None:
        return ToolResult(success=False, message="缺少用户标识")
    try:
        user_id = int(user_id)
        amount = float(args.get("amount"))
    except (TypeError, ValueError):
        return ToolResult(success=False, message="收款金额或用户标识无效")
    if amount <= 0:
        return ToolResult(success=False, message="收款金额必须大于 0")

    try:
        user = get_user(db, user_id)
    except BankingError as exc:
        return ToolResult(success=False, message=str(exc))

    share = amount / 2
    aa = AATransfer(
        title=args.get("note") or "AA收款",
        total_amount=amount,
        initiator_id=user.id,
        status="collecting",
    )
    db.add(aa)
    db.flush()
    db.add(AAMember(aa_id=aa.id, member_name=user.name, amount=share, paid=True))
    db.add(
        AAMember(
            aa_id=aa.id,
            member_name=args.get("to_name") or "好友",
            amount=share,
            paid=False,
        )
    )
    db.commit()

    message = (
        f"AA 收款已创建（编号 {aa.id}）：总额 {amount:.2f} 元，"
        f"每人 {share:.2f} 元。"
    )
    return ToolResult(
        success=True,
        message=message,
        data={"aa_id": aa.id, "total": amount, "per_person": share},
    )


registry.register(
    Tool(
        name="transfer_money",
        description="即时转账：按姓名或手机号向他人转账，金额达到阈值时需二次确认。",
        args_schema=TransferMoneyArgs,
        func=transfer_money,
    )
)
registry.register(
    Tool(
        name="schedule_transfer",
        description="定时转账：按日期表达式（明天/每月）创建到点自动执行的转账任务。",
        args_schema=ScheduleTransferArgs,
        func=schedule_transfer,
    )
)
registry.register(
    Tool(
        name="create_aa_collection",
        description="AA 收款：创建一笔 AA 收款单，发起人已付一半，另一位待付。",
        args_schema=AACollectionArgs,
        func=create_aa_collection,
    )
)

register_handler("scheduled_transfer", _run_scheduled_transfer)
