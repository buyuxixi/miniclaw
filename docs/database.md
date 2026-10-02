# miniclaw 数据库说明

核对日期：2026-10-02。依据固定 Hermes 提交 `f97608f178d1ffeca59860195ab7da295f7c8e5f` 的建表、写入与恢复代码，以及本机 SQLite 的只读结构检查。本文不包含聊天内容、Key 或完整模型请求。

## 谁创建数据库

没有为 miniclaw 另写数据库 schema，当前复用 Hermes 的 `SessionDB`。启动器将 `HERMES_HOME` 指向项目 `.hermes`；后端首次打开可写 `SessionDB` 时，在该目录创建 `state.db`，执行 `CREATE TABLE IF NOT EXISTS`，补齐缺失列、创建索引，并按版本执行数据迁移。`prepare` 只初始化配置和插件链接，不负责建数据库；前端也不直接操作 SQLite。

入口：`hermes_state.py` 的 `_default_db_path()`、`SessionDB.__init__()` 和 `_connect_and_init()`；schema 位于 `hermes_state_common.py` 的 `SCHEMA_SQL`；初始化和迁移位于 `hermes_state_schema.py` 的 `_init_schema()`。

当前实际日志模式为 DELETE，SQLite 3.49.1 触发上游 WAL-reset 保护；未手动关闭保护。它不是需要独立启动的 MySQL/PostgreSQL 服务。本地数据库被 Git 忽略。

## 先理解四张表

| 表 | 保存什么 | 先关注的字段 |
|---|---|---|
| `sessions` | 一场会话的元数据、模型配置、标题、统计与生命周期 | `id`, `title`, `source`, `model`, `model_config`, `started_at`, `ended_at`, `system_prompt_hash` |
| `messages` | 用户输入、助手输出、模型工具调用和程序工具结果 | `id`, `session_id`, `role`, `content`, `tool_calls`, `tool_call_id`, `tool_name`, `timestamp` |
| `system_prompts` | 按内容哈希去重的提示文本；上游也复用该存储保存工具选择 pin | `hash`, `prompt` |
| `session_model_usage` | 同一会话按模型、计费渠道和任务维度累计的 API 用量与费用 | `session_id`, `model`, `task`, `api_call_count`, 各类 `*_tokens` 和 `*_cost_usd` |

`messages.session_id` 关联 `sessions.id`，是一场会话对多条消息；`sessions.system_prompt_hash` 关联 `system_prompts.hash`。`sessions.system_prompt` 是保留的兼容字段，当前写入路径优先存哈希引用，不应只查旧列就认为没有系统提示。

工具调用没有独立业务表。模型在 `role=assistant` 的行中提出调用，`tool_calls` 保存 JSON 文本；程序执行后以 `role=tool` 保存结果，通过 `tool_call_id` 对应调用数组中的 ID。失败结果也保存为工具结果，不是只存成功。

## 一次请求如何理解

假设用户发送“读取 product-note.md”，以下是简化示例，不是生产数据库导出：

| 顺序 | `role` | `content` | 工具字段 |
|---|---|---|---|
| 1 | `user` | 读取 product-note.md | 空 |
| 2 | `assistant` | 可为空，也可先解释下一步 | `tool_calls` 中有 `miniclaw_read_file`、参数与调用 ID `call-demo` |
| 3 | `tool` | 程序返回的 JSON：成功与文件内容，或失败原因 | `tool_name=miniclaw_read_file`, `tool_call_id=call-demo` |
| 4 | `assistant` | 根据工具结果给用户的回复 | 通常为空 |

模型判断是否调用以及提议参数；插件程序校验路径、参数和读取上限；Hermes 持久化消息与统计；前端消费流式事件并在恢复时读消息接口。真实写入会按持久化阶段批量刷新，不等于每个流式字符单独写一行。

## 数据库记录、界面和模型上下文

