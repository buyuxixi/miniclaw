"""Narrow tools use a trusted per-turn project snapshot, never model-owned paths."""

import json
from .store import digest

_service = None


def set_service(service):
    global _service
    _service = service


def canvas_tool(name, args, session_id):
    from tui_gateway import server

    try:
        if not _service or not session_id:
            raise ValueError("请从图片工作区的助手发起本轮请求")
        session = next(
            (
                s
                for s in server._sessions.values()
                if s.get("session_key") == session_id
                or getattr(s.get("agent"), "session_id", None) == session_id
            ),
            None,
        )
        if not session or name not in {
            d["function"]["name"] for d in getattr(session.get("agent"), "tools", [])
        }:
            raise ValueError("本对话未加载画布工具")
        ctx = session.get("miniclaw_canvas_turn")
        if (
            not ctx
            or _service.get(ctx["project_id"])["chat_id"] != session["session_key"]
        ):
            raise ValueError("本轮没有关联的图片项目")
        if not isinstance(args, dict):
            raise ValueError("参数无效")
        project = ctx["project_id"]
        if name == "miniclaw_canvas_view":
            if args:
                raise ValueError("读取画布无需参数")
            row = _service.get(project)
            result = dict(
                project_id=project,
                name=row["name"],
                revision=row["revision"],
                width=row["document"]["width"],
                height=row["document"]["height"],
                layers=[
                    {k: l[k] for k in ("id", "kind", "name", "visible", "locked")}
                    for l in row["document"]["layers"]
                ],
                target_layer=ctx["layer_id"],
                selection=bool(_service.selection(project)),
                jobs=_service.jobs(project)[:5],
            )
        elif name == "miniclaw_canvas_region":
            if set(args) != {"operation", "params"}:
                raise ValueError("需要operation和params")
            if ctx["selection_hash"] != digest(
                json.dumps(_service.selection(project), sort_keys=True)
            ):
                raise ValueError("本轮选区已改变，请重新发送消息")
            if not ctx["selection_id"]:
                raise ValueError("本轮没有选区，请先选择并重新发送消息")
            row = _service.masked(
                project,
                ctx["revision"],
                ctx["layer_id"],
                args["operation"],
                args["params"],
                ctx["selection_id"],
            )
            ctx["revision"] = row["revision"]
            result = dict(
                project_id=project,
                revision=row["revision"],
                operation=args["operation"],
                completed=True,
                selection_cleared=True,
            )
        elif name == "miniclaw_canvas_ai":
            if set(args) != {"prompt", "request_id", "region"}:
                raise ValueError("需要prompt、request_id、region")
            if args["region"] and ctx["selection_hash"] != digest(
                json.dumps(_service.selection(project), sort_keys=True)
            ):
                raise ValueError("本轮选区已改变，请重新发送消息")
            if args["region"] and not ctx["selection_id"]:
                raise ValueError("本轮没有选区，请先选择并重新发送消息")
            result = _service.submit(
                project,
                ctx["revision"],
                ctx["layer_id"],
                args["prompt"],
                args["request_id"],
                args["region"],
                selection_id=ctx["selection_id"] if args["region"] else None,
            )
        elif name == "miniclaw_canvas_job":
            if set(args) != {"job_id"}:
                raise ValueError("需要job_id")
            result = _service.job(project, args["job_id"])
        else:
            raise ValueError("未知画布工具")
        return json.dumps({"success": True, **result}, ensure_ascii=False)
    except (ValueError, KeyError, TypeError, OSError) as error:
        return json.dumps(
            {
                "success": False,
                "error": str(error)
                if isinstance(error, ValueError)
                else "画布请求无效",
            },
            ensure_ascii=False,
        )
