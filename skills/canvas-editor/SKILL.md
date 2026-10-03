---
name: canvas-editor
description: 在独立图片项目内，使用已有图层与真实选区完成局部修图，保留原图和候选版本。
---

先用 miniclaw_canvas_view 读取本轮关联项目的摘要。不要猜测路径、项目ID或图片内容；文字聊天模型不能凭图层名字声称看见了画面。

局部调色、擦除或提取使用 miniclaw_canvas_region，只作用于本轮目标图片图层的已有选区。没有选区或版本过期时，请用户重新选择，不扩大操作范围。

需要语义替换或消除时，用 miniclaw_canvas_ai 提交明确提示和唯一request_id。region=true作用于已有选区，false修改整层。百炼可能计费；超时或未知结果不得自动重试。

用 miniclaw_canvas_job 查询候选状态。仅succeeded且存在output表示候选生成。候选需要用户在画布里比较并采用，不能声称已经替用户覆盖原图。
