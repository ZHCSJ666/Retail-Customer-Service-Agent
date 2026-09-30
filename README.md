# 可配置零售客服 Agent 框架

这是“星选生活（Star Select）”虚构商家的零售客服 Agent MVP。当前已完成基础工程、订单查询、可追溯知识问答、确定性退款资格判断与模拟人工升级：可配置商家数据、SQLite 会话、结构化意图路由、可替换业务工具协议和本地 RAG。

四个核心 Skill 均可执行：`knowledge_qa`、`order_lookup`、`refund_eligibility` 和 `human_handoff`。项目包含 Streamlit Demo、HTTP-only 人工验收页，以及第二个独立商家验证样例。

所有示例中的商品、客户、订单、物流与工单都是模拟数据。本项目不提供真实身份认证、真实退款、真实人工客服接线或生产多租户能力。

## 快速启动

要求 Python 3.11+。在项目根目录执行：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
python scripts/init_demo.py --all-merchants
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

API 文档位于 <http://127.0.0.1:8000/docs>。默认 `LLM_MODE=mock`：它只产生经 Pydantic 校验的意图/订单号提取计划，订单和物流答复始终来自 Mock 业务工具。使用 OpenAI-compatible Chat Completions 时，在 `.env` 设置 `LLM_MODE=openai_compatible`、`LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`、`LLM_TIMEOUT` 和可选的 `LLM_MAX_RETRIES`；不要提交 `.env`。

真实模型的结构化输出解析失败、超时或调用失败会在有限重试后返回 `MODEL_UNAVAILABLE`，且不会调用业务工具或伪造结果。

在另一个终端启动 Web Demo：

```bash
source .venv/bin/activate
streamlit run app/ui/streamlit_app.py --server.port 8501
```

打开 <http://127.0.0.1:8501>。如 API 不在默认地址，设置 `UI_API_BASE_URL=http://host:port` 后再启动 Streamlit，或在 Demo 侧栏直接修改地址。

若当前开发环境的端口预览无法渲染 Streamlit（通常是 WebSocket 代理不兼容），可直接用 FastAPI 提供的 HTTP-only 人工验收页：<http://127.0.0.1:8000/demo-ui>。该页面调用相同的会话、Agent、工具、知识库和 trace API；它只是不依赖 Streamlit WebSocket，不替代 Streamlit Demo。

## 当前 API

| 接口 | 当前作用 |
| --- | --- |
| `GET /health` | 检查 API、SQLite 和模型模式。 |
| `POST /sessions` | 用商家 ID 与模拟客户创建会话。 |
| `GET /sessions/{session_id}` | 读取会话及已记录的消息。 |
| `POST /sessions/{session_id}/reset` | 清空该会话消息。 |
| `GET /skills` | 查看商家启用的 Skill 契约和实际状态；四个核心 Skill 当前均为 `active`。 |
| `GET /demo/merchants` | 获取可在 Demo 中切换的模拟商家。 |
| `GET /demo/customers` | 获取 Demo 客户选择项。 |
| `GET /demo/orders` | 获取所选 Demo 客户的订单摘要。 |
| `POST /chat` | 执行已注册的 Agent/Skill；支持知识引用、订单追问、退款资格和人工升级。 |

## 框架接入（v1）

除 Demo 接口外，框架提供稳定的 `/v1` 调用面：`GET /v1/framework` 用于发现能力，`GET /v1/merchants` 查看商家能力，`POST /v1/sessions` 创建宿主认证后的会话，`POST /v1/chat` 执行对话；会话读取、重置和 Skill 查询也提供对应的 `/v1` 路由。`POST /v1/framework/merchant-config/validate` 可预检 YAML 等价 JSON 配置，但不会写入配置或执行代码。

业务系统通过 `ToolAdapterRegistry` 在宿主 Python 进程显式注册订单、物流、商品或工单适配器；YAML 只能选择已注册名称。完整接口、适配器示例和身份边界见[框架接入指南](docs/framework_integration.md)。

本地 Demo 保持 `FRAMEWORK_AUTH_MODE=disabled`。部署框架给外部系统时应启用 `FRAMEWORK_AUTH_MODE=api_key`，用 `FRAMEWORK_API_KEYS_JSON` 从密钥管理服务注入接入方 Key 和允许的商家范围；所有 `/v1` 请求需发送 `X-Framework-Api-Key`。这认证的是接入方，不替代终端用户认证。详见[框架接入指南](docs/framework_integration.md)与[鉴权验收](docs/security_acceptance.md)。

