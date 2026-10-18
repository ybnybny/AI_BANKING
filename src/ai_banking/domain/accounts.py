"""账户与流水共享原语（转账/账单/跨场景等场景共用）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.errors import InsufficientFundsError, InvalidOperationError, NotFoundError
from ..core.models import Account, Transaction, User
from ..core.timeutil import utcnow

MAIN_ACCOUNT_TYPE = "demand"


def get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError(f"用户 {user_id} 不存在")
    return user


def get_user_by_phone(db: Session, phone: str) -> User | None:
    return db.execute(select(User).where(User.phone == phone)).scalar_one_or_none()


def get_user_by_name(db: Session, name: str) -> User | None:
    return db.execute(select(User).where(User.name == name)).scalar_one_or_none()


def list_accounts(db: Session, user_id: int) -> list[Account]:
    return list(
        db.execute(select(Account).where(Account.user_id == user_id)).scalars().all()
    )


def get_main_account(db: Session, user_id: int) -> Account:
    acct = db.execute(
        select(Account).where(
            Account.user_id == user_id, Account.account_type == MAIN_ACCOUNT_TYPE
        )
    ).scalar_one_or_none()
    if acct is None:
        raise NotFoundError(f"用户 {user_id} 无活期账户")
    return acct


def get_account_balance(db: Session, account_id: int) -> float:
    acct = db.get(Account, account_id)
    if acct is None:
        raise NotFoundError(f"账户 {account_id} 不存在")
    return acct.balance


def record_transaction(
    db: Session,
    user_id: int,
    amount: float,
    category: str = "其他",
    merchant: str | None = None,
    counterparty: str | None = None,
    txn_type: str = "expense",
    note: str | None = None,
    account_id: int | None = None,
    is_subscription: bool = False,
    txn_time: datetime | None = None,
) -> Transaction:
    txn = Transaction(
        user_id=user_id,
        account_id=account_id,
        amount=amount,
        category=category,
        merchant=merchant,
        counterparty=counterparty,
        txn_type=txn_type,
        note=note,
        is_subscription=is_subscription,
        txn_time=txn_time or utcnow(),
    )
    db.add(txn)
    return txn


def transfer_funds(
    db: Session,
    from_user_id: int,
    to_user_id: int,
    amount: float,
    note: str | None = None,
) -> tuple[Account, Account]:
    """两个用户主账户间转账：扣减付款方、增加收款方，并各自记账。"""
    if amount <= 0:
        raise InvalidOperationError("转账金额必须大于 0")
    from_acct = get_main_account(db, from_user_id)
    to_acct = get_main_account(db, to_user_id)
    if from_acct.balance < amount:
        raise InsufficientFundsError(f"余额不足：当前 {from_acct.balance:.2f} 元，需转 {amount:.2f} 元")
    from_acct.balance -= amount
    to_acct.balance += amount
    from_user = get_user(db, from_user_id)
    to_user = get_user(db, to_user_id)
    record_transaction(
        db, from_user_id, -amount, category="转账",
        counterparty=to_user.name, txn_type="transfer", note=note, account_id=from_acct.id,
    )
    record_transaction(
        db, to_user_id, amount, category="转账",
        counterparty=from_user.name, txn_type="transfer", note=note, account_id=to_acct.id,
    )
    return from_acct, to_acct


def debit_main_account(db: Session, user_id: int, amount: float, note: str | None = None) -> Account:
    """从主账户扣款（用于申购/下单等），返回扣款后账户。"""
    acct = get_main_account(db, user_id)
    if acct.balance < amount:
        raise InsufficientFundsError(f"余额不足：当前 {acct.balance:.2f} 元，需 {amount:.2f} 元")
    acct.balance -= amount
    record_transaction(
        db, user_id, -amount, category="支出", txn_type="expense", note=note, account_id=acct.id,
    )
    return acct


def lock_funds(db: Session, user_id: int, amount: float, note: str | None = None) -> Account:
    """锁定资金：从活期转入锁定账户（跨场景联动用）。"""
    acct = get_main_account(db, user_id)
    if acct.balance < amount:
        raise InsufficientFundsError(f"余额不足，无法锁定 {amount:.2f} 元")
    locked = db.execute(
        select(Account).where(
            Account.user_id == user_id, Account.account_type == "locked"
        )
    ).scalar_one_or_none()
    if locked is None:
        locked = Account(
            user_id=user_id,
            account_no=f"L{acct.account_no}",
            account_type="locked",
            balance=0.0,
        )
        db.add(locked)
        db.flush()
    acct.balance -= amount
    locked.balance += amount
    record_transaction(
        db, user_id, -amount, category="锁定", txn_type="expense",
        note=note or "资金锁定", account_id=acct.id,
    )
    return locked


def list_transactions(
    db: Session, user_id: int, start: datetime | None = None, end: datetime | None = None
) -> list[Transaction]:
    stmt = select(Transaction).where(Transaction.user_id == user_id)
    if start:
        stmt = stmt.where(Transaction.txn_time >= start)
    if end:
        stmt = stmt.where(Transaction.txn_time <= end)
    return list(db.execute(stmt.order_by(Transaction.txn_time.desc())).scalars().all())
