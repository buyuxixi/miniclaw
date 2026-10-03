"""Manual editor routes share auth/Origin middleware with the Chat application."""

import asyncio
import base64
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from .attachments import MAX_IMAGE, decode_upload, upload
from .canvas import Conflict
from .image_provider import provider_status
from .segmentation import status, prepare


def routes(service, body, resolve_session, persist_session):
    router = APIRouter(prefix="/canvas")

    async def call(function, *args, **kwargs):
        try:
            return await asyncio.to_thread(function, *args, **kwargs)
        except Conflict as e:
            raise HTTPException(409, str(e)) from None
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        except (KeyError, TypeError):
            raise HTTPException(400, "请求字段无效") from None
        except OSError:
            raise HTTPException(400, "素材读取失败") from None

    @router.get("/projects")
    async def projects(archived: bool = False):
        return await call(service.list, archived)

    @router.post("/projects")
    async def create(request: Request):
        p = await body(request)
        return await call(service.create, p.get("name", "未命名图片项目"))

    @router.get("/capabilities")
    async def capabilities():
        return {"sam": status(), "cloud": provider_status()}

    @router.post("/sam/prepare")
    async def sam_prepare():
        return prepare(service.store.home)

    @router.get("/projects/{project}")
    async def get(project: str):
        return await call(service.get, project)

    @router.patch("/projects/{project}")
    async def metadata(project: str, request: Request):
        p = await body(request)
        if set(p) - {"revision", "name", "archived", "session_id", "unlink"}:
            raise HTTPException(400, "项目字段无效")
        chat_id = None
        if p.get("session_id"):
            session = resolve_session(p["session_id"])
            chat_id = session["session_key"]

            def link_preflight():
                service._cas(service.get(project), p.get("revision"))
                persist_session(session)

            await call(link_preflight)
        return await call(
            service.metadata,
            project,
            p.get("revision"),
            p.get("name"),
            p.get("archived"),
            chat_id,
            "session_id" in p or p.get("unlink") is True,
        )

    @router.put("/projects/{project}/document")
    async def save(project: str, request: Request):
        p = await body(request)
        return await call(
            service.save,
            project,
            p.get("revision"),
            p.get("document"),
            p.get("label", "编辑画布"),
        )

    @router.get("/projects/{project}/history")
    async def history(project: str):
        return await call(service.history, project)

    @router.post("/projects/{project}/restore")
    async def restore(project: str, request: Request):
        p = await body(request)
        return await call(service.restore, project, p.get("revision"), p.get("seq"))

    @router.get("/projects/{project}/export")
    async def export(project: str, seq: int | None = None):
        return Response(
            await call(service.export, project, seq),
            media_type="image/png",
            headers={
                "Content-Disposition": 'attachment; filename="canvas.png"',
                "Cache-Control": "no-store",
            },
        )

    @router.get("/projects/{project}/assets")
    async def assets(project: str):
        return await call(service.assets, project)

    @router.post("/projects/{project}/assets")
    async def asset(project: str, request: Request):
        p = await body(request, 8 * 1024 * 1024)

        def execute():
            raw, kind, _, _ = decode_upload(p.get("name"), p.get("data"))
            if kind != "image":
                raise ValueError("画布只接受图片素材")
            return service.add_asset(project, raw, p["name"])

        return await call(execute)

    @router.post("/projects/{project}/import-chat")
    async def import_chat(project: str, request: Request):
        p = await body(request)
        session = resolve_session(p.get("session_id"))

        def execute():
            source = service.store.get(
                "attachments", p.get("asset_id"), session["session_key"]
            )
            if source["kind"] != "image":
                raise ValueError("请选择图片")
            service.get(project)
            persist_session(session)
            return service.add_asset(
                project, Path(source["path"]).read_bytes(), source["name"]
            )

        return await call(execute)

    @router.post("/projects/{project}/send-chat")
    async def send_chat(project: str, request: Request):
        p = await body(request)
        session = resolve_session(p.get("session_id"))

        def execute():
            raw = service.export(project)
            if len(raw) > MAX_IMAGE:
                raise ValueError("合成图片超过聊天附件5 MiB上限，请缩小画布")
            persist_session(session)
            output = upload(
                service.store,
                session["session_key"],
                "canvas.png",
                base64.b64encode(raw).decode(),
            )
            record = service.store.get(
                "attachments", output["id"], session["session_key"]
            )
            record["canvas_project_id"] = project
            service.store.put(
                "attachments", output["id"], record, session["session_key"]
            )
            return {**output, "canvas_project_id": project}

        return await call(execute)

    @router.get("/projects/{project}/selection")
    async def selection(project: str):
        return await call(service.selection, project)

    @router.post("/projects/{project}/selection")
    async def select(project: str, request: Request):
        p = await body(request)
        return await call(
            service.select,
            project,
            p.get("revision"),
            p.get("layer_id"),
            p.get("mode"),
            p.get("points"),
            p.get("radius", 20),
            p.get("combine", "replace"),
        )

    @router.post("/projects/{project}/segment")
    async def segment(project: str, request: Request):
        p = await body(request)
        return await call(
            service.segment,
            project,
            p.get("revision"),
            p.get("layer_id"),
            p.get("point"),
            p.get("combine", "replace"),
        )

    @router.post("/projects/{project}/masked")
    async def masked(project: str, request: Request):
        p = await body(request)
        return await call(
            service.masked,
            project,
            p.get("revision"),
            p.get("layer_id"),
            p.get("operation"),
            p.get("params", {}),
            p.get("selection_id"),
        )

    @router.get("/projects/{project}/jobs")
    async def jobs(project: str):
        return await call(service.jobs, project)

    @router.get("/projects/{project}/jobs/{job_id}")
    async def job(project: str, job_id: str):
        return await call(service.job, project, job_id)

    @router.post("/projects/{project}/local")
    async def local(project: str, request: Request):
        p = await body(request)
        if p.get("operation") not in ("adjust", "rotate", "flip", "resize"):
            raise HTTPException(400, "本地操作不支持")
        return await call(
            service.local,
            project,
            p.get("revision"),
            p.get("layer_id"),
            p.get("operation"),
            p.get("params", {}),
        )

    @router.post("/projects/{project}/jobs")
    async def submit(project: str, request: Request):
        p = await body(request)
        if p.get("region", True) and not isinstance(p.get("selection_id"), str):
            raise HTTPException(400, "请提交当前选区ID")
        return await call(
            service.submit,
            project,
            p.get("revision"),
            p.get("layer_id"),
            p.get("prompt"),
            p.get("request_id"),
            p.get("region", True),
            p.get("feather", 0),
            p.get("selection_id"),
        )

    @router.post("/projects/{project}/jobs/{job_id}/{action}")
    async def job_action(project: str, job_id: str, action: str, request: Request):
        p = await body(request)
        if action == "cancel":
            return await call(service.cancel, project, job_id)
        if action == "adopt":
            return await call(service.adopt, project, p.get("revision"), job_id)
        raise HTTPException(404, "操作不存在")

    return router
