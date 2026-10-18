"""跨场景联动场景工具：检测爱人生日，锁定礼金并调度鲜花/蛋糕订单。"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta

from pydantic import BaseModel

from ...core.errors import BankingError, InsufficientFundsError
from ...core.models import Order, ScheduledJob
from ...core.tooling import Tool, registry
from ...core.timeutil import utcnow
from ...domain.accounts import debit_main_account, get_user, lock_funds
from ...domain.scheduler import register_handler
from ...schemas.common import ToolResult

logger = logging.getLogger(__name__)


class CheckBirthdayPlanArgs(BaseModel):
    days_before: int | None = None
    amount: float | None = None


def _next_birthday(birthday_str: str, today: date) -> date | None:
    """解析 MM-DD 生日，返回距今最近的一个生日日期（含当天）。"""
    try:
        month, day = (int(part) for part in birthday_str.split("-"))
    except (AttributeError, ValueError):
        return None
    for year in (today.year, today.year + 1):
        try:
            bday = date(year, month, day)
        except ValueError:
            if month == 2 and day == 29:
                bday = date(year, 2, 28)
            else:
                return None
        if bday >= today:
            return bday
    return None


def check_birthday_plan(db, args: dict) -> ToolResult:
    """检测爱人生日，锁定礼金并调度生日前订购鲜花与蛋糕。"""
    user_id = args.get("user_id")
    if user_id is None:
        return ToolResult(success=False, message="缺少用户标识")
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return ToolResult(success=False, message="用户标识无效")

    try:
        user = get_user(db, user_id)
    except BankingError as exc:
        return ToolResult(success=False, message=str(exc))

    if not user.spouse_name or not user.spouse_birthday:
        return ToolResult(success=False, message="未登记爱人生日信息")

    amount = args.get("amount")
    if amount is None:
        amount = 1000.0
    amount = float(amount)
    days_before = args.get("days_before")
    if days_before is None:
        days_before = 2
    days_before = int(days_before)

    try:
        lock_funds(db, user_id, amount, note="爱人生日礼金锁定")
        db.commit()
    except BankingError as exc:
        db.rollback()
        return ToolResult(success=False, message=str(exc))
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return ToolResult(success=False, message=f"锁定资金失败: {exc}")

    today = utcnow().date()
    next_birthday = _next_birthday(user.spouse_birthday, today)
    if next_birthday is None:
        return ToolResult(success=False, message="生日日期无效")

    order_date = next_birthday - timedelta(days=days_before)
    run_at = datetime.combine(order_date, datetime.min.time())
    job = ScheduledJob(
        user_id=user_id,
        job_type="birthday_check",
        payload=json.dumps({"amount": amount, "days_before": days_before}),
        run_at=run_at,
        status="pending",
    )
    db.add(job)
    try:
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return ToolResult(success=False, message=f"创建生日订单任务失败: {exc}")

    date_str = order_date.isoformat()
    message = f"已锁定 {amount} 元；将于生日前 {days_before} 天（{date_str}）订购鲜花与蛋糕。"
    return ToolResult(
        success=True,
        message=message,
        data={"locked_amount": amount, "order_date": date_str},
    )


def _birthday_check_handler(db, job) -> None:
    """生日检测调度处理器：创建鲜花/蛋糕订单，并从主账户扣款。"""
    try:
        flower = Order(
            user_id=job.user_id,
            order_type="flower",
            description="鲜花",
            amount=200.0,
            status="paid",
        )
        cake = Order(
            user_id=job.user_id,
            order_type="cake",
            description="蛋糕",
            amount=300.0,
            status="paid",
        )
        db.add_all([flower, cake])
        try:
            debit_main_account(db, job.user_id, 500.0, note="生日礼物")
        except InsufficientFundsError:
            flower.status = "created"
            cake.status = "created"
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("生日检测任务 %s 执行失败", getattr(job, "id", "-"))


registry.register(
    Tool(
        name="check_birthday_plan",
        description="跨场景联动：检测爱人生日，锁定礼金（默认 1000 元），并调度生日前（默认 2 天）订购鲜花与蛋糕。",
        args_schema=CheckBirthdayPlanArgs,
        func=check_birthday_plan,
    )
)

register_handler("birthday_check", _birthday_check_handler)
