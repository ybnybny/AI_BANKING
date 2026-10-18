"""账单分析场景工具：支出分析、异常检测、账单报告（全部只读）。"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from pydantic import BaseModel

from ...core.errors import BankingError
from ...core.tooling import Tool, registry
from ...core.timeutil import utcnow
from ...domain.accounts import get_user, list_transactions
from ...schemas.common import ToolResult


class AnalyzeSpendingArgs(BaseModel):
    pass


class DetectAnomaliesArgs(BaseModel):
    pass


class GenerateReportArgs(BaseModel):
    period: Optional[str] = None


def _fmt(value: float) -> float:
    return round(float(value), 2)


def analyze_spending(db, args: dict) -> ToolResult:
    """按类目聚合支出/收入，给出总额、占比与 Top3 类目。"""
    user_id = args.get("user_id")
    if user_id is None:
        return ToolResult(success=False, message="缺少用户标识")
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return ToolResult(success=False, message="用户标识无效")

    try:
        get_user(db, user_id)
    except BankingError as exc:
        return ToolResult(success=False, message=str(exc))

    txns = list_transactions(db, user_id)
    total_expense = 0.0
    total_income = 0.0
    expense_by_cat: dict[str, float] = {}
    income_by_cat: dict[str, float] = {}
    expense_count: dict[str, int] = {}
    income_count: dict[str, int] = {}

    for t in txns:
        if t.amount < 0:
            amount = abs(t.amount)
            total_expense += amount
            expense_by_cat[t.category] = expense_by_cat.get(t.category, 0.0) + amount
            expense_count[t.category] = expense_count.get(t.category, 0) + 1
        elif t.amount > 0:
            total_income += t.amount
            income_by_cat[t.category] = income_by_cat.get(t.category, 0.0) + t.amount
            income_count[t.category] = income_count.get(t.category, 0) + 1

    categories: list[dict] = []
    for name, total in sorted(
        expense_by_cat.items(), key=lambda kv: kv[1], reverse=True
    ):
        pct = (total / total_expense * 100.0) if total_expense > 0 else 0.0
        categories.append(
            {
                "category": name,
                "type": "expense",
                "total": _fmt(total),
                "percentage": _fmt(pct),
                "count": expense_count.get(name, 0),
            }
        )
    for name, total in sorted(
        income_by_cat.items(), key=lambda kv: kv[1], reverse=True
    ):
        pct = (total / total_income * 100.0) if total_income > 0 else 0.0
        categories.append(
            {
                "category": name,
                "type": "income",
                "total": _fmt(total),
                "percentage": _fmt(pct),
                "count": income_count.get(name, 0),
            }
        )

    top_categories = [
        {"category": c["category"], "total": c["total"]}
        for c in categories
        if c["type"] == "expense"
    ][:3]

    if total_expense <= 0 and total_income <= 0:
        message = "暂无可分析的交易记录。"
    else:
        parts = [f"共 {len(txns)} 笔交易，总支出 {total_expense:.2f} 元，总收入 {total_income:.2f} 元。"]
        if top_categories:
            top_text = "、".join(
                f"{c['category']} {c['total']:.2f} 元" for c in top_categories
            )
            parts.append(f"支出最多的前 3 类为：{top_text}。")
        message = "".join(parts)

    return ToolResult(
        success=True,
        message=message,
        data={
            "categories": categories,
            "total_expense": _fmt(total_expense),
            "total_income": _fmt(total_income),
            "count": len(txns),
            "top_categories": top_categories,
        },
    )


def _anomaly_entry(t, reason: str) -> dict:
    txn_time = t.txn_time
    return {
        "transaction_id": t.id,
        "amount": _fmt(t.amount),
        "category": t.category,
        "merchant": t.merchant,
        "counterparty": t.counterparty,
        "time": txn_time.isoformat() if txn_time else None,
        "reason": reason,
    }


def detect_anomalies(db, args: dict) -> ToolResult:
    """识别单笔金额远超平均水平或同类目中的异常大额交易。"""
    user_id = args.get("user_id")
    if user_id is None:
        return ToolResult(success=False, message="缺少用户标识")
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return ToolResult(success=False, message="用户标识无效")

    try:
        get_user(db, user_id)
    except BankingError as exc:
        return ToolResult(success=False, message=str(exc))

    txns = list_transactions(db, user_id)
    expenses = [t for t in txns if t.amount < 0]
    avg_expense = (
        sum(abs(t.amount) for t in expenses) / len(expenses) if expenses else 0.0
    )
    threshold = avg_expense * 3.0 if avg_expense > 0 else 1000.0

    anomalies: list[dict] = []
    seen_ids: set[int] = set()

    for t in expenses:
        if abs(t.amount) > threshold:
            seen_ids.add(t.id)
            anomalies.append(_anomaly_entry(t, "单笔金额远超平均支出"))

    # 同类目单笔大额尖峰
    cat_groups: dict[str, list] = {}
    for t in expenses:
        cat_groups.setdefault(t.category, []).append(t)
    for items in cat_groups.values():
        if len(items) < 2:
            continue
        mean = sum(abs(t.amount) for t in items) / len(items)
        max_t = max(items, key=lambda t: abs(t.amount))
        if mean > 0 and abs(max_t.amount) > mean * 3.0 and max_t.id not in seen_ids:
            seen_ids.add(max_t.id)
            anomalies.append(_anomaly_entry(max_t, "同类目中的异常大额支出"))

    anomalies.sort(key=lambda a: abs(a["amount"]), reverse=True)

    if not anomalies:
        return ToolResult(
            success=True,
            message="未发现异常交易",
            data={"anomalies": []},
        )

    lines = [f"共发现 {len(anomalies)} 笔异常交易："]
    for a in anomalies:
        merchant = a["merchant"] or a["counterparty"] or "未知商户"
        lines.append(
            f"{a['category']}｜{merchant}｜{abs(a['amount']):.2f} 元（{a['reason']}）"
        )
    return ToolResult(
        success=True,
        message="；".join(lines),
        data={"anomalies": anomalies},
    )


def _month_end(now: datetime) -> datetime:
    if now.month == 12:
        return datetime(now.year + 1, 1, 1) - timedelta(microseconds=1)
    return datetime(now.year, now.month + 1, 1) - timedelta(microseconds=1)


def _prev_month_start(now: datetime) -> datetime:
    if now.month == 1:
        return datetime(now.year - 1, 12, 1)
    return datetime(now.year, now.month - 1, 1)


def generate_report(db, args: dict) -> ToolResult:
    """按月或按年汇总收支、类目、商户与订阅支出，输出结构化报告。"""
    user_id = args.get("user_id")
    if user_id is None:
        return ToolResult(success=False, message="缺少用户标识")
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return ToolResult(success=False, message="用户标识无效")

    try:
        get_user(db, user_id)
    except BankingError as exc:
        return ToolResult(success=False, message=str(exc))

    period = args.get("period") or "monthly"
    if period not in ("monthly", "annual"):
        period = "monthly"

    now = utcnow()
    if period == "annual":
        start = datetime(now.year, 1, 1)
        end = datetime(now.year, 12, 31, 23, 59, 59, 999999)
        period_label = "本年度"
    else:
        start = datetime(now.year, now.month, 1)
        end = _month_end(now)
        period_label = "本月"

    txns = list_transactions(db, user_id, start, end)

    total_income = 0.0
    total_expense = 0.0
    subscription_total = 0.0
    cat_totals: dict[str, float] = {}
    cat_counts: dict[str, int] = {}
    merchant_totals: dict[str, float] = {}
    merchant_counts: dict[str, int] = {}

    for t in txns:
        if t.amount > 0:
            total_income += t.amount
        elif t.amount < 0:
            amount = abs(t.amount)
            total_expense += amount
            cat_totals[t.category] = cat_totals.get(t.category, 0.0) + amount
            cat_counts[t.category] = cat_counts.get(t.category, 0) + 1
            merchant = t.merchant or t.counterparty or "未知商户"
            merchant_totals[merchant] = merchant_totals.get(merchant, 0.0) + amount
            merchant_counts[merchant] = merchant_counts.get(merchant, 0) + 1
            if t.is_subscription:
                subscription_total += amount

    net = total_income - total_expense

    categories = []
    for name, total in sorted(cat_totals.items(), key=lambda kv: kv[1], reverse=True):
        pct = (total / total_expense * 100.0) if total_expense > 0 else 0.0
        categories.append(
            {
                "category": name,
                "total": _fmt(total),
                "percentage": _fmt(pct),
                "count": cat_counts.get(name, 0),
            }
        )

    top_merchants = [
        {"merchant": name, "total": _fmt(total), "count": merchant_counts.get(name, 0)}
        for name, total in sorted(
            merchant_totals.items(), key=lambda kv: kv[1], reverse=True
        )[:5]
    ]

    if period == "annual":
        monthly_totals: list[float] = [0.0] * 12
        for t in txns:
            if t.amount < 0 and t.txn_time:
                monthly_totals[t.txn_time.month - 1] += abs(t.amount)
        trend = [
            {"month": f"{now.year}-{m:02d}", "expense": _fmt(monthly_totals[m - 1])}
            for m in range(1, 13)
        ]
        month_count = sum(1 for v in monthly_totals if v > 0)
    else:
        cur_expense = total_expense
        prev_start = _prev_month_start(now)
        prev_txns = list_transactions(db, user_id, prev_start, start - timedelta(microseconds=1))
        prev_expense = sum(abs(t.amount) for t in prev_txns if t.amount < 0)
        mom_change_pct = (
            (cur_expense - prev_expense) / prev_expense * 100.0
            if prev_expense > 0
            else None
        )
        trend = [
            {"month": prev_start.strftime("%Y-%m"), "expense": _fmt(prev_expense)},
            {"month": now.strftime("%Y-%m"), "expense": _fmt(cur_expense)},
        ]
        month_count = 2 if txns or prev_txns else 0

    top_cat_text = categories[0]["category"] if categories else "无"
    top_merchant_text = top_merchants[0]["merchant"] if top_merchants else "无"
    if period == "annual":
        trend_text = f"全年共 {month_count} 个月有支出记录。"
    elif isinstance(trend[-1].get("expense"), (int, float)):
        mom = (
            "暂无环比数据"
            if mom_change_pct is None
            else f"环比变化 {mom_change_pct:+.1f}%"
        )
        trend_text = f"{mom}。"
    else:
        trend_text = ""

    message = (
        f"{period_label}账单报告：总收入 {total_income:.2f} 元，"
        f"总支出 {total_expense:.2f} 元，净收支 {net:+.2f} 元；"
        f"支出最多的类目为「{top_cat_text}」，"
        f"消费最多的商户为「{top_merchant_text}」；"
        f"订阅支出合计 {subscription_total:.2f} 元。{trend_text}"
    )

    data = {
        "period": period,
        "total_income": _fmt(total_income),
        "total_expense": _fmt(total_expense),
        "net": _fmt(net),
        "categories": categories,
        "top_merchants": top_merchants,
        "subscription_total": _fmt(subscription_total),
        "trend": trend,
    }
    if period == "monthly":
        data["month_count"] = month_count
        data["mom_change_pct"] = (
            _fmt(mom_change_pct) if mom_change_pct is not None else None
        )
    else:
        data["month_count"] = month_count

    return ToolResult(success=True, message=message, data=data)


registry.register(
    Tool(
        name="analyze_spending",
        description="支出分析：按类目聚合用户交易，给出总支出、总收入、各类目占比与 Top3 支出类目。",
        args_schema=AnalyzeSpendingArgs,
        func=analyze_spending,
    )
)
registry.register(
    Tool(
        name="detect_anomalies",
        description="异常检测：识别单笔金额远超平均水平或同类目中出现异常大额尖峰的交易。",
        args_schema=DetectAnomaliesArgs,
        func=detect_anomalies,
    )
)
registry.register(
    Tool(
        name="generate_report",
        description="账单报告：按月或按年汇总收入、支出、净收支、类目分布、Top 商户与订阅支出。",
        args_schema=GenerateReportArgs,
        func=generate_report,
    )
)
