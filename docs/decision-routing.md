# Laya 优先，Jev 备用

2026-10-12：聊天和 Studio 的决策入口统一使用 `decision_service`。默认首选本地 round07 Laya，云端 Jev 作为第二选项；主模型继续规划、生成和调用工具。

## 启动

本开发机另开终端启动 Laya：

```powershell
cd E:\AI\miniclaw
.\scripts\start-laya.ps1
```

然后正常启动项目：

```powershell
.\scripts\miniclaw.ps1 web
```

Laya 不必与项目一起启动；未启动时决策会使用 Jev。需在 `.hermes/.env` 保留 `TYPESAFE_API_KEY`（也兼容 `JEV_API_KEY`、`JEV_API`），不要把密钥写入代码或聊天。Laya 启动脚本默认依赖本机 D:/model 的运行环境、权重及已保存 gate；其他机器需迁移这些资源后修改脚本参数与对应双 pin。

冻结 gate 随源码提供在 `config/laya/round07-joint-gates.json`，保留原始字节以匹配双 pin；请勿因格式化或换行转换改变其 SHA256。微调权重和 GPU/Python 运行环境不随 Git 仓库分发，首次克隆后可先仅配置云端 Jev 运行项目，再单独准备本地 Laya。

## 回退规则

- 连接失败、3 秒超时、HTTP 非200、无效响应、checkpoint/gate 不匹配、不支持当前状态/问题合同：调用 Jev 一次。
- 意图没有被本地门槛接纳、且没有已接纳冲突：以 `local_intent_abstention` 回退 Jev；不会降低 Laya 门槛。
- Laya 已接纳 `unclear` 或 `conflict=present`：保留澄清，不让另一模型覆盖。被消费掩码停用的 target/scope/role 也不单独触发云回退。
- 本地故障后短暂冷却 5 秒，期间新请求直接用备用；随后新请求重新尝试 Laya。已有 ID 保持原结果，不因服务恢复改变结论。
- SQLite `decision_routes` 保存路由结果；同 scope/id 同输入复用，不同内容或版本拒绝。Jev 原有费用账本和预算继续生效，云端未知/中断不自动重发。
- 两个模型都不可用时返回原有不可用、预算耗尽或未知状态，由宿主主模型/澄清流程处理，不能伪造成功或绕过确认。

## 全项目路由与模型支持范围

所有项目中的 `JevDecisions` 生产构造入口已改为统一工厂；只有工厂内部保留 Jev 备用实例，以及显式 Jev 开关。实验脚本仍可直接构造两种 provider，用于无回退比较。

当前 round07 双 pin 校准覆盖正式聊天七问、0–4 候选对象及有限确认结构。Studio 的 action、operation_target、content_impact、noul 等问题没有对应训练/校准，统一路由会明确以 `unsupported_local_contract` 使用备用 Jev。**这意味着已全量切换首选路由，但不能宣称 Studio 的全部语义问题已经由 Laya 独立替代。** 该部分需要单独数据、训练、校准和实际流程验证，不能冒用七问门槛。

对象归属、真实选择、版本、局部位置、用户确认、工具参数和幂等执行继续由宿主验证。模型分数不授予写入许可；恢复已回答任务仍消费持久化状态。

## 配置与观察

`MINICLAW_DECISION_PROVIDER=laya` 为默认；设为 `jev` 可全局改回云端。聊天默认 `MINICLAW_CHAT_DECISION_PROVIDER=inherit`；可单独设 `jev`。显式 `laya` 仍使用有回退的服务。

默认 URL `http://127.0.0.1:8771`，只允许 loopback HTTP；`MINICLAW_LAYA_TIMEOUT` 默认3秒，范围大于0且不超过30。权重和 gate SHA256 默认固定 round07，可通过 `.env.example` 中的配置覆盖。修改配置后需重启项目；无效本地配置不会阻止启动，而会使用备用 Jev。

`GET /api/miniclaw/decision-runtime` 可读取首选/备选、双 pin、超时及备用是否配置；该接口只返回配置，不推断服务健康，也不调用模型。每次决策结果有 `provider`、`primary_provider`、`jev_fallback`、`fallback_reason` 和 `route_latency_ms`，不会返回密钥或原始网络错误。账本分别统计本地结果、回退请求和 Jev 费用；不能把回退后的结果全部归为 Laya 效果。
