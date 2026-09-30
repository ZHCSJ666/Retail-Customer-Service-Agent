"""Interactive Streamlit Demo for the retail customer Agent.

Run from the project root after starting FastAPI:
    streamlit run app/ui/streamlit_app.py
"""

from __future__ import annotations

import os
from typing import Any

import streamlit as st

from app.ui.api_client import ApiClientError, RetailApiClient


DEFAULT_MERCHANT_ID = "star_select"
DEFAULT_API_BASE_URL = os.getenv("UI_API_BASE_URL", "http://127.0.0.1:8000")
STATUS_LABELS = {
    "completed": "已完成",
    "needs_info": "需要补充信息",
    "handed_off": "已转人工（模拟）",
    "failed": "执行失败",
}


def main() -> None:
    st.set_page_config(page_title="星选生活｜零售客服 Agent Demo", page_icon="🛍️", layout="wide")
    _initialize_state()
    st.title("🛍️ 零售客服 Agent Demo")
    st.caption("演示环境：商品、客户、订单、物流、知识库与人工工单均为模拟数据。")

    with st.sidebar:
        st.header("演示控制台")
        api_base_url = st.text_input("FastAPI 地址", value=st.session_state.api_base_url)
        if api_base_url != st.session_state.api_base_url:
            st.session_state.api_base_url = api_base_url
            _clear_local_session()
        try:
            api = RetailApiClient(st.session_state.api_base_url)
            health = api.health()
        except (ApiClientError, ValueError) as exc:
            st.error(str(exc))
            st.info("先启动 API：`uvicorn app.main:app --port 8000`")
            st.stop()

        mode = health["llm_mode"]
        st.success("API 已连接")
        st.caption(f"模型模式：{'Mock（稳定演示）' if mode == 'mock' else 'OpenAI-compatible'}")
        st.caption(f"SQLite：{'正常' if health['database_ready'] else '不可用'}")

        try:
            merchants = api.merchants()
        except ApiClientError as exc:
            st.error(str(exc))
            st.stop()
        if not merchants:
            st.error("当前没有可选模拟商家。")
            st.stop()
        merchant_map = {merchant["merchant_id"]: merchant for merchant in merchants}
        merchant_ids = list(merchant_map)
        merchant_index = merchant_ids.index(st.session_state.selected_merchant_id) if (
            st.session_state.selected_merchant_id in merchant_ids
        ) else 0
        merchant_id = st.selectbox(
            "模拟商家",
            options=merchant_ids,
            index=merchant_index,
            format_func=lambda value: merchant_map[value]["display_name"],
        )
        if merchant_id != st.session_state.selected_merchant_id:
            st.session_state.selected_merchant_id = merchant_id
            _clear_local_session(clear_merchant=False)
        st.caption(merchant_map[merchant_id]["demo_disclaimer"])

        try:
            customers = api.customers(merchant_id)
        except ApiClientError as exc:
            st.error(str(exc))
            st.stop()
        if not customers:
            st.error("当前商家没有可选模拟客户。")
            st.stop()

        customer_map = {customer["customer_id"]: customer["display_name"] for customer in customers}
        customer_ids = list(customer_map)
        initial_index = customer_ids.index(st.session_state.selected_customer_id) if (
            st.session_state.selected_customer_id in customer_ids
        ) else 0
        customer_id = st.selectbox(
            "模拟客户",
            options=customer_ids,
            index=initial_index,
            format_func=lambda value: f"{customer_map[value]}（{value}）",
        )
        _ensure_session(api, merchant_id, customer_id)

        if st.session_state.session_id:
            st.caption(f"会话：`{st.session_state.session_id[:8]}…`")
        session_buttons = st.columns(2)
        if session_buttons[0].button("新建会话", width="stretch"):
            _create_fresh_session(api, merchant_id, customer_id)
            st.rerun()
        if session_buttons[1].button("清空会话", width="stretch"):
            _reset_session(api)
            st.rerun()

        st.divider()
        st.subheader("该客户的模拟订单")
        try:
            orders = api.orders(merchant_id, customer_id)
        except ApiClientError as exc:
            st.error(str(exc))
            orders = []
        order_ids = ["（不预选订单）"] + [order["order_id"] for order in orders]
        selected_order_id = st.selectbox("订单", order_ids)
        if selected_order_id != "（不预选订单）":
            selected_order = next(order for order in orders if order["order_id"] == selected_order_id)
            st.caption(
                f"{selected_order['status']} · "
                f"{'无物流' if not selected_order['shipping_status'] else selected_order['shipping_status']}"
            )

        st.divider()
        st.subheader("快捷演示问题")
        quick_message = _quick_questions(selected_order_id)

    chat_column, observation_column = st.columns((1.15, 0.85), gap="large")
    with chat_column:
        st.subheader("客服对话")
        for record in st.session_state.chat_records:
            with st.chat_message(record["role"]):
                st.markdown(record["content"])
                if record.get("status"):
                    st.caption(f"状态：{STATUS_LABELS.get(record['status'], record['status'])}")

        typed_message = st.chat_input("例如：我的订单到哪了？")
        message = quick_message or typed_message
        if message:
            _submit_message(api, message)
            st.rerun()

    with observation_column:
        _render_observation_panel(st.session_state.latest_response)


