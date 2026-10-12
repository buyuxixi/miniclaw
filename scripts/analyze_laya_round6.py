"""Frozen joint-gate comparison; old test is regression, never refit input."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'hermes-agent')]
from scripts.evaluate_jev_laya_matched import cache,write
from scripts.analyze_laya_round5 import task_for,result_for,metrics
from scripts.formal_seven_consumption_gates import apply_consumption
from scripts.formal_seven_joint_gates import apply_joint
from scripts.formal_seven_gates import key
from miniclaw_web.candidate_clarification_policy import CandidateClarificationPolicy
from scripts.operational_clarification_policy import OperationalClarificationPolicy


def analyze(out):
    old=ROOT/'.codex/verification/laya-formal-round5-2026-10-11'
    gates=json.loads((out/'joint-gates.json').read_text(encoding='utf-8'))
    frozen=json.loads((out/'gate-freeze.json').read_text(encoding='utf-8'))
    repair=json.loads((out/'name-repair.json').read_text(encoding='utf-8'))
    if hashlib.sha256((out/'joint-gates.json').read_bytes()).hexdigest()!=frozen['gate_sha256']:raise ValueError('gate_changed_after_test')
    for p,h in frozen['sources'].items():
        current=hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
        if current!=h:
            if not (p=='miniclaw_web/candidate_clarification_policy.py' and repair['status']=='passed' and
                    repair['original_candidate_sha256']==h and repair['repaired_sources'][p]==current):
                raise ValueError('frozen_source_changed:'+p)
    previous=json.loads((old/'round05/consumption-gates.json').read_text(encoding='utf-8'))
    summary={};details=[]
    for split,source,cached,jcached in [('fresh',out/'data/fresh.json',cache(out/'scores.jsonl'),cache(out/'jev.jsonl')),
        ('known-round5',old/'data/fresh.json',cache(old/'round05/scores.jsonl'),cache(old/'jev.jsonl'))]:
        rows=[r for r in json.loads(source.read_text(encoding='utf-8')) if r['split']=='test']
        paired=[r for r in rows if cached.get(key(r['request']),{}).get('answers') and jcached.get(key(r['request']),{}).get('answers')]
        arms={}
        for model in ('jev','laya-raw','laya-previous','laya-joint'):
            group=[]
            for r in paired:
                raw=(jcached if model=='jev' else cached)[key(r['request'])]
                pred=(apply_consumption(raw,previous,r['request']) if model=='laya-previous' else
                    apply_joint(raw,gates,r['request']) if model=='laya-joint' else deepcopy(raw))
                behavior=result_for(task_for(r),pred,CandidateClarificationPolicy)
                group.append(dict(id=r['id'],family=r['family'],kind=r['kind'],model=model,split=split,
                    gold=r['expected'],gold_questions=r['expected_questions'],prediction=pred,**behavior))
            arms[model]=metrics(group);details.extend(group)
        # Isolate the policy change from the joint gate change, same raw checkpoint.
        oldpolicy=[]
        for r in paired:
            raw=cached[key(r['request'])]; pred=apply_consumption(raw,previous,r['request'])
            oldpolicy.append(dict(id=r['id'],family=r['family'],gold=r['expected'],gold_questions=r['expected_questions'],prediction=pred,
                **result_for(task_for(r),pred,OperationalClarificationPolicy)))
        arms['laya-previous-old-policy']=metrics(oldpolicy)
        summary[split]=dict(total=len(rows),paired=len(paired),excluded=[r['id'] for r in rows if r not in paired],arms=arms)
    write(out/'analysis.json',summary);write(out/'behavior-detail.json',details)
    write(out/'joint-errors.json',[r for r in details if r['split']=='fresh' and r['model']=='laya-joint' and set(r['questions'])!=set(r['gold_questions'])])
    print(json.dumps({s:{m:dict(correct=a['question_sets_correct'],missed=a['missed_questions'],extra=a['extra_questions'],abstentions=a['abstentions']) for m,a in v['arms'].items()} for s,v in summary.items()}))


if __name__=='__main__':analyze(Path(sys.argv[1]).resolve())
