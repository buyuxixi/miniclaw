# 第二十五步：可视化裁剪与商品细节对照

日期：2026-10-04。用户授权“继续优化，你自己安排”。优先减少图片节点的坐标输入和缩略图核对负担，沿用单主Chat、共享依据和节点工作台。

## 已完成与操作入口

图片方案→预览截图裁剪：完整截图上显示两条保留边界及遮罩，可拖动上下沿；键盘方向键微调，Shift按10像素移动，Home/End到合法边界。“精确调整边界”折叠数字输入。改动范围后，应用按钮禁用，必须更新真实PNG预览后再确认；原图保留，可撤销。窄屏拖柄文字至少12px，可视柄至少28px高，触摸命中区至少44px高。更新预览/保存期间禁用操作并阻止Esc提前退出，避免产生“已放弃”的错误印象。

图片修改前后对比→放大对照商品细节：原图和候选并排显示，100%适配窗口宽度，最大400%；两边共享倍率，滚动按相对位置联动。可以恢复全图、关闭或Esc返回，滚动区可键盘访问。不同尺寸或构图不自动对齐；放大查看不采用候选、不修改核对记录。切换owner/素材关闭旧对照，不让上一商品窗口留在新项目。

## 原生真实素材复验

首次上手复验 · 深绿茶壶：保留Creator bb26610bd6d24ac78643ac0aab6dfb51/v4。原生撤销上轮裁剪回完整1280×2778截图，再打开建议范围。桌面实际拖动至y884..1788，更新预览得到1280×904；窄屏发现原拖柄太小，修正最小尺寸后重新实测拖动，再用键盘微调到y860..1810，更新真实预览并确认1280×950。操作没有依赖展开数字输入。

最终工作画布94014b0eb93f4a6aa37f87b2cb58b60d/revision5/cursor2。通过主Chat返回项目并重新打开，Canvas文档和历史完全等于应用后快照；导出逐像素等于原截图RGBA.crop(0,860,1280,1810)。仍未将首次任务工作图采用为封面或新增主稿。

乳白茶壶原生打开旧百炼候选：桌面150%放大、水平联动滚动；窄屏400%上限、键盘及水平滚动、恢复100%、Esc关闭。细纹变平更易对照，但这只是查看工具，未实现自动纹理审核。旧任务69675419c1d96fff25e4a8434de30fd2的未采用决定及原因保持；采用按钮仍禁用。GET-only collector断言白壶任务和画布、两正式Creator及封面文件、首次Creator都和试跑前完全相同；变化仅首次任务工作画布的原生撤销/重新确认裁剪。

## 实现、检查和审查

新增ImageDetailReview复用ImageComparison已认证获取的blob；没有新的下载服务、依赖或数据库字段。CropReview使用SVG范围、Pointer Capture及ResizeObserver，边界限制仍由cropDocument/服务文档校验与冻结revision保护；没有把UI绘制当实际图片结果。

- 基线：两个相关文件9项通过。
- 最终前端八文件52项通过（visual-review、candidate-review、canvas-interactions、creator-interactions、chat-interactions、creator-flow、photo-design、session-resume）。新增回归验证拖动夹紧、键盘调整、空输入/旧预览不能应用、busy时Esc、联动滚动、恢复全图、切owner关闭旧窗口。
- TypeScript/Vite生产构建通过，git diff --check通过，既有工作树和Hermes子模块保持。
- 原生1440×900和约320×672实测；恢复临时viewport并保留工作台。没有实体触摸设备测试，不能把鼠标窄屏拖动写成手机触摸验收。
- 本轮没有后端改动；未重跑后端/API套件，不把上一轮15项Canvas作为新检查。没有新的图片生成、模型Chat、配音、视频、Blender或平台发布。

审查在本轮范围未发现未解决的工程阻断项。普通创作者独立完成率/耗时、商业摄影质感、AI事实正确性和不同构图逐像素对齐未验。最小尺寸修正源于真实窄屏观察；同步相对滚动不能保证重构商品部件一一对应，仍需人工核对。

## 证据与评价

outputs/visual-review-v5包含crop-drag-desktop.png、crop-drag-narrow.png、detail-desktop.png、detail-narrow.png、green-cropped-applied.png、green-cropped-reopened.png、evidence-before/applied/reopened/final.json。收集器.codex/verification/collect_visual_review.py只GET/读原文件，不替代原生操作。

沿用第二十一步评价体系：本轮改善起步和核对成本，原图及采用封面不变，不因此提高照片或口播分数。现有工作台还需要更明确的已处理状态和自然语言修改范围、可信商品资料及更好的摄影结果；不能用功能完成替代普通用户体验验收。