- `content` 是持久化正文。用户、助手和工具的内容都放在这里，语义由 `role` 区分。
- `tool_calls` 是模型的工具调用描述；`tool_call_id` 是结果与调用的关联键。`messages.id` 是 SQLite 消息行 ID，三个 ID 的用途不同。
- `api_content` 是上游在单条消息发送内容与持久化正文不同时保存的保真副本，不是整份模型 HTTP 请求。它可为空。
- `active` 标记仍活跃的消息，回退可让行失活；`compacted` 和 `_compressed_summary` 与压缩后的展示、重放和摘要有关。界面历史与模型恢复使用不同的筛选/重放规则。
- `display_kind`、`display_metadata`、`display_identity`、`display_order` 是展示与消息身份/顺序的辅助字段，不由模型决定 UI 样式。`observed` 也不是“模型读过消息”的通用标志。
- 消息中的 reasoning/provider 辅助字段用于保持相应协议和重放数据；存在列不代表当前模型必定填充，也不代表前端展示。

因此，数据库所有消息、界面显示的消息和下一次模型调用的上下文不能画等号。系统提示、工具 schema、当前轮输入、历史筛选、压缩和 provider 适配都会影响最终请求。第一阶段尚未捕获并验收完整模型 HTTP 请求。

当前 `state.db` 没有名为 `checkpoints` 的表，也没有接入 LangGraph checkpointer。不要把 SQLite WAL checkpoint、Hermes 其他快照/压缩机制与 Agent 可恢复执行检查点混为一谈。

## 其他上游表为何存在

Hermes 的初始化包含多入口与扩展功能需要的表；表存在不代表 miniclaw 已开启相应能力：

| 表 | 用途 |
|---|---|
| `schema_version` | schema 数据迁移版本 |
| `state_meta` | 数据库存储身份、创建时间、FTS 状态等键值元数据 |
| `gateway_routing` | 网关路由状态 |
| `gateway_hygiene_state` | 网关会话处理的失败计数 |
| `conversation_generations` | 路由会话代数，避免退休会话的范围被复用 |
| `gateway_heartbeats` | 后端进程存活心跳 |
| `compression_locks` | 压缩操作的有期限锁 |
| `session_turn_leases` | 对话轮次的有期限租约，用于并发协调 |
| `async_delegations` | 异步委派任务、结果和投递状态；当前未开放委派工具 |
| `messages_fts`, `messages_fts_trigram` | SQLite FTS5 搜索索引，不是 RAG 向量库 |

FTS 的 `_config`、`_data`、`_docsize`、`_idx` 表是 SQLite 自动管理的索引内部表；`sqlite_sequence` 管理自增序号。它们不能当作独立业务表设计。当前没有另外创建商品、图片任务、用户账号或 Skills/MCP 配置业务表；`sessions.user_id` 列存在也不代表已经实现用户认证隔离。

## 动手查看

用数据库工具以只读方式打开本地 `.hermes/state.db`，先查看结构：

```sql
SELECT name, type FROM sqlite_master WHERE type = 'table' ORDER BY name;
PRAGMA table_info(sessions);
PRAGMA table_info(messages);
```

再自行选择一场会话，查看对应消息的 `role`、`tool_calls` 与 `tool_call_id`。不要复制整个数据库或消息日志到公共仓库，也不要直接修改活跃服务的记录。

## 本机只读核对的完整字段清单

下面只列结构，不列实际业务内容。INTEGER 中的布尔标志由程序按 0/1 使用；JSON 值通常存为 TEXT，并由程序编码/解码。


实际 schema_version：30；SQLite 表对象共 24 个，包含虚拟索引和内部表。

### `async_delegations`

| 字段 | 类型 | 主键顺序 | NOT NULL | 默认值 |
|---|---|---|---|---|
| `delegation_id` | TEXT | 1 | 否 | — |
| `origin_session` | TEXT | — | 是 | — |
| `origin_ui_session_id` | TEXT | — | 是 | '' |
| `parent_session_id` | TEXT | — | 否 | — |
| `state` | TEXT | — | 是 | — |
| `dispatched_at` | REAL | — | 是 | — |
| `completed_at` | REAL | — | 否 | — |
| `updated_at` | REAL | — | 是 | — |
| `event_json` | TEXT | — | 否 | — |
| `result_json` | TEXT | — | 否 | — |
| `delivery_state` | TEXT | — | 是 | 'pending' |
| `delivery_attempts` | INTEGER | — | 是 | 0 |
| `delivered_at` | REAL | — | 否 | — |
| `owner_pid` | INTEGER | — | 否 | — |
| `owner_started_at` | INTEGER | — | 否 | — |
| `task_json` | TEXT | — | 否 | — |
| `delivery_claim` | TEXT | — | 否 | — |
| `delivery_claimed_at` | REAL | — | 否 | — |
| `origin_session_id` | TEXT | — | 是 | '' |

