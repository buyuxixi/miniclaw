# LibTV 媒体节点与逐任务模型选择（2026-10-08）

用户否定图片撑出节点、边上文字、表单式视频卡片及不能逐任务选模型。本轮以用户提供的两张 LibTV 截图为参照，保留 miniclaw 品牌、项目导航、完整 Chat、导演和完整精修入口。

## 改动与实际效果

- 媒体是画布节点；长文件名省略，图片按比例限制在节点内。视频结果保持独立可拖动对象，连接更新真实首帧/参考图关系。
- 连线改为无文字细曲线，选中关系突出；结果线落在输入端口。生成参数从节点卡片移到选中对象下方，工具条位于上方，使用实际宽高定位。
- 生成面板有编号参考图、提示词、任务模型菜单、参数、提交和状态反馈。模型菜单根据可用空间滚动；小窗口结果采用按钮不会被底栏遮住。
- 图片生成、图片编辑、视频分别按服务器能力目录选模型；选择保存在各自对象中，刷新保留。服务端白名单校验供应商、模型、任务，任务回执固定模型，重复请求不能改参数。
- 百炼 Qwen 图片生成/修图、Wan 视频和 MiniMax Image 01、H3/H3 Max、Hailuo 视频走各自协议。Image 01 仅支持文生图，不伪装成通用修图。H3 使用 V2 内容/角色协议，Hailuo 保留 V1；多图参考仅提供给支持的模型。
- 完整精修工作区也可选修图模型，并继承节点选择。云端候选仍先比较再采用，原图和编辑历史保留。

## 真实供应商与界面操作

操作在独立测试项目 `model-qa-bbbe5287-2486-4b06-8e7f-293b13422bfc`，没有替换原 BUV 项目的采用视频。

1. 节点选择 MiniMax Image 01，真实文生图成功；候选采用为画布图片。
2. 对该生成图选择百炼 Qwen Image Edit Plus，真实修图成功；打开完整对比、采用并回到画布。读回图片为 720×1280，原图/候选回执保留。采用后重开完整编辑器，模型仍为 Edit Plus，图片正确加载，返回画布成功。
3. 视频节点选 MiniMax H3，连接上述图片并提交；供应商任务 `450019665584424` 成功。原生视频 5.166992 秒、768×1344，保留原下载；工作台输出 5.000 秒 H.264 静音片段。浏览器原生播放器播放到 ended=true/currentTime=5；核对并采用到测试时间线，显示5秒。
4. H3 的真实下载地址为明确的 `algeng-video-infer.oss-cn-shanghai.aliyuncs.com`。初次下载被旧域名白名单拒绝，补入此精确主机后继续查询同一任务并下载，没有重复生成。下载不带 API Key；任意其他 OSS 主机仍拒绝。

证据：`outputs/libtv-node-models/real-model-evidence.json`；图片生成/修图队列与原请求持久保存于 Canvas。实际账单金额未知，不从旧 Wan 费率推算 MiniMax。

## 界面与回归证据

当前截图均无控制台错误、页面横向溢出或图片加载失败：

- `final-video/page-1920x1000.png`、`page-1280x720.png`：参考布局和视频模型菜单。
- `final-generation/page-1920x1000.png`、`page-1280x720.png`：图片生成菜单，MiniMax Image 01 与百炼分别可选。
- `final-image/page-1920x1000.png`、`page-1280x720.png`：修图菜单与结果采用按钮。
- `final-short/page-@2x.png`：960×500 CSS 短窗口、DPR2；不是原生浏览器200%缩放。
- `final-canvas-200/page.png`：实际画布控制条200%，不是仅提高截图像素密度。
- `real-h3-adopted/page-1920x1000.png`、`page-1280x720.png`：真实H3模型、已采用状态与5秒时间线。
- `full-editor-model/page.png`：完整精修的修图模型入口与采用后的实际图片。
- `final-user-project/page-1920x1000.png`、`page-1280x720.png`：原BUV项目在新界面中的实际布局与既有10秒采用片段；服务端仍为revision38、更新时间2026-10-07 22:52:05，未采用测试产物。

独立存量视觉评审未打分。第一轮指出工具条偏离节点中心；修复后第二轮确认视频/修图/新建图片工具条居中，以及1280×720、短窗口提交/采用按钮完整可见。菜单滚动由主任务实际选择模型验证。首次出场及连续动效没有完整录像，不记成通过。早期带空格的截图步骤没有正确命中控件，产生的三张多余测试视频节点已移除；早期截图不作为最终证据。

最终相关检查连续三轮，每轮：前端30项、后端54项、TypeScript通过。日志：`frontend-final-1/2/3.log`、`backend-final-1/2/3.log`、`typecheck-final-1/2/3.log`。

命令：`vitest run src/studio-operations.test.js src/studio-save.test.js src/canvas-interactions.test.tsx --root frontend`；`python -m unittest tests.test_studio_projects_video tests.test_generation_audit tests.test_studio tests.test_canvas tests.test_studio_models -q`；`tsc --noEmit -p frontend/tsconfig.json`。完整精修前端已通过 Vite 构建；9120服务已加载新后端。

范围仅为本轮媒体节点与模型路由，不推断全部应用无bug、全部供应商型号都已付费生成成功，或视频严格满足画面质量要求。真实实付调用为 Image 01、Edit Plus、H3；其他目录型号由协议/能力校验覆盖，账号权限以供应商返回为准。没有提交、推送或发布。

协议来源：[MiniMax 文生图](https://platform.minimax.io/docs/api-reference/image-generation-t2i)、[H3 V2 创建](https://platform.minimax.io/docs/api-reference/video-generation-v2-create)、[H3 V2 查询](https://platform.minimax.io/docs/api-reference/video-generation-v2-query)、[Hailuo 图生视频](https://platform.minimax.io/docs/api-reference/video-generation-i2v)、[百炼 Qwen 图片 API](https://help.aliyun.com/zh/model-studio/qwen-image-api)。
