# 架构说明（当前：框架接入阶段）

当前项目是单体 Python 服务。Streamlit Demo 通过 HTTP 调用 FastAPI；`app/main.py` 创建 API 应用；`AppContainer` 组装配置、数据仓库、会话库、RAG 索引、模型适配器、Skill Registry 和 Agent 编排器。没有微服务、消息队列或动态代码执行。

```text
Streamlit Demo
  └─ RetailApiClient ──> HTTP API

HTTP API
  ├─ /v1 Framework API ──> 外部宿主的版本化会话/聊天/能力发现
  ├─ MerchantCatalog ──> 多份 YAML + Prompt + fixture paths + order ID pattern
  ├─ DemoDataRepository ──> products / customers / orders JSON
  ├─ SessionStore ──> SQLite sessions + messages + state + mock tickets
  ├─ SQLiteRagStore ──> Markdown/TXT chunks + FTS5 + citations
  └─ AgentOrchestrator
       ├─ StructuredIntentModel (Mock / OpenAI-compatible)
       ├─ SkillRegistry ──> knowledge / order / refund / handoff
       └─ Tool Protocols ──> ToolAdapterRegistry ──> Mock 或宿主注册的 Product / Order / Shipping / Handoff adapters
```

商家资料只能经 YAML 中的固定路径加载，用户输入不能指定文件路径。创建会话时先验证模拟客户存在；订单工具从会话客户取得可信 Demo 上下文，而不是信任聊天文本中的客户 ID。每个商家声明自己的订单号正则，Agent 从配置读取，不再硬编码星选生活格式。`MockOrderTool` 即使找到订单，也会先比较归属；不匹配时只返回 `forbidden`，不返回订单对象或所有者信息。

SQLite 保存会话元数据、消息和少量路由状态（例如是否正在等待订单号），也保存模拟人工工单。它不保存 API 密钥或 trace。重置会话会清除消息与路由状态。运行中的每个 trace 直接随 `/chat` 响应返回，记录意图提取、路由、工具结果和安全失败状态。

`SQLiteRagStore` 将受配置约束的 Markdown/TXT 按段落切分，持久化文档 ID、文件名、段落 ID 和原文，并建立 FTS5 索引。检索回答的每个来源都能映射回该片段。文档从不作为系统提示、代码、SQL 或工具参数执行；RAG 无命中时 `knowledge_qa` 返回无法核实而不臆测。

模型适配器只能输出经 Pydantic 校验的有限意图和订单号 schema。Mock 模式只用于稳定地生成该结构化计划；它不会生成最终业务答复。OpenAI-compatible 模式会设置超时、有限重试和 JSON 验证，失败后返回安全的 `MODEL_UNAVAILABLE`。执行器还在商家 YAML 中限制最大工具步数，绝不执行模型生成的 SQL、shell 或 Python。

`refund_eligibility` 仅调用已授权订单工具和商家 YAML 的确定性规则；返回资格、理由与规则版本，不含任何退款执行路径。`human_handoff` 经 Tool Protocol 创建本地 Mock 工单，并保存摘要、原因、时间和工单 ID。四个核心 Skill 都已注册为 `active`。

Streamlit 不包含 Agent、RAG 或业务规则副本。它只保留浏览器会话中的聊天显示状态，并读取 `/health`、`/demo/merchants`、`/demo/customers`、`/demo/orders`、会话接口和 `/chat`。为让 UI 准确展示意图和参数，`POST /chat` 响应包含经模型 schema 校验后的 `intents` 字段；执行细节仍以 `trace` 为准。

`star_select.yaml` 是完整验收商家；`paper_harbor.yaml` 是独立的极简替换实例，拥有自己的订单号格式、知识资料、Mock 数据、退款规则和 `fixture_mock` 适配器配置。两者共用同一个 Agent/Skill/RAG/Tool Protocol 工作流。

框架对外提供版本化 `/v1` 会话和聊天接口，以及 `/v1/framework`、`/v1/merchants` 的能力发现。`FRAMEWORK_AUTH_MODE=api_key` 时，`/v1` 全部路由要求 `X-Framework-Api-Key`，并按 Key 配置的商家集合过滤发现结果和会话访问；默认 `disabled` 仅用于本地 Demo。外部宿主仍须在创建会话前完成终端用户认证，并把可信客户上下文传给框架；MVP 不把 `customer_id` 误称为生产认证。`ToolAdapterRegistry` 是唯一的业务适配扩展点：宿主 Python 代码显式注册适配器工厂，商家 YAML 只能选择注册名称；不存在远程配置执行、动态导入或静默 Mock 回退。`POST /v1/framework/merchant-config/validate` 只做 YAML 等价 JSON 的 schema/Skill/适配器预检，不会写入配置或加载文件。