### `compression_locks`

| 字段 | 类型 | 主键顺序 | NOT NULL | 默认值 |
|---|---|---|---|---|
| `session_id` | TEXT | 1 | 否 | — |
| `holder` | TEXT | — | 是 | — |
| `acquired_at` | REAL | — | 是 | — |
| `expires_at` | REAL | — | 是 | — |

### `conversation_generations`

| 字段 | 类型 | 主键顺序 | NOT NULL | 默认值 |
|---|---|---|---|---|
| `source` | TEXT | 1 | 是 | — |
| `session_key` | TEXT | 2 | 是 | — |
| `generation` | INTEGER | — | 是 | 0 |

### `gateway_heartbeats`

| 字段 | 类型 | 主键顺序 | NOT NULL | 默认值 |
|---|---|---|---|---|
| `backend_id` | TEXT | 1 | 否 | — |
| `pid` | INTEGER | — | 是 | — |
| `started_at` | REAL | — | 是 | — |
| `last_heartbeat` | REAL | — | 是 | — |
| `profile` | TEXT | — | 是 | '' |
| `host` | TEXT | — | 是 | '' |

### `gateway_hygiene_state`

| 字段 | 类型 | 主键顺序 | NOT NULL | 默认值 |
|---|---|---|---|---|
| `session_key` | TEXT | 1 | 否 | — |
| `failure_streak` | INTEGER | — | 是 | 0 |

### `gateway_routing`

| 字段 | 类型 | 主键顺序 | NOT NULL | 默认值 |
|---|---|---|---|---|
| `scope` | TEXT | 1 | 是 | '' |
| `session_key` | TEXT | 2 | 是 | — |
| `entry_json` | TEXT | — | 是 | — |
| `updated_at` | REAL | — | 是 | — |

### `messages`

| 字段 | 类型 | 主键顺序 | NOT NULL | 默认值 |
|---|---|---|---|---|
| `id` | INTEGER | 1 | 否 | — |
| `session_id` | TEXT | — | 是 | — |
| `role` | TEXT | — | 是 | — |
| `content` | TEXT | — | 否 | — |
| `tool_call_id` | TEXT | — | 否 | — |
| `tool_calls` | TEXT | — | 否 | — |
| `tool_name` | TEXT | — | 否 | — |
| `effect_disposition` | TEXT | — | 否 | — |
| `timestamp` | REAL | — | 是 | — |
| `token_count` | INTEGER | — | 否 | — |
| `finish_reason` | TEXT | — | 否 | — |
| `reasoning` | TEXT | — | 否 | — |
| `reasoning_content` | TEXT | — | 否 | — |
| `reasoning_details` | TEXT | — | 否 | — |
| `codex_reasoning_items` | TEXT | — | 否 | — |
| `codex_message_items` | TEXT | — | 否 | — |
| `platform_message_id` | TEXT | — | 否 | — |
| `observed` | INTEGER | — | 否 | 0 |
| `_compressed_summary` | INTEGER | — | 是 | 0 |
| `active` | INTEGER | — | 是 | 1 |
| `compacted` | INTEGER | — | 是 | 0 |
| `api_content` | TEXT | — | 否 | — |
| `display_kind` | TEXT | — | 否 | — |
| `display_metadata` | TEXT | — | 否 | — |
| `display_identity` | BLOB | — | 否 | — |
| `display_order` | INTEGER | — | 否 | — |

外键：`session_id` → `sessions.id`；ON DELETE `NO ACTION`。

### `messages_fts`

| 字段 | 类型 | 主键顺序 | NOT NULL | 默认值 |
|---|---|---|---|---|
| `content` | FTS/内部定义 | — | 否 | — |
| `tool_name` | FTS/内部定义 | — | 否 | — |
| `tool_calls` | FTS/内部定义 | — | 否 | — |

### `messages_fts_config`

| 字段 | 类型 | 主键顺序 | NOT NULL | 默认值 |
|---|---|---|---|---|
| `k` | FTS/内部定义 | 1 | 是 | — |
| `v` | FTS/内部定义 | — | 否 | — |

### `messages_fts_data`

