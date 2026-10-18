"""ORM 模型：用户、账户、流水、理财、卡片、订阅、调度任务、订单、审计、会话记忆。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .timeutil import utcnow


def _now() -> datetime:
    return utcnow()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    phone: Mapped[str] = mapped_column(String(32), unique=True)
    email: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 跨场景联动所需
    spouse_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    spouse_birthday: Mapped[str | None] = mapped_column(String(16), nullable=True)  # MM-DD
    risk_level: Mapped[str | None] = mapped_column(String(8), nullable=True)  # R1..R5
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    accounts: Mapped[list["Account"]] = relationship(back_populates="user")
    cards: Mapped[list["Card"]] = relationship(back_populates="user")


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    account_no: Mapped[str] = mapped_column(String(32), unique=True)
    account_type: Mapped[str] = mapped_column(String(16))  # demand(活期)/time(定期)/locked(锁定)
    balance: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    user: Mapped["User"] = relationship(back_populates="accounts")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    amount: Mapped[float] = mapped_column(Float)  # 正=收入, 负=支出
    category: Mapped[str] = mapped_column(String(32), default="其他")
    merchant: Mapped[str | None] = mapped_column(String(128), nullable=True)
    counterparty: Mapped[str | None] = mapped_column(String(64), nullable=True)
    txn_time: Mapped[datetime] = mapped_column(DateTime, default=_now)
    txn_type: Mapped[str] = mapped_column(String(16), default="expense")  # income/expense/transfer
    note: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_subscription: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="completed")


class WealthProduct(Base):
    __tablename__ = "wealth_products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    product_type: Mapped[str] = mapped_column(String(16))  # fund/bond/deposit/money_fund
    risk_level: Mapped[str] = mapped_column(String(8))  # R1..R5
    expected_return: Mapped[float] = mapped_column(Float)  # 年化 %
    min_amount: Mapped[float] = mapped_column(Float, default=1.0)
    term_days: Mapped[int] = mapped_column(Integer, default=0)  # 0=活期/灵活
    status: Mapped[str] = mapped_column(String(16), default="on_sale")


class Holding(Base):
    __tablename__ = "holdings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("wealth_products.id"))
    amount: Mapped[float] = mapped_column(Float)
    purchased_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    status: Mapped[str] = mapped_column(String(16), default="holding")  # holding/redeemed


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    answers: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    risk_level: Mapped[str] = mapped_column(String(8))  # R1..R5
    assessed_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Card(Base):
    __tablename__ = "cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    card_no: Mapped[str] = mapped_column(String(32), unique=True)
    card_type: Mapped[str] = mapped_column(String(16), default="debit")  # debit/credit
    credit_limit: Mapped[float] = mapped_column(Float, default=0.0)
    daily_limit: Mapped[float] = mapped_column(Float, default=50000.0)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active/locked/lost
    transaction_restricted: Mapped[bool] = mapped_column(Boolean, default=False)
    expiry: Mapped[str | None] = mapped_column(String(8), nullable=True)  # YYYY-MM
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    user: Mapped["User"] = relationship(back_populates="cards")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    merchant: Mapped[str] = mapped_column(String(128))
    amount: Mapped[float] = mapped_column(Float)
    cycle: Mapped[str] = mapped_column(String(16), default="monthly")  # monthly/yearly
    next_renewal: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    category: Mapped[str] = mapped_column(String(32), default="视频会员")
    status: Mapped[str] = mapped_column(String(16), default="active")  # active/cancelled
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    job_type: Mapped[str] = mapped_column(String(32))  # transfer/birthday_check/renewal_reminder
    payload: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    run_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/done/cancelled
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class AATransfer(Base):
    """AA 收款单。"""

    __tablename__ = "aa_transfers"

    id: Mapped[int] = mapped_column(primary_key=True)
    initiator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(128))
    total_amount: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default="collecting")  # collecting/settled
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    members: Mapped[list["AAMember"]] = relationship(back_populates="aa", cascade="all, delete-orphan")


class AAMember(Base):
    __tablename__ = "aa_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    aa_id: Mapped[int] = mapped_column(ForeignKey("aa_transfers.id"))
    member_name: Mapped[str] = mapped_column(String(64))
    member_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    amount: Mapped[float] = mapped_column(Float)
    paid: Mapped[bool] = mapped_column(Boolean, default=False)

    aa: Mapped["AATransfer"] = relationship(back_populates="members")


class Order(Base):
    """跨场景联动中的外部订单（鲜花/蛋糕）。"""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    order_type: Mapped[str] = mapped_column(String(16))  # flower/cake
    description: Mapped[str | None] = mapped_column(String(256), nullable=True)
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="created")  # created/paid/delivered
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Conversation(Base):
    """Agent 会话记忆（消息历史）。"""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user/assistant
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    risk: Mapped[str] = mapped_column(String(16), default="low")  # low/medium/high
    status: Mapped[str] = mapped_column(String(16), default="success")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
