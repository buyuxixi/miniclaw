# SRT 驱动的口播动效编排

这一轮把“录制后的真实字幕 → 动效编排文件”接入现有 Chat。使用同一个 Hermes，视频渲染在独立本机 Overlay 工作台完成；没有新增 Agent、通用剪辑器或发布接口。

进度和所有功能的串行验收入口见[进度总表](project-progress.md)。用户暂时不方便实际验证，自己的素材体验保持为“待验收”，不阻塞开发者独立检查。

## 功能一：SRT 附件

实现流程：浏览器允许选择 `.srt` → 后端按 UTF-8 文本校验 → 保存本机不可变附件与聊天归属 → 本轮发送给模型 → 历史保存附件引用。沿用文本64 KiB、每轮4个附件、文本合计128 KiB限制。视频文件不发送给模型。

入口：Chat 的“添加附件”，选择真实字幕文件。仅需分析字幕时可以普通聊天；使用动效编排时，本轮上传一份 SRT。

验证步骤：

1. 上传一个正常 UTF-8 `.srt`，确认附件名称出现，可预览/移除；发送后刷新仍可找回。
2. 测试超过64 KiB的字幕或非UTF-8文本，预期明确拒绝。
3. 删除附件引用后再发送，预期不会继续把旧字幕作为本轮编排来源。

开发者已验证：实际上传API、归属拒绝、文本大小限制与历史引用；前端文件大小检查。SRT不可信正文和解析后的cue列表都会中和Hermes的 `@file:` 等上下文引用标记，避免附件文字触发预处理读取。

## 功能二：口播动效编排 Skill 与编译工具

实现流程：

```text
本轮SRT附件
  → 服务器按owner读取原字幕、严格解析cue、冻结正文hash
  → overlay-plan Skill选择少量重点、card kind与cue范围
  → miniclaw_overlay_compile复核实际工具与本轮SRT引用
  → 程序从原字幕计算start/end，检查卡片和摘录
  → 独占创建artifacts/*.json
  → 既有工具卡片提供认证下载
```

模型不能提交自定义时间、字幕正文替身、宿主路径、媒体URL或执行代码。编排文件只保存已校验的公共 `OverlayDoc version:1` 格式；源字幕ID/hash保留在工具结果与聊天记录中，不添加外部工作台不需要的字段。

新增“设置 → 工具 → 视频动效编排”，默认未启用。保存后新建对话，在“选择技能”选“口播动效编排”，上传SRT并发送：

> 按本轮真实字幕挑2–5处重点，生成不重叠的简洁文字动效。优先短重点和金句，保存为我的口播-v1.json。不要加新事实、署名或视频路径。

展开“生成动效编排”工具卡片，成功时点击下载JSON。失败时会给原因，没有成功结果不能当作文件已生成。文件存在时不会覆盖，需要新的版本名。

第一版支持3种文字动效：

| kind | 用途 | 摘录参数 | 位置 |
|---|---|---|---|
| punch-pill | 短重点 | text，最多60字 | top-left/top-right/bottom |
| quote-lockup | 金句 | quote，最多100字，竖线分行 | left/right，署名固定为空 |
| type-shift | 多行收尾 | lines，最多120字，竖线分行 | left/right/center，重排800–4000ms |

程序边界：SRT最多500条/2小时，支持BOM、CRLF和多行正文；坏块、重复原编号、倒序/重叠时间均明确拒绝，不默默丢条。cue编号从1按文件顺序，与原SRT编号可能不同。1–32张卡、唯一id、已知类型、有效cue范围、每张0.6–30秒且互不重叠；文字逐段须是引用字幕的摘录。强调色限定blue/alert/orange，位置固定允许列表，不接受媒体、任意CSS、偏移、字体文件、lintOff或未知参数。

实现入口：`miniclaw_web/overlay.py` 负责解析、编译、当前轮归属检查；`runtime.py` 冻结本轮来源并在提交拒绝时恢复旧快照；`plugins/miniclaw-files` 注册受限工具并复用既有独占产物写入；`Message.tsx` 复用认证下载卡片。`skills/overlay-plan/SKILL.md` 定义输出、工具与失败行为。安装继续使用`prepare`，正文变化仍需重新核对依赖。

验证命令：

```powershell
.\scripts\miniclaw.ps1 test
.\scripts\miniclaw.ps1 build

# 服务运行时：实际工具schema与绑定，不调用模型
.\.venv\Scripts\python.exe scripts/verify_overlay_live.py

# 可选：一次配置模型调用，虚构SRT，生成JSON，最终恢复原工具选择
.\.venv\Scripts\python.exe scripts/verify_overlay_live.py --model
```

开发者已验证：88项自动检查（38前端、23基础API、8图片、12画布、6字幕编译/工具、1安装），既有文件边界与SQLite重开通过；tsc/Vite通过。真实模型只调用一次编译工具，得到2张卡；输出时间精确为0.25–2.5s、3–5.5s，与上传字幕相同；认证下载与文件字节相同，原工具配置恢复。

