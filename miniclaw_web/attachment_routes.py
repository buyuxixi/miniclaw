"""Attachment transfer routes use the host's token/cookie authentication middleware."""
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from .attachment_uploads import UploadError


def routes(uploads, body, persist_owner=None):
    async def same_origin(request: Request):
        origin = request.headers.get('origin')
        if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
            raise HTTPException(403, '附件接口仅接受同源浏览器请求')

    router = APIRouter(dependencies=[Depends(same_origin)])

    async def call(function, *args):
        try:
            return await asyncio.to_thread(function, *args)
        except UploadError as error:
            raise HTTPException(error.status, str(error)) from None
        except (ValueError, KeyError, TypeError):
            raise HTTPException(400, '附件请求字段或内容无效') from None
        except OSError:
            raise HTTPException(503, '本机附件读写失败，请稍后重试') from None

    @router.post('/uploads')
    async def initialize(request: Request):
        payload = await body(request)
        if set(payload) != {'owner', 'name', 'size', 'request_id'}:
            raise HTTPException(400, '需要会话、文件名、大小与上传请求标识')
        if persist_owner is not None:
            await call(persist_owner, payload['owner'])
        return await call(uploads.init, payload['owner'], payload['name'], payload['size'], payload['request_id'])

    @router.get('/uploads/{identifier}')
    async def status(identifier: str, owner: str):
        return await call(uploads.status, identifier, owner)

    @router.put('/uploads/{identifier}/parts/{part_no}')
    async def part(identifier: str, part_no: int, owner: str, request: Request):
        # Check ownership before accepting any file bytes from a foreign task.
        await call(uploads.status, identifier, owner)
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > uploads.part_size:
                raise HTTPException(413, '上传分片最大4 MiB')
            raw.extend(chunk)
        return await call(uploads.put_part, identifier, owner, part_no, raw, request.headers.get('x-part-sha256'))

    @router.post('/uploads/{identifier}/complete')
    async def complete(identifier: str, request: Request):
        payload = await body(request)
        if set(payload) != {'owner'}:
            raise HTTPException(400, '需要当前会话标识')
        return await call(uploads.complete, identifier, payload['owner'])

    @router.delete('/uploads/{identifier}')
    async def cancel(identifier: str, owner: str):
        return await call(uploads.cancel, identifier, owner)

    return router
