"""Opt-in creator Skills smoke check against the running local service.

--model sends two fictional prompts to the configured chat model. No image,
terminal, artifact or publishing tools are enabled for the verification agent.
The user's tool selection is restored in finally; saved demo chats remain.
"""
import argparse
import json
import re
import time
import uuid
from pathlib import Path

import httpx
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:9120'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', action='store_true')
    opts = parser.parse_args()
    token = re.search(r'__HERMES_SESSION_TOKEN__="([^"]+)"', httpx.get(BASE, trust_env=False).text).group(1)
    api = httpx.Client(base_url=BASE, headers={'X-Hermes-Session-Token': token}, trust_env=False, timeout=30)

    def request(method, path, **kwargs):
        response = api.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    original = [g['id'] for g in request('GET', '/api/miniclaw/tools')['groups'] if g['enabled']]
    report = {'model_called': opts.model, 'skills': {}}
    output = ROOT / '.codex/verification'
    output.mkdir(parents=True, exist_ok=True)
    try:
        for name, tools in [('mono-color', ['skill_view']), ('spoken-script', [])]:
            binding = request('GET', '/api/miniclaw/skills/content', params={'name': name})['binding']
            assert binding['current'] and binding['required_tools'] == tools, binding
            report['skills'][name] = {'binding_ready': True}
        if opts.model:
            request('PUT', '/api/miniclaw/tools', json={'enabled': ['miniclaw-files', 'miniclaw-skills']})
            with connect('ws://127.0.0.1:9120/api/ws?token=' + token) as ws:
                events = []

                def receive():
                    frames = [json.loads(line) for line in ws.recv(timeout=30).splitlines()]
                    events.extend(f['params'] for f in frames if f.get('method') == 'event')
                    return frames

                def rpc(method, params):
                    rid = uuid.uuid4().hex
                    ws.send(json.dumps({'jsonrpc': '2.0', 'id': rid, 'method': method, 'params': params}))
                    while True:
                        for frame in receive():
                            if frame.get('id') == rid:
                                if 'error' in frame:
                                    raise RuntimeError(frame['error']['message'])
                                return frame['result']

                prompts = {
                    'mono-color': '这是虚构练习商品：360mL陶瓷杯，没有品牌，未验证保温能力。请设计3:4商品封面，标题严格用“每天一杯，慢一点”。先读取技能规定的设计方法、配色、构图、字体资源，再给出方案和提示词；列实际目录ID与准确色值。不出图、不修改画布。',
                    'spoken-script': '这是虚构练习商品，已知事实只有360mL陶瓷杯、没有品牌。请优化以下草稿成约20秒自然口播，保留原句“每天一杯，慢一点”。草稿：这个杯子保温12小时，绝不烫手，我用了一个月特别好。每天一杯，慢一点。注意保温、温度与体验没有证据，请从主稿删掉，给两种开头及简单分镜。',
                }
                for name, prompt in prompts.items():
                    snapshot = rpc('session.create', {'source': 'desktop', 'follow_profile_config': True})
                    sid = snapshot['session_id']
                    try:
                        for _ in range(100):
                            caps = request('GET', '/api/miniclaw/session-capabilities', params={'session_id': sid})
                            if caps['ready']:
                                break
                            time.sleep(.2)
                        assert caps['ready'], 'Agent did not become ready'
                        start = len(events)
                        accepted = rpc('miniclaw.turn.submit', {'session_id': sid, 'text': prompt, 'skill': name, 'attachments': []})
                        complete = None
                        deadline = time.monotonic() + 200
                        while not complete and time.monotonic() < deadline:
                            complete = next((e['payload'] for e in events[start:] if e.get('session_id') == sid and e.get('type') == 'message.complete'), None)
                            if not complete:
                                try:
                                    receive()
                                except TimeoutError:
                                    continue
                        assert complete and complete.get('status') not in ('error', 'interrupted'), 'Model turn failed or timed out'
                        reply = complete.get('text', '')
                        (output / (name + '-live.md')).write_text(reply, encoding='utf-8')
                        assert '每天一杯，慢一点' in reply and len(reply) > 120, 'Incomplete output'
                        calls = [e['payload'] for e in events[start:] if e.get('session_id') == sid and e.get('type') == 'tool.complete']
                        (output / (name + '-calls.json')).write_text(json.dumps(calls, ensure_ascii=False, indent=2), encoding='utf-8')
                        if name == 'mono-color':
                            recorded = json.dumps(calls, ensure_ascii=False)
                            for resource in ['design-guide.md', 'colors.json', 'compositions.json', 'typography.json']:
                                assert resource in recorded, 'Resource was not read: ' + resource
                            assert re.search(r'#[0-9a-fA-F]{6}', reply), 'Missing exact color'
                            assert all(call['name'] in ('skills_list', 'skill_view') for call in calls), 'Unexpected tool'
                        else:
                            assert not calls, 'Text Skill unexpectedly used tools'
                        turn = request('GET', '/api/miniclaw/turns', params={'owner': snapshot['stored_session_id']})[str(accepted['user_row_id'])]
                        assert turn['skill'] == name
                        report['skills'][name].update(session=snapshot['stored_session_id'], row_id=accepted['user_row_id'], tool_calls=calls, reply_chars=len(reply))
                        print(name + ': passed', flush=True)
                    finally:
                        rpc('session.close', {'session_id': sid})
    finally:
        request('PUT', '/api/miniclaw/tools', json={'enabled': original})
        api.close()
    report['status'] = 'passed'
    (output / ('creator-live-model.json' if opts.model else 'creator-live.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status': 'passed', 'model_called': opts.model, 'tools_restored': True}, ensure_ascii=False))


if __name__ == '__main__':
    main()
