# 最终验收

以下结果以当前工作区实际命令为准。

```bash
python scripts/init_demo.py --all-merchants
python -m pytest -q
python -m compileall -q app agent skills tools rag scripts tests
uvicorn app.main:app --host 127.0.0.1 --port 8000
streamlit run app/ui/streamlit_app.py --server.port 8501
```

## 已验收能力

| 验收项 | 实际结果 |
| --- | --- |
| 商品/政策复合问答 | 通过：返回真实知识片段与文档/段落来源。 |
| 知识无答案和恶意资料 | 通过：拒绝臆测；恶意文本仅作引用数据。 |
| 合法订单、多轮追问、未知物流 | 通过：使用会话客户和工具结果，不推断送达时间。 |
| 不存在/他人订单 | 通过：明确提示或拒绝，且不泄露详情。 |
| 退款资格 | 通过：确定性规则返回资格、理由、版本；不执行退款。 |
| 多意图 | 通过：订单和退款分别处理。 |
| 人工升级 | 通过：明确请求、重复缺信息、连续工具失败均创建 Mock 工单。 |
| LLM/工具失败 | 通过：安全失败，没有虚假业务结果。 |
| 第二商家 | 通过：纸舟文具的独立配置、资料、数据、订单号格式和规则均可运行。 |
| Web Demo | 通过：FastAPI/Streamlit 可启动，快捷问题渲染聊天、引用和观察面板。 |

## 实际执行摘要

- `python scripts/init_demo.py --all-merchants`：通过；星选生活导入 5 份知识文档/21 个片段，纸舟文具导入 2 份知识文档/9 个片段。
- `python -m pytest -q`：**26 passed**；另有 FastAPI/Starlette 的第三方弃用警告。
- `python -m compileall -q app agent skills tools rag scripts tests`：通过。
- API 与 Streamlit 已实际启动并通过 health 检查。纸舟文具 API 多轮查询 `PH-2026-001` 成功；Streamlit 实际切换纸舟文具并展示其 `products.md` 来源。测试服务随后已停止。

完整命令输出和阶段范围见 [第五阶段验收](phase5_acceptance.md)。

