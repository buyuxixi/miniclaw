"""Frozen round-02 auxiliary comparison: planning diagnostics plus native execution."""
from copy import deepcopy
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import time

import httpx
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from miniclaw_web.laya_advisory import LayaAdvisoryClient,parse_prediction
from scripts.build_laya_state_contrast import advice_context
from scripts.evaluate_chat_harness import Budget,main_plan,score,state_for,SYSTEM
from scripts.evaluate_native_fastpath import BUSINESS_EXTENSION


def write(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def summarize(rows, cases):
    by_id={c['id']:c for c in cases}
    arms={}
    for arm in ('main','laya_advisory'):
        rs=[r for r in rows if r['arm']==arm]
        arms[arm]=dict(flows=len(rs),correct=sum(r['metrics']['joint_match'] for r in rs),
            missed_clarification=sum(r['metrics']['missing_questions'] for r in rs),
            unnecessary_clarification=sum(r['metrics']['unnecessary_questions'] for r in rs),
            false_execution_plans=sum(r['metrics']['false_execution'] for r in rs),
            steps_mismatch=sum(not r['metrics']['steps_match'] for r in rs),
            total_tokens=sum(r['response'].get('usage',{}).get('total_tokens',0) for r in rs),
            median_http_ms=statistics.median(r['response']['latency_ms'] for r in rs) if rs else None,
            invalid=sum(r['response']['status']!='valid' for r in rs))
    index={(r['id'],r['repeat'],r['arm']):r for r in rows}
    pairs=[]
    for (ident,rep,arm), a in index.items():
        if arm!='main' or (ident,rep,'laya_advisory') not in index: continue
        b=index[ident,rep,'laya_advisory']
        pairs.append(dict(id=ident,family=by_id[ident]['family'],repeat=rep,
            corrected=not a['metrics']['joint_match'] and b['metrics']['joint_match'],
            harmed=a['metrics']['joint_match'] and not b['metrics']['joint_match'],
            both_correct=a['metrics']['joint_match'] and b['metrics']['joint_match']))
    families={}
    for family in sorted({c['family'] for c in cases}):
        family_ids={c['id'] for c in cases if c['family']==family}
        families[family]={arm:dict(variants_correct=sum(all(index[i,rep,arm]['metrics']['joint_match'] for i in family_ids)
            for rep in sorted({r['repeat'] for r in rows}) if all((i,rep,arm) in index for i in family_ids)))
            for arm in arms}
    return dict(arms=arms,paired=pairs,corrected=sum(p['corrected'] for p in pairs),
                harmed=sum(p['harmed'] for p in pairs),families=families,
                limitation='Planning correctness only. False execution here means an incorrect proposed step, not a real tool action.')


def run(args):
    data=json.loads(args.dataset.read_text(encoding='utf-8'))
    cases=data['planning']
    if args.case_ids: cases=[c for c in cases if c['id'] in args.case_ids.split(',')]
    if not cases: raise ValueError('empty_case_set')
    if args.out.exists(): raise ValueError('use_new_output_no_paid_rerun')
    args.out.mkdir(parents=True)
    gates=json.loads(args.gates.read_text(encoding='utf-8'))
    if gates['questions']['intent']['enabled'] or gates['questions']['clarification'].get('direct_labels'):
        raise ValueError('This experiment requires original disabled intent and no direct questions')
    helper=LayaAdvisoryClient(args.url,gates)
    manifest=dict(status='running',dataset_sha256=hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        gates_sha256=hashlib.sha256(args.gates.read_bytes()).hexdigest(),checkpoint_sha256=gates['checkpoint_sha256'],
        repeats=args.repeats,training=False,recalibration=False,
        no_direct_questions=True,identical_system_prompt=True,
        provenance=data['provenance'],model='deepseek-flash',thinking='disabled',
        price_note='Ledger uses conservative existing Budget reservation coefficients; not supplier invoice pricing.')
    write(args.out/'manifest.json',manifest)
    for source in ('scripts/evaluate_laya_state_contrast.py','scripts/build_laya_state_contrast.py',
                   'scripts/evaluate_chat_harness.py','miniclaw_web/laya_advisory.py'):
        dest=args.out/source.replace('/','__');dest.write_bytes((ROOT/source).read_bytes())
    (args.out/'dataset.json').write_bytes(args.dataset.read_bytes())
    (args.out/'gates.json').write_bytes(args.gates.read_bytes())
    # One frozen shadow score per state, shared by all repeated planning arms.
    shadow={}
    for case in cases:
        start=time.monotonic();result=helper.evaluate(case['text'],advice_context(case))
        result['http_ms']=round((time.monotonic()-start)*1000,2)
        if result['status']!='received': raise ValueError('shadow_service_failure:'+case['id'])
        if result['advice']['question'] or result['advice']['intent'] is not None:
            raise ValueError('unexpected_non_auxiliary_output')
        result['parsed']=parse_prediction(result['raw'])
        shadow[case['id']]=result
    write(args.out/'shadow.json',shadow)
    # Reference labels are diagnostic-only and never sent to either model.
    shadow_metrics=dict(cases=len(cases),
        clarification_correct=sum(v['parsed']['clarification']['choice']==('none' if not c['gold']['questions'] else c['gold']['questions'][0])
            for c in cases for v in [shadow[c['id']]]),
        categories_exact=sum({k.removeprefix('category_') for k,p in v['parsed'].items() if k.startswith('category_') and p['choice']=='yes'}==set(c['categories'])
            for c in cases for v in [shadow[c['id']]]),
        accepted_categories=sum(len(v['advice']['categories']) for v in shadow.values()),
        correct_accepted_categories=sum(len(set(shadow[c['id']]['advice']['categories']) & set(c['categories'])) for c in cases),
        accepted_clarification=sum(v['advice']['clarification'] is not None for v in shadow.values()),
        median_http_ms=statistics.median(v['http_ms'] for v in shadow.values()))
    write(args.out/'shadow-metrics.json',shadow_metrics)
    env={**dotenv_values(ROOT/'.hermes/.env'),**os.environ}
    key=env.get('DEEPSEEK_API_KEY')
    if not key:raise ValueError('main_key_missing')
    budget=Budget(args.out/'ledger.json',usd=args.budget,max_calls=args.max_calls)
    rows=[]
    # Full confirmed state is supplied identically to both arms. Existing SYSTEM
    # says pending state matters; expose original request and already answered slots.
    system=SYSTEM+BUSINESS_EXTENSION+'\ncontext.confirmed是用户已经回答的槽位；不重复问已回答内容。结合context.original_user_request理解待答短回复。'
    write(args.out/'system.json',dict(content=system))
    with httpx.Client(timeout=45,trust_env=False) as client:
        for rep in range(args.repeats):
            for i,case in enumerate(cases):
                for arm in (('main','laya_advisory') if (rep+i)%2==0 else ('laya_advisory','main')):
                    advice=deepcopy(shadow[case['id']]['advice']) if arm=='laya_advisory' else None
                    response=main_plan(client,key,case,advice,budget,system_override=system)
                    row=dict(id=case['id'],repeat=rep,arm=arm,response=response,metrics=score(response['plan'],case['gold']))
                    rows.append(row)
                    with (args.out/'planning.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
                    print(json.dumps(dict(id=case['id'],repeat=rep,arm=arm,correct=row['metrics']['joint_match']),ensure_ascii=False),flush=True)
                    write(args.out/'summary.json',summarize(rows,cases))
                    if response['status']=='unavailable' and 'usage' not in response:
                        # Do not make a new billable request after an unknown result.
                        raise RuntimeError('main_request_failed_no_automatic_retry:'+response.get('reason','unknown'))
    manifest.update(status='completed',main_calls=len(budget.entries),shadow_calls=len(shadow))
    write(args.out/'manifest.json',manifest)
    print(json.dumps(summarize(rows,cases),ensure_ascii=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset',type=Path,default=ROOT/'docs/chat-laya-state-contrast.v1.json')
    p.add_argument('--out',type=Path,required=True);p.add_argument('--gates',type=Path,required=True)
    p.add_argument('--url',default='http://127.0.0.1:8767');p.add_argument('--repeats',type=int,choices=(1,2),default=2)
    p.add_argument('--case-ids');p.add_argument('--budget',type=float,default=.40);p.add_argument('--max-calls',type=int,default=128)
    run(p.parse_args())
