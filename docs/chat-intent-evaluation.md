# 固定业务意图评测

冻结样例为 [chat-intent-evaluation.v1.json](chat-intent-evaluation.v1.json)，日期为 2026-10-11。共 48 条人工标注的商品创作 Chat 输入，覆盖讨论、草稿、执行、否定、收费生成、采用、多图目标、局部范围、冲突、复合要求、取消、修改需求、新话题和引用文字。标签按用户要求标注，不能为了使当前策略通过而修改标签；调整业务要求时发布新版本。

同一文件的 `regression_cases` 另保留 4 条定向补充样例，固定“提到生成”被误当收费授权的新回归；不删改原主集。报告将原 24 条规则子集、4 条新增回归、扩展 28 条规则分别计分，完整离线运行包含 48+4 条。补充样例不改变原主集的 24/24 执行边界历史口径。

默认执行真实 `ClarificationPolicy` 和 `JevDecisions`，在临时 SQLite 账本中关闭凭据，不读取 `.hermes/.env`，不联网、不运行 Agent 或媒体工具，也不改变正式会话与项目。24 条 `rule_fallback` 样例计入规则保底成绩；24 条 `semantic_required` 样例只展示保底输出与缺口，离线语义准确率明确为空。

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_chat_intent.py --output .codex/verification/chat-intent-2026-10-11/offline.json
.\.venv\Scripts\python.exe -m pytest tests/test_chat_intent_evaluation.py -q
```

报告分别列出细分意图命中、执行边界命中、澄清模板命中、误判为执行及漏判执行。执行边界将 `execute_change`、`generate_media`、`adopt_result` 归为执行，其余为只读或待确定。它只衡量前置分类结果，**不证明实际工具已被允许或被阻断**；付费确认、目标版本、操作账本仍由真实工具门禁另行验证。比如保底把“采用”归为 `execute_change`，细分意图会记错，执行边界仍可命中。

关系评测独立调用 `ClarificationPolicy.relation(text)` 的真实 API。8 条明确控制／否定／引用／假设／疑问／短答案样例计算 `explicit_action_accuracy`，验证是否路由为取消、修改、另开话题或保持当前任务。原有 5 条依赖语义的关系样例保留原任务与待回答问题，独立列为 `semantic_relationships_not_verified`。其中“改成蓝色”保留当前任务只证明没有误改任务，不证明系统能理解或自动提交它作为当前问题答案；报告明确 `answer_submission_verified=false`。复合要求的结构化子目标也列为未评测。

本机若保留 2026-10-09 的 `jev-smoke.json`，离线模式会另用 `httpx.MockTransport` 重播其中 3 条真实 Jev **answers**，通过生产响应校验器和当前分类策略重新计算结果。不会相信历史记录外层保存的 intent，也不会重新发送请求。重播的 usage 使用 0 作为校验支架，原历史估算费用单独保留；它验证历史答案与当前策略的兼容性，不能代表今天模型可用性或线上准确率。其他 checkout 缺少该私有历史文件时，报告 `source_missing`，规则评测仍可运行。

可选少量实时评测必须显式使用 `--live`，此时才读取项目凭据：

```powershell
# 会发送最多 3 次 Jev 文本请求；只有明确授权收费评测时运行。
.\.venv\Scripts\python.exe scripts/evaluate_chat_intent.py --live --case-id r06 --case-id r13 --case-id r20 --max-calls 3 --budget-usd 0.01 --output .codex/verification/chat-intent-2026-10-11/live.json
```

实时所有样例共用一个临时账本，调用限额不会随 task_id 重置。默认最多 3 次、上限 10 次；预算必须在 0.000001–0.01 美元间，沿用 Jev 执行前费用估算预留，余额不够时不发送请求，未知结果不自动重试。`--case-id` 可重复选择样例，`--limit` 限制数量。这个美元预算基于当前代码的标价估算，供应商 usage 与账单由供应商决定，不能宣称账单绝对硬上限。报告始终标明 `online_accuracy_claim=false`。

冻结样例是回归种子集，当前没有线上分布采样、双人标注、一致性审核或阈值校准。真实评测应关注误执行和漏追问的具体输入，再扩大独立标注样例；不应仅凭总体命中率降低收费与目标门禁。

2026-10-11 首次离线运行曾发现 r24“生成一张候选，不要修改原图。”保底被广义草稿正则归为 `draft`，造成漏判执行；该输入保留在冻结集中，由核心策略另行修复，评测器不会更换标签掩盖差异。最新结果见 `.codex/verification/chat-intent-2026-10-11/offline.json`。这是种子集及历史兼容结果，不能推成线上准确率，本轮新增收费调用 0 次。

同日修复后离线复跑：规则细分意图 21/24（采用和生成保底仍合并为执行），执行边界 24/24、前置澄清模板 24/24、误执行与漏执行均 0；明确控制动作 8/8。历史 Jev 答案重播细分意图 2/3、执行边界 3/3。24 条语义意图样例、5 条任务关系语义和复合拆解仍需另行验证，不能因其他成绩通过将它们标为完成。

随后新增的 4 条定向回归执行边界 4/4，扩展规则集执行边界 28/28、细分意图 23/28；讨论与草稿尚未完全细分，因此两个讨论回归会在细分意图中记错而不影响只读边界。专项测试另验证这 4 条的收费次数授权为 0，模型若调用收费工具会转入 `Q_EXECUTION` 澄清；又补充“不要再生成图片”“不需要生成图片，先帮我写文案”两条否定的次数授权与两种收费工具门禁检查，不改变冻结主集或计分分母。该结果只覆盖列出的输入，不能解释为任意中文否定、引用或疑问都已正确识别。

最终执行 `python -m pytest tests/test_chat_intent_evaluation.py -q`：27 项通过；离线报告重跑，新增网络请求 0 次。