示例：

```bash
curl -X POST http://127.0.0.1:8000/sessions \
  -H 'content-type: application/json' \
  -d '{"merchant_id":"star_select","customer_id":"CUS-1001"}'
```

模拟客户选择只用于 Demo 上下文，不是生产认证。订单工具从会话中读取客户并校验订单归属；绝不会直接信任聊天文本中的 `customer_id`。若查询他人订单，响应不含订单详情、商品或真实归属客户。

## 已实现的订单对话

1. 发送“我的订单到哪了？”会返回 `needs_info` 并追问订单号。
2. 下一轮只发送 `SS-2026-10002`，会延续同一会话并返回该模拟客户的真实订单/物流数据。
3. 不存在订单会明确提示；其他模拟客户的订单会被拒绝；物流资料缺失时不会推断送达日期。

每个响应都含真实的 `trace`：意图提取、Skill 路由、订单归属校验、物流工具调用以及失败/跳过状态。Trace 不输出模型密钥或完整用户原始消息。

## Streamlit Demo

Demo 左侧提供聊天记录、模拟商家/客户和该客户订单选择、快捷演示问题，以及新建/清空会话。右侧只展示 API 实际返回的：意图/参数、Skill 顺序、工具 trace、知识引用、退款规则依据、错误和模拟人工工单。

界面会清楚标记 Mock/真实模型模式及模拟数据边界。它不会以动画或预设回答冒充工具执行结果。

> 演示截图占位：启动 API 和 Streamlit 后，使用“商品＋退货政策”快捷问题，截取左侧回答与右侧“知识来源”展开区；使用“退款资格”并补充订单号，截取规则依据与 trace 区。

## 切换或接入商家

项目附带两个可运行商家：星选生活（完整验收样例）和纸舟文具（极简替换样例）。在 Web Demo 的“模拟商家”下拉框切换即可；不需要改 Agent 编排代码。

命令行单独验证第二商家：

```bash
python scripts/init_demo.py --merchant paper_harbor
```

同时导入并校验所有配置商家：

```bash
python scripts/init_demo.py --all-merchants
```

新商家的配置、数据、适配器和新增 Skill 步骤见 [商家接入指南](docs/merchant_integration.md) 与 [Skill Pack](docs/skill_pack.md)。

## 知识、退款与人工升级

- 启动时会把商家 YAML 指向的 Markdown/TXT 文档切分并导入 SQLite FTS5；每条 `sources` 都包含真实的文档 ID、文件名、段落 ID 和原文片段。检索不到资料时会明确说明无法核实，不会猜测。
- 知识库文本是不可信数据，只作为可引用材料；其中的“忽略之前指令”等内容不会影响路由、工具或规则执行。
- `refund_eligibility` 先使用会话客户校验订单归属，再依 YAML 的规则版本判断“可申请 / 不可申请 / 信息不足”。它绝不会执行退款、取消订单或支付退回。
- 明确要求人工、连续三次缺少订单号，或连续两次业务工具失败时，会创建本地 `MOCK-TKT-*` 工单。工单保存摘要、原因和时间，但不连接真实人工客服。

## 验证

```bash
python scripts/init_demo.py
python -m pytest -q
```

## 已知限制与 P1

- 当前是本地 Demo：Mock 身份选择不是生产认证，Mock 工单不连接真人客服。
- RAG 只支持 Markdown/TXT 和 SQLite FTS5；PDF、向量检索、重排序属于 P1。
- 当前没有真实退款/取消订单、企业认证、多租户、高并发部署或工作流编辑器。
- HTTP 业务适配器和真实模型已留好协议边界，但未提供生产连接器。

模块边界和验收记录见 [架构说明](docs/architecture.md)、[项目展示操作清单](docs/demo_showcase.md)、[框架接入指南](docs/framework_integration.md)、[Skill Pack](docs/skill_pack.md)、[商家接入指南](docs/merchant_integration.md)、[最终验收](docs/acceptance.md)、[第五阶段验收](docs/phase5_acceptance.md)、[框架接入阶段验收](docs/framework_acceptance.md)、[鉴权验收](docs/security_acceptance.md) 及各阶段验收记录。
