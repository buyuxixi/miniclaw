# 自由画布返工与 MiniMax 实测（2026-10-07）

用户指出原生项目菜单白底、素材/视频拖不动、无法手动连线、空口播删不掉、备注用途不清及遗漏 MiniMax。上一轮只验证部分状态与脚本，没有覆盖真实 DOM 和完整指针入口，不能作为画布验收。

本轮沿用深色中性灰与品牌紫，按 LibTV 的端口操作方式补基本画布行为。没有改成另一套工作流，也没有给视觉效果打分。

## 实际改动

- 原生项目菜单应用 dark color-scheme；已展开检查实际深色表面。
- 图片本体、备注正文与成功视频画面可以拖动；播放器底部控制区域保留原生输入。视频结果有独立对象 ID，位置/收起状态进入 canvasLayout，支持刷新和撤销。
- 图片或备注右端口可拖到片段左端口，也可依次点击端口。连接更新 first/refs/briefSource；点击输入端口可查看来源、断开并撤销。输入线绕节点上方；结果线检测其他节点，遇到遮挡改走节点组外侧。选中关系显示名称和方向。
- 口播只在用户明确添加后建立；删除使用 x-if 移除 DOM，修复 x-show 的 display:none 被定位 :style 覆盖。保留删除、撤销和共享项目保存。
- “方案”入口改为“创意备注”：保存 Chat 想法与讨论来源，作为片段创意依据。画面运动仍在片段中设置；备注不是必填步骤。删除没有动作的历史模型小字。
- 已配置 MiniMax 时默认使用 MiniMax；生成弹窗可选择供应商。兼容已有 MINIMAX_API，亦支持 MINIMAX_API_KEY；密钥仅留后端。旧万相任务按已记录供应商继续查询。

## 真实功能证据

证据目录：`outputs/canvas-repair/`。UI 操作使用 Oil UI 的 Windows 截图工具副本，独立临时 Edge；接口回读确认持久状态。测试副本与原项目的素材/采用关系隔离。原项目布局已整理，返工前坐标快照保留在 original-project.json。

- `drag-image/motion-*.jpg`：从图片本体拖动，曲线跟随；保存后位置读回。
- `success-video-drag-final/motion-*.jpg`：从真实成功视频画面拖动；刷新后 canvasLayout 为 x=1326.153846、y=415.299145。
- `video-routing-fixed/page.png`：同一移动位置，结果线绕开 O2，避免 O1→O2 假连接。
- `success-playback/motion-end.jpg`：真实播放器显示 0:01 / 0:05；不把错误结果卡当成功视频证据。
- `port-drag-undo/frames/f0045.jpg`：拖动端口后 O2 首帧实际变为斜放产品图；随后撤销恢复正面图，服务端 revision 13→14。
- `disconnect-undo-verified/motion-*.jpg`：断开和撤销；服务端 revision 10→11→12。
- `narration-add/page.png`、`narration-delete/page.png`：新增后 removed=false（revision 6），删除后 removed=true（revision 7）；新浏览器读回没有口播 DOM。即时刷新与保存失败另由既有保存回归覆盖。
- `dark-project-menu/page.png`：原生菜单展开态。
- `final-original/page-1920x1000.png`、`page-1280x720.png`：默认工作尺度、矮桌面窗口，无控制台错误、横向溢出或图片加载错误。
- `minimax-model-dialog/page.png`：模型选择和原生6秒计费/5秒输出提示。

拖动工具三帧没有覆盖每个运动时刻；不据此宣称所有位置的避让或拖动性能都已验证。独立视觉复核确认深色菜单、61%工作尺度、实际播放态；第二轮发现移动结果线假连接，修复后第三轮确认该位置的缺陷消除。功能与持久化结论依据 UI 操作及接口回读，不依赖静态图推断。

## MiniMax 真实生成

通过生成弹窗提交一次 MiniMax-Hailuo-2.3 / 768P / 6秒任务，在测试副本完成查询、下载、转码和播放。供应商 task_id=449869534654852；请求6秒，下载文件探测5.875秒，输出裁为5.000秒、768×1364、H.264、无音轨。产物：`minimax-5s.mp4`；安全状态记录：`minimax-status.json`。未替换原项目已采用视频，未将技术生成成功认定为产品画面效果验收。

实际下载地址使用 MiniMax 返回的具体阿里云 CDN；校验补入该精确域名，未开放任意云存储域名。该任务通过查询原 task_id 恢复，没有为下载问题再提交付费生成。未知提交状态不自动重试 POST。

原 ¥1.00 为万相 2.2 Flash 按参考单价 ¥0.20/秒×5秒估算，来源是阿里云模型价格页，不是 MiniMax 价格或已核对账单。MiniMax 本轮未取得可核对金额，estimate_cny 与 actual_cny 均保持 null，UI 显示“费用待账单核对”；计费用量记录完整6秒请求，输出时长另记5秒。

来源：[MiniMax 图生视频](https://platform.minimax.cn/docs/api-reference/video-generation-i2v)、[MiniMax 计费](https://platform.minimax.cn/docs/guides/pricing-paygo)、[万相参考价格](https://help.aliyun.com/zh/model-studio/model-pricing)。

## 最终连续三轮验证

| 轮次 | 画布/保存前端 | 项目/视频/审计后端 | TypeScript |
| --- | --- | --- | --- |
| 1 | 16通过 | 31通过 | 通过 |
| 2 | 16通过 | 31通过 | 通过 |
| 3 | 16通过 | 31通过 | 通过 |

命令：`vitest run src/studio-operations.test.js src/studio-save.test.js --root frontend`；`python -m unittest tests.test_studio_projects_video tests.test_generation_audit tests.test_studio -q`；`tsc --noEmit -p frontend/tsconfig.json`。日志为 frontend-run-1/2/3.log、backend-run-1/2/3.log、typecheck-run-1/2/3.log。

补充覆盖：真实播放器拖动入口/控制区、图片按钮入口、多个对象联合删除后一次撤销、结果移动后避开另一个镜头、结果布局保存、旧客户端省略新字段仍保留位置、MiniMax 原任务恢复及下载域名校验。9120 服务已重新加载代码并返回 READY。

范围仅限上述画布行为与 MiniMax 首帧生成链路；没有重新验收整个 Chat、精修、多人并发、配音或全部导出流程。
