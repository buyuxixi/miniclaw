"""Check real installed overlay schema; --model compiles a fictional SRT file.

No video upload, rendering or cloud image call. Original tool choices are restored.
"""
import argparse
import base64
import json
import re
import time
import uuid
from pathlib import Path

import httpx
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:9120'
SRT = '1\n00:00:00,250 --> 00:00:02,500\n这是一个陶瓷杯。\n\n2\n00:00:03,000 --> 00:00:05,500\n每天一杯，慢一点。\n'


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--model', action='store_true'); opts = parser.parse_args()
    token = re.search(r'__HERMES_SESSION_TOKEN__="([^"]+)"', httpx.get(BASE, trust_env=False).text).group(1)
    api = httpx.Client(base_url=BASE, headers={'X-Hermes-Session-Token': token}, trust_env=False, timeout=30)
    def request(method, path, **kwargs):
        r = api.request(method, path, **kwargs); r.raise_for_status(); return r.json()
    original = [g['id'] for g in request('GET', '/api/miniclaw/tools')['groups'] if g['enabled']]
    report = {'model_called': opts.model, 'video_rendered': False}
    proof = ROOT / '.codex/verification'; proof.mkdir(parents=True, exist_ok=True)
    try:
        current = request('GET', '/api/miniclaw/skills/content', params={'name': 'overlay-plan'})
        assert current['binding']['current'] and current['binding']['required_tools'] == ['miniclaw_overlay_compile']
        request('PUT', '/api/miniclaw/tools', json={'enabled': ['miniclaw-files', 'miniclaw-overlay']})
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
                    for f in receive():
                        if f.get('id') == rid:
                            if 'error' in f: raise RuntimeError(f['error']['message'])
                            return f['result']
            snapshot = rpc('session.create', {'source': 'desktop', 'follow_profile_config': True}); sid = snapshot['session_id']
            try:
                for _ in range(100):
                    if request('GET', '/api/miniclaw/session-capabilities', params={'session_id': sid})['ready']: break
                    time.sleep(.2)
                info = None
                while info is None:
                    info = next((e['payload'] for e in events if e.get('type') == 'session.info' and e.get('session_id') == sid and e.get('payload', {}).get('tools')), None)
                    if info is None: receive()
                tools = sorted(t for group in info['tools'].values() for t in group)
                assert tools == ['miniclaw_list_files', 'miniclaw_overlay_compile', 'miniclaw_read_file'], tools
                report['actual_tools'] = tools
                if opts.model:
                    source = request('POST', '/api/miniclaw/attachments', json={'owner': snapshot['stored_session_id'], 'name': 'overlay-demo.srt', 'data': base64.b64encode(SRT.encode()).decode()})
                    filename = 'overlay-demo-' + uuid.uuid4().hex[:8] + '.json'
                    start = len(events)
                    accepted = rpc('miniclaw.turn.submit', {'session_id': sid, 'skill': 'overlay-plan', 'attachments': [source['id']],
                        'text': '这是明确虚构的开发验收字幕。请只用本轮SRT，生成恰好两张不重叠卡：第1条用punch-pill摘录“陶瓷杯”，第2条用quote-lockup摘录“每天一杯，慢一点。”。落位分别top-left、right，不加署名。调用编译工具保存为' + filename + '。不列目录、不读文件、不运行终端；不要生成视频。'})
                    complete = None; deadline = time.monotonic() + 200
                    while not complete and time.monotonic() < deadline:
                        complete = next((e['payload'] for e in events[start:] if e.get('session_id') == sid and e.get('type') == 'message.complete'), None)
                        if not complete:
                            try: receive()
                            except TimeoutError: continue
                    assert complete and complete.get('status') not in ('error', 'interrupted'), 'Model turn failed/timed out'
                    calls = [e['payload'] for e in events[start:] if e.get('session_id') == sid and e.get('type') == 'tool.complete']
                    assert len(calls) == 1 and calls[0]['name'] == 'miniclaw_overlay_compile', 'Unexpected tool calls'
                    assert calls[0]['result']['success'], calls[0]['result']
                    path = ROOT / 'workspace/artifacts' / filename
                    document = json.loads(path.read_text(encoding='utf-8'))
                    assert len(document['cards']) == 2
                    assert [(c['start'], c['end']) for c in document['cards']] == [(.25, 2.5), (3, 5.5)]
                    assert [c['kind'] for c in document['cards']] == ['punch-pill', 'quote-lockup']
                    download = api.get('/api/miniclaw/artifacts/' + filename); download.raise_for_status()
                    assert download.content == path.read_bytes()
                    turn = request('GET', '/api/miniclaw/turns', params={'owner': snapshot['stored_session_id']})[str(accepted['user_row_id'])]
                    assert turn['skill'] == 'overlay-plan' and turn['attachments'][0]['id'] == source['id']
                    (proof / 'overlay-live-reply.md').write_text(complete.get('text', ''), encoding='utf-8')
                    (proof / 'overlay-demo.srt').write_text(SRT, encoding='utf-8')
                    (proof / 'overlay-demo.json').write_bytes(path.read_bytes())
                    report.update(artifact=str(path.relative_to(ROOT)), session=snapshot['stored_session_id'], source=source['id'], exact_subtitle_times=True, authenticated_download=True, tool_calls=calls)
            finally: rpc('session.close', {'session_id': sid})
    finally:
        request('PUT', '/api/miniclaw/tools', json={'enabled': original}); api.close()
    report['status'] = 'passed'
    (proof / ('overlay-live-model.json' if opts.model else 'overlay-live.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'tool_calls'}, ensure_ascii=False))


if __name__ == '__main__': main()