| 字段 | 类型 | 主键顺序 | NOT NULL | 默认值 |
|---|---|---|---|---|
| `id` | INTEGER | 1 | 否 | — |
| `block` | BLOB | — | 否 | — |

### `messages_fts_docsize`

| 字段 | 类型 | 主键顺序 | NOT NULL | 默认值 |
|---|---|---|---|---|
| `id` | INTEGER | 1 | 否 | — |
| `sz` | BLOB | — | 否 | — |

### `messages_fts_idx`

| 字段 | 类型 | 主键顺序 | NOT NULL | 默认值 |
|---|---|---|---|---|
| `segid` | FTS/内部定义 | 1 | 是 | — |
| `term` | FTS/内部定义 | 2 | 是 | — |
| `pgno` | FTS/内部定义 | — | 否 | — |

### `messages_fts_trigram`

| 字段 | 类型 | 主键顺序 | NOT NULL | 默认值 |
|---|---|---|---|---|
| `content` | FTS/内部定义 | — | 否 | — |
| `tool_name` | FTS/内部定义 | — | 否 | — |

### `messages_fts_trigram_config`

| 字段 | 类型 | 主键顺序 | NOT NULL | 默认值 |
|---|---|---|---|---|
| `k` | FTS/内部定义 | 1 | 是 | — |
| `v` | FTS/内部定义 | — | 否 | — |

### `messages_fts_trigram_data`

| 字段 | 类型 | 主键顺序 | NOT NULL | 默认值 |
|---|---|---|---|---|
| `id` | INTEGER | 1 | 否 | — |
| `block` | BLOB | — | 否 | — |

### `messages_fts_trigram_docsize`

| 字段 | 类型 | 主键顺序 | NOT NULL | 默认值 |
|---|---|---|---|---|
| `id` | INTEGER | 1 | 否 | — |
| `sz` | BLOB | — | 否 | — |

### `messages_fts_trigram_idx`

| 字段 | 类型 | 主键顺序 | NOT NULL | 默认值 |
|---|---|---|---|---|
| `segid` | FTS/内部定义 | 1 | 是 | — |
| `term` | FTS/内部定义 | 2 | 是 | — |
| `pgno` | FTS/内部定义 | — | 否 | — |

### `schema_version`

| 字段 | 类型 | 主键顺序 | NOT NULL | 默认值 |
|---|---|---|---|---|
| `version` | INTEGER | — | 是 | — |

### `session_model_usage`

| 字段 | 类型 | 主键顺序 | NOT NULL | 默认值 |
|---|---|---|---|---|
| `session_id` | TEXT | 1 | 是 | — |
| `model` | TEXT | 2 | 是 | — |
| `billing_provider` | TEXT | 3 | 是 | '' |
| `billing_base_url` | TEXT | 4 | 是 | '' |
| `billing_mode` | TEXT | 5 | 是 | '' |
| `task` | TEXT | 6 | 是 | '' |
| `api_call_count` | INTEGER | — | 是 | 0 |
| `input_tokens` | INTEGER | — | 是 | 0 |
| `output_tokens` | INTEGER | — | 是 | 0 |
| `cache_read_tokens` | INTEGER | — | 是 | 0 |
| `cache_write_tokens` | INTEGER | — | 是 | 0 |
| `reasoning_tokens` | INTEGER | — | 是 | 0 |
| `estimated_cost_usd` | REAL | — | 是 | 0 |
| `actual_cost_usd` | REAL | — | 是 | 0 |
| `cost_status` | TEXT | — | 否 | — |
| `cost_source` | TEXT | — | 否 | — |
| `first_seen` | REAL | — | 否 | — |
| `last_seen` | REAL | — | 否 | — |

外键：`session_id` → `sessions.id`；ON DELETE `CASCADE`。

### `session_turn_leases`

| 字段 | 类型 | 主键顺序 | NOT NULL | 默认值 |
|---|---|---|---|---|
| `conversation_id` | TEXT | 1 | 否 | — |
| `holder` | TEXT | — | 是 | — |
| `acquired_at` | REAL | — | 是 | — |
| `expires_at` | REAL | — | 是 | — |

### `sessions`

