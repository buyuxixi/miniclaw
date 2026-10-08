# 业务数据库审查

后续状态：用户已授权修复。本轮迁移002及代码修复已应用；原审查内容保留作为修复前证据。结果见[43-database-hardening.md](../acceptance/43-database-hardening.md)，实际schema已更新为32表。

2026-10-08；ai-dev-review。只读检查实际库、31张表DDL、字段、索引及代码查询；缺陷复现与建议索引验证仅在内存副本进行。没有执行实际库DDL/DML或删除媒体。

结论：当前单机工作台的“媒体文件对象 + SQLite引用 + 正式版本”架构合理，现存数据核对通过；上一轮完成的是媒体规范与历史迁移，原表约束、热查询索引和服务端分页尚未全面规范。没有发现P0/P1现存数据故障；以下P2项建议作为下一次数据库迁移处理。

## 发现

### P2：版本外键不能保证同一素材内部的关联

定位：[001_media_storage.sql](../../miniclaw_web/schema/001_media_storage.sql:15)，`media_revisions.parent_id`；同文件`media_heads`定义。

当前外键分别保证item与revision存在，却允许素材A的head指向素材B的revision，或B版本以A版本作parent。内存开启foreign_keys后，两种写入均成功，foreign_key_check仍为空。当前应用append/select的实现会写正确关联，运行库无错连；问题在于下一次导入/脚本/直接数据库维护出现错误时，数据库无法阻止，可能使版本内容错配或父链跨素材。

建议：revision增加`UNIQUE(item_id,id)`，head使用复合外键`(item_id,revision_id) → revisions(item_id,id)`；parent使用`(item_id,parent_id) → revisions(item_id,id)`或等效严格触发器。parent允许NULL表示根版本。迁移前检查所有已有关系；不要修改已执行的001校验迁移。

### P2：11类已存在查询缺少匹配索引

定位：[store.py](../../miniclaw_web/store.py:70)、[canvas.py](../../miniclaw_web/canvas.py:619)、[studio_video.py](../../miniclaw_web/studio_video.py:102)、[studio.py](../../miniclaw_web/studio.py:91)，以及creator/image_plans对应列表。

实际EXPLAIN QUERY PLAN确认以下查询走SCAN。现有数据少，不等于已发生卡顿；随其他项目、附件和任务增长，每次读取一个项目仍需扫描全表，有关操作会受总量影响。

| 表 | 当前查询条件 | 建议索引 |
| --- | --- | --- |
| attachments | owner，rowid倒序 | `(owner)` |
| turns | owner | `(owner)` |
| image_jobs | owner，rowid倒序 | `(owner)` |
| canvas_jobs / canvas_plans / creator_jobs | project，rowid倒序 | 各`(project)` |
| studio_video_jobs / studio_video_renders | workspace | 各`(workspace)` |
| studio_reservations | workspace数量 | `(workspace)` |
| video_precision_links | json_extract(data,'$.project') | 相同表达式索引；后续提升为project列 |
| media_grants | object_id | `(object_id)` |

上述单列普通索引在当前rowid表上可配合反向扫描；attachments/canvas_jobs、视频workspace、精修project查询已在内存副本验证由SCAN变SEARCH，未增加实际库索引。不必给每个字段建索引。

已有合理索引：`canvas_history(project,seq)`支持定位与顺序历史；回执`(workspace,id)`支持幂等重放；`media_items(scope,target,kind)`支持逻辑素材唯一；`media_revisions(item_id,created_at)`支持单素材历史；`media_revision_objects(object_id)`支持文件反查。`file_objects.sha256`唯一与backend/key唯一适合去重。workspace_snapshots当前主要按id取值，workspace/revision索引可供未来审计/管理使用，暂不判为缺陷。

### P2：字段约束不足，关键空值/坏JSON可直接入库

定位：[000_business_legacy.sql](../../miniclaw_web/schema/000_business_legacy.sql:4)、[001_media_storage.sql](../../miniclaw_web/schema/001_media_storage.sql:2)。

