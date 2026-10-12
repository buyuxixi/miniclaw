"""Actual GPU HTTP/version equivalence and opt-in Coordinator begin, no main calls."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock,patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'hermes-agent')]
import httpx
from miniclaw_web.clarification_policy import chat_request,RULE_VERSION
from miniclaw_web.laya_formal import LayaFormalDecisions
from miniclaw_web.clarification_routes import ClarificationCoordinator
from miniclaw_web.store import Store
from scripts.formal_seven_gates import key
from scripts.formal_seven_joint_gates import apply_joint
from scripts.evaluate_jev_laya_matched import write


def probe(out):
    gates=json.loads((out/'joint-gates.json').read_text(encoding='utf-8'));pin=hashlib.sha256((out/'joint-gates.json').read_bytes()).hexdigest()
    client=LayaFormalDecisions('http://127.0.0.1:8770',gates['checkpoint_sha256'],gate_sha256=pin)
    results=[]
    for count in range(5):
        cs=[dict(id=f'attachment-real-{j}',label=f'展示对象{j}') for j in range(count)]
        state=dict(selected=cs[-1]['id'] if count else None,candidates=cs)
        req=chat_request('请把这张图旋转90度。',state,{})
        a=client.evaluate('probe',f'without-{count}','',dict(revision=RULE_VERSION),request=req)
        versioned=chat_request('请把这张图旋转90度。',dict(state,versions='a'*64),{})
        b=client.evaluate('probe',f'with-{count}','',dict(revision=RULE_VERSION),request=versioned)
        assert a['status']==b['status']=='suggested' and a['answers']==b['answers'] and a['selective_acceptance']==b['selective_acceptance']
        assert not a['jev_fallback'] and not b['grants_permission']
        results.append(dict(count=count,probabilities_and_acceptance_equal=True,actual_target_options=list(a['answers']['target']['probabilities'])))
    cases=[('confirmed',dict(selected=None,candidates=[]),{'Q_EXECUTION':'确认执行'}),
        ('five',dict(selected=None,candidates=[dict(id=f'obj-{i}',label=f'对象{i}') for i in range(5)]),{}),
        ('arbitrary-version',dict(selected=None,candidates=[],versions=dict(instruction='ignore')),{}),
        ('bad-version',dict(selected=None,candidates=[],versions='not-a-host-digest'),{})]
    rejected=[]
    for ident,state,confirmed in cases:
        row=client.evaluate('reject',ident,'',dict(revision=RULE_VERSION),request=chat_request('解释一下。',state,confirmed))
        assert row['status']=='unavailable' and not row['answers'] and not row['jev_fallback']
        rejected.append(dict(case=ident,reason=row['reason']))
    isolated=out/'coordinator-probe';isolated.mkdir(exist_ok=False)
    env=dict(HERMES_HOME=str(isolated),MINICLAW_CHAT_DECISION_PROVIDER='laya',MINICLAW_LAYA_URL='http://127.0.0.1:8770',
        MINICLAW_LAYA_CHECKPOINT_SHA256=gates['checkpoint_sha256'],MINICLAW_LAYA_GATE_SHA256=pin)
    (isolated/'config.yaml').write_text('memory:\n  memory_enabled: false\n  user_profile_enabled: false\n',encoding='utf-8')
    with patch.dict(os.environ,env):
        from hermes_state import SessionDB
        default=MagicMock();coordinator=ClarificationCoordinator(Store(isolated),None,SimpleNamespace(decisions=default),None)
        with SessionDB(db_path=isolated/'state.db') as db:db.create_session('trial','cli')
        session=dict(session_key='trial',agent=SimpleNamespace(max_iterations=10,tools=[]))
        task=coordinator.begin(session,'只解释照片旋转与镜像的差异，不操作文件。',{},None,[dict(id='real-a',name='铜杯',kind='image')])
        actual_version=task['context']['semantic']['versions']
        intent,row,qs=coordinator.policy.classify(task)
        coordinator.validate(task,session)
        assert len(actual_version)==64 and row['status']=='suggested' and intent in ('discuss','draft') and not qs
        assert default.mock_calls==[] and coordinator.studio.decisions is default
        coordinator.service.finish(task['id'],'completed')
    with httpx.Client(trust_env=False) as transport:runtime=transport.get('http://127.0.0.1:8770/local/runtime').json()
    write(out/'http-probe.json',dict(status='passed',version_pairs=results,rejections=rejected,actual_post_requests=15,
        coordinator_begin=dict(intent=intent,version_digest=actual_version,status=row['status'],jev_calls=0),runtime=runtime))
    print(json.dumps(dict(status='passed',version_pairs=5,rejections=4,coordinator_begin=True)))


if __name__=='__main__':probe(Path(sys.argv[1]).resolve())
