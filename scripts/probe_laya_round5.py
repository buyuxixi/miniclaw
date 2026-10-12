"""Actual ID/name/count HTTP equivalence and unsupported count rejection."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from miniclaw_web.laya_formal import LayaFormalDecisions
from miniclaw_web.clarification_policy import chat_request
from scripts.formal_seven_gates import key
from scripts.formal_seven_consumption_gates import apply_consumption
from scripts.probe_laya_formal import CountingTransport
from scripts.evaluate_jev_laya_matched import cache,write

def probe(out):
    path=out/'round05/consumption-gates.json';gates=json.loads(path.read_text(encoding='utf-8'))
    transport=CountingTransport();model=LayaFormalDecisions('http://127.0.0.1:8769',gates['checkpoint_sha256'],transport=transport,gate_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    scores=cache(out/'round05/scores.jsonl');data=json.loads((out/'data/fresh.json').read_text(encoding='utf-8'))
    pairs=[(0,0,False),(0,1,False),(0,2,True),(4,3,False),(7,4,True),(8,2,False),(8,4,True),(16,0,False),(16,3,True),(20,4,False),(24,3,False),(32,1,False)]
    chosen=[next(r for r in data if r['id']==f'r5-test-{i}-{n}-{int(bound)}') for i,n,bound in pairs];result=[]
    for index,r in enumerate(chosen):
        original=r['request'];s=json.loads(original[0]);ids={c['id']:f'actual-upload-{index}-{j}-opaque' for j,c in enumerate(s['candidates'])};reverse={v:k for k,v in ids.items()}
        s['candidates']=[dict(c,id=ids[c['id']]) for c in s['candidates']];s['selected']=ids.get(s['selected'],s['selected'])
        qs=deepcopy(original[1]);qs['target']['criteria']={ids.get(k,k):v for k,v in qs['target']['criteria'].items()};req=[json.dumps(s,ensure_ascii=False),qs]
        pred=model.evaluate('r5-http',r['id'],'unused',dict(revision=1),request=req);expected=apply_consumption(scores[key(original)],gates,original)
        match=bool(pred['answers']);delta=0.
        for h,a in pred['answers'].items():
            choice=reverse.get(a['choice'],a['choice']) if h=='target' else a['choice']
            match &= choice==expected['answers'][h]['choice'] and pred['selective_acceptance'][h]==expected['selective_acceptance'][h]
            probs={reverse.get(k,k) if h=='target' else k:v for k,v in a['probabilities'].items()}
            delta=max(delta,max(abs(v-probs[k]) for k,v in expected['answers'][h]['probabilities'].items()))
        count=transport.calls;again=model.evaluate('r5-http',r['id'],'unused',dict(revision=1),request=req)
        result.append(dict(id=r['id'],match=bool(match),max_delta=delta,memo_preserved=again==pred and transport.calls==count,status=pred['status']))
    unsupported=chat_request('把当前图旋转90度。',dict(selected=None,candidates=[dict(id=f'opaque-{i}',label=f'图片{i}') for i in range(5)]),{})
    decline=model.evaluate('r5-http','unsupported-five','unused',dict(revision=1),request=unsupported)
    domain=[]
    for index,req in enumerate((chat_request('把当前图旋转90度。',dict(selected=None,candidates=[]),{'Q_TARGET':'某个对象'}),
        chat_request('解释图片原理。',dict(selected=None,candidates=[],versions='a'*64),{}))):
        value=model.evaluate('r5-http',f'unsupported-state-{index}','unused',dict(revision=1),request=req)
        domain.append(value['status']=='unavailable' and value.get('reason')=='local_http_422')
    report=dict(cases=result,physical_local_calls=transport.calls,all_matched=all(r['match'] and r['memo_preserved'] and r['max_delta']<1e-6 for r in result),
        unsupported_count_declined=decline['status']=='unavailable' and decline.get('reason')=='local_http_422',unsupported_confirmation_or_version_declined=domain,production_selected=False,external_calls=0)
    write(out/'local-http-probe.json',report);print(json.dumps(report))
    if not report['all_matched'] or not report['unsupported_count_declined'] or not all(domain):raise ValueError('http_equivalence_failed')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);probe(p.parse_args().out.resolve())