def _initialize_state() -> None:
    defaults: dict[str, Any] = {
        "api_base_url": DEFAULT_API_BASE_URL,
        "selected_merchant_id": DEFAULT_MERCHANT_ID,
        "selected_customer_id": None,
        "session_id": None,
        "chat_records": [],
        "latest_response": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _clear_local_session(clear_merchant: bool = True) -> None:
    if clear_merchant:
        st.session_state.selected_merchant_id = DEFAULT_MERCHANT_ID
    st.session_state.selected_customer_id = None
    st.session_state.session_id = None
    st.session_state.chat_records = []
    st.session_state.latest_response = None


def _ensure_session(api: RetailApiClient, merchant_id: str, customer_id: str) -> None:
    if st.session_state.session_id and st.session_state.selected_customer_id == customer_id:
        return
    _create_fresh_session(api, merchant_id, customer_id)


def _create_fresh_session(api: RetailApiClient, merchant_id: str, customer_id: str) -> None:
    try:
        session = api.create_session(merchant_id, customer_id)
    except ApiClientError as exc:
        st.error(str(exc))
        st.stop()
    st.session_state.selected_customer_id = customer_id
    st.session_state.session_id = session["session_id"]
    st.session_state.chat_records = []
    st.session_state.latest_response = None


def _reset_session(api: RetailApiClient) -> None:
    session_id = st.session_state.session_id
    if not session_id:
        return
    try:
        api.reset_session(session_id)
    except ApiClientError as exc:
        st.error(str(exc))
        return
    st.session_state.chat_records = []
    st.session_state.latest_response = None


def _quick_questions(selected_order_id: str) -> str | None:
    question_groups = [
        ("商品＋退货政策", "这款耳机防水吗？买了多久能退？"),
        ("订单查询", "我的订单到哪了？"),
        ("退款资格", "这笔订单没发货，能退款吗？"),
        ("转人工", "我要人工客服"),
    ]
    if selected_order_id != "（不预选订单）":
        question_groups.insert(2, ("查询所选订单", f"查询订单 {selected_order_id} 到哪了？"))
    for index, (label, message) in enumerate(question_groups):
        if st.button(label, key=f"quick_question_{index}", width="stretch"):
            return message
    return None


def _submit_message(api: RetailApiClient, message: str) -> None:
    clean_message = message.strip()
    if not clean_message or not st.session_state.session_id:
        return
    st.session_state.chat_records.append({"role": "user", "content": clean_message})
    try:
        response = api.chat(st.session_state.session_id, clean_message)
    except ApiClientError as exc:
        error_text = str(exc)
        st.session_state.chat_records.append({"role": "assistant", "content": f"请求失败：{error_text}", "status": "failed"})
        st.session_state.latest_response = {"error": {"code": "API_UNAVAILABLE", "message": error_text}}
        return
    st.session_state.chat_records.append(
        {"role": "assistant", "content": response["answer"], "status": response["status"]}
    )
    st.session_state.latest_response = response


def _render_observation_panel(response: dict[str, Any] | None) -> None:
    st.subheader("执行观察")
    if not response:
        st.info("发送消息后，这里会显示 Agent 的真实执行轨迹、来源、规则和工单状态。")
        return

    error = response.get("error")
    if error:
        st.error(f"{error.get('code', 'ERROR')}：{error.get('message', '执行失败')}")
    handoff = response.get("handoff")
    if handoff:
        st.warning(
            f"模拟人工工单：{handoff['ticket_id']} · {handoff['status']}"
            f" · {handoff.get('created_at') or '时间未知'}"
        )

    st.markdown("#### 意图与参数")
    intents = response.get("intents", [])
    if intents:
        st.dataframe(
            [
                {
                    "意图": item["intent"],
                    "订单号": item.get("order_id") or "—",
                    "识别依据": item["rationale"],
                }
                for item in intents
            ],
            hide_index=True,
            width="stretch",
        )
    else:
        st.caption("本次没有可展示的已验证意图。")

    st.markdown("#### Skill 与工具轨迹")
    skills = response.get("used_skills", [])
    st.caption("执行的 Skill：" + (" → ".join(skills) if skills else "无"))
    trace = response.get("trace", [])
    if trace:
        st.dataframe(
            [
                {
                    "步骤": item["step"],
                    "动作": item["action"],
                    "状态": item["status"],
                    "摘要": item["summary"],
                    "错误码": item.get("error_code") or "—",
                }
                for item in trace
            ],
            hide_index=True,
            width="stretch",
        )
    else:
        st.caption("没有 trace。")

    rule_events = [item for item in trace if item["action"] == "deterministic_refund_rules.evaluate"]
    if rule_events:
        st.markdown("#### 退款规则依据")
        for event in rule_events:
            st.info(event["summary"])

    st.markdown("#### 知识来源")
    sources = response.get("sources", [])
    if not sources:
        st.caption("本次未使用知识库来源。")
    for source in sources:
        with st.expander(f"{source['filename']} · {source['paragraph_id']}"):
            st.caption(f"文档 ID：{source['document_id']}")
            st.code(source["excerpt"], language="markdown")


if __name__ == "__main__":
    main()
