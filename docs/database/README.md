# 数据库、文件对象与版本管理

更新：2026-10-08。已完成本地迁移。Chat 附件上传界面和分片协议留到后续。

## 存储位置

截图中的 `main` 是 SQLite 默认数据库名称。应用使用两个持久数据库，未引入 Redis。

| 内容 | 位置 | 职责 |
| --- | --- | --- |
| Chat | `E:/AI/miniclaw/.hermes/state.db` | Hermes 会话、消息、检索索引及运行状态，本次未修改表结构 |
| 业务库 | `E:/AI/miniclaw/.hermes/miniclaw.sqlite3` | 项目、画布、生成任务、附件关联、文件索引和正式版本 |
| 媒体字节 | `.hermes/media/objects/sha256/<前两位>/<hash>` | 本地不可变文件，按内容去重 |
| 临时写入/云缓存 | `.hermes/media/staging/`、`media/cache/` | 流式写入及校验；为云对象本地处理预留缓存 |
| 旧媒体 | `.hermes/images/miniclaw/`、`attachments/miniclaw/`、`studio_video/` | 兼容文件和生成工作目录，本次未删除 |
| 草稿与视图 | localStorage/sessionStorage/IndexedDB | 未保存编辑恢复；已保存状态以业务库为准 |

默认根目录由 `HERMES_HOME` 决定。`MINICLAW_MEDIA_ROOT` 可指定对象目录，变更时需同步迁移已有对象。演示媒体 `frontend/public/studio/` 和工具产物 `artifacts/` 保持原用途。

数据库保存 object ID、backend、相对 storage_key、hash、大小与 MIME。前端使用固定同源地址 `/studio/media/objects/<id>`；不保存过期签名 URL。旧记录中的 path 继续兼容读取，新对象身份不依赖绝对路径。

## 表结构在哪里

- [000_business_legacy.sql](../../miniclaw_web/schema/000_business_legacy.sql)：原业务表集中兼容基线，旧服务兼容建表调用保留。
- [001_media_storage.sql](../../miniclaw_web/schema/001_media_storage.sql)：新增文件和版本表、外键及索引。
- [002_integrity_catalog.sql](../../miniclaw_web/schema/002_integrity_catalog.sql)：完整性约束、项目外键、查询索引和事务性项目摘要。
- [current-miniclaw-schema.sql](current-miniclaw-schema.sql)：迁移后的实际 DDL 快照，仅供查看。
- [media_storage.py](../../miniclaw_web/media_storage.py)：schema 初始化、校验和文件后端。

业务库现在 **32 张表**：原有23张、7张媒体/版本表、`workspace_catalog`及`schema_migrations`。新连接启用外键，没有重命名旧表。审查修复已应用迁移2，迁移1校验和保持不变。

| 表 | 含义 |
| --- | --- |
| file_objects | 不可变文件索引：hash、backend、key、bytes、MIME |
| media_items / media_revisions / media_heads | 逻辑内容、正式版本及父版本、当前指针 |
| media_revision_objects / media_grants | 固定版本文件引用、本地工作区访问范围 |
| workspace_snapshots | 精确历史响应 JSON，只有文件引用；保存回执改存 snapshot_id |
| workspace_catalog | 项目列表摘要：名称、时间、revision、封面、简短方案及素材/镜头数量；SQL分页，不存完整画布 |
| schema_migrations | 迁移版本和校验和；结构迁移1、2；存量数据迁移1001 |
| attachments / turns / bindings / image_jobs | 附件元数据、原生消息 row_id 展示关联和旧图片任务 |
| canvas_projects / canvas_history / canvas_selections / canvas_jobs / canvas_plans | 图层文档、有限撤销、选区、任务和修改方案 |
| video_workspaces / video_workspace_receipts | 自由画布 assets/shots/notes/sequence/布局 JSON、幂等签名及快照指针 |
| studio_projects / studio_links / studio_limits / studio_reservations / studio_image_requests | 名称、Chat 关联、限额和图片请求 |
| video_precision_links / video_precision_requests | 素材与精修文档关联、编辑请求 |
| studio_video_jobs / studio_video_renders | 视频任务、输入对象清单、结果对象和合成采用版本清单 |
| creator_projects / creator_jobs / creation_decisions | 原 Creator 兼容数据 |

节点、边、图层继续使用文档 JSON；文件、版本关系及索引独立成表。Hermes 原生 schema 由 `hermes-agent/hermes_state.py` 及其 schema 模块维护。

## 完整性、分页和助手关联

- 必需键非空、JSON检查`json_valid`、限额非负、文件ID等于有效SHA256；适用项目/任务/历史关系由外键保护，不级联删除历史。
- head/parent使用同一item的组合外键。正式内容禁止UPDATE/DELETE；恢复切换当前指针，再编辑追加分支。
- `workspace_catalog`由SQLite触发器与保存事务同步，失败保存不留下错误摘要。项目info按主键查询；owner/project/workspace、对象反查及旧文件查找补索引。
- `video_precision_links.project_id`为JSON提取的持久生成列，外键指向`canvas_projects`。早期独立精修scope未必有短片`video_workspaces`；5个独立scope原样保留，不能补造原项目。
- `studio_links.workspace`关联自由画布，chat_id是Hermes持久会话ID。两库间不创建假外键，由应用核验对话归属；9个现有关联均能找到原生session。一个对话可关联多个项目，每轮明确携带项目上下文。
- 创作/导演助手固定发送过程的workspace/target/session，切换或错误绑定会中止发送并保留草稿。精修上下文必须属于当前项目；新消息sidecar保存服务器确认的素材版本清单和精修version_id。旧消息不伪造缺失引用。

