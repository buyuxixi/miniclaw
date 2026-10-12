# Chat 重试、兜底、超时与失败提示

2026-10-10 实现。通用机制在 `miniclaw_web/chat_recovery.py`，业务场景通过只读性、错误类型、凭据和任务预算选择策略；执行继续使用唯一 Hermes Agent 循环。托管适配入口是 `hermes_clarification_adapter.py` / `clarification_routes.py`。固定上游提交上的 v1 澄清补丁之后安装 v2 恢复补丁，启动检查兼容版本 2。

## 场景策略

| 场景 | 处理 |
| --- | --- |
| 模型网络超时、限流、5xx | 单服务、单模型步骤最多 3 次请求，即初次加 2 次重试；指数退避与抖动，遵守 Retry-After。等待过长时尝试备用或停止，不截短服务端要求的等待后重发 |
| 余额 / 额度不足、鉴权或模型不可用 | 不重复请求同服务，尝试已配置备用；两家均不可用则明确停止 |
| 一般参数错误、安全策略拒绝、证书验证错误 | 停止。Hermes 已有的特定协议修正、上下文压缩仍保留，后续主模型请求受相同预算约束 |
| 已向用户显示文字后流式中断 | 保留并持久化部分文字，停止自动重新生成；未完整接收的工具调用不执行 |
| 明确只读工具临时失败 | 默认初次加 1 次重试；权限、参数、文件不存在等永久错误不重试 |
| 写入、收费工具 | 不自动重放。沿用任务 + 语义参数 + 来源版本回执：成功复用结果；超时、异常、未知或不可解析回执先核对 |
| 画布方案保存 | 虽属业务上的“建议”，实际会写入方案，因此不套用只读重试 |
| 取消 / 任务超时 / 预算耗尽 | 停止等待和新增调用。取消本地等待不代表供应商已取消或不会计费 |
| 工具轮数耗尽 | 本地说明未完成并保留已有步骤，不额外调用模型总结来绕过预算 |
| 断线 / 重连 | 恢复后端权威会话、部分回复和错误提示，不自动重发用户消息 |

重试与降级状态使用现有 `status.update`；终止说明使用 `message.complete` / 既有错误描述。前端负责显示和保留文字，不自行调度模型或工具重试。备用模型继续遵守原工具和业务权限。

## 当前本地配置

主服务保持 DeepSeek `deepseek-flash`，备用是百炼 `qwen-plus`（OpenAI 兼容接口，中国内地）。Key 只从 `DEEPSEEK_API_KEY` / `DASHSCOPE_API_KEY` 读取；备用条目使用 `key_env`，不会在配置里复制 Key。缺少声明的备用 Key 时跳过该备用，避免底层改读其他服务的通用凭据。

`scripts/miniclaw.ps1 prepare` 只补缺失项，保留已有主模型、恢复参数及备用链；显式 `fallback_providers: []` 会关闭备用。已有图片端点不修改。新安装的备用端点可通过 `MINICLAW_CHAT_FALLBACK_BASE_URL` 指定，安装后改 `config.yaml` 的对应备用条目即可。

```yaml
fallback_providers:
  - provider: custom
    model: qwen-plus
    base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
    key_env: DASHSCOPE_API_KEY
    api_mode: chat_completions
miniclaw:
  chat_recovery:
    model_attempts: 3
    tool_attempts: 2
    max_model_requests: 24
    max_recovery_attempts: 6
    max_reserved_tokens: 240000
    max_output_tokens: 4096
    request_timeout_seconds: 60
    task_timeout_seconds: 180
    backoff_seconds: 1
    max_backoff_seconds: 15
```

预算存储在 `miniclaw.sqlite3` 的 `chat_recovery_budget`，按任务 ID 累计；模型失败、备用切换和只读工具重试共同计入恢复次数。澄清回答后继续原任务不会清零；等待用户回答不计活跃执行时间。`max_recovery_attempts: 0` 可关闭自动重试和备用切换。

60 秒是网络读取 / 空闲超时，连接最多等待 10 秒；连续到达的流式数据仍可能超过 60 秒。180 秒任务活跃时间上限通过 Agent 中断阻止继续调用，回收连接、线程及结果保存可能另需短暂时间。远端已接收的写入或生成不会因此得到“确定取消”的保证。

成本控制采用主模型请求数、单次输出上限和文本输入的保守 UTF-8 字节预留；失败和未知请求不退还预留。它限制调用规模，**不是供应商精确 Token 计量或人民币账单硬上限**。图片输入 Token、上下文压缩等辅助模型调用，以及独立图像 / 视频生成，仍由各自预算和回执负责；后续若设人民币上限，需要明确模型价格、缓存/思考计费和账单核对规则。

## 验证

应用层测试使用临时 HERMES_HOME、真实 Hermes / OpenAI SDK / SQLite 和本地假 HTTP，覆盖非流式/流式重试、主备切换和恢复、凭据隔离、网络超时、实际任务中断、预算跨续跑、未知写回执、部分文字落库、并发预算预留和补丁安装。

后端恢复 / 澄清 / 补丁测试 54 项通过，前端全套 338 项、类型检查、生产构建通过。真实服务仅做最小接通与工具调用格式烟测：DeepSeek / 百炼各两次 HTTP 200，共报告 503 Token；测试工具未执行，不提交图片、视频或其他写入。未通过耗尽真实账户来验证余额错误，故障通过假 HTTP 注入。

上游相关回归首次 66 项通过；5 个 Anthropic 专属测试在构造 Agent 时因当前环境缺少可选 `anthropic` SDK 失败，与本次 DeepSeek / 百炼请求链无关，未为此改变项目依赖。

参考：[百炼 OpenAI 兼容接口与地域说明](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)、[DeepSeek API 文档](https://api-docs.deepseek.com/)。当前中国内地兼容端点经真实调用验证；变更地域时同时核对 Key 和端点。
