"""Check the running GUI agent's real tool schemas, without calling a model."""
from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:9120'


def main() -> None:
    response = httpx.get(BASE, timeout=15, trust_env=False)
    response.raise_for_status()
    match = re.search(r'__HERMES_SESSION_TOKEN__="([^"]+)"', response.text)
    if not match:
        raise ValueError('Local handshake missing; start miniclaw web first')
    with connect('ws://127.0.0.1:9120/api/ws?token=' + match.group(1), open_timeout=15) as ws:
        events = []

        def rpc(method: str, params: dict) -> dict:
            ws.send(json.dumps({'jsonrpc': '2.0', 'id': method, 'method': method, 'params': params}))
            while True:
                for line in ws.recv(timeout=30).splitlines():
                    frame = json.loads(line)
                    if frame.get('method') == 'event':
                        events.append(frame['params'])
                    if frame.get('id') == method:
                        if 'error' in frame:
                            raise RuntimeError(frame['error']['message'])
                        return frame['result']

        snapshot = rpc('session.create', {'source': 'desktop', 'follow_profile_config': True})
        try:
            def ready_info():
                return next((event['payload'] for event in events
                             if event.get('type') == 'session.info'
                             and event.get('session_id') == snapshot['session_id']
                             and (event.get('payload') or {}).get('tools')), None)

            info = ready_info()
            while info is None:
                for line in ws.recv(timeout=30).splitlines():
                    frame = json.loads(line)
                    if frame.get('method') == 'event':
                        events.append(frame['params'])
                info = ready_info()
            names = sorted(name for group in info['tools'].values() for name in group)
            expected = ['miniclaw_list_files', 'miniclaw_read_file']
            assert names == expected, f'Unexpected model tools: {names}'
            report = {'real_gui_schema_verified': True, 'tools': names, 'model_called': False}
            out = ROOT / '.codex' / 'verification' / 'gateway-tool-scope.json'
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2), encoding='utf-8')
            print(json.dumps(report))
        finally:
            rpc('session.close', {'session_id': snapshot['session_id']})


if __name__ == '__main__':
    main()
