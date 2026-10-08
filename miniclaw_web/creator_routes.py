"""Profile-local routes; same loopback token/Origin middleware as Chat."""
import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from .canvas import Conflict
from .video import MAX_MEDIA
from .creator import SLOTS, UPLOAD_IMAGE_SLOTS


def routes(service, body, session=None, persist=None):
    async def same_origin(request: Request):
        origin = request.headers.get('origin')
        if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
            raise HTTPException(403, '创作接口仅接受同源浏览器请求')
    router = APIRouter(prefix='/creator', dependencies=[Depends(same_origin)])
    async def call(fn, *args):
        try: return await asyncio.to_thread(fn, *args)
        except Conflict as e: raise HTTPException(409, str(e)) from None
        except ValueError as e: raise HTTPException(400, str(e)) from None
        except (KeyError, TypeError): raise HTTPException(400, '请求字段无效') from None
        except OSError: raise HTTPException(400, '本机素材读写失败') from None

    @router.get('/capabilities')
    async def capabilities(): return service.capabilities()

    @router.get('/projects')
    async def projects(owner: str | None = None): return await call(service.list, owner)

    @router.post('/projects')
    async def create(request: Request):
        p = await body(request)
        if set(p) - {'name'}: raise HTTPException(400, '任务字段无效')
        return await call(service.create, p.get('name', '新创作任务'))

    @router.get('/projects/{project}')
    async def get(project: str): return await call(service.get, project)

    @router.patch('/projects/{project}')
    async def patch(project: str, request: Request): return await call(service.patch, project, await body(request))

    @router.post('/projects/{project}/assets/{slot}')
    async def upload(project: str, slot: str, request: Request, name: str, revision: int):
        # Stream raw bytes instead of base64 JSON; bounded memory and no multipart dependency.
        if slot not in SLOTS: raise HTTPException(400, '素材类型无效')
        await call(service.get, project)
        folder = await call(service.project_folder, project)
        temp = folder / ('upload-' + uuid.uuid4().hex + '.tmp')
        limit = 64*1024 if slot in ('plan', 'srt') else 5*1024*1024 if slot in UPLOAD_IMAGE_SLOTS else MAX_MEDIA
        try:
            total = 0
            with temp.open('xb') as stream:
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > limit: raise HTTPException(413, '素材超过大小限制')
                    stream.write(chunk)
            return await call(service.import_file, project, revision, slot, name, temp)
        finally:
            temp.unlink(missing_ok=True)

    @router.post('/projects/{project}/link-chat')
    async def link_chat(project: str, request: Request):
        p = await body(request)
        if set(p) != {'revision', 'session_id'} or session is None: raise HTTPException(400, '需要当前revision和运行对话')
        live = session(p['session_id'])
        if persist(live) is False: raise HTTPException(503, '对话保存失败，未建立关联')
        return await call(service.link_chat, project, p['revision'], live['session_key'])

    @router.post('/projects/{project}/adopt-cover')
    async def adopt_cover(project: str, request: Request):
        p = await body(request)
        if set(p) != {'revision', 'owner', 'attachment'}: raise HTTPException(400, '需要当前revision、对话与图片标识')
        return await call(service.adopt_cover, project, p['revision'], p['owner'], p['attachment'])

    @router.post('/projects/{project}/render')
    async def render(project: str, request: Request):
        p = await body(request)
        if set(p) != {'revision'}: raise HTTPException(400, '需要当前revision')
        return await call(service.render, project, p['revision'])

    @router.post('/projects/{project}/jobs/{job}/cancel')
    async def cancel(project: str, job: str): return await call(service.cancel, project, job)

    @router.post('/projects/{project}/package')
    async def package(project: str, request: Request):
        p = await body(request)
        if set(p) != {'revision'}: raise HTTPException(400, '需要当前revision')
        return await call(service.package, project, p['revision'])

    @router.get('/projects/{project}/files/{file}')
    async def download(project: str, file: str):
        path, name = await call(service.file, project, file)
        if not path.is_file(): raise HTTPException(404, '素材文件不可用')
        return FileResponse(path, filename=name)

    return router
