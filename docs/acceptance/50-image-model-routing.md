# 百炼图像模型映射与对比核查 · 2026-10-08

用户提供新试验：改写词和短词都出现颗粒，Edit Plus结果背景正常，怀疑模型命名或路由错误。

## 结论和边界

四个界面选项映射为 qwen-image-2.0-pro、qwen-image-2.0、qwen-image-edit-max、qwen-image-edit-plus，运行服务catalog与源代码一致。这些都是[百炼编辑API](https://help.aliyun.com/zh/model-studio/qwen-image-edit-api)列出的有效模型，2.0系列支持编辑，并非误把只支持生图的模型标成修图。

最新六份studio回执与canvas任务的model/provider一致，源图相同。21:06:12 Edit Plus与21:07:04 2.0 Pro都收到“商品中的洗面奶向左倾斜90°”：前者保存图有明显转动、背景正常；后者保存图出现颗粒、姿态接近原图。Plus并未准确完成90°，不能记为完全成功。新短优化词及未优化短词也在Pro上失败；应撤回将优化词长度作为主要处理重点的判断。

前端selectedModel→POST/images→studio.submit_image→canvas.submit→canvas._execute→image_provider.edit_image均保留选定ID，适配器写入官方HTTP请求体的model，不被环境默认模型覆盖。新增测试在真实服务/任务/适配器链路上用MockTransport截取四模型HTTP请求，验证官方host/path、输入图Base64、单个指令、模型ID及结果request_id绑定；不调用云端。历史数据库模型是应用请求字段，供应商响应未回显权重版本；没有历史原始HTTP请求/响应存档，不能将本次MockTransport证明写成历史网络抓包。厂商内部别名解析、权重和运行状态需凭request_id在供应商核查，本次没有访问其账单或发送支持消息。

## 修正一个真实界面问题

切换模型后旧imageJob保留，原“结果已生成”不显示生成该结果的模型，容易误解旧结果属于新选择。按oil-ui-pro的小改动路径，复用既有状态行，不新建说明卡：显示“结果已生成 · 实际模型”；选择与结果不同时显示“上次结果 · 实际模型”。下拉框的无障碍名改“选择下次生成模型”。当前结果仍按确切job输出进入比较，不改图、不自动生成、不自动切换默认模型。

## 验证

- 基线后端8项通过。新增测试首次使用含点号的request_id，被应用合法拒绝；修正测试标识后最终9项连续三轮通过。
- 前端节点操作50项连续三轮通过，包含切换模型保留原结果来源、下一请求发送新ID及结果更新。TypeScript检查通过。
- 实际9120页面从画布选中商品→修图，显示“结果已生成 · Qwen Image 2.0 Pro”，截图result-model.jpg已查看，未遮挡状态或比较按钮。没有切换或生成用户媒体，没有付费调用。只有状态文案变化，无新增动效；未独立视觉评审。
- 当前页切换模型后的来源提示由回归测试覆盖，未在用户工作区改变模型配置来拍摄。默认选择和当前任务保留。

证据目录：`.codex/verification/model-routing-2026-10-08/`，audit.json记录六任务、时间、源图、模型、输出hash和供应商request_id，result-model.jpg记录实际界面。
