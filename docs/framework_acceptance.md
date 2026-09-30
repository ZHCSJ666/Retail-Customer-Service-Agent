# 框架接入阶段验收

## 已完成

- `ToolAdapterRegistry`：按 product/order/shipping/handoff 协议注册适配器；商家配置只能选择已注册名称。
- 内置 `mock`、`fixture_mock` 仍可运行；Skill 与 Agent 不再依赖 Mock 具体类型。
- `/v1`：版本化健康检查、会话、聊天、会话读取/重置、Skill 查询，以及框架/商家能力发现。
- `POST /v1/framework/merchant-config/validate`：只校验、不写入的商家配置预检。
- `create_app(tool_adapters=...)`：宿主可注入自定义适配器，无需修改 Agent 编排或 Skill 实现。

## 实际检查

```text
pytest -q tests/test_framework_integration.py  => 2 passed
pytest -q => 29 passed, 1 third-party deprecation warning
compileall app agent skills tools rag scripts tests => passed
```

另已对运行中的 `8010` 服务实际调用 `/v1/framework`、`/v1/sessions` 和 `/v1/chat`：返回 `v1` manifest，创建纸舟文具会话成功，知识问答返回 `knowledge_qa` 与真实引用。

测试覆盖：`/v1` 会话和聊天调用、框架能力发现、配置预检失败信息，以及自定义 `recording_oms` 订单适配器被 Agent 实际调用。

## 边界

- 未实现动态远程代码安装、运行时写入商家配置、企业认证或生产多租户。
- 真实 OMS/CRM/物流系统由接入方按 Tool Protocol 实现；本仓库继续提供可复现的 Mock Demo。
