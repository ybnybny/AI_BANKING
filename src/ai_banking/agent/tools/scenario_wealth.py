"""理财操作场景工具：风险测评、产品推荐、产品对比、基金申购、基金赎回。"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel
from sqlalchemy import select

from ...config import settings
from ...core.errors import BankingError
from ...core.models import Holding, RiskAssessment, WealthProduct
from ...core.tooling import Tool, registry
from ...domain.accounts import debit_main_account, get_main_account, get_user
from ...schemas.common import ToolResult


class AssessRiskArgs(BaseModel):
    pass


class RecommendProductsArgs(BaseModel):
    pass


class CompareProductsArgs(BaseModel):
    pass


class SubscribeFundArgs(BaseModel):
    amount: Optional[float] = None
    product_id: Optional[int] = None
    confirmed: Optional[bool] = None


class RedeemFundArgs(BaseModel):
    product_id: Optional[int] = None
    amount: Optional[float] = None
    confirmed: Optional[bool] = None


def _get_user_id(args: dict) -> int | None:
    raw = args.get("user_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _product_dict(product: WealthProduct) -> dict:
    return {
        "id": product.id,
        "name": product.name,
        "type": product.product_type,
        "risk": product.risk_level,
        "expected_return": product.expected_return,
        "term_days": product.term_days,
        "min_amount": product.min_amount,
    }


def assess_risk(db, args: dict) -> ToolResult:
    """风险测评：已有等级直接返回，否则按 R3（平衡型）建档。"""
    user_id = _get_user_id(args)
    if user_id is None:
        return ToolResult(success=False, message="缺少用户标识")
    try:
        user = get_user(db, user_id)
    except BankingError as exc:
        return ToolResult(success=False, message=str(exc))

    if user.risk_level:
        return ToolResult(
            success=True,
            message=f"您已完成风险测评，当前风险等级为 {user.risk_level}。",
            data={"risk_level": user.risk_level},
        )

    user.risk_level = "R3"
    db.add(RiskAssessment(user_id=user_id, risk_level="R3", answers="{}"))
    db.commit()
    return ToolResult(
        success=True,
        message=(
            "请回答以下问题：1) 您的投资经验年限；2) 可承受的最大亏损比例；"
            "3) 预期投资期限。根据您的初步情况，已为您暂定风险等级 R3（平衡型）。"
        ),
        data={"risk_level": "R3"},
    )


def recommend_products(db, args: dict) -> ToolResult:
    """按用户风险等级推荐在售产品（只读）。"""
    user_id = _get_user_id(args)
    if user_id is None:
        return ToolResult(success=False, message="缺少用户标识")
    try:
        user = get_user(db, user_id)
    except BankingError as exc:
        return ToolResult(success=False, message=str(exc))

    risk_level = user.risk_level or "R3"
    on_sale = list(
        db.execute(
            select(WealthProduct).where(WealthProduct.status == "on_sale")
        ).scalars().all()
    )
    suitable = [p for p in on_sale if p.risk_level <= risk_level]
    suitable.sort(key=lambda p: p.expected_return, reverse=True)
    top = suitable[:3]
    if not top:
        return ToolResult(success=False, message="暂无可推荐的产品，请稍后再试。")

    lines = [
        f"{i + 1}. {p.name}（{p.product_type}，风险 {p.risk_level}，"
        f"年化 {p.expected_return}%，期限 {p.term_days} 天，"
        f"起购 {p.min_amount:.2f} 元）"
        for i, p in enumerate(top)
    ]
    return ToolResult(
        success=True,
        message="为您推荐以下产品：\n" + "\n".join(lines),
        data={"products": [_product_dict(p) for p in top]},
    )


def compare_products(db, args: dict) -> ToolResult:
    """横向对比最多 3 只在售产品（只读）。"""
    user_id = _get_user_id(args)
    if user_id is None:
        return ToolResult(success=False, message="缺少用户标识")
    try:
        get_user(db, user_id)
    except BankingError as exc:
        return ToolResult(success=False, message=str(exc))

    on_sale = list(
        db.execute(
            select(WealthProduct).where(WealthProduct.status == "on_sale")
        ).scalars().all()
    )
    on_sale.sort(key=lambda p: p.expected_return, reverse=True)
    picked = on_sale[:3]
    if not picked:
        return ToolResult(success=False, message="暂无可比较的产品。")

    lines = [
        f"{p.name} | 类型 {p.product_type} | 风险 {p.risk_level} | "
        f"年化 {p.expected_return}% | 期限 {p.term_days} 天 | "
        f"起购 {p.min_amount:.2f} 元"
        for p in picked
    ]
    return ToolResult(
        success=True,
        message="产品对比：\n" + "\n".join(lines),
        data={"products": [_product_dict(p) for p in picked]},
    )


def subscribe_fund(db, args: dict) -> ToolResult:
    """基金申购：缺省选择最低风险产品与起购金额，大额需二次确认。"""
    user_id = _get_user_id(args)
    if user_id is None:
        return ToolResult(success=False, message="缺少用户标识")
    try:
        get_user(db, user_id)
    except BankingError as exc:
        return ToolResult(success=False, message=str(exc))

    product = None
    product_id = args.get("product_id")
    if product_id is not None:
        try:
            product_id = int(product_id)
        except (TypeError, ValueError):
            return ToolResult(success=False, message="产品编号无效")
        product = db.get(WealthProduct, product_id)
        if product is None or product.status != "on_sale":
            return ToolResult(success=False, message="未找到该在售产品")
    else:
        on_sale = list(
            db.execute(
                select(WealthProduct).where(WealthProduct.status == "on_sale")
            ).scalars().all()
        )
        if on_sale:
            product = min(on_sale, key=lambda p: p.risk_level)
        if product is None:
            return ToolResult(success=False, message="暂无可申购的产品")

    amount = args.get("amount")
    if amount is None:
        amount = product.min_amount
    else:
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            return ToolResult(success=False, message="申购金额无效")
    if amount <= 0:
        return ToolResult(success=False, message="申购金额必须大于 0")

    if amount >= settings.transfer_confirm_threshold and not args.get("confirmed"):
        prompt = (
            f"确认申购 {product.name}，金额 {amount:.2f} 元？"
            "回复“确认”执行，回复“取消”放弃。"
        )
        return ToolResult(
            success=True, requires_confirmation=True, confirmation_prompt=prompt
        )

    try:
        acct = debit_main_account(db, user_id, amount, note="申购" + product.name)
        holding = Holding(user_id=user_id, product_id=product.id, amount=amount)
        db.add(holding)
        db.commit()
    except BankingError as exc:
        db.rollback()
        return ToolResult(success=False, message=str(exc))

    return ToolResult(
        success=True,
        message=(
            f"申购成功：{product.name} {amount:.2f} 元，"
            f"当前活期余额 {acct.balance:.2f} 元。"
        ),
        data={
            "holding_id": holding.id,
            "product_id": product.id,
            "product_name": product.name,
            "amount": amount,
            "balance": acct.balance,
        },
    )


def redeem_fund(db, args: dict) -> ToolResult:
    """基金赎回：需二次确认后回款至活期账户并标记持仓。"""
    user_id = _get_user_id(args)
    if user_id is None:
        return ToolResult(success=False, message="缺少用户标识")
    try:
        get_user(db, user_id)
    except BankingError as exc:
        return ToolResult(success=False, message=str(exc))

    stmt = select(Holding).where(
        Holding.user_id == user_id, Holding.status == "holding"
    )
    product_id = args.get("product_id")
    if product_id is not None:
        try:
            product_id = int(product_id)
        except (TypeError, ValueError):
            return ToolResult(success=False, message="产品编号无效")
        stmt = stmt.where(Holding.product_id == product_id)
    holding = db.execute(stmt.order_by(Holding.purchased_at.desc())).scalars().first()
    if holding is None:
        return ToolResult(success=False, message="未找到可赎回的持仓")

    amount = args.get("amount")
    if amount is None:
        amount = holding.amount
    else:
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            return ToolResult(success=False, message="赎回金额无效")

    if not args.get("confirmed"):
        prompt = f"确认赎回持仓 {amount:.2f} 元？回复“确认”执行，回复“取消”放弃。"
        return ToolResult(
            success=True, requires_confirmation=True, confirmation_prompt=prompt
        )

    if amount <= 0:
        return ToolResult(success=False, message="赎回金额必须大于 0")
    if amount > holding.amount:
        return ToolResult(success=False, message="赎回金额超过持仓金额")

    try:
        acct = get_main_account(db, user_id)
        acct.balance += amount
        holding.status = "redeemed"
        db.commit()
    except BankingError as exc:
        db.rollback()
        return ToolResult(success=False, message=str(exc))

    return ToolResult(
        success=True,
        message=f"赎回成功：{amount:.2f} 元已到账，当前活期余额 {acct.balance:.2f} 元。",
        data={"amount": amount, "balance": acct.balance, "holding_id": holding.id},
    )


registry.register(
    Tool(
        name="assess_risk",
        description="风险测评：生成或返回用户风险等级（R1..R5）。",
        args_schema=AssessRiskArgs,
        func=assess_risk,
    )
)
registry.register(
    Tool(
        name="recommend_products",
        description="按用户风险等级推荐在售理财产品（最多 3 只）。",
        args_schema=RecommendProductsArgs,
        func=recommend_products,
    )
)
registry.register(
    Tool(
        name="compare_products",
        description="横向对比在售理财产品（最多 3 只）。",
        args_schema=CompareProductsArgs,
        func=compare_products,
    )
)
registry.register(
    Tool(
        name="subscribe_fund",
        description="基金申购：按产品编号或默认最低风险产品申购，大额需二次确认。",
        args_schema=SubscribeFundArgs,
        func=subscribe_fund,
    )
)
registry.register(
    Tool(
        name="redeem_fund",
        description="基金赎回：将持仓回款至活期账户，需二次确认。",
        args_schema=RedeemFundArgs,
        func=redeem_fund,
    )
)