人工验证步骤：上传自己的字幕生成文件；对照原字幕核对每张卡的文字和时间；试一次越界cue/不存在类型，预期不写文件；不附字幕的下一轮不能偷偷复用旧来源。摘录检查不证明观点没有断章取义，也不证明字幕与实际视频对齐，最终仍需播放确认。

## 功能三：独立 Overlay 试跑

来源为 [jeszhou/overlay-studio](https://github.com/jeszhou/overlay-studio)，固定提交`836e68cd1aea54e0c73fa712aaf8aca4151c9fc2`。源码、依赖和测试导出在被Git忽略的 `.codex/tools/`，没有复制到miniclaw生产目录。适配器独立实现，只使用文件类型和参数契约。原软件的自用、分发与对外服务限制参见其LICENSE，本项目没有把它作为公开内置服务。

本机准备流程：取得同提交的官方源归档 → 按锁运行npm ci → 构建/卡片检查 → 配置本地FFmpeg、ffprobe与匹配的Chrome for Testing → 用127.0.0.1启动既有Vite → 将miniclaw生成的同一JSON送入官方export接口 → 核对MOV和实际帧。

本机工作台：[Overlay Studio](http://127.0.0.1:5177/)。首次使用有授权协议页面，需要你阅读并决定确认；开发者没有代你点击同意。官方导出专用视图用于CLI渲染，不修改授权页面。

安装遇到的实际问题与处理：

- npm的Chromium下载长时间没有进展；核对准确安装进程的工作目录后结束它，使用同版本的官方Chrome for Testing归档，再按锁安装并跳过重复下载。没有修改全局PATH或替换日常浏览器。
- 上游`check:motion`用Windows反斜杠路径生成ID，与POSIX豁免台账不一致。私有副本仅将路径统一为斜杠；台账和动画不改，`check:cards`通过。生产miniclaw未复制该脚本。
- 外部服务仅绑定127.0.0.1，使用自有启动辅助文件关闭自动打开浏览器。预览/导出是开发服务器能力，不能把静态build部署当作完整导出后端。

本机重新启动（若5177仍在运行，不要重复启动）：

```powershell
$overlayRoot = 'E:\AI\miniclaw\.codex\tools\overlay-studio-836e68cd1aea54e0c73fa712aaf8aca4151c9fc2\motion-playground'
$mediaRoot = 'E:\AI\miniclaw\.codex\tools\media-runtime'
$env:PATH = "$mediaRoot;$mediaRoot\node_modules\ffprobe-static\bin\win32\x64;" + $env:PATH
$env:PUPPETEER_EXECUTABLE_PATH = "$mediaRoot\chrome-win64\chrome.exe"
Set-Location $overlayRoot
node miniclaw-launch.mjs
```

这些是本机私用目录，干净克隆不会自带第三方源码和二进制。换机器先按上游安装指南取得指定版本，再准备对应工具；不把本机依赖打入生产仓库。miniclaw运行与编排JSON不依赖外部工作台已启动。

开发者实际导出结果（虚构字幕，没有真实录制视频）：同一模型生成JSON经官方导出接口成功渲染66帧，5.5秒/12fps，MOV为1920×1080 ProRes 4444（ap4h/yuva444p10le），大小6,269,070字节，另有47,376字节WebM。用时118.53秒。MOV的1秒和4秒帧实际解码，透明像素与不透明文字共存，人工查看中文“陶瓷杯”“每天一杯，慢一点。”可读。正式29.97fps长视频性能、真实音画、9:16布局均未据此验收。

用户之后的验证步骤：

1. 准备自己的30–60秒口播视频，用剪辑工具导出同一版本的SRT。
2. 在miniclaw生成JSON，下载后到Overlay导入；加载同一视频/SRT。
3. 播放并确认文字、人物位置、时间与原视频对应；修改位置、主题或换卡后再预览。
4. 导出透明MOV；在剪辑软件置顶轨道覆盖原视频，保留原视频音轨，导出最终MP4。
5. 确认MP4可播放、中文字幕可读、没有挡脸或丢卡、声音与字幕一致；记录耗时和最终修改。

当前外部画布为横版1920×1080。这是文件连接与横版渲染验证，不代表9:16适配完成。没有真实录制素材、完整剪辑、自动字幕、配音或发布结果。新工具只生成文字动效JSON，也不接受视频素材路径。

## 下一步

后续已实现本机视频合成、原创9:16文字卡、固定创作任务和发布包，见[视频报告](acceptance/03-video-composition.md)、[工作台报告](acceptance/04-creator-workspace.md)、[发布包报告](acceptance/05-publish-package.md)。通过文件交换连接已有步骤，用户真实效果留待串行验收。本机原创文字卡不依赖外部Overlay已启动；独立Overlay仍按其许可私用，当前没有对外提供其服务或复制其渲染器。
