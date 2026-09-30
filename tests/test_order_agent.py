from pathlib import Path

from fastapi.testclient import TestClient

from agent.contracts import ConversationState
from agent.model_adapter import ModelAdapterError
from app.core.config import MerchantCatalog
from app.core.database import SessionStore
from app.demo_data.repository import DemoDataRepository
from app.schemas.api import ChatStatus
from skills.base import SkillContext, ToolStepBudget
from skills.order_lookup import OrderLookupSkill
from tools.mock import MerchantToolSet, MockHandoffTool, MockOrderTool, MockProductTool, MockShippingTool


def create_session(client: TestClient, customer_id: str) -> str:
    response = client.post("/sessions", json={"customer_id": customer_id})
    assert response.status_code == 201
    return response.json()["session_id"]


def chat(client: TestClient, session_id: str, message: str) -> dict:
    response = client.post("/chat", json={"session_id": session_id, "message": message})
    assert response.status_code == 200
    return response.json()


def test_order_lookup_follows_up_then_uses_session_context(client: TestClient):
    session_id = create_session(client, "CUS-1001")

    first = chat(client, session_id, "我的订单到哪了？")
    second = chat(client, session_id, "SS-2026-10002")

    assert first["status"] == "needs_info"
    assert "请提供要查询的订单号" in first["answer"]
    assert second["status"] == "completed"
    assert second["used_skills"] == ["order_lookup"]
    assert "订单 SS-2026-10002 当前状态：运输中" in second["answer"]
    assert "星速配送" in second["answer"]
    assert "2026-09-26T18:00:00Z" in second["answer"]
    assert [event["step"] for event in second["trace"]] == list(range(1, len(second["trace"]) + 1))
    assert {event["action"] for event in second["trace"]} >= {
        "intent_extraction",
        "skill_router",
        "mock_order.lookup",
        "mock_shipping.lookup",
    }


def test_nonexistent_and_cross_customer_orders_do_not_return_data(client: TestClient):
    session_id = create_session(client, "CUS-1001")

    missing = chat(client, session_id, "查询 SS-2026-99999")
    foreign = chat(client, session_id, "查询 SS-2026-10005")  # CUS-1002 order

    assert missing["status"] == "completed"
    assert "未找到订单 SS-2026-99999" in missing["answer"]
    assert foreign["status"] == "completed"
    assert "无法查询该订单" in foreign["answer"]
    assert "便携榨汁杯" not in foreign["answer"]
    assert "CUS-1002" not in foreign["answer"]
    rejected = next(event for event in foreign["trace"] if event["action"] == "mock_order.ownership_check")
    assert rejected["error_code"] == "ORDER_ACCESS_DENIED"


def test_unknown_shipping_does_not_invent_delivery_time(client: TestClient):
    session_id = create_session(client, "CUS-1003")

    response = chat(client, session_id, "SS-2026-10010 的订单到哪了？")

    assert response["status"] == "completed"
    assert "物流信息暂缺" in response["answer"]
    assert "无法确认运输进度或预计送达时间" in response["answer"]
    assert "预计送达时间：" not in response["answer"]


def test_multi_intent_processes_order_and_deterministic_refund_eligibility(client: TestClient):
    session_id = create_session(client, "CUS-1001")

    response = chat(client, session_id, "SS-2026-10001 为什么还没发货？能退款吗？")

    assert response["status"] == "completed"
    assert response["used_skills"] == ["order_lookup", "refund_eligibility"]
    assert "当前状态：待发货" in response["answer"]
    assert "退款申请资格：可申请" in response["answer"]
    assert "不会执行退款" in response["answer"]
    assert any(event["action"] == "deterministic_refund_rules.evaluate" for event in response["trace"])


def test_model_failure_returns_safe_failure_without_business_tools(client: TestClient):
    class FailingModel:
        def extract_intents(self, **_kwargs):
            raise ModelAdapterError("simulated provider outage")

    client.app.state.container.agent.intent_model = FailingModel()
    session_id = create_session(client, "CUS-1001")

    response = chat(client, session_id, "SS-2026-10001 到哪了？")

    assert response["status"] == "failed"
    assert response["used_skills"] == []
    assert response["error"]["code"] == "MODEL_UNAVAILABLE"
    assert response["trace"][0]["action"] == "intent_extraction"
    assert "订单 SS-2026-10001 当前状态" not in response["answer"]


def test_reset_clears_pending_order_slot(client: TestClient):
    session_id = create_session(client, "CUS-1001")
    assert chat(client, session_id, "我的订单到哪了？")["status"] == "needs_info"

    assert client.post(f"/sessions/{session_id}/reset").status_code == 200
    response = chat(client, session_id, "你好")

    assert response["status"] == "needs_info"
    assert response["used_skills"] == []
    assert "订单号" not in response["answer"]


def test_tool_timeout_has_safe_failed_result_without_order_data(tmp_path: Path):
    catalog = MerchantCatalog()
    merchant = catalog.get("star_select")
    repository = DemoDataRepository(catalog)
    faulted_tools = MerchantToolSet(
        product=MockProductTool(repository, "star_select"),
        order=MockOrderTool(repository, "star_select", fault_mode="timeout"),
        shipping=MockShippingTool(),
        handoff=MockHandoffTool(SessionStore(tmp_path / "sessions.db"), "star_select"),
    )

    result = OrderLookupSkill().execute(
        SkillContext(
            merchant=merchant,
            session_id="session-test",
            customer_id="CUS-1001",
            tools=faulted_tools,
            state=ConversationState(),
            tool_budget=ToolStepBudget(4),
            retriever=None,  # Order Skill does not access the retriever.
            message="SS-2026-10001",
            conversation_summary="test",
        ),
        order_id="SS-2026-10001",
    )

    assert result.status == ChatStatus.FAILED
    assert result.error is not None and result.error.code == "TOOL_TIMEOUT"
    assert "待发货" not in result.answer
    assert result.trace[-1].error_code == "TOOL_TIMEOUT"
