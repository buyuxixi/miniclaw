"""Real local service/Agent image loop using a fictional drawing, never personal files.

--model invokes the configured chat model once; edits remain local, no DashScope fees.
Temporarily adds the image toolset and restores the previous selection.
"""
import argparse
import base64
import io
import json
import re
import time
import uuid
from pathlib import Path
import httpx
from PIL import Image, ImageDraw
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:9120'


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--model', action='store_true'); args = parser.parse_args()
    token = re.search(r'__HERMES_SESSION_TOKEN__="([^"]+)"', httpx.get(BASE, trust_env=False).text).group(1)
    api = httpx.Client(base_url=BASE, headers={'X-Hermes-Session-Token': token}, timeout=30, trust_env=False)
    def request(method, path, **kwargs):
        response = api.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise RuntimeError(f"{path}: HTTP {response.status_code}: {response.json().get('detail')}")
        return response.json()
    original = [g['id'] for g in request('GET', '/api/miniclaw/tools')['groups'] if g['enabled']]
    report = {'model_called': args.model, 'dashscope_called': False}
    try:
        request('PUT', '/api/miniclaw/tools', json={'enabled': sorted(set(original + ['miniclaw-images']))})
        with connect('ws://127.0.0.1:9120/api/ws?token=' + token) as ws:
            events = []
            def receive(timeout=30):
                frames = [json.loads(line) for line in ws.recv(timeout=timeout).splitlines()]
                events.extend(f['params'] for f in frames if f.get('method') == 'event'); return frames
            def rpc(method, params):
                rid = uuid.uuid4().hex; ws.send(json.dumps({'jsonrpc': '2.0', 'id': rid, 'method': method, 'params': params}))
                while True:
                    for frame in receive():
                        if frame.get('id') == rid:
                            if frame.get('error'): raise RuntimeError(frame['error']['message'])
                            return frame['result']
            snapshot = rpc('session.create', {'source': 'desktop', 'follow_profile_config': True})
            sid, owner = snapshot['session_id'], snapshot['stored_session_id']
            try:
                for _ in range(100):
                    if request('GET', '/api/miniclaw/session-capabilities', params={'session_id': sid})['ready']: break
                    time.sleep(.2)
                info = None
                while info is None:
                    info = next((e['payload'] for e in events if e.get('session_id') == sid and e['type'] == 'session.info' and e['payload'].get('tools')), None)
                    if info is None: receive()
                tools = sorted(t for names in info['tools'].values() for t in names)
                assert all(t in tools for t in ('miniclaw_image_list', 'miniclaw_edit_image', 'miniclaw_image_status'))
                image = Image.new('RGB', (480, 320), (180, 188, 198)); draw = ImageDraw.Draw(image)
                draw.rounded_rectangle((160, 65, 320, 270), 28, fill=(70, 100, 140))
                draw.rectangle((190, 138, 290, 183), fill=(230, 230, 225)); draw.text((205, 150), 'DEMO', fill=(40, 45, 50))
                stream = io.BytesIO(); image.save(stream, 'PNG'); raw = stream.getvalue()
                (ROOT / '.codex/verification/image-demo.png').write_bytes(raw)
                source = request('POST', '/api/miniclaw/attachments', json={'owner': owner, 'name': 'image-demo.png', 'data': base64.b64encode(raw).decode()})
                payload = {'session_id': sid, 'source_id': source['id'], 'operation': 'adjust', 'params': {'brightness': .2}, 'request_id': uuid.uuid4().hex}
                job = request('POST', '/api/miniclaw/image-jobs', json=payload)
                duplicate = request('POST', '/api/miniclaw/image-jobs', json=payload); assert job['id'] == duplicate['id']
                for _ in range(100):
                    job = request('GET', '/api/miniclaw/image-jobs/' + job['id'], params={'owner': owner})
                    if job['state'] not in ('queued', 'running'): break
                    time.sleep(.05)
                assert job['state'] == 'succeeded', job
                downloaded = api.get('/api/miniclaw/attachments/' + job['output']['id'], params={'owner': owner}); downloaded.raise_for_status()
                result = Image.open(io.BytesIO(downloaded.content)); assert result.size == (480, 320)
                assert result.getpixel((240, 90))[:3] == (84, 120, 168)
                assert api.get('/api/miniclaw/attachments/' + source['id'], params={'owner': owner}).content == raw
                assert api.get('/api/miniclaw/image-jobs/' + job['id'], params={'owner': 'other'}).status_code == 404
                report.update(tools=tools, manual_pixels_verified=True, original_preserved=True, idempotency=True, owner_isolated=True, output_download_verified=True, owner=owner, image_job=job['id'])
                # No chat message has been sent: manual editing must still make
                # the native conversation durable, not orphan its image owner.
                rpc('session.close', {'session_id': sid})
                resumed = rpc('session.resume', {'session_id': owner, 'source': 'desktop', 'eager_build': True})
                sid = resumed['session_id']
                assert (resumed.get('stored_session_id') or resumed.get('session_key') or resumed.get('info', {}).get('stored_session_id')) == owner
                assert request('GET', '/api/miniclaw/image-jobs/' + job['id'], params={'owner': owner})['output']['id'] == job['output']['id']
                report['manual_session_resume'] = True
                for _ in range(100):
                    if request('GET', '/api/miniclaw/session-capabilities', params={'session_id': sid})['ready']: break
                    time.sleep(.2)
                if args.model:
                    accepted = rpc('miniclaw.turn.submit', {'session_id': sid, 'text': '请把本轮附件的亮度增加20%，只调用本地adjust修图，不调用AI付费编辑；不要改其他参数。', 'skill': 'product-image-edit', 'attachments': [source['id']]})
                    while not any(e.get('session_id') == sid and e['type'] == 'message.complete' for e in events): receive(180)
                    jobs = request('GET', '/api/miniclaw/image-jobs', params={'owner': owner})['jobs']
                    native = next(j for j in jobs if j['id'] != job['id'])
                    assert native['state'] == 'succeeded' and native['operation'] == 'adjust' and native['provider'] == 'local', native
                    native_image = api.get('/api/miniclaw/attachments/' + native['output']['id'], params={'owner': owner}); native_image.raise_for_status()
                    assert Image.open(io.BytesIO(native_image.content)).getpixel((240, 90))[:3] == (84, 120, 168)
                    report.update(native_skill_tool_loop=True, native_job=native['id'], user_row_id=accepted['user_row_id'])
            finally: rpc('session.close', {'session_id': sid})
    finally:
        request('PUT', '/api/miniclaw/tools', json={'enabled': original}); api.close()
    name = 'image-live-model.json' if args.model else 'image-live.json'
    (ROOT / '.codex/verification' / name).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__': main()
