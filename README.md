# miniclaw

基于 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 二次开发的 Web 聊天智能体，用于个人 Agent 工程学习与电商业务实践。

第一版先跑通普通聊天与工具执行。后续按业务需要扩展商品图片编辑、口播与内容辅助，不为覆盖概念提前加入复杂架构。

## 当前能力

- 左侧会话列表与新对话，中间 Markdown 回复，底部多行输入。
- 流式输出、发送与停止；可展开查看工具参数和结果。
- 保存聊天，刷新后恢复；后端重启后可手动重连。
- 两项默认只读工具：列目录、读取UTF-8教学文本；可选技能读取与受限文本产物工具。
- 已用 DeepSeek `deepseek-flash` 验证真实聊天和工具闭环。
- 侧栏会话搜索、改名、列表分页、归档与恢复；各会话草稿隔离、刷新保留。
- 独立设置中的技能添加/导入/编辑/启停、版本化工具依赖绑定、工具配置与实际加载状态、手动长期记忆维护；输入框独立选择技能。
- 图片与UTF-8 TXT/Markdown附件：上传、预览、移除、发送、历史恢复；视觉能力不足时明确提示。

界面与浏览器状态管理在 `frontend/` 中实现；连接协议复用 Hermes 的共享 JSON-RPC 客户端。模型调用、Agent loop、工具分发和 SQLite 持久化继续由 Hermes 完成。

## Windows 首次安装

先安装 Git for Windows、Node.js 22.12+（推荐 24 LTS，含 npm）和 uv，并确保 `git`、`node`、`npm`、`uv` 在 PATH 中。Python 由 uv 按需准备，使用 3.12；不需要 Docker。

```powershell
git clone --recurse-submodules --shallow-submodules https://github.com/buyuxixi/miniclaw.git
cd miniclaw
.\scripts\setup.ps1
```

`setup` 初始化固定提交的上游 submodule；使用上游 `uv.lock` 创建根目录 `.venv`，安装 web/dev 依赖；按前端锁文件运行 `npm ci`；最后创建缺失的本地配置与插件目录链接。已有配置和 Key 不会被覆盖。

在本地 `.hermes/.env` 填入模型 Key：

```dotenv
DEEPSEEK_API_KEY=你的真实Key
```

随后构建和启动：

```powershell
.\scripts\miniclaw.ps1 build
.\scripts\miniclaw.ps1 web
```

