# 2026-10-08 画布取消选中与自由 Chat 修复

用户最新反馈：孤立删除按钮、空白处无法关闭编辑、自由 Chat 无反应。基线 21 项相关测试通过，实际页面仍复现问题；不把旧验收当成这次交互已通过。

## 修复

- 框选结束未清空 selection，浮层定位的字符串 style 又覆盖 x-show 的 display:none；定位改为仅绑定位置属性的对象，选中身份必须同时存在于 selectedIds 和有效节点。空白点击清理选中、编辑入口、模型/参考菜单及边选择；拖动画布/框选不误当点击。取消选择不删除图片提示词，重开和刷新保留。
- 编辑任务必须有真实图片；selection 和 imagePanel 同为空不再成为图片编辑任务。
- Chat 等待耐久保存并显示进行中状态，主页面展示保存错误和重试。用户截图项目实际读到 409 跨窗口版本冲突，之前错误藏在项目资料内；现在可进入恢复界面，先备份再读取最新进度，随后继续原 Chat 跳转。
- 恢复实测发现 localStorage 与 sessionStorage 同时满。备份在两者失败后写入 IndexedDB，事务完成后才清理旧收据/草稿，项目资料保留再次下载备份入口。按保存时间选最新备份。备份失败仍保留当前原稿。
- 新 Chat 建立时会触发 React 关联查询，提前清除 controller.workspace；连接过程固定原项目，关联落盘完成前暂停查询。实际 Chat 不再出现 undefined.id，保持项目与镜头目标，返回画布指向同一项目。
- 401 时重新读取同源凭据并仅重试一次原请求。409、网络未知结果不自动重发；原幂等收据及正文不变。此项验证为单元回归，没有重启用户本地服务作额外测试。

## 验收证据

独立项目 `interaction-qa-21cefb36-9fb2-492b-947b-b96400f78830`，原 BUV 项目 revision 38 保持不变，没有调用付费模型。

真实浏览器操作：选择图片 → 修图 → 输入草稿 → 点击画布空白 (840,460)；composer 与 context-toolbar 均不可见，无孤立删除按钮。重开修图、刷新后提示词仍在。自由 Chat 完成跳转，输入框可用，canvas-return 指向同一验收项目。

以另一个写入者推进验收项目 revision 后制造真实 409：页面显示冲突，原稿保留；点击查看与恢复 → 备份当前编辑并读取最新项目。Web Storage 满时 IndexedDB 备份完成，继续进入原项目 Chat；重开项目资料仍显示下载未保存编辑备份入口。IAB 未捕获下载事件，文件导出的下载完成不计通过；持久备份及重开入口已通过。

最终连续三轮每轮 **57 项通过**：studio-operations、studio-save、workspace-chat、chat-interactions、creator-flow。TypeScript 检查通过；重新生成本地前端产物以应用 Chat 修复，Vite 成功。两份截图报告无控制台错误、横向溢出或加载失败图片。

- `outputs/canvas-selection-chat/closed/page.png`：空白点击后浮层均关闭。
- `outputs/canvas-selection-chat/chat/page.png`：对应项目 Chat 可输入、已连接、可返回画布。
- `outputs/canvas-selection-chat/evidence.json`：结果与原项目版本核对。

本次范围是上述实际交互和保存/跳转恢复；没有重新评审整体审美，也不声称整个应用通过。旧页面需要刷新加载代码；原有版本冲突需要走有备份的恢复入口，不能无声覆盖另一窗口编辑。