`GET /api/workspaces?page=1&page_size=6&q=搜索词`提供项目分页。`GET /api/workspaces/{workspace}/versions?page=1&page_size=20&target=素材ID`返回`{items,total,page,page_size,targets}`，每页最多100条。精修`/api/miniclaw/canvas/projects/{project}/versions`同样分页。正文摘要最多220字，完整正文/图层通过对应`/versions/{version_id}`按需读取。项目下拉兼容不带page的小型摘要数组，不再读全库画布文档。

`GET /api/workspaces/{workspace}/storage`提供版本数、元数据字节、独立对象数/字节和快照容量。同一文件可被多个项目引用，项目用量不能直接相加当磁盘总占用。当前不自动清理；未来GC须计入消息版本、正式版本、活跃任务、快照和回执，另定恢复窗口。

本轮原30张内容表的3,342条记录逐表指纹一致；摘要23条、正式版本533条、文件对象72个均保留。备份：`E:/AI/miniclaw/.hermes/backups/hardening-20261008-155806/`（两个数据库副本、对象清单；媒体原位保留）。结构自动迁移对有数据的旧库先额外生成`backups/schema-v2-*.sqlite3`；约束/关联校验失败回滚本次结构变更。

证据：[43-database-hardening.md](../acceptance/43-database-hardening.md)、[hardening-2026-10-08.json](hardening-2026-10-08.json)。Navicat数据库文件仍选择`E:/AI/miniclaw/.hermes/miniclaw.sqlite3`，刷新表结构即可。

## 版本使用

1. 自由画布：**项目资料 → 版本**，按内容筛选。图片/文案可恢复，旧视频可查看后明确采用，旧成片可下载。窄屏入口简称“资料”。
2. 精修：**历史**中保留正式文档版本。快捷撤销仍最多 101 个位置，回退后编辑只截断快捷撤销，不删除正式分支。
3. 比较页：**基于此版继续**将右侧候选作为工作底图，无须先采用到画布。

图片、提示词、备注、共同要求和口播变化会追加版本；拖动节点不创建媒体版本。恢复切换当前指针，后续版本保留。视频/成片固定实际输入对象或版本清单；重用旧视频不自动收费重做。

旧资料仅存 file 时只能恢复像素，不能伪造旧图层。已经被旧逻辑删除的历史无法恢复。删除节点不会自动删除正式版本和文件；目前无自动 GC 或历史配额。

## 本地大文件与 OSS

[ObjectBackend / MediaStorage](../../miniclaw_web/media_storage.py) 实现流式写入、hash 去重、原子发布、完整性校验和云对象本地缓存。适配协议为 `publish(key, source_path, sha256, size)`、`open(key)`、`size(key)`。

后续 OSS 实现该协议，注册为 `MediaStorage(store, backends={"oss": adapter}, write_backend="oss")`。已有对象继续按各自 backend 读取。**OSS SDK、凭据配置、签名访问和分片直传尚未接入**；当前全部本地存储。密钥只能在服务端，长期业务记录保存 object key。

画布导入改为二进制图片上传，仍受 5 MiB 格式校验上限限制，不再写 Base64 状态。底层通过 201 MiB 流式对象测试，这不等于 Chat 已支持该大小上传。Chat 当前上传协议/UI不变，附件落盘复用新文件服务。断点续传、固定消息版本引用及跨库发送补偿留到后续。

对象读取保留凭据/同源检查，支持 Range/206。授权范围适用于本地个人工作台；未来多租户需增加独立用户身份与权限判定。

## 迁移、备份与恢复

报告：[storage-migration-2026-10-08.json](storage-migration-2026-10-08.json)；验收：[42-media-storage-versions.md](../acceptance/42-media-storage-versions.md)。业务库由 **750,260,224 字节（715.5 MiB）降至 6,729,728 字节（6.4 MiB）**。媒体字节移到对象目录；旧文件保留，磁盘总用量并非同步缩小。

保留 23 个工作区、370 条回执、196 个撤销快照及原有表记录；登记 72 个去重对象、533 个版本。核对回执签名和历史响应、全部对象 hash、SQLite integrity/外键、Chat 数量和原生成任务状态；没有重提交收费任务。

迁移前备份：`E:/AI/miniclaw/.hermes/backups/storage-20261008-150216-174700/`，包含两个数据库的离线 backup API 副本、旧文件 hash 清单和报告。旧媒体原位保留，**备份目录本身不含媒体完整副本**；异地备份应同时复制两个库、旧媒体与新 objects 并校验清单。

[storage_migration.py](../../miniclaw_web/storage_migration.py) 默认只审计；`--apply` 先备份后迁移，`--vacuum` 仅离线使用。大批存量迁移不在应用启动时执行。维持原 DELETE journal，未改为 WAL。

恢复先停止应用、备份当前两个库，再恢复指定 backup 内两个数据库并保留对应旧文件。旧代码回退应配套迁移前代码；当前代码启动会补 schema，存量 Base64 重迁仍需专用命令。禁止服务写入期间覆盖活动库。
