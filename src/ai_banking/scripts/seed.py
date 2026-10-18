"""演示数据种子脚本。运行：python -m ai_banking.scripts.seed"""
from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import delete

from ai_banking.core.database import SessionLocal, init_db
from ai_banking.core.models import (
    AAMember,
    AATransfer,
    Account,
    AuditLog,
    Card,
    Conversation,
    Holding,
    Order,
    RiskAssessment,
    ScheduledJob,
    Subscription,
    Transaction,
    User,
    WealthProduct,
)

# 删除顺序需满足外键依赖（子表在前，父表在后）
DELETE_ORDER = [
    AAMember,
    AATransfer,
    Order,
    ScheduledJob,
    Holding,
    RiskAssessment,
    Subscription,
    Card,
    Transaction,
    Account,
    WealthProduct,
    User,
]


def _build_transactions(account_id: int, now: datetime) -> list[Transaction]:
    """为张三生成近 12 个月的流水，用于账单分析。"""
    rng = random.Random(42)
    rows: list[Transaction] = []

    def expense(
        amount: float,
        category: str,
        merchant: str | None,
        days_ago: int,
        *,
        subscription: bool = False,
    ) -> Transaction:
        return Transaction(
            user_id=1,
            account_id=account_id,
            amount=-amount,
            category=category,
            merchant=merchant,
            txn_time=now - timedelta(days=days_ago),
            txn_type="expense",
            is_subscription=subscription,
        )

    def income(amount: float, category: str, counterparty: str, days_ago: int) -> Transaction:
        return Transaction(
            user_id=1,
            account_id=account_id,
            amount=amount,
            category=category,
            counterparty=counterparty,
            txn_time=now - timedelta(days=days_ago),
            txn_type="income",
        )

    # 工资收入：近 12 个月每月一笔
    for days in range(10, 365, 30):
        rows.append(income(15000.0, "工资", "某某科技有限公司", days))

    # 订阅类：腾讯视频（每月）与阿里云盘
    for days in (5, 35, 65):
        rows.append(expense(25.0, "视频会员", "腾讯视频", days, subscription=True))
    for days in (20, 140):
        rows.append(expense(68.0, "云服务", "阿里云盘", days, subscription=True))

    # 异常大额支出
    rows.append(expense(8000.0, "购物", "京东商城", 200))

    # 日常随机支出
    category_ranges = {
        "餐饮": (15, 120),
        "交通": (5, 50),
        "购物": (50, 400),
        "娱乐": (30, 200),
    }
    category_weights = ["餐饮"] * 5 + ["交通"] * 4 + ["购物"] * 4 + ["娱乐"] * 3
    merchants = {
        "餐饮": ["美团外卖", "肯德基", "海底捞", "星巴克"],
        "交通": ["滴滴出行", "中国石油", "地铁公司"],
        "购物": ["淘宝", "京东商城", "拼多多"],
        "娱乐": ["万达影城", "KTV 量贩", "网易云音乐"],
    }
    for _ in range(20):
        category = rng.choice(category_weights)
        lo, hi = category_ranges[category]
        rows.append(
            expense(
                float(rng.randint(lo, hi)),
                category,
                rng.choice(merchants[category]),
                rng.randint(0, 365),
            )
        )

    return rows


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        # 1. 清空旧数据（外键安全顺序）
        for model in DELETE_ORDER:
            db.execute(delete(model))
        db.commit()

        now = datetime.now()

        # 2. 用户
        spouse_birthday = (now.date() + timedelta(days=2)).strftime("%m-%d")
        zhangsan = User(
            id=1,
            name="张三",
            phone="13800000001",
            email="zhangsan@example.com",
            spouse_name="王芳",
            spouse_birthday=spouse_birthday,
            risk_level="R3",
        )
        lisi = User(id=2, name="李四", phone="13800000002")
        db.add_all([zhangsan, lisi])
        db.flush()

        # 3. 账户
        demand_1 = Account(
            user_id=1,
            account_no="6217000000000001",
            account_type="demand",
            balance=50000.0,
            currency="CNY",
            status="active",
        )
        locked_1 = Account(
            user_id=1,
            account_no="L6217000000000001",
            account_type="locked",
            balance=0.0,
            currency="CNY",
            status="active",
        )
        demand_2 = Account(
            user_id=2,
            account_no="6217000000000002",
            account_type="demand",
            balance=10000.0,
            currency="CNY",
            status="active",
        )
        db.add_all([demand_1, locked_1, demand_2])
        db.flush()

        # 4. 流水（张三）
        transactions = _build_transactions(demand_1.id, now)
        db.add_all(transactions)
        db.flush()

        # 5. 理财产品
        products = [
            WealthProduct(
                name="活期宝",
                product_type="money_fund",
                risk_level="R1",
                expected_return=1.8,
                min_amount=1,
                term_days=0,
                status="on_sale",
            ),
            WealthProduct(
                name="稳盈债券",
                product_type="bond",
                risk_level="R2",
                expected_return=3.2,
                min_amount=100,
                term_days=90,
                status="on_sale",
            ),
            WealthProduct(
                name="均衡混合",
                product_type="fund",
                risk_level="R3",
                expected_return=5.5,
                min_amount=1000,
                term_days=365,
                status="on_sale",
            ),
            WealthProduct(
                name="进取股票",
                product_type="fund",
                risk_level="R5",
                expected_return=9.8,
                min_amount=5000,
                term_days=365,
                status="on_sale",
            ),
        ]
        db.add_all(products)

        # 6. 卡片
        cards = [
            Card(
                user_id=1,
                card_no="6222021234568888",
                card_type="credit",
                credit_limit=20000.0,
                daily_limit=50000.0,
                status="active",
            ),
            Card(
                user_id=1,
                card_no="6222021234569999",
                card_type="debit",
                credit_limit=0.0,
                daily_limit=50000.0,
                status="active",
            ),
        ]
        db.add_all(cards)

        # 7. 订阅
        subscriptions = [
            Subscription(
                user_id=1,
                merchant="腾讯视频",
                amount=25.0,
                cycle="monthly",
                next_renewal=now + timedelta(days=15),
                category="视频会员",
                status="active",
            ),
            Subscription(
                user_id=1,
                merchant="阿里云盘",
                amount=68.0,
                cycle="yearly",
                next_renewal=now + timedelta(days=40),
                category="云服务",
                status="active",
            ),
        ]
        db.add_all(subscriptions)

        db.commit()

        counts = {
            "用户": db.query(User).count(),
            "账户": db.query(Account).count(),
            "交易流水": db.query(Transaction).count(),
            "理财产品": db.query(WealthProduct).count(),
            "卡片": db.query(Card).count(),
            "订阅": db.query(Subscription).count(),
        }
        print("演示数据插入完成：")
        for name, value in counts.items():
            print(f"  {name}: {value}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
