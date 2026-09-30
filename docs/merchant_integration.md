# 商家接入指南

本项目通过商家 YAML、知识资料、业务 fixture/适配器和规则替换商家，不修改 Agent 编排逻辑。`configs/merchants/paper_harbor.yaml` 是最小可运行参考。

## 接入步骤

1. 复制一份 `configs/merchants/*.yaml`，设置唯一、小写的 `merchant_id`、显示名、免责声明和 `order_id_pattern`。
2. 指向商家专属的 Prompt、`knowledge_dir`、商品/客户/订单/故障 JSON 路径，并在 `demo_requirements` 写明该演示资料的最小数量和要求覆盖的订单状态。
3. 写入 `refund_rules`、启用的 Skills、最大工具步数和 Tool adapter 名称。`mock` 与 `fixture_mock` 是内置本地 fixture adapter；它们遵循相同 Tool Protocol。
4. 放入 Markdown/TXT 知识资料。启动或运行 `init_demo.py` 时，系统会切分、存储并建立 FTS5 索引。
5. 运行 `python scripts/init_demo.py --merchant <merchant_id>`，再运行 `python -m pytest -q`。
6. 启动 API 和 Streamlit，从“模拟商家”选择该商家，完成知识、订单、退款和人工场景验证。

## 接真实订单系统

为每类业务实现 `tools/protocols.py` 中的 `OrderTool`、`ShippingTool`、`ProductTool` 或 `HandoffTool`，再由宿主通过 `ToolAdapterRegistry` 显式注册名称。适配器必须：

- 只接受 Agent 传入的受信任会话客户 ID；不得把消息内客户 ID 当认证。
- 对订单归属校验失败只返回 `forbidden`，不泄露详情。
- 将网络超时和上游异常转换为 `ToolTimeout` 或 `ToolFailure`。
- 在适配器工厂中注册名称，然后在商家 YAML 的 `tool_adapters` 选择该名称；YAML 不会动态导入代码，未注册名称会在启动时失败。

这类替换局限在工具适配层；Skill 和 Agent Orchestrator 不需要知道商家数据格式或 HTTP API。外部调用、配置预检和完整注册示例见[框架接入指南](framework_integration.md)。

## 验证第二商家

纸舟文具使用 `PH-\d{4}-\d{3}` 订单号、不同资料和 14 天退货窗口。自动化测试创建其会话，检索“这支笔防水吗？”，再以 `PH-2026-001` 完成多轮订单查询，证明核心 Agent 代码未绑定星选生活。
