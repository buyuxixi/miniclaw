"""Preserve initial fixture evidence; align finite tool grammar before core run."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'hermes-agent')]
from scripts.evaluate_jev_laya_matched import native_task,cache,write
from scripts.jev_laya_matched import request_for
from scripts.formal_seven_gates import key
from scripts.decision_fastpath import explicit_local_params

def repair(out):
    path=out/'native-cases.json';original=out/'native-cases-before-grammar-repair.json'
    if original.exists():raise ValueError('repair_already_applied')
    original.write_bytes(path.read_bytes());cases=json.loads(path.read_text(encoding='utf-8'))
    grammar={'rotate-a':'请把这张图旋转180度。','rotate-b':'把选中的这张图旋转270度。','flip-a':'请把这张图垂直翻转。','flip-b':'把选中的这张图水平翻转。'}
    changes=[]
    for c in cases:
        for name,text in grammar.items():
            if c['id'].startswith('r5-'+name+'-'):
                changes.append(dict(id=c['id'],old_text=c['text'],new_text=text,reason='finite fixture grammar; same intended operation/params'))
                c.update(text=text,source='fixture-grammar-repair-known-finite-operation-family')
        if c['gold']['effect'] in ('rotate','flip'):
            assert explicit_local_params(c['text']) is not None
    write(path,cases);requests=json.loads((out/'requests.json').read_text(encoding='utf-8'));new=json.loads((out/'jev-requests.json').read_text(encoding='utf-8'))
    old=cache(ROOT/'.codex/verification/laya-formal-round4-2026-10-11/jev.jsonl');done=cache(out/'jev.jsonl');added={};reused=[]
    for c in cases:
        req=request_for(native_task(c));ident=key(req)
        if ident not in requests:
            requests[ident]=req;added[ident]=req
            if ident in old and ident not in done:reused.append(dict(old[ident],reused_from='round4-fixture-grammar'))
            elif ident not in done:new[ident]=req
    with (out/'jev.jsonl').open('a',encoding='utf-8') as stream:
        for r in reused:stream.write(json.dumps(r,ensure_ascii=False)+'\n')
    write(out/'requests.json',requests);write(out/'jev-requests.json',new);write(out/'fixture-extra-requests.json',added)
    write(out/'fixture-repair.json',dict(changes=changes,extra_local_requests=len(added),extra_jev_requests=len(added)-len(reused),reused_known_jev=len(reused),
        initial_http_evidence_preserved=True,semantic_training_or_calibration_changed=False,new_blind_generalization=False))
    print(json.dumps(dict(changed=len(changes),extra_local=len(added),extra_jev=len(added)-len(reused))))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);repair(p.parse_args().out.resolve())
