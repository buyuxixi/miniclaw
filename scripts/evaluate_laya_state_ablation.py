"""Exploratory follow-up: separate score hints from the auxiliary JSON scaffold."""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys

import httpx
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.evaluate_chat_harness import Budget,main_plan,score
from scripts.evaluate_laya_state_contrast import write

ARMS=('main','full','neutral','category_only','clarification_only')
IDS=('rotate-binding-0','flip-binding-0','discussion-binding-0','pending-target-1',
     'confirmed-purpose-0','region-binding-0','answered-region-0')


def hint(arm,full):
    if arm=='main':return None
    if arm not in ARMS:raise ValueError('unknown_arm')
    out=deepcopy(full)
    if arm in ('neutral','clarification_only'):out['categories']=[]
    if arm in ('neutral','category_only'):out['clarification']=None
    return out


def summarize(rows):
    return {arm:dict(flows=len(rs),correct=sum(r['metrics']['joint_match'] for r in rs),
                     failed=[f'{r["id"]}:{r["repeat"]}' for r in rs if not r['metrics']['joint_match']])
            for arm in ARMS if (rs:=[r for r in rows if r['arm']==arm])}


def run(parent):
    out=parent/'ablation'
    out.mkdir()
    planning=parent/'planning'
    data=json.loads((planning/'dataset.json').read_text(encoding='utf-8'))
    shadow=json.loads((planning/'shadow.json').read_text(encoding='utf-8'))
    cases=[c for c in data['planning'] if c['id'] in IDS]
    if len(cases)!=len(IDS):raise ValueError('missing_diagnostic_case')
    system=json.loads((planning/'system.json').read_text(encoding='utf-8'))['content']
    manifest=dict(status='running',cases=list(IDS),arms=list(ARMS),repeats=2,
        design='Post-hoc exploratory follow-up chosen after primary results; not a new independent test. Cached original scores, labels and system unchanged; neutral carries same metadata without categories or clarification.',
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),new_laya_calls=0)
    write(out/'manifest.json',manifest)
    (out/Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    env={**dotenv_values(ROOT/'.hermes/.env'),**os.environ}
    budget=Budget(out/'ledger.json',usd=.10,max_calls=70)
    rows=[]
    with httpx.Client(timeout=45,trust_env=False) as client:
        for rep in range(2):
            for i,c in enumerate(cases):
                arms=list(ARMS);offset=(rep+i)%len(arms);arms=arms[offset:]+arms[:offset]
                for arm in arms:
                    advice=hint(arm,shadow[c['id']]['advice'])
                    response=main_plan(client,env['DEEPSEEK_API_KEY'],c,advice,budget,system_override=system)
                    row=dict(id=c['id'],repeat=rep,arm=arm,advice=advice,response=response,metrics=score(response['plan'],c['gold']))
                    rows.append(row)
                    with (out/'planning.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
                    print(json.dumps(dict(id=c['id'],repeat=rep,arm=arm,correct=row['metrics']['joint_match'])),flush=True)
                    write(out/'summary.json',summarize(rows))
                    if response['status']=='unavailable' and 'usage' not in response:raise RuntimeError('unknown_main_result_no_retry')
    manifest.update(status='completed',main_calls=len(budget.entries))
    write(out/'manifest.json',manifest)
    print(json.dumps(summarize(rows)),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('parent',type=Path);run(p.parse_args().parent)
