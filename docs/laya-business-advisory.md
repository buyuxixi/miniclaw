# Laya 产品宣传业务辅助原型

本原型给主模型提供意图、必要澄清原因和业务类别建议。模型结构保持既有encoder与共享决策层；监督数据更新两部分参数。类别通过六个独立yes/no问题支持多选，不把工具目录永久分割成单一类别。辅助输出不产生执行权限、不选择对象ID、不替代工具参数和业务校验。

## 契约

- intent：沿用discuss/draft/propose_change/execute_change/generate_media/adopt_result/cancel/revise_task/new_topic/unclear。
- clarification：none/intent/target/region/conflict。只缺对象不改变明确执行意图；讨论不需要执行对象；低分交给主模型，不自动宣称用户没说清。
- categories：scheme/image/image_prompt/video_prompt/narration/video，可同时成立。只优化视频提示词不归类为视频成片操作。
- 可信context：会话候选ID、selected、selection、已确认值、当前待答问题/任务，以及宿主确定的绑定状态。不能从模型分数推导needs_existing_target/target_bound/region_bound，不发送完整历史、附件全文或评分标签。

模型输入超长时拒绝，不默默截断。评分输出含截断/选项碰撞、概率非法或缺问题则回到主模型。用最高选项概率和概率间隔选择性接纳，不把Laya熵confidence当正确率。门槛文件绑定问题schema和checkpoint哈希；更换问题或权重必须重做校准。

辅助建议即使通过门槛也可能错误，主模型必须结合请求独立判断；类别用于提示搜索，不可作为排除其他工具的硬门槛。初版只在对应校准样本充分且宿主确定对象/区域缺失时支持模板直接提问；当前的小校准集不满足直接提问条件。返回main_model_required=true表示本原型仍需要主模型理解/规划。

## 本地运行

原始页面8766与现有项目Jev配置不自动切换。单独启动8767的开发预览：

```powershell
& 'D:\model\laya-runtime\.venv\Scripts\python.exe' -u -X utf8 'E:\AI\miniclaw\scripts\serve_laya_advisory.py' --checkpoint 'D:\model\laya-business-advisory\round-02' --gates 'E:\AI\miniclaw\.codex\verification\laya-advisory-v2-2026-10-11\trained\runtime-gates.json' --port 8767
```

访问http://127.0.0.1:8767，原始答案和接纳后的建议分别显示；模拟绑定信息只是测试上下文，页面不执行工具。服务仅监听loopback，模型与tokenizer离线加载，不调用Jev、主模型或媒体模型。/local/runtime显示实际检查点，POST /v1/advice接收contract_version与state。

项目显式客户端为miniclaw_web.laya_advisory.LayaAdvisoryClient；传入本地地址及runtime-gates.json内容，evaluate(text, trusted_context)返回advice/raw/status。runtime-gates仅规范问题契约指纹的换行表示，原门槛/评分不变；原gates.json保留。默认没有在生产路径自动构造此客户端。身份不符、断线、超时等返回fallback；不重试收费请求。

## 数据与训练

advisory-v1为216训练/16开发/24校准/32测试；advisory-v2为311训练/48开发/36校准/40新测试。第一轮已观察的测试转为第二轮开发回归。商品替换和相同短回复的上下文变体按场景族整体放在一侧；所有标注均为合成开发数据，不声称是用户已审批或外部盲测。

第一轮从原始多语言权重训练3轮：encoder_lr=2.5e-5、head_lr=1e-4、标签平滑0。第二轮从round-01继续2轮：encoder_lr=1e-5、head_lr=5e-5、标签平滑.05。AdamW、weight_decay=.01、余弦衰减到1e-6、grad_clip=1、micro_batch2/grad_accum4、FP32、梯度检查点、选项顺序打乱、seed20261011。学习率初值参考安装版Laya默认设置；继续训练降低学习率和平滑标签是针对开发失败的尝试，不是最优参数结论。

训练只用train，dev检查训练前后变化；自动按训练item拆校准被关闭。calibration单独拟合选择性门槛，然后冻结测试。测试后不调本轮门槛或替换原始成绩。综合8组准确率含大量二分类负例，必须同时看意图、澄清和各业务正类F1。

原生隔离验证可显式运行evaluate_native_fastpath.py的main,laya_business两组；建议作为首条用户JSON的数据字段，不写入系统指令。对照采用同一提示、同一有限动作校验和原生回执流程。只执行人工fixture图片旋转/翻转和文本保存，不外推到生产网关、付费媒体质量或真实用户分布。

详细结果分别保存在.codex/verification/laya-advisory-v1-2026-10-11及laya-advisory-v2-2026-10-11。硬路由、自动执行、替换Jev及成本节省需要额外证据。

## 2026-10-11 状态对照验证

用户明确定位为辅助，不承担主线。本次保持round-02及原门槛：32条状态对照×两次、两组规划，严格匹配46/64→54/64，8次纠正、0次退步；14个真实原生场景×两次、两组均28/28流程匹配。原生目标/像素、等待续跑及复合文本结构没有差异，未证明最终业务效果增加。

探索性拆分7条×两次：完整提示7/14、空白辅助结构5/14，单类别/单澄清均5/14。部分被纠正案例的Laya澄清提示本身是错的，不能把全部规划改善归为分类能力。32状态原始澄清24/32、类别集合22/32；接纳澄清16/20正确。双方口播均出现未经提供的产品性能描述，流程通过不等于内容质量通过。

新增入口scripts/build_laya_state_contrast.py、evaluate_laya_state_contrast.py、evaluate_laya_state_ablation.py、analyze_laya_state_contrast.py及docs/chat-laya-state-contrast.v1.json；报告见[状态对照验证](../.codex/verification/laya-state-contrast-2026-10-11/README.md)。没有新训练/校准/生产切换。收益判断分别看流程错误、干扰、时延、内容及替代Jev辅助费用，不以省主模型调用作唯一标准。
