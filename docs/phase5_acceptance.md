# 第五阶段验收记录

第五阶段交付：第二商家替换验证、动态商家切换、商家接入/Skill Pack/最终验收文档，以及全量运行检查。

## 实际执行结果

```bash
python scripts/init_demo.py --all-merchants
python -m pytest -q
python -m compileall -q app agent skills tools rag scripts tests
```

- 初始化通过：
  - `paper_harbor`：2 商品、1 客户、2 订单、2 知识文档、1 故障样例；导入 9 个片段。
  - `star_select`：10 商品、3 客户、12 订单、5 知识文档、5 故障样例；导入 21 个片段。
- 自动化测试：**26 passed**。运行输出含 1 条 FastAPI/Starlette 的第三方弃用警告，不影响测试结果。
- Python 编译检查：通过。

## Web 与商家替换复验

实际启动了 FastAPI 和 Streamlit。两个 health 入口均返回正常。

- `/demo/merchants` 返回 `paper_harbor` 与 `star_select`。
- 创建纸舟文具客户 `PH-CUS-01` 会话后，“我的订单到哪了？”会追问；下一轮 `PH-2026-001` 成功返回速写中性笔订单。
- Streamlit 实际切换到纸舟文具，触发“商品＋退货政策”后展示纸舟文具的 `products.md` 资料来源和右侧执行轨迹。

API 与 Streamlit 测试服务均已停止。`.venv`、SQLite 数据库和 `.env` 均由 `.gitignore` 排除。

## 完成状态

MVP 的五个实施阶段均已完成。P1 限制保留在 README：PDF/向量 RAG、真实业务/人工服务连接器、生产认证与多租户、工作流编辑器及高并发部署均不在本次范围内。