| 字段 | 类型 | 主键顺序 | NOT NULL | 默认值 |
|---|---|---|---|---|
| `id` | TEXT | 1 | 否 | — |
| `source` | TEXT | — | 是 | — |
| `user_id` | TEXT | — | 否 | — |
| `session_key` | TEXT | — | 否 | — |
| `chat_id` | TEXT | — | 否 | — |
| `chat_type` | TEXT | — | 否 | — |
| `thread_id` | TEXT | — | 否 | — |
| `display_name` | TEXT | — | 否 | — |
| `origin_json` | TEXT | — | 否 | — |
| `expiry_finalized` | INTEGER | — | 否 | 0 |
| `model` | TEXT | — | 否 | — |
| `model_config` | TEXT | — | 否 | — |
| `system_prompt` | TEXT | — | 否 | — |
| `system_prompt_hash` | TEXT | — | 否 | — |
| `parent_session_id` | TEXT | — | 否 | — |
| `started_at` | REAL | — | 是 | — |
| `ended_at` | REAL | — | 否 | — |
| `end_reason` | TEXT | — | 否 | — |
| `message_count` | INTEGER | — | 否 | 0 |
| `tool_call_count` | INTEGER | — | 否 | 0 |
| `input_tokens` | INTEGER | — | 否 | 0 |
| `output_tokens` | INTEGER | — | 否 | 0 |
| `cache_read_tokens` | INTEGER | — | 否 | 0 |
| `cache_write_tokens` | INTEGER | — | 否 | 0 |
| `reasoning_tokens` | INTEGER | — | 否 | 0 |
| `cwd` | TEXT | — | 否 | — |
| `git_branch` | TEXT | — | 否 | — |
| `git_repo_root` | TEXT | — | 否 | — |
| `git_metadata_generation` | INTEGER | — | 是 | 0 |
| `billing_provider` | TEXT | — | 否 | — |
| `billing_base_url` | TEXT | — | 否 | — |
| `billing_mode` | TEXT | — | 否 | — |
| `estimated_cost_usd` | REAL | — | 否 | — |
| `actual_cost_usd` | REAL | — | 否 | — |
| `cost_status` | TEXT | — | 否 | — |
| `cost_source` | TEXT | — | 否 | — |
| `pricing_version` | TEXT | — | 否 | — |
| `title` | TEXT | — | 否 | — |
| `title_source` | TEXT | — | 否 | — |
| `last_activity_at` | REAL | — | 否 | — |
| `last_activity_description` | TEXT | — | 否 | — |
| `last_activity_provenance` | TEXT | — | 否 | — |
| `api_call_count` | INTEGER | — | 否 | 0 |
| `handoff_state` | TEXT | — | 否 | — |
| `handoff_platform` | TEXT | — | 否 | — |
| `handoff_error` | TEXT | — | 否 | — |
| `compression_failure_cooldown_until` | REAL | — | 否 | — |
| `compression_failure_error` | TEXT | — | 否 | — |
| `compression_fallback_streak` | INTEGER | — | 是 | 0 |
| `compression_ineffective_count` | INTEGER | — | 是 | 0 |
| `compression_recovery_deadline` | REAL | — | 否 | — |
| `profile_name` | TEXT | — | 否 | — |
| `transport_profile` | TEXT | — | 否 | — |
| `rewind_count` | INTEGER | — | 是 | 0 |
| `archived` | INTEGER | — | 是 | 0 |
| `pinned` | INTEGER | — | 是 | 0 |
| `hidden` | INTEGER | — | 是 | 0 |
| `last_read_at` | REAL | — | 否 | — |
| `tool_names` | TEXT | — | 否 | — |

外键：`system_prompt_hash` → `system_prompts.hash`；ON DELETE `NO ACTION`。

外键：`parent_session_id` → `sessions.id`；ON DELETE `NO ACTION`。

### `sqlite_sequence`

| 字段 | 类型 | 主键顺序 | NOT NULL | 默认值 |
|---|---|---|---|---|
| `name` | FTS/内部定义 | — | 否 | — |
| `seq` | FTS/内部定义 | — | 否 | — |

### `state_meta`

| 字段 | 类型 | 主键顺序 | NOT NULL | 默认值 |
|---|---|---|---|---|
| `key` | TEXT | 1 | 否 | — |
| `value` | TEXT | — | 否 | — |

### `system_prompts`

| 字段 | 类型 | 主键顺序 | NOT NULL | 默认值 |
|---|---|---|---|---|
| `hash` | TEXT | 1 | 否 | — |
| `prompt` | TEXT | — | 是 | — |
