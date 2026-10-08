"""Loopback-only shared creation slice. Existing media; no video generation API."""
import argparse
import asyncio
import json
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import dotenv_values
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
import uvicorn

from miniclaw_web.canvas import Conflict
from miniclaw_web.creation import Creation
from miniclaw_web.decisions import JevConfig, JevDecisions
from miniclaw_web.store import Store


def make_app(folder, home, config=None, transport=None):
    folder = Path(folder)
    store = Store(home)
    creation = Creation(store)
    decisions = JevDecisions(store, config, transport)
    creation.create_sample('form-01')
    token = secrets.token_urlsafe(32)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])
    app.state.creation, app.state.decisions = creation, decisions
    app.state.token = token

    async def body(request):
        if request.headers.get('x-lab-token') != token:
            raise HTTPException(403, '页面已过期，请刷新后重试')
        origin = request.headers.get('origin')
        if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
            raise HTTPException(403, '仅允许同源操作')
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 16_000: raise HTTPException(413, '请求过大')
        try:
            data = json.loads(raw)
            if not isinstance(data, dict): raise ValueError()
            return data
        except (ValueError, UnicodeError): raise HTTPException(400, '需要 JSON 对象') from None

    @app.exception_handler(Conflict)
    async def conflict(request, error):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=409, content={'detail': str(error)})

    @app.exception_handler(ValueError)
    async def invalid(request, error):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content={'detail': str(error)})

    @app.get('/api/state')
    async def state():
        return dict(project=await asyncio.to_thread(creation.get, 'form-01'),
                    capabilities=decisions.capabilities(), ledger=decisions.ledger('interactive-form-01'))

    @app.post('/api/command')
    async def command(request: Request):
        data = await body(request)
        return await asyncio.to_thread(creation.command, 'form-01', data)

    @app.post('/api/decision')
    async def decision(request: Request):
        data = await body(request)
        if set(data) != {'request_id', 'revision', 'instruction', 'selected'}:
            raise ValueError('决策请求字段无效')
        snapshot = creation.get('form-01')
        if type(data['revision']) is not int or data['revision'] != snapshot['revision']:
            raise Conflict('项目已变化，请刷新后重新判断')
        result = await asyncio.to_thread(decisions.evaluate, 'interactive-form-01', data['request_id'], data['instruction'], snapshot, data['selected'])
        result = {**result, 'stale': creation.get('form-01')['revision'] != snapshot['revision']}
        return result

    @app.get('/', response_class=HTMLResponse)
    async def index():
        html = (folder / 'index.html').read_text(encoding='utf-8')
        return HTMLResponse(html.replace('__LAB_TOKEN__', token), headers={'Cache-Control': 'no-store'})

    @app.get('/comparison', response_class=HTMLResponse)
    async def comparison():
        return HTMLResponse((folder / 'style-explorer.html').read_text(encoding='utf-8'))

    app.mount('/assets', StaticFiles(directory=folder / 'assets'), name='assets')
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=9182)
    parser.add_argument('--folder', default=str(ROOT / 'outputs/2026-10-07-creation-lab'))
    args = parser.parse_args()
    config = JevConfig.from_env(dotenv_values(ROOT / '.hermes/.env'))
    uvicorn.run(make_app(args.folder, ROOT / '.hermes/creation-lab', config), host='127.0.0.1', port=args.port, access_log=False)
