# 鉴权与商家隔离阶段验收

## 已完成

- `/v1` 路由支持 `FRAMEWORK_AUTH_MODE=disabled|api_key`；旧 Demo 路由不受影响。
- `api_key` 模式从 `FRAMEWORK_API_KEYS_JSON` 加载接入方、密钥和允许商家集合。
- 所有 `/v1` 路由均验证 Key；商家清单按范围过滤，创建会话、读取/重置会话、聊天、Skill 查询和配置预检均检查商家范围。
- `FrameworkManifest` 明示当前鉴权模式，但从不返回 Key 或配置中的密钥内容。
- 配置无 Key、格式错误、重复主体或重复 Key 会在应用启动时失败。

## 实际检查

```text
pytest -q tests/test_integration_security.py tests/test_configuration_and_fixtures.py => 5 passed
compileall app agent skills tools rag scripts tests => passed
```

跨商家测试使用两把测试 Key：无 Key 的 `/v1/framework` 返回 401；星选 Key 只能发现星选生活，访问纸舟商家/会话返回 403；纸舟 Key 可以创建纸舟会话并完成知识问答。

## 边界

- API Key 认证的是接入方，不替代终端用户登录、企业 SSO、RBAC、审计留存或完整生产多租户治理。
- Key 通过部署环境变量或密钥管理服务注入；不应提交 `.env`，也不应在浏览器前端保存 Key。
