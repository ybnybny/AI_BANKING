"""端到端测试：覆盖 6 大核心场景的意图路由与工具执行。"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import ai_banking.agent.tools  # noqa: E402,F401  触发工具注册
from ai_banking.api.main import app  # noqa: E402
from ai_banking.core.database import init_db  # noqa: E402
from ai_banking.scripts.seed import main as seed_main  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _setup():
    init_db()
    seed_main()
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def chat(client: TestClient, sid: str, msg: str, uid: int = 1) -> dict:
    r = client.post("/api/chat", json={"user_id": uid, "session_id": sid, "message": msg})
    assert r.status_code == 200, r.text
    return r.json()


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["tools"] >= 21


def test_tools_list(client):
    r = client.get("/api/tools")
    assert r.status_code == 200
    names = {t["name"] for t in r.json()["tools"]}
    assert {"transfer_money", "generate_report", "recommend_products", "report_card_loss",
            "cancel_subscription", "check_birthday_plan"} <= names


def test_chitchat(client):
    d = chat(client, "t-chat", "你好")
    assert d["intent"] == "chitchat"
    assert d["response"]


def test_transfer(client):
    d = chat(client, "t-transfer", "转 100 元给李四，备注聚餐")
    assert d["intent"] == "transfer"
    assert d["tool_used"] == "transfer_money"
    assert "转账成功" in d["response"]


def test_high_value_transfer_confirmation(client):
    sid = "t-big-transfer"
    d = chat(client, sid, "转 6000 元给李四，备注借款")
    assert d["tool_used"] == "transfer_money"
    assert d["requires_confirmation"] is True
    d2 = chat(client, sid, "确认")
    assert d2["requires_confirmation"] is False
    assert "转账成功" in d2["response"]


def test_schedule_transfer(client):
    d = chat(client, "t-sched", "明天转 200 元给李四")
    assert d["tool_used"] == "schedule_transfer"
    assert "定时转账" in d["response"]


def test_aa_collection(client):
    d = chat(client, "t-aa", "发起 AA 收款 300 元，备注团建")
    assert d["tool_used"] == "create_aa_collection"
    assert "AA 收款" in d["response"]


def test_bill_analysis(client):
    d = chat(client, "t-bill", "分析我上个月的账单")
    assert d["tool_used"] == "generate_report"
    assert d["response"]


def test_anomaly_detection(client):
    d = chat(client, "t-anomaly", "检测异常交易")
    assert d["tool_used"] == "detect_anomalies"
    assert d["response"]


def test_monthly_report(client):
    d = chat(client, "t-report", "生成月度账单报告")
    assert d["tool_used"] == "generate_report"
    assert "账单报告" in d["response"]


def test_wealth_recommend(client):
    d = chat(client, "t-wealth", "推荐一款稳健理财")
    assert d["tool_used"] == "recommend_products"
    assert d["response"]


def test_risk_assessment(client):
    d = chat(client, "t-risk", "评估我的风险等级")
    assert d["tool_used"] == "assess_risk"
    assert "R3" in d["response"]


def test_product_compare(client):
    d = chat(client, "t-compare", "对比理财产品")
    assert d["tool_used"] == "compare_products"
    assert "对比" in d["response"]


def test_card_loss_confirmation_flow(client):
    sid = "t-card"
    d = chat(client, sid, "帮我挂失尾号 8888 的卡")
    assert d["tool_used"] == "report_card_loss"
    assert d["requires_confirmation"] is True
    d2 = chat(client, sid, "确认")
    assert d2["requires_confirmation"] is False
    assert "挂失" in d2["response"]


def test_subscription_detect(client):
    d = chat(client, "t-subdetect", "识别我的订阅扣费")
    assert d["tool_used"] == "detect_subscriptions"
    assert d["response"]


def test_subscription_remind(client):
    d = chat(client, "t-subremind", "提醒我的续费")
    assert d["tool_used"] == "remind_renewals"
    assert d["response"]


def test_subscription_cancel_flow(client):
    sid = "t-subcancel"
    d = chat(client, sid, "取消腾讯视频订阅")
    assert d["tool_used"] == "cancel_subscription"
    assert d["requires_confirmation"] is True
    d2 = chat(client, sid, "确认")
    assert d2["requires_confirmation"] is False
    assert "取消" in d2["response"]


def test_cross_scenario_birthday(client):
    d = chat(client, "t-cross", "检测我爱人生日，锁定1000元")
    assert d["tool_used"] == "check_birthday_plan"
    assert "锁定" in d["response"]
