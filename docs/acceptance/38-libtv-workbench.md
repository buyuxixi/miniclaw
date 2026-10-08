# LibTV 工作区复刻与打磨

方向：按用户提供的 LibTV 原型保留深色媒体画布、独立媒体节点、细曲线、多参考缩略图和选中节点旁的操作面板。项目资料、Chat、剪辑导出延续同一工作区密度，去掉欢迎页大标题、三张模板卡片、重复画布名称栏与底部跳转栏。字体以 12–13px 为正文、17px 为弹窗标题；边界用中性灰，蓝色只用于连接和选中反馈。

主要操作：拖入多个素材连接同一视频，选择与任务匹配的模型，再生成；Chat 与画布保持项目关联；已采用片段在导出页可直接预览并本地合成。

保存：内容修改立即备份，600ms 防抖异步保存；视图选择不保存项目。版本冲突保留原编辑与幂等请求，停止自动重试，固定浮层提示不改变画布高度。需要用户处理的冲突不自动覆盖其他窗口的内容。

动效：选中视频时输入边的蓝色光线沿曲线流动；项目资料与编辑页短暂淡入；Chat 进入与输入框聚焦反馈。系统减少动效时停止动画。

验收：1920×1000、1280×720 与窄屏；长文件名、多图连接后刷新、断开与撤销、保存失败后编辑保留、冲突期间布局稳定、Chat 关联导航、片段预览与导出入口。付费生成不作为本次回归操作；服务器已有模型能力验证仍必须保留。


## 实际验证（2026-10-08）

最终三个连续回归：10:27:13、10:27:20、10:27:30 开始，每轮前端 64/64、后端 20/20 通过。记录 `outputs/libtv-workbench/final-regression.txt`。TypeScript 检查通过，当前本地服务已使用新 React 静态产物。

命令：

```powershell
node frontend/node_modules/vitest/vitest.mjs run src/studio-save.test.js src/studio-operations.test.js src/workspace-chat.test.ts src/chat-interactions.test.tsx src/creator-flow.test.tsx --root frontend
.venv/Scripts/python.exe -m unittest tests.test_studio_projects_video tests.test_studio_models
node frontend/node_modules/typescript/bin/tsc -p frontend/tsconfig.json --noEmit
```

实际浏览器从画布入口完成多图添加、刷新读回、Chat 往返和未发送草稿保留。隔离项目三张素材（产品主体、包装、叶子侧光参考）连接同一 H3 视频节点；第二张图片使首帧模式转为多图参考；模式切换保留全部引用。测试覆盖断开、撤销、节点独立模型和不支持多图模型的前后端限制。

保存几何：画布宽 1280、高 672、顶部 48；真实编辑保存与 409 版本冲突出现前后均相同。冲突前后 world transform 均为 `translate(241.8px, 52.5px) scale(0.55)`。冲突保留最新提示词；点击“备份并读取更新”后显示新共同要求、项目已保存和“下载编辑备份”入口。浏览器未捕获下载事件，所以不把备份文件下载计为通过。持久备份与缓存满的恢复由测试覆盖。

原 BUV 项目 `project-43091686-0e57-441f-bb96-360d0013be3b` 仍是 revision 38，未改原素材、采用关系或成片。新隔离项目 `workbench-qa-f7e616bf-0bb7-44de-8e5a-085ed3ed2e62` 目前 revision 6。导出预览使用既有 model-qa 项目的真实 5 秒历史叶子视频，未将其当成新生成的产品片。

## 图像与动效证据

最终交付画面（均已实际查看）：

- `outputs/libtv-workbench/delivered-canvas/motion-end.jpg`，1920×1000：三图汇入视频、流光、连线绕开节点和编辑面板。
- `outputs/libtv-workbench/delivered-chat/motion-end.jpg`，1280×800：项目摘要/动作与输入区相邻，名称只保留在顶栏。
- `outputs/libtv-workbench/final-project/motion-end.jpg`，1280×800：项目资料、镜头缩略图、模型费用分类。
- `outputs/libtv-workbench/delivered-export/motion-end.jpg`，1280×800：真实视频预览、导出规格、已采用 5/10 秒、视频轨道。
- `outputs/libtv-workbench/final-models/page-@2x.png`：DPR 2 模型菜单细节，不能称为浏览器 200% 缩放。
- 窄屏390×844：`delivered-chat-narrow/page.png`、`delivered-export-narrow/page.png`。后者滚到底可见导出与轨道。

三个基本动效和入口证据：

| 触发 | 录屏 |
| --- | --- |
| 选中视频，输入曲线蓝色高光循环 | `outputs/libtv-workbench/delivered-canvas/record.mp4` |
| 打开项目资料，遮罩/弹层淡入 | `outputs/libtv-workbench/final-project/record.mp4` |
| 聚焦 Chat，边框与快捷键提示反馈 | `outputs/libtv-workbench/delivered-chat/record.mp4` |
| 从画布进入 Chat，读取状态与上下文出场 | `outputs/libtv-workbench/delivered-entry/record.mp4` |

每个录屏目录含开始、中间、结束三帧和 report.json。截图工具未报告控制台错误、横向溢出或图片加载失败。此结论不等于接口调用、下载、帧率或费用验收；未测 FPS。

## 独立评审与收尾

三轮隔离评审分别 7/10、7/10、8/10，达到三轮上限，未宣称达到9分。按反馈修了竖屏媒体比例、画布底部工具栏、素材边界、对象/提示词对应、连线穿过素材、Chat恢复闪跳、导出5/10秒采用摘要。最后一轮指出的重复Chat标题、重复导出跳转栏、编辑面板遮线均已修，并重新截图/连续回归；收尾版本未再次打分。

删除了“今天想完成什么”、三张通用欢迎卡片、重复的画布名称栏/底部成片跳转栏、“把采用的片段连成一支短片”、巨大的预览说明文字、Chat正文重复项目名、导出额外返回横栏。对象名称、生成模型、关键状态与失败恢复保留。

剩余范围：这是用户所指出工作区的实现与视觉返工，不是整个 LibTV 所有工具的完整复刻；其逐帧拉片、高清增强、智能去字幕等工具未在本轮新增。Chat仍支持原有对话/技能/附件/结果，但全部有消息、工具展开、设置等状态未做全套视觉截图。新付费生成、真实供应商扣费、成片画质与大规模画布性能未在本轮复验。保存仍有同步本地草稿备份，后台网络保存不移动界面；不是将数据耐久性完全改为异步。

Oil UI 当前0.16.5，检查提示0.16.8可更新。本轮没有更新技能；可用命令：

```powershell
E:\AI\miniclaw\.venv\Scripts\python.exe C:\Users\bocai\.codex\skills\oil-ui-pro\scripts\check_update.py --update
```
