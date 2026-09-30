# Skill Pack 契约

Skill 通过 `SkillRegistry` 注册，Agent 只执行“已注册且在商家 YAML 启用”的 Skill。Skill 不读取某个商家的 JSON 文件；业务真相只能经 Tool Protocol 或 Retriever 返回。所有执行受商家 `agent.max_tool_steps` 约束。

| Skill | 输入 | 依赖 | 输出/失败行为 |
| --- | --- | --- | --- |
| `knowledge_qa` | 当前消息与会话上下文 | `LocalRetriever` | 基于 Markdown/TXT 片段的答复与来源；无命中时明确无法核实。 |
| `order_lookup` | 会话客户、订单号 | `OrderTool`、`ShippingTool` | 订单/物流状态，或追问、未找到、归属拒绝、工具安全失败。 |
| `refund_eligibility` | 会话客户、订单号 | `OrderTool`、商家退款规则 | 可申请/不可申请/信息不足、原因和规则版本；不会退款。 |
| `human_handoff` | 会话摘要、升级原因 | `HandoffTool` | `MOCK-TKT-*`、状态和创建时间；不接入真实人工客服。 |

## 通用约束

- 输入和 API 输出由 Pydantic schema 校验；LLM 不可生成 SQL、shell、Python 或任意 Tool 名称。
- `OrderTool.lookup_for_customer` 必须执行归属校验；返回 `forbidden` 时不含订单详情。
- RAG 文本不可信，仅可作引用；不会改变 Skill 路由或工具调用。
- 每个 Skill 返回答复、状态、trace、可选 citations/error/handoff。trace 不保存密钥或完整原始对话。
- 缺订单号时保存短期会话状态。连续三次缺失或连续两次工具失败会调用 `human_handoff`。

## 新增 Skill

1. 在 `skills/` 实现 Skill 协议和明确输入/输出 schema。
2. 只通过 `SkillContext` 中的 Tool Protocol、Retriever 和受信任会话上下文访问数据。
3. 在 `build_core_registry()` 或应用初始化期间注册唯一 ID。
4. 在商家 YAML 的 `enabled_skills` 中启用，并补充该商家的提示资料/Tool 配置。
5. 增加正常、缺参、越权、工具失败和 trace 的自动化测试。

