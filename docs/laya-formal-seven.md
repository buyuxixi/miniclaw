# 项目的八问与正式七问

2026-10-12 更新：全项目决策入口已采用 Laya 首选、Jev 备用，详见 [决策路由](decision-routing.md)。以下按轮次保留当时的实验状态，“未切换/无Jev兜底”描述对应历史实验，不代表现在生产路由。当前 Studio 未校准合同仍明确走备用 Jev。

这两套问题都是 miniclaw 的应用层业务契约，不是 Laya 或 Jev 规定的标准题目数量。实际调用把项目构造的 `questions` 送给评分器；模型/API负责返回各选项的评分，宿主决定这些字段如何参与流程。

2026-10-11用户进一步明确：**最终目标是微调Laya替代Jev的决策识别职责**。此前“保持辅助定位、不替换Jev”是第三轮的阶段安排，不是永久目标。后续以相同正式契约下的直接替换效果为验收依据；主模型继续负责主线规划和执行，宿主继续负责对象绑定和权限。

## 旧八问：业务辅助

定义在 `miniclaw_web/laya_advisory.py::questions`：

| 字段 | 作用 |
|---|---|
| intent | 讨论、写草稿、提案、执行、生成、采用、取消、修改任务、换话题、意图不清 |
| clarification | 不用问、问目的、问对象、问局部区域、问冲突取舍 |
| category_scheme | 是否涉及宣传方案 |
| category_image | 是否涉及图片 |
| category_image_prompt | 是否涉及图片/修图提示词 |
| category_video_prompt | 是否涉及视频提示词 |
| category_narration | 是否涉及口播 |
| category_video | 是否涉及视频成片 |

后六项各问yes/no，允许一条请求涉及多个业务。第二轮round-02是在这套中文说明、状态和标签上训练的，原8767服务仍保留。

## 正式七问：结构化决策依据

定义在 `miniclaw_web/clarification_policy.py::chat_request`，当前正式路径由Jev回答：

| 字段 | 选项与含义 |
|---|---|
| intent | discuss、draft、propose_change、execute_change、generate_media、adopt_result、cancel、revise_task、new_topic、unclear |
| target | 候选对象的真实ID，加none（无对象）、multiple（多个明确对象）、ambiguous（对象不清） |
| reference_role | primary（操作主体）、reference（只作参考）、feedback（反馈当前对象）、comparison（比较）、unclear |
| scope | selected_region（局部区域）、whole_object（整对象）、explicit_multiple（多个对象）、unclear |
| conflict | none、present、unclear；新要求替代旧要求不自动算冲突 |
| answer_relation | answers_current、revises_task、new_topic、cancel、unclear；判断当前回复与待答问题的关系 |
| fact_review | clear（当前请求无新增未证实事实）、review（有产品事实需要证据）；clear不证明产品性能已经核实 |

七问没有单独的clarification问题，也没有那六个业务类别。正式策略主要消费intent、target、reference_role、scope、conflict来构造澄清；answer_relation/fact_review有输出并不等于已经改变生产流程。正式请求目前缺少pending_question、selection、original_user_request等详细状态。

## 第三轮适配的边界

从round-02继续训练一个单独的七问checkpoint `D:/model/laya-business-advisory/round-03-formal-seven`。正式问题文字、选项顺序、primary请求结构保持一致；enriched仅在隔离实验给两种模型相同完整状态。旧权重与原服务保持，第三轮不会自动继承原八问gates，也未验证第三轮仍保留原八问分类能力。

选择性校准只接纳有独立校准支持的字段/标签。不足的字段停用，接纳标记不是正确概率；评分/提示不能授予执行许可、绑定对象、证明事实或替代用户确认。真正辅助对照保留Jev的正式分类与澄清，Laya只给主模型可忽略的提示。

本轮训练、校准、独立测试与真实工具流程见 `.codex/verification/laya-formal-round3-2026-10-11/README.md`。目前未替换正式Jev或8767旧八问服务。

## 第四轮：向替代Jev推进

第四轮扩到800训练记录，96基础表达族；从round03继续一次2epoch，输出独立round04。新primary197有效配对意图Jev158、round03 155、round04 183；真实Jev与Laya直接替换流程77/82与82/82，Laya没有Jev兜底，修复5个错误对象追问。

复杂澄清诊断中，新权重原门槛163/197超过Jev153，但独立逐标签校准146/197仍有退步；target/fact_review未获门槛支持，部分待答关系正例缺失。全量生产尚未切换，后续以替换效果检验按消费场景校准、回退及真实状态覆盖。

