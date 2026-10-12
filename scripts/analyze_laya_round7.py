"""Same-calibration-algorithm weight comparison and separate known regressions."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'hermes-agent')]
from scripts.evaluate_jev_laya_matched import cache,write
from scripts.analyze_laya_round5 import result_for,metrics
from scripts.formal_seven_joint_gates import apply_joint
from scripts.formal_seven_gates import key
from miniclaw_web.candidate_clarification_policy import CandidateClarificationPolicy


def task_for(row):
    state=json.loads(row['request'][0])
    return dict(id=row['id'],text=state['user_request'],confirmed=state['confirmed'],context=deepcopy(row.get('host_context',dict(semantic=row['context']))))


def analyze(out):
    def read(p):return json.loads(p.read_text(encoding='utf-8'))
    freeze=read(out/'gate-freeze.json')
    repair=read(out/'dispatch-only-repair.json')
    policy=CandidateClarificationPolicy
    intent_repair=read(out/'intent-repair.json') if (out/'intent-repair.json').exists() else None
    if intent_repair:
        namespace={'__name__':'miniclaw_web.pre_intent_repair','__package__':'miniclaw_web'}
        original=out/'source-before-intent-repair/candidate_clarification_policy.py'
        if hashlib.sha256(original.read_bytes()).hexdigest()!=intent_repair['original_sha256']:raise ValueError('original_policy_changed')
        exec(compile(original.read_bytes(),str(original),'exec'),namespace)
        policy=namespace['CandidateClarificationPolicy']  # Reproduce original frozen comparison, not post-flow repair.
    for p,h in freeze['sources'].items():
        current=hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
        if current!=h:
            if p==repair['source_path'] and repair['status']=='passed' and repair['before_model_ast_unchanged'] and h==repair['original_sha256'] and current==repair['current_sha256']:continue
            if intent_repair and p==intent_repair['source_path'] and intent_repair['status']=='passed' and h==intent_repair['original_sha256'] and current==intent_repair['current_sha256']:continue
            raise ValueError('frozen_source_changed:'+p)
    gates={m:read(out/m/'joint-gates.json') for m in ('round05','round07')}
    for m,h in freeze['gates'].items():
        if hashlib.sha256((out/m/'joint-gates.json').read_bytes()).hexdigest()!=h:raise ValueError('gate_changed')
    cached={m:cache(out/m/'scores.jsonl') for m in gates};cached['jev']=cache(out/'jev.jsonl')
    rows=[r for r in read(out/'data/fresh.json') if r['split']=='test']
    paired=[r for r in rows if all(cached[m].get(key(r['request']),{}).get('answers') for m in cached)]
    summary={};detail=[]
    for model in cached:
        for mode in (('raw',) if model=='jev' else ('raw','joint')):
            group=[]
            for r in paired:
                raw=cached[model][key(r['request'])];prediction=apply_joint(raw,gates[model],r['request']) if mode=='joint' else deepcopy(raw)
                behavior=result_for(task_for(r),prediction,policy)
                group.append(dict(id=r['id'],family=r['family'],kind=r['kind'],confirmation_profile=r['confirmation_profile'],source=r['source'],model=model,mode=mode,
                    gold=r['expected'],gold_questions=r['expected_questions'],prediction=prediction,**behavior))
            label=model+'-'+mode;summary[label]=metrics(group)
            summary[label]['by_confirmation']={p:metrics([r for r in group if r['confirmation_profile']==p]) for p in ('none','execute','draft','target')}
            summary[label]['fresh_surface_only']=metrics([r for r in group if r['source']=='synthetic-author'])
            detail+=group
    write(out/'analysis.json',dict(total=len(rows),paired=len(paired),excluded=[r['id'] for r in rows if r not in paired],arms=summary))
    write(out/'behavior-detail.json',detail)
    write(out/'joint-errors.json',[r for r in detail if r['model']=='round07' and r['mode']=='joint' and set(r['questions'])!=set(r['gold_questions'])])
    oldpath=ROOT/'.codex/verification/laya-formal-round6-2026-10-11'
    oldrows=[r for r in read(oldpath/'data/fresh.json') if r['split']=='test'];oldjev=cache(oldpath/'jev.jsonl');regression={}
    oldpaired=[r for r in oldrows if oldjev.get(key(r['request']),{}).get('answers')]
    for model in ('jev','round05','round07'):
        group=[]
        for r in oldpaired:
            raw=(oldjev if model=='jev' else cached[model])[key(r['request'])]
            pred=raw if model=='jev' else apply_joint(raw,gates[model],r['request'])
            group.append(dict(id=r['id'],family=r['family'],gold=r['expected'],gold_questions=r['expected_questions'],prediction=pred,**result_for(task_for(r),pred,policy)))
        regression[model]=metrics(group)
    write(out/'known-round6-regression.json',regression)
    print(json.dumps(dict(paired=len(paired),arms={k:dict(intent=v['heads']['intent']['correct'],questions=v['question_sets_correct'],extra=v['extra_questions'],missed=v['missed_questions']) for k,v in summary.items()})))

if __name__=='__main__':analyze(Path(sys.argv[1]).resolve())
