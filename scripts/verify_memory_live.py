"""No-model memory injection check; restore contents/config with conflict checks.

Uses only fixture text. Leaves empty initialized memory files if previously empty.
Run while no user is editing these two files or their loading switches.
"""
import hashlib
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
    html = httpx.get(BASE, trust_env=False).text
    token = re.search(r'__HERMES_SESSION_TOKEN__="([^"]+)"', html).group(1)
    with httpx.Client(base_url=BASE, headers={'X-Hermes-Session-Token': token}, trust_env=False, timeout=30) as api:
        def read(path):
            response = api.get(path); response.raise_for_status(); return response.json()
        def write(path, data):
            response = api.put(path, json=data); response.raise_for_status(); return response.json()
        original = read('/api/miniclaw/memory')
        if any(original[target]['text'] for target in ('memory', 'user')):
            raise RuntimeError('Use an empty verification profile; refusing to overwrite user memory')
        cfg = read('/api/config')['memory']
        flags = {k: cfg.get(k, True) for k in ('memory_enabled', 'user_profile_enabled')}
        written = {}
        flags_changed = False
        try:
            for target, text in [('memory', 'Verification fixture: fictional project pine-42.'), ('user', 'Verification fixture: prefer concise Chinese explanations.')]:
                # Keep the expected hash even if the response times out after
                # an accepted write; restoration still uses compare-and-swap.
                written[target] = hashlib.sha256(text.encode('utf-8')).hexdigest()
                write('/api/miniclaw/memory', {'target': target, 'text': text, 'hash': original[target]['hash']})
            flags_changed = True
            write('/api/config', {'config': {'memory': {'memory_enabled': True, 'user_profile_enabled': True}}})
            with connect('ws://127.0.0.1:9120/api/ws?token=' + token) as ws:
                def rpc(method, params):
                    identifier = uuid.uuid4().hex
                    ws.send(json.dumps({'jsonrpc': '2.0', 'id': identifier, 'method': method, 'params': params}))
                    while True:
                        for line in ws.recv(timeout=30).splitlines():
                            frame = json.loads(line)
                            if frame.get('id') == identifier:
                                if 'error' in frame: raise RuntimeError(frame['error']['message'])
                                return frame['result']
                snapshot = rpc('session.create', {'source': 'desktop', 'follow_profile_config': True})
                sid = snapshot['session_id']
                try:
                    for _ in range(100):
                        state = read('/api/miniclaw/session-capabilities?session_id=' + sid)
                        if state['ready']: break
                        time.sleep(.2)
                    assert state['ready'], 'Agent construction did not complete'
                    assert all(state['memory'][target] == {'enabled': True, 'loaded': True} for target in ('memory', 'user')), state['memory']
                    context = rpc('session.context_breakdown', {'session_id': sid})
                    memory = next(c for c in context['categories'] if c['id'] == 'memory')
                    assert memory['tokens'] > 0
                    report = dict(model_called=False, memory_loaded=True, user_preferences_loaded=True, memory_estimated_tokens=memory['tokens'])
                finally:
                    rpc('session.close', {'session_id': sid})
        finally:
            # Hash conflicts preserve concurrent edits instead of clobbering.
            failures = []
            for target, current_hash in written.items():
                try:
                    if read('/api/miniclaw/memory')[target]['hash'] != original[target]['hash']:
                        write('/api/miniclaw/memory', {'target': target, 'text': original[target]['text'], 'hash': current_hash})
                except Exception:
                    failures.append(target)
            if flags_changed:
                current = read('/api/config')['memory']
                if all(current.get(k) is True for k in flags):
                    write('/api/config', {'config': {'memory': flags}})
                elif not all(current.get(k) == v for k, v in flags.items()):
                    failures.append('loading_switches_changed_elsewhere')
            if failures:
                raise RuntimeError('Restoration conflicted; concurrent data preserved: ' + ', '.join(failures))
        after = read('/api/miniclaw/memory')
        assert all(after[target]['hash'] == original[target]['hash'] for target in ('memory', 'user'))
        assert all(read('/api/config')['memory'].get(k) == v for k, v in flags.items())
        report['original_content_and_flags_restored'] = True
        path = ROOT / '.codex/verification/basic-memory-live.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report))


if __name__ == '__main__':
    main()