`miniclaw_web/laya_formal.py`及`scripts/serve_laya_formal.py`提供正式七问本地候选调用；第四轮当时只支持已验证双图、第一张/第二张标签，其他状态明确拒绝。它是接替正式调用契约的候选实现，生产仍使用Jev，Studio其他问题契约也尚未覆盖。具体结果、限制和候选启动命令见 `.codex/verification/laya-formal-round4-2026-10-11/README.md`。

## 第五轮：对象状态收益与校准限制

第五轮实际1160训练记录（360新状态+800旧train重放），新40表面表达族，0–4对象及不同业务名称。一次1epoch、1015优化更新，输出独立round05。356新有效配对中，target311→345、scope323→329、conflict340→355，intent323→314。新门槛冻结后，原门槛+同一实验policy澄清272→301，而按消费场景严格校准264→244；不能把新checkpoint直接当全面升级。

相同修复后宿主下，Jev与校准Laya真实45对均45/45，没有新增完成收益/回归；原门槛补充诊断45/45也是已知fixture。Laya没有Jev兜底。初始HTTP3/4与修复后另4/4分别保留；有限grammar/弃权许可修复属于验证入口和宿主收益，不归因于微调。84测试及143流程完整性通过，内容仍有未经证实的外观/场景和旧性能声称。

原round04候选8768保留双图限制；新round05候选8769支持0–4对象业务名称，但只接空confirmed、版本None，其他状态明确拒绝。客户端可同时固定checkpoint/gate SHA256。正常生产会传版本摘要，正式provider仍Jev，多轮resume仍跳过分类器；因此候选HTTP联调通过不等于已接完生产。后续先优化联合行为校准和真实待答/名称绑定/版本契约，而非继续按同模板复制状态行数。详见 `.codex/verification/laya-formal-round5-2026-10-11/README.md`。

## 第六轮：联合校准和显式聊天provider

使用现有round05权重未重训。新140配对，冲突优先联合校准把前置澄清匹配从旧校准88提高到124，Jev95；原门槛132仍更好。新cal140加旧cal360，门槛在新test评分前保存，运行掩码只依赖预测/宿主事实，不能把校准+数据收益说成权重收益。

新8770服务支持0–4对象、空confirmed及合法版本SHA256摘要；仅语义模型输入把摘要投影None，原请求cache和宿主版本核验保留。实际Coordinator.begin、五组HTTP等价及四种拒绝状态通过。聊天Coordinator用chat_decisions.chat_policy工厂，默认Jev；显式MINICLAW_CHAT_DECISION_PROVIDER=laya必须设置loopback URL、checkpoint与gate SHA256双pin。Studio其他契约仍原provider，现有9120未重启或切换。

真实8对Laya8/Jev7，两组主调用10/10；真实选图回复后Jev意图弃权重复问执行、Laya恢复旋转，属于意图消费收益，关系头未参与。仅已知有限两图语法fixture，不能视作广域生产替代。123相关测试通过，16原图/5像素/5重复回执/5等待拦截完整。名称重复选项改用唯一ID，但直接名称命令覆盖宿主选择仍待实现，非空确认/关系正例/其他Studio契约仍缺。结果、启动与可选环境变量见 `.codex/verification/laya-formal-round6-2026-10-11/README.md`。

## 第七轮：再微调与有限确认支持

固定1epoch，从round05继续720训练记录（320新+400旧train重放），630优化更新，输出round07。同一新cal320与联合算法对照，新318有效配对意图round05 249→round07 316（Jev292），澄清匹配218→307（Jev227）。旧round6意图140→138及角色133→128有少量退步；剩余局部范围漏问仍保留。

新8771 joint-v2支持0–4对象与空/执行/草稿/实际选图四类confirmed，19组HTTP与离线完全一致，真实Coordinator显式工厂与真实执行确认像素检查通过。Q_SCOPE文字、未知key/不一致target、5+对象仍拒绝；primary七问没有新增pending字段，resume仍不重新分类，关系/事实review和其他Studio契约未完成。

共同宿主新增有限肯定完整名称命令绑定，仅本任务附件旋转/翻转；未知/同名清空旧选中并等待实际回答，引用/否定不绑定。真实18对初跑双方17/18；同名回答后重复执行确认的共同宿主缺陷已修复，独立重跑1对双方成功，保留原失败，不将修复后样本合成全套18/18。164相关测试及10 subtests通过；生产9120默认Jev未改。

新权重SHA256 `6c1d336ea08c1bd87292c573a393a7ed0b58bb8ce5b7a60a79cb72456083d041`，gate SHA256 `69639c48ac04dbe6de7fb99a098a7d184acf1e16a32b823efe52b4112694f315`；显式试验必须配置URL8771及两份pin。完整数据、结果、已披露修复、预算与启动命令见 `.codex/verification/laya-formal-round7-2026-10-11/README.md`。下一步用独立实际请求和真实pending/ROI补关系正例与范围判断，不能把作者模板上的高分当全量替代完成。
