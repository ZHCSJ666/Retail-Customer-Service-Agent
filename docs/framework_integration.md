# 框架接入指南（v1）

本项目是框架加 Demo：商家 YAML 选择能力，宿主程序注册业务适配器，外部业务系统通过 `/v1` 调用对话。Demo 的 JSON 与 Mock 仅是内置适配器实现。

## 外部调用

先查看 `GET /v1/framework`，它列出版本化对话接口、已注册适配器和身份边界；再用以下接口：

| 接口 | 用途 |
| --- | --- |
| `GET /v1/merchants` | 发现已加载商家的 Skill、订单号格式和适配器选择。 |
| `POST /v1/sessions` | 由可信宿主传入 `merchant_id`、已认证的 `customer_id`，创建会话。 |
| `POST /v1/chat` | 发送 `session_id` 与消息，获得答复、Skill、引用、trace、错误或工单。 |
| `GET /v1/sessions/{session_id}` / `POST .../reset` | 读取或重置会话。 |
| `GET /v1/skills` | 查看某商家声明和启用的 Skill。 |

### 启用接入方 API Key

本地 Demo 默认 `FRAMEWORK_AUTH_MODE=disabled`。部署时设置 `FRAMEWORK_AUTH_MODE=api_key`，并把密钥仅放在部署环境变量中：

```dotenv
FRAMEWORK_API_KEYS_JSON=[{"principal_id":"partner_app","api_key":"从密钥库注入的至少16位随机值","merchant_ids":["star_select"]}]
```

调用方在每个 `/v1` 请求中发送 `X-Framework-Api-Key`。Key 只能查看、创建和访问其 `merchant_ids` 中的商家会话；越权商家和会话返回 `403 MERCHANT_ACCESS_DENIED`，缺失或错误 Key 返回 `401`。密钥不会出现在 manifest、trace、日志或响应中；轮换密钥后重启应用加载新环境变量。

`customer_id` 是宿主完成认证后传入的可信上下文；不得从用户聊天文本提取身份。API Key 认证的是接入方而非终端用户，MVP 仍未提供企业 SSO、终端用户身份体系或完整生产多租户网关。

## 接入业务适配器

实现 `tools/protocols.py` 中对应的 `ProductTool`、`OrderTool`、`ShippingTool` 或 `HandoffTool`，然后由宿主程序显式注册。YAML 只能引用已注册的名称，不能加载 Python 模块或任意代码。

```python
from app.main import create_app
from tools.registry import build_default_tool_adapter_registry

adapters = build_default_tool_adapter_registry()
adapters.register(
    tool_kind="order",
    adapter_id="acme_oms",
    description="Acme OMS read-only adapter",
    factory=lambda context: AcmeOrderAdapter(context.merchant, context.sessions),
)
app = create_app(tool_adapters=adapters)
```

在商家 YAML 中把 `tool_adapters.order` 设为 `acme_oms`。若适配器未注册、缺少方法或配置名称错误，应用会在启动时失败，不会静默回退到 Mock。

`OrderTool` 必须用传入的可信客户上下文校验归属；上游超时/异常必须转换为 `ToolTimeout` 或 `ToolFailure`；退款 Skill 只做资格判断，不执行支付或取消订单。

## 配置预检

调用 `POST /v1/framework/merchant-config/validate`，请求体为：

```json
{"merchant_config": {"...": "与 merchant YAML 相同的完整 JSON 配置"}}
```

它校验配置 schema、未知 Skill 和当前宿主未注册的适配器；不写文件、不加载路径、不注册商家，也不执行任何业务操作。预检通过后，仍需将受审核的 YAML、知识资料和适配器部署到宿主进程，并运行 `python scripts/init_demo.py --merchant <merchant_id>`。

## 接入顺序

1. 实现并测试业务适配器。
2. 在宿主应用显式注册适配器。
3. 用预检接口校验完整商家配置。
4. 部署 YAML、Prompt 和知识资料，重启应用。
5. 调用 `/v1/sessions` 与 `/v1/chat` 验证真实链路和 trace。
