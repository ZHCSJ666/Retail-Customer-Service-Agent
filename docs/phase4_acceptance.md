# 第四阶段验收记录

第四阶段交付：Streamlit Web Demo、FastAPI HTTP 客户端、API 意图/参数展示字段，以及 Demo 启动与可观察性说明。

启动命令：

```bash
python scripts/init_demo.py
uvicorn app.main:app --host 127.0.0.1 --port 8000
streamlit run app/ui/streamlit_app.py --server.port 8501
```

Demo 页面应提供：

- 左侧聊天、快捷演示问题、模拟客户/订单选择以及新建/清空会话。
- 右侧真实意图/参数、Skill 顺序、trace、原文引用、退款规则依据、错误和模拟工单状态。
- Mock/真实模型模式与模拟数据边界标识。

自动化验收覆盖 API 返回 `intents`、Streamlit HTTP 客户端的 query/payload 编码和安全 HTTP 错误信息。实际 pytest 结果为 **23 passed**（另有 FastAPI/Starlette 的第三方弃用警告）。

端到端验收实际启动了 API 与 Streamlit：两个 health 入口均可访问。随后通过 Streamlit 测试运行器点击“商品＋退货政策”快捷问题，确认页面出现 2 条聊天记录、真实商品/退货来源展开项，以及右侧“意图与参数”和“Skill 与工具轨迹”区域。测试服务已停止。

UI 不生成或伪造 Agent 答复。若 API 不可用，页面会清晰显示连接错误；若 API 返回失败或转人工，右侧会原样展示错误码或 Mock 工单。
