"""Opt-in integration: inspect real schemas; --model also exercises a saved text Skill.

Temporarily enables the two bounded optional groups, then restores selection.
Never opens terminal, prints credentials or sends personal files to the model.
"""
import argparse
import json
import re
import uuid
import time
from pathlib import Path
import httpx
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:9120'


def main():
    args = argparse.ArgumentParser(); args.add_argument('--model', action='store_true'); opts = args.parse_args()
    html = httpx.get(BASE, trust_env=False).text
    token = re.search(r'__HERMES_SESSION_TOKEN__="([^"]+)"', html).group(1)
    api = httpx.Client(base_url=BASE, headers={'X-Hermes-Session-Token': token}, trust_env=False, timeout=30)
    assert httpx.get(BASE + '/api/miniclaw/tools', trust_env=False).status_code in (401, 403)
    def get(path):
        r = api.get(path); r.raise_for_status(); return r.json()
    def put(path, payload):
        r = api.put(path, json=payload); r.raise_for_status(); return r.json()
    original = [g['id'] for g in get('/api/miniclaw/tools')['groups'] if g['enabled']]
    report = {'auth_enforced': True, 'model_called': opts.model}
    try:
        put('/api/miniclaw/tools', {'enabled': ['miniclaw-files', 'miniclaw-skills', 'miniclaw-artifacts']})
        with connect('ws://127.0.0.1:9120/api/ws?token=' + token) as ws:
            events = []
            def receive(timeout=30):
                frames = [json.loads(line) for line in ws.recv(timeout=timeout).splitlines()]
                events.extend(f['params'] for f in frames if f.get('method') == 'event')
                return frames
            def rpc(method, params):
                identifier = uuid.uuid4().hex
                ws.send(json.dumps({'jsonrpc': '2.0', 'id': identifier, 'method': method, 'params': params}))
                while True:
                    for frame in receive():
                        if frame.get('id') == identifier:
                            if 'error' in frame: raise RuntimeError(frame['error']['message'])
                            return frame['result']
            snapshot = rpc('session.create', {'source': 'desktop', 'follow_profile_config': True})
            sid = snapshot['session_id']
            try:
                info = None
                while not info:
                    info = next((e['payload'] for e in events if e.get('session_id') == sid and e.get('type') == 'session.info' and e.get('payload', {}).get('tools')), None)
                    if not info: receive()
                names = sorted(t for group in info['tools'].values() for t in group)
                assert names == sorted(['miniclaw_list_files', 'miniclaw_read_file', 'miniclaw_save_artifact', 'skills_list', 'skill_view']), names
                # Some session.info tool metadata is published before the cold
                # AIAgent finishes construction. Wait for an actual prompt build.
                for _ in range(100):
                    breakdown = rpc('session.context_breakdown', {'session_id': sid})
                    if breakdown['categories']: break
                    time.sleep(.2)
                skills = next((c for c in breakdown['categories'] if c['id'] == 'skills'), None)
                if skills is None:
                    raise RuntimeError('Context category ids: ' + json.dumps([c['id'] for c in breakdown['categories']]))
                assert skills['tokens'] > 0, skills
                report.update(tools=names, skills_index_tokens=skills['tokens'])
                if opts.model:
                    name = 'learning-save-note'
                    content = '---\nname: learning-save-note\ndescription: 用受限工具保存一段UTF-8学习笔记。\n---\n\n用户要求保存时，调用miniclaw_save_artifact，文件名使用用户给定名称，正文使用用户给定内容。工具成功后报告相对路径；失败时如实报告，不运行终端。'
                    installed = {s['name'] for s in get('/api/miniclaw/skills')}
                    if name not in installed:
                        result = api.post('/api/miniclaw/skills', json={'name': name, 'content': content}); result.raise_for_status()
                    current = get('/api/miniclaw/skills/content?name=' + name)
                    assert current['content'] == content, 'Existing demo Skill differs; refusing overwrite'
                    put('/api/miniclaw/skills/binding', {'name': name, 'content_hash': current['content_hash'], 'required_tools': ['miniclaw_save_artifact']})
                    rpc('skills.reload', {'session_id': sid})
                    filename = 'learning-' + uuid.uuid4().hex[:8] + '.md'
                    accepted = rpc('miniclaw.turn.submit', {'session_id': sid, 'text': f'请保存 {filename}，内容严格为：# 学习笔记\n测试代号：松果-73。不要额外添加文字。', 'skill': name, 'attachments': []})
                    while not any(e.get('session_id') == sid and e.get('type') == 'message.complete' for e in events): receive(180)
                    complete = next(e['payload'] for e in events if e.get('session_id') == sid and e.get('type') == 'message.complete')
                    assert complete.get('status') not in ('error', 'interrupted'), complete.get('status')
                    path = ROOT / 'workspace/artifacts' / filename
                    assert path.is_file() and '松果-73' in path.read_text(encoding='utf-8')
                    downloaded = api.get('/api/miniclaw/artifacts/' + filename)
                    downloaded.raise_for_status()
                    assert downloaded.content == path.read_bytes()
                    assert any(e.get('type') == 'tool.complete' and e.get('session_id') == sid for e in events)
                    turn = get('/api/miniclaw/turns?owner=' + snapshot['stored_session_id'])[str(accepted['user_row_id'])]
                    assert turn['skill'] == name and 'IMPORTANT' not in turn['text']
                    report.update(skill=name, artifact=str(path.relative_to(ROOT)), artifact_download=True, row_id=accepted['user_row_id'])
            finally: rpc('session.close', {'session_id': sid})
    finally:
        put('/api/miniclaw/tools', {'enabled': original}); api.close()
    path = ROOT / '.codex/verification' / ('basic-live-model.json' if opts.model else 'basic-live.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__': main()
