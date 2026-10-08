# 第三方源码与依赖

`hermes-agent/` 是 [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) 的 Git submodule，固定提交 `f97608f178d1ffeca59860195ab7da295f7c8e5f`（`v2026.9.24`）。该提交的源码采用 MIT License，完整许可和版权声明保留在 `hermes-agent/LICENSE` 中。

miniclaw 前端直接引用该 submodule 中的共享 JSON-RPC 客户端；Agent 运行时、模型调用、工具注册与 SQLite 存储也来自 Hermes。这里没有把上游源码声明为 miniclaw 原创。

前端依赖及精确版本见 `frontend/package.json` 和 `frontend/package-lock.json`；Python 依赖与许可信息由上游 `pyproject.toml`、`uv.lock` 和对应包提供。

根目录 miniclaw 自有代码的许可尚未选定，本版不新增根 LICENSE。

本机视频合成的Python编排、Pillow文字布局与任务/打包代码为独立实现，调用用户本机FFmpeg/FFprobe；没有移植Overlay组件。FFmpeg程序、Windows字体、Windows SAPI语音及测试导出不随仓库分发；使用/再分发各工具仍须遵循各自许可。验收脚本的本机合成语音只用于自制技术样片，不代表应用新增TTS服务。

口播动效编排适配 [jeszhou/overlay-studio](https://github.com/jeszhou/overlay-studio) 提交 `836e68cd1aea54e0c73fa712aaf8aca4151c9fc2` 的公共JSON字段（version/cards/kind/start/end/params与三种文字卡参数）。SRT解析、验证、受限工具和产物写入为独立实现；没有复制该项目的组件、渲染器、原Skill或示例作品。开发机私用副本及运行时不在仓库分发范围内，仍须遵循上游自有授权协议；不能据此适配宣称获得内置分发或对外服务授权。

`skills/mono-color/` 包含 [Yan Liu 的 mono-color-skill](https://github.com/yanliudesign/mono-color-skill) 的软件设计目录（固定提交 `c8ff70597ddedcd65f21a0b528f6a70c35690b0a`），采用 MIT License，完整声明保留在该目录的 `LICENSE`。miniclaw 的入口与设计方法摘要为适配版本；来源记录见 `UPSTREAM.json`。上游 examples 和第三方参考作品没有复制，也不属于此软件许可的打包范围。

图片编辑接入参考了 [yuyuanweb/ai-picture-editor](https://github.com/yuyuanweb/ai-picture-editor) 的功能与 Provider 结构（审阅提交 `49f6ad8c96740a68b7e6228a47e8e2be6876eb34`）。本仓库未复制其应用源码；图片工作区、执行器、工具和百炼适配为独立实现，使用既有 Pillow/httpx 依赖和公开 API。

画布使用 [Konva](https://github.com/konvajs/konva) 与 [react-konva](https://github.com/konvajs/react-konva)，两者采用MIT许可，许可随已安装包提供，版本固定在npm锁文件。点选使用 [rembg](https://github.com/danielgatis/rembg) 公共接口（MIT），ONNX SAM权重来自官方发布资产，原始 [Segment Anything](https://github.com/facebookresearch/segment-anything) 项目采用Apache-2.0许可。Python可选依赖固定在 `canvas-requirements.txt`，权重没有提交进仓库。