内存复现：`attachments(id=NULL,owner='owner',data='not-json')`成功；`studio_video_jobs(workspace=NULL,data=NULL)`成功。许多普通TEXT主键未显式NOT NULL，不能以PRIMARY KEY推断它禁止NULL；SQLite官方说明了这一兼容行为：[CREATE TABLE](https://www.sqlite.org/lang_createtable.html#the_primary_key)。代码的json.loads/必需字段访问会在读取坏记录时失败。当前实际数据中未发现无效JSON或上述抽查关系孤儿，这属于防御不足。

建议增量重建涉及表：主键/业务必需键显式NOT NULL，JSON列`NOT NULL CHECK(json_valid(data))`，calls/reserve非负；新版本kind、hash格式、对象id=sha256一致性增加CHECK。NULL语义保留给origin/parent等真实可选字段。不将全部旧表直接STRICT化而不测试兼容。

旧表canvas_jobs/plans/history/selections等project关系目前依赖应用校验，缺数据库FK；可在确认生命周期后增加到canvas_projects的RESTRICT约束。已存在历史的版本、文件、付费任务不使用随项目删除的CASCADE。多态scope、工作区内JSON节点ID、跨state.db的message_row_id不能生造普通FK。

### P2：列表未分页，索引不能解决读取全部文档

定位：[media_versions.py](../../miniclaw_web/media_versions.py:40)、[studio_projects.py](../../miniclaw_web/studio_projects.py:40)、[integration.js](../../frontend/public/studio/integration.js:48)。

版本接口fetchall并返回整份data；界面先加载全部版本，再客户端筛选。项目库也先读全部工作区文档，单项目project_info复用全列表。这在长期精修/多项目时会增加传输、JSON解析与内存，客户端分页没有降低后端读取成本。当前规模下没有测出性能故障。

建议：版本按target/kind以及`(created_at,id)`游标分页，每页只取标签、摘要、缩略图、parent/current；打开详情再读完整版本。现有created_at+rowid排序与未来游标排序需一致调整索引。项目列表将name/updated_at/revision/cover等提升到索引列，SQL筛选排序分页；project_info直接按id查询。不要仅添加created_at索引后仍fetchall。

### P3：正式历史和保存快照没有容量策略

定位：[media_versions.py](../../miniclaw_web/media_versions.py:133)。

Base64已移除，但每个幂等操作仍保留精确响应快照；含revision/time/events的不同响应通常不能靠hash去重。数据库会按元数据持续增长，媒体正式版本也无限保留。这不是当前数据损坏，且保留精确旧响应本身正确。

建议先提供按项目的版本/快照/媒体用量统计和归档方案；明确请求重放窗口、保留期限、用户恢复要求后再清理。不要用当前状态代替旧回执，不仅按ref_count删文件。正式版本/消息引用/活跃任务/快照都要计入引用清单；实施GC前需扩展当前仅正式版本文件引用模型。

## 表和字段设计判断

31张表数量本身不是问题。当前包括Chat展示关联4表、精修5表、自由画布2表、项目/请求5表、精修关联2表、视频2表、兼容Creator3表、媒体/版本7表及迁移1表。部分是历史兼容，不能仅因少数据就删除。源码中project既可能表示精修文档，也可能表示Creator项目，文档应明确，不做一次性大改名。

适合继续放JSON：节点/连线布局、图层几何、模型参数、提示词正文、精确历史文档。适合提升为字段：workspace/project/owner、state、provider/model、provider_task_id、created_at/updated_at、revision、object_id等高频过滤/关联值。先迁热路径，不强行把每个画布节点属性拆表。

file_objects里id与sha256当前相同。重复字段并非必要，但暂保留兼容，补一致性CHECK即可。REAL时间表示UTC Unix秒，接口转本地显示；当前可用，新表可统一整数毫秒，避免未经迁移混用单位。`media_grants`当前是本地个人工作台的scope/object关联，没有独立user/role；多用户OSS部署前须增加主体授权，当前媒体GET仅检查对象存在grant不能作为多租户隔离证明。

## 大文件事实

本地文件位于`.hermes/media/objects/sha256/...`。`file_objects`存对象标识、backend、storage_key、sha256、bytes、mime、created_at；业务文档存固定同源地址/object_id，版本表通过media_revision_objects固定引用。旧路径保留兼容，文件不会以视频BLOB或data:image存入当前业务记录。文本正文/图层JSON继续存库，不能说数据库“只有URL”。

本次检查所有有data列的表，含data:image行数为0；所有当前本地对象存在且字节大小/hash匹配。已预留OSS协议，无实际云端存储或Redis；Chat整包上传尚未改成大文件分片。

## 验证证据与边界

[schema-review-2026-10-08.json](schema-review-2026-10-08.json)记录逐表行数/索引/JSON大小、执行计划与内存复现结果，不含消息正文、凭据或完整媒体。

- SQLite integrity_check=ok、foreign_key_check=0。
- 当前head/parent跨item错配=0、附件缺object=0、抽查任务/项目关系孤儿=0、回执缺snapshot=0。
- 全部31表审查，有data列的JSON有效；本地对象缺失/损坏=0。
- 11类查询实际SCAN；代表建议索引在内存副本变为SEARCH。
- 没有做万级项目压测、真实OSS/多租户访问验证，不以小库结果推断大规模性能。

优先顺序：新增002迁移补约束和热路径索引 → 服务端列表分页/提取过滤字段 → 容量统计与保留/归档设计。需要重建表时应离线备份、先副本迁移、校验数量/关系/文件，再实际切换；只读审查轮不执行这些变更。
