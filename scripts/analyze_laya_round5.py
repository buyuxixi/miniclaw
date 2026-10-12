"""Paired raw fields, calibration, rule ablation, and finite native evidence."""
import argparse
from collections import defaultdict
from copy import deepcopy
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'hermes-agent')]
from miniclaw_web.clarification_policy import ClarificationPolicy,high
from scripts.operational_clarification_policy import OperationalClarificationPolicy
from scripts.formal_seven_label_gates import apply_labels
from scripts.formal_seven_consumption_gates import apply_consumption
from scripts.formal_seven_gates import key
from scripts.evaluate_jev_laya_matched import cache,write,native_task
from scripts.jev_laya_matched import request_for

def read(p):return json.loads(p.read_text(encoding='utf-8'))
class Fixed:
    def __init__(self,r):self.r=r
    def evaluate(self,*a,**kw):return deepcopy(self.r)

def task_for(row):
    state=json.loads(row['request'][0])
    return dict(id=row['id'],text=state['user_request'],confirmed=state['confirmed'],context=dict(semantic=row['context']))

def result_for(task,pred,policy):
    intent,dec,qs=policy(Fixed(pred)).classify(task)
    return dict(intent=intent,questions=[q['template'] for q in qs],abstained=dec.get('semantic_abstention',False))

def metrics(items):
    if not items:return dict(n=0)
    heads={}
    for h in items[0]['gold']:
        families=defaultdict(list);accepted=[]
        for r in items:
            families[r['family']].append(r['prediction']['answers'][h]['choice']==r['gold'][h])
            if high(r['prediction'],h) is not None:accepted.append(r)
        heads[h]=dict(correct=sum(sum(v) for v in families.values()),accepted=len(accepted),accepted_correct=sum(r['prediction']['answers'][h]['choice']==r['gold'][h] for r in accepted),
            family_mean_accuracy=round(sum(sum(v)/len(v) for v in families.values())/len(families),4))
    return dict(n=len(items),families=len({r['family'] for r in items}),heads=heads,
        question_sets_correct=sum(set(r['questions'])==set(r['gold_questions']) for r in items),
        extra_questions=sum(len(set(r['questions'])-set(r['gold_questions'])) for r in items),
        missed_questions=sum(len(set(r['gold_questions'])-set(r['questions'])) for r in items),
        rule_intent_correct=sum(r['intent']==r['gold']['intent'] for r in items),abstentions=sum(r['abstained'] for r in items))

def analyze(out):
    data=[r for r in read(out/'data/fresh.json') if r['split']=='test']
    caches={name:cache(out/name/'scores.jsonl') for name in ('round04','round05')};jev=cache(out/'jev.jsonl')
    paired=[r for r in data if jev.get(key(r['request']),{}).get('answers') and all(c.get(key(r['request']),{}).get('answers') for c in caches.values())]
    details=[];summary={};gates={m:{g:read(out/m/(g+'-gates.json')) for g in ('label','consumption')} for m in caches}
    for model in ('jev','round04','round05'):
        for calibration in (('raw',) if model=='jev' else ('raw','label','consumption')):
            for pname,policy in [('original',ClarificationPolicy),('operational',OperationalClarificationPolicy)]:
                group=[]
                for r in paired:
                    raw=jev[key(r['request'])] if model=='jev' else caches[model][key(r['request'])]
                    pred=raw if calibration=='raw' else apply_labels(raw,gates[model]['label']) if calibration=='label' else apply_consumption(raw,gates[model]['consumption'],r['request'])
                    behavior=result_for(task_for(r),pred,policy)
                    entry=dict(id=r['id'],family=r['family'],kind=r['kind'],count=r['state_variant']['candidate_count'],bound=r['state_variant']['bound'],model=model,calibration=calibration,policy=pname,
                        gold=r['expected'],gold_questions=r['expected_questions'],prediction=pred,**behavior)
                    group.append(entry);details.append(entry)
                name=f'{model}-{calibration}-{pname}';summary[name]=metrics(group)
                summary[name]['by_count']={str(n):metrics([r for r in group if r['count']==n]) for n in range(5)}
    write(out/'analysis.json',dict(paired=len(paired),total=len(data),excluded=[r['id'] for r in data if r not in paired],arms=summary,
        limitations=['author synthetic families and correlated object variants','primary has no pending state; resume adapter skips classifier','operational rule changes are common to both models; separate from weight benefit','preclassifier question metric excludes later main clarification recovery']))
    write(out/'test-behavior-detail.json',details)
    write(out/'test-errors.json',[r for r in details if r['model']=='round05' and r['calibration']=='consumption' and r['policy']=='operational' and (set(r['questions'])!=set(r['gold_questions']) or r['prediction']['answers']['intent']['choice']!=r['gold']['intent'])])
    known=read(ROOT/'.codex/verification/laya-formal-round4-2026-10-11/data/review.json');regression={}
    oldjev=cache(ROOT/'.codex/verification/laya-formal-round4-2026-10-11/jev.jsonl')
    old=[r for r in known if r['split']=='test' and r['profile']=='primary' and oldjev[key(r['request'])].get('answers')]
    for model in ('jev','round04','round05'):
        heads={h:sum((oldjev if model=='jev' else caches[model])[key(r['request'])]['answers'][h]['choice']==r['expected'][h] for r in old) for h in old[0]['expected']}
        regression[model]=dict(n=len(old),heads=heads)
    write(out/'known-regression.json',regression)
    path=out/'native'
    if (path/'report.json').exists() and read(path/'report.json')['status']=='complete':
        rows=[json.loads(s) for s in (path/'flows.jsonl').read_text(encoding='utf-8').splitlines() if s];by={};content=[]
        for r in rows:
            by.setdefault(r['id'],{})[r['arm']]=r
            for a in r['artifacts']:
                content.append(dict(id=r['id'],arm=r['arm'],name=a['name'],bytes=a['bytes'],text=a['content']))
        wins=[i for i,p in by.items() if p['laya']['joint_match'] and not p['jev']['joint_match']]
        losses=[i for i,p in by.items() if p['jev']['joint_match'] and not p['laya']['joint_match']]
        write(path/'paired-differences.json',dict(wins=wins,regressions=losses,pairs=len(by)))
        write(path/'content-candidates.json',content)
    print(json.dumps(dict(paired=len(paired),intent={m:summary[f'{m}-raw-original']['heads']['intent']['correct'] for m in ('jev','round04','round05')},questions={m:summary[f'{m}-'+('raw' if m=='jev' else 'consumption')+'-operational']['question_sets_correct'] for m in ('jev','round04','round05')})))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);analyze(p.parse_args().out.resolve())
