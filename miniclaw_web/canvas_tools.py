"""Narrow tools use a trusted per-turn project snapshot, never model-owned paths."""

import json
from .store import digest

_service = None

def _turn_session(sessions,session_id):
    matches=[s for s in tuple(sessions.values()) if s.get('session_key')==session_id or getattr(s.get('agent'),'session_id',None)==session_id]
    active=[s for s in matches if s.get('running')]
    if len(active)>1:raise ValueError('同一项目有多个正在执行的对话，请先完成当前任务')
    return active[0] if active else matches[0] if len(matches)==1 else None


def set_service(service):
    global _service
    _service = service


def planning_guard(tool_name='', session_id='', **kwargs):
    """Native pre-tool hook: a proposal turn cannot escape through unrelated tools."""
    if not session_id:
        return None
    from tui_gateway import server
    try:session = _turn_session(server._sessions,session_id)
    except ValueError:return {'action':'block','message':'同一项目有多个正在执行的对话，无法确定当前画布引用'}
    if session and (session.get('miniclaw_canvas_turn') or {}).get('mode') == 'plan':
        if tool_name not in {'miniclaw_canvas_view', 'miniclaw_canvas_propose', 'miniclaw_canvas_job', 'skill_view', 'skills_list', 'tool_search', 'tool_describe'}:
            return {'action':'block','message':'本轮只整理修图方案，不能通过其他工具执行或读写无关文件。请使用画布读取与提案工具，用户随后在工作台预览或生成。'}
    return None


def canvas_tool(name, args, session_id):
    from tui_gateway import server

    try:
        if not _service or not session_id:
            raise ValueError("请从图片工作区的助手发起本轮请求")
        session = _turn_session(server._sessions,session_id)
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
        if ctx.get('mode') in ('plan','context') and name not in ('miniclaw_canvas_view', 'miniclaw_canvas_propose', 'miniclaw_canvas_job'):
            raise ValueError('本轮只整理修改方案；请在工作台预览、应用或生成候选')
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
                    {**{k: l[k] for k in ("id", "kind", "name", "visible", "locked", "x", "y", "width", "height", "scale_x", "scale_y", "rotation", "opacity")}, **({'asset_id':l['asset_id']} if l.get('asset_id') else {})}
                    for l in row["document"]["layers"]
                ],
                target_layer=ctx["layer_id"],
                selection=bool(_service.selection(project)),
                jobs=_service.jobs(project)[:5],
                plans=_service.plans.list(project)[:3],
                operation_semantics='resize_canvas只改变宽高，不移动/缩放图层；move使用绝对坐标；crop_canvas移动所有图层以保持裁剪位置；split_subject需要已确认主体选区，先拆层再改背景；replace_background(color)按当前主体选区保留原像素并换纯色背景，必须第一步，随后仅允许排版。',
            )
        elif name == 'miniclaw_canvas_propose':
            if set(args) != {'goal', 'preserve', 'steps'}:
                raise ValueError('需要goal、preserve与steps')
            if ctx['selection_hash'] != digest(json.dumps(_service.selection(project), sort_keys=True)):
                raise ValueError('本轮选区已改变，请重新发送消息')
            result = _service.plans.propose(project, ctx['revision'], ctx['layer_id'],
                                             args['goal'], args['preserve'], args['steps'])
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
