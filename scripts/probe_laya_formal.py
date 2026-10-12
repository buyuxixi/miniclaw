"""Real local HTTP probe with randomized host IDs and matched cached evidence."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import httpx
from miniclaw_web.laya_formal import LayaFormalDecisions
from scripts.formal_seven_gates import key
from scripts.formal_seven_label_gates import apply_labels
from scripts.evaluate_jev_laya_matched import cache,native_task,write
from scripts.jev_laya_matched import request_for

class CountingTransport(httpx.BaseTransport):
    def __init__(self):self.calls=0
    def handle_request(self,request):
        self.calls+=1
        with httpx.HTTPTransport(retries=0) as transport:
            response=transport.handle_request(request);response.read();return response

def probe(out,url):
    summary=json.loads((out/'round04/summary.json').read_text(encoding='utf-8'));gates=json.loads((out/'round04/label-gates.json').read_text(encoding='utf-8'))
    transport=CountingTransport();model=LayaFormalDecisions(url,summary['checkpoint_sha256'],transport=transport)
    cached=cache(out/'round04/scores.jsonl');cases=json.loads((out/'native-cases.json').read_text(encoding='utf-8'))
    selected=[c for c in cases if c['id'] in ('quote-missing','rotate-bound','r4-action-0-None','r4-action-2-1',
        'r4-quote-0-None','r4-quote-3-1','r4-draft-4-None','r4-draft-5-1','r4-unknown-0-None','r4-unknown-1-1')]
    result=[]
    for i,case in enumerate(selected):
        original=request_for(native_task(case));state=json.loads(original[0]);ids={c['id']:f'actual-attachment-{i}-{j}-a1b2c3' for j,c in enumerate(state['candidates'])}
        reverse={v:k for k,v in ids.items()};state['candidates']=[dict(c,id=ids[c['id']]) for c in state['candidates']]
        state['selected']=ids.get(state['selected'],state['selected']);qs=deepcopy(original[1]);qs['target']['criteria']={ids.get(k,k):v for k,v in qs['target']['criteria'].items()}
        request=(json.dumps(state,ensure_ascii=False),qs)
        prediction=model.evaluate('local-real-probe',f'probe-{i:04}',case['text'],dict(revision=1),request=request)
        expected=apply_labels(cached[key(original)],gates);match=bool(prediction.get('answers'));max_delta=0.
        if match:
            for head,a in prediction['answers'].items():
                chosen=reverse.get(a['choice'],a['choice']) if head=='target' else a['choice']
                match &= chosen==expected['answers'][head]['choice']
                match &= prediction['selective_acceptance'][head]==expected['selective_acceptance'][head]
                p={reverse.get(k,k) if head=='target' else k:v for k,v in a['probabilities'].items()}
                max_delta=max(max_delta,max(abs(p[k]-v) for k,v in expected['answers'][head]['probabilities'].items()))
        count_before=transport.calls
        again=model.evaluate('local-real-probe',f'probe-{i:04}',case['text'],dict(revision=1),request=request)
        result.append(dict(id=case['id'],status=prediction['status'],choice_and_gate_match=bool(match),probability_max_delta=max_delta,
            memo_preserved=again==prediction and transport.calls==count_before,latency_ms=prediction['latency_ms'],jev_fallback=prediction['jev_fallback']))
    # Unsupported candidate labels decline explicitly; do not broaden gate coverage.
    unsupported=deepcopy(list(request_for(native_task(cases[0]))));s=json.loads(unsupported[0]);s['candidates'][0]['label']='商品照片'
    unsupported[0]=json.dumps(s,ensure_ascii=False);unsupported[1]['target']['criteria']['img1']='商品照片'
    declined=model.evaluate('local-real-probe','unsupported-1','unused',dict(revision=1),request=unsupported)
    report=dict(cases=result,physical_local_calls=transport.calls,all_matched=all(r['choice_and_gate_match'] and r['memo_preserved'] for r in result),
        unsupported_state_declined=declined['status']=='unavailable' and declined.get('reason')=='local_http_422',
        external_model_calls=0,production_selected=False)
    write(out/'local-http-probe.json',report);print(json.dumps(report,ensure_ascii=False))
    if not report['all_matched'] or not report['unsupported_state_declined']:raise ValueError('local_probe_failed')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);p.add_argument('--url',default='http://127.0.0.1:8768');a=p.parse_args();probe(a.out,a.url)
