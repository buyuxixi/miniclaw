# 第三方源码与依赖

`hermes-agent/` 是 [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) 的 Git submodule，固定提交 `f97608f178d1ffeca59860195ab7da295f7c8e5f`（`v2026.9.24`）。该提交的源码采用 MIT License，完整许可和版权声明保留在 `hermes-agent/LICENSE` 中。

miniclaw 前端直接引用该 submodule 中的共享 JSON-RPC 客户端；Agent 运行时、模型调用、工具注册与 SQLite 存储也来自 Hermes。这里没有把上游源码声明为 miniclaw 原创。

前端依赖及精确版本见 `frontend/package.json` 和 `frontend/package-lock.json`；Python 依赖与许可信息由上游 `pyproject.toml`、`uv.lock` 和对应包提供。

根目录 miniclaw 自有代码的许可尚未选定，本版不新增根 LICENSE。