打开 [miniclaw 工作台](http://127.0.0.1:9120/)。终端保持运行，按 Ctrl+C 停止。Python 服务同时提供前端页面和后端接口，不需要再启动一个前端服务。

如果只执行过普通 `git clone`，可先运行 `git submodule update --init --recursive`；`setup` 也会执行该步骤。当前安装脚本面向 Windows，Linux 服务器部署留到后续阶段。

## 日常启动与二次开发

```powershell
# 日常启动；启动前确认旧进程已关闭
.\scripts\miniclaw.ps1 web

# 修改前端后重新构建，再刷新浏览器
.\scripts\miniclaw.ps1 build

# 仅补齐缺失配置和插件链接，不重新安装依赖
.\scripts\miniclaw.ps1 prepare

# 插件边界、基础API、SQLite重开与前端行为检查；不调用模型
.\scripts\miniclaw.ps1 test
```

`prepare` 是初始化，不是依赖安装。修改 Key 或插件源码后重启服务。模型与工具配置位于 `.hermes/config.yaml`；凭据始终由 Python 后端读取，不发送到浏览器。

启动脚本默认从 PATH 查找运行时。使用非标准安装目录时，可创建被 Git 忽略的 `runtime.local.json`：

```json
{
  "node": "C:/tools/nodejs/node.exe",
  "npm_cli": "C:/tools/nodejs/node_modules/npm/bin/npm-cli.js",
  "uv": "C:/tools/uv/uv.exe"
}
```

工具选择使用真实 `platform_toolsets.cli` 配置；启动器检查显式列表，再桥接到上游既有 `HERMES_TUI_TOOLSETS` 固定列表，避免 GUI 追加其他工具。空列表、all 和未知工具集会阻止启动。

## 目录与上游管理

```text
hermes-agent/              官方上游 Git submodule，固定提交
frontend/                 miniclaw React 前端、测试与锁文件
plugins/miniclaw-files/    受限文本读取与可选文本产物工具
miniclaw_web/              项目REST/RPC适配、附件、依赖与显示存储
scripts/                  安装、初始化、启动与验证
workspace/                虚构教学素材
patches/                  可选的上游测试调整；不自动应用
UPSTREAM.json             上游提交与验证环境记录
THIRD_PARTY_NOTICES.md     第三方源码说明
.hermes/                  本地配置、Key、日志和会话数据库，不入库
.venv/                    Python 环境，不入库
runtime.local.json        可选本机运行时路径，不入库
```

上游固定为 `v2026.9.24` / `f97608f178d1ffeca59860195ab7da295f7c8e5f`。前端从该目录引用共享客户端，因此不要省略 submodule。安装脚本会核对提交与 `UPSTREAM.json` 一致。

插件通过 Windows Junction 接入 `.hermes/plugins/`，修改源码后重启加载。Hermes 生产核心未修改；首次本机调试中对 ConPTY 测试做过一项调整，已单独保存为可选 patch，干净克隆默认保持官方源码。升级上游需要同时评估客户端协议、配置选择和历史消息契约。

原上游 Dashboard 可通过 `miniclaw.ps1 dashboard` 在 9119 运行，是终端式诊断入口。干净克隆若要使用它，需要在 `hermes-agent/` 按其文档安装 web/ui-tui 的 npm 依赖，再运行 `miniclaw.ps1 build-upstream`；普通 miniclaw Web 不需要这些构建。

## 验证与练习

“设置 → 开发者 → 上下文诊断”可查看当前运行时用量、分类估算、文件加载清单、模型工具与历史恢复规则，并手动调用 Hermes 压缩。实际恢复检查及零模型费用的压缩结构演示见 [上下文实战](docs/context-learning.md)。面板快照不等于完整模型 API 请求。

本次基础能力的使用路径、架构、工具绑定、附件与记忆实现，以及验证限制见[基础Agent实现](docs/basic-agent.md)。本机已验证TypeScript/Vite构建、18项前端行为检查、13项基础API检查、文件工具2项成功/10项拒绝，以及SQLite保存重开。

真实浏览器验证过多轮聊天、新会话边界、目录与文件工具、缺失文件失败、流式显示、停止、刷新恢复和后端重启后的旧页面重连。权限复核纠正过错误的配置字段，并在修正后重新验证真实 GUI agent 仅开放两个文件工具及模型工具闭环。

服务启动且已配置 Key 时，可检查实际 GUI agent 的工具 schema；该检查创建临时运行会话，不提交提示词、不调用模型：

```powershell
.\.venv\Scripts\python.exe .\scripts\verify_gateway.py
```

`inspect_acceptance.py` 专门检查开发机先前的三场固定验收记录，不是新克隆必须运行的通用测试。数据库消息检查也不等于捕获了实际模型 API 的完整上下文。

先发送：“列出教学目录，再读取 product-note.md，区分已知信息和缺少的证据。”展开工具卡片，比较文件事实、模型推断和缺少证据。接着请求“读取 missing.txt”，比较程序错误与模型解释。

## 当前限制

当前只绑定 `127.0.0.1`，面向受信任的本机单人使用。上游仍有管理接口，工具限制不等于应用级操作系统沙箱。多人登录、会话与文件隔离、公网部署尚未实现。

侧栏首屏20场，可加载更早对话。正文/ID搜索最多100个结果，标题检索扫描分页元数据。工具结果补齐最近500条存储消息，更早卡片显示“结果未加载”。主聊天滚动分页和压缩祖先跳转尚未实现。运行中禁止切换会话或提交第二条消息；断线需手动重连。提交超时不自动重发，以避免重复执行。

文件工具限制在教学目录内，拒绝绝对路径、越界路径、隐藏文件和未知参数；最多列100项、读64 KiB文本。尚未处理恶意进程同时替换文件等竞争情况。

短期记忆复用会话历史；长期记忆与个人偏好默认关闭，可在设置中手动维护并选择加载。当前工具集未开放模型写入记忆。技能依赖与工具权限分别管理，绑定随正文hash变化失效；声明工具齐备仍需维护者核对运行环境。PDF/Word/Excel/幻灯片脚本缺少terminal，选择与提交前提示限制；此次未开放任意终端。开启原生技能读取组后，新Agent注入技能索引，并可按需查阅正文。添加支持单个SKILL.md，不自动安装脚本环境。

图片与TXT/Markdown附件已实现，每轮最多4个；文本单文件64 KiB/合计128 KiB，图片单文件5 MiB/2000万像素。上传先保存到本机，发送时交给模型；移除只取消引用，暂无总磁盘配额与过期清理。真实链路验证不保证模型视觉判断准确。

智能路由、敏感拦截等待用户共同设计；未来智能路由先选择处理流程。工具绑定采用项目version 1契约，未核对或接入aiwa协议。

配置为12轮/180秒运行预算，触发边界还未专门验收。修图、更多工具、聊天正文滚动分页、压缩祖先附件浏览、完整模型上下文追踪留在后续。教学商品为虚构素材；不可信文件示例不是程序执行指令。

本次验证的 Python 3.12.10 内置 SQLite 3.49.1 触发上游 WAL-reset 保护，自动使用 DELETE 模式；不应根据配置宣称实际启用了 WAL。新安装的解释器版本可能不同，应以运行诊断为准。

第三方许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。根项目代码的许可尚未选定。
