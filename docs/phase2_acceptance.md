# 第二阶段验收记录

第二阶段交付：结构化意图适配、Skill Registry、短期会话状态、最大工具步数、订单/物流 Tool Protocol 与 Mock 适配器，以及 `order_lookup` 多轮链路。

复现命令：

```bash
python scripts/init_demo.py
python -m pytest -q
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

本阶段实际运行了初始化、编译检查和 pytest；pytest 结果为 **14 passed**（运行时另有 FastAPI/Starlette 的第三方弃用警告）。

已覆盖的验收点：

- “我的订单到哪了？”返回 `needs_info`，下一轮仅给订单号仍能查询，说明会话状态实际生效。
- 合法订单返回 fixture 中的状态、商品、物流与存在时的预计时间。
- 不存在订单有明确提示；查询其他客户订单只返回拒绝信息，trace 标记 `ORDER_ACCESS_DENIED`，不泄露订单详情。
- 未知物流不会声称有送达时间。
- 在第二阶段结束时，同一消息的订单与退款意图会被识别；订单执行，退款 Skill 当时尚未实现。第三阶段已补上退款资格判断。
- 模型不可用和模拟工具超时返回失败状态及安全错误码，不伪造订单结果。
- `/sessions/{session_id}/reset` 会清除正在等待订单号的状态。

第二阶段结束时尚未验收为已完成的能力是 RAG 引用、退款资格规则、人工工单、第二商家和 Streamlit UI；前三项已在第三阶段完成。
