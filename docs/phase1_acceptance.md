# 第一阶段验收记录

第一阶段交付：工程基础、商家配置、Mock 数据、SQLite 会话持久化、基础 FastAPI API 和自动化测试。

该阶段已完成；以下命令仍可复现基础工程验收。

```bash
python scripts/init_demo.py
python -m pytest -q
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

应检查：

- 初始化输出 10 件商品、3 名客户、12 笔订单、5 份知识文档和 5 个故障场景，且 SQLite ready。
- `/health` 返回 `ok`；`POST /sessions` 只允许已配置的模拟商家和存在的模拟客户。
- `GET /demo/orders` 仅返回所选模拟客户的订单摘要，不携带客户 ID。
- 新建、读取、重置会话可用，消息可持久化。
- 第二阶段之前，`POST /chat` 曾如实返回 `AGENT_NOT_ENABLED`；当前已由可执行的订单 Agent 替代，订单行为见第二阶段验收。
- `.env` 和 SQLite 文件受 `.gitignore` 保护。
