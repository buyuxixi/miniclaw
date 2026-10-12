"""Explicit provider factory, actual Coordinator.begin and pinned loopback request."""
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'hermes-agent')]
from scripts.evaluate_jev_laya_matched import write
from miniclaw_web.store import Store
from miniclaw_web.clarification_routes import ClarificationCoordinator
from miniclaw_web.clarification_policy import chat_request
from hermes_state import SessionDB


def probe(out):
    gates=json.loads((out/'round07/joint-gates.json').read_text(encoding='utf-8'))
    home=out/'coordinator-probe';home.mkdir(exist_ok=False)
    os.environ.update(HERMES_HOME=str(home),MINICLAW_CHAT_DECISION_PROVIDER='laya',MINICLAW_LAYA_URL='http://127.0.0.1:8771',MINICLAW_LAYA_CHECKPOINT_SHA256=gates['checkpoint_sha256'],MINICLAW_LAYA_GATE_SHA256=hashlib.sha256((out/'round07/joint-gates.json').read_bytes()).hexdigest())
    class NoJev:
        def evaluate(self,*args,**kwargs):raise AssertionError('unexpected Jev call')
    coordinator=ClarificationCoordinator(Store(home),None,SimpleNamespace(decisions=NoJev()),None)
    with SessionDB(db_path=home/'state.db') as db:db.create_session('live-chat','cli')
    session=dict(session_key='live-chat',agent=SimpleNamespace(max_iterations=10,tools=[]))
    saved=coordinator.begin(session,'请把「竹编篮」旋转90度。',{},None,[dict(id='a'*32,name='白瓷杯',kind='image'),dict(id='b'*32,name='竹编篮',kind='image')])
    assert saved['context']['semantic']['selected']=='b'*32
    semantic=saved['context']['semantic'];request=chat_request(saved['text'],semantic,saved['confirmed'])
    result=coordinator.policy.decisions.evaluate('coordinator','actual-begin','actual host state',{'revision':'round7'},request=request)
    assert result['status']=='suggested' and result['answers']['target']['choice']=='b'*32 and not result['jev_fallback']
    assert len(semantic['versions'])==64 and coordinator.studio.decisions is not coordinator.policy.decisions
    write(out/'coordinator-probe.json',dict(status='passed',actual_begin=True,provider_factory='laya',named_attachment_bound=True,actual_id_restored=True,host_version_preserved=True,jev_calls=0,paid_main_calls=0,production_default_changed=False))
    print(json.dumps(dict(status='passed',actual_coordinator=True,jev_calls=0)))

if __name__=='__main__':probe(Path(sys.argv[1]).resolve())
