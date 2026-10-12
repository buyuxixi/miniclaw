"""Frozen formal contract comparison; never changes production configuration."""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'hermes-agent')]
from dotenv import dotenv_values
import httpx
from miniclaw_web.decisions import JevConfig,JevDecisions
from miniclaw_web.store import Store
from miniclaw_web.clarifications import Clarifications
from scripts.evaluate_chat_harness import Budget,state_for
from scripts.chat_action_contract import explicit_target
from scripts.jev_laya_matched import cases,formal_task,request_for,signature,validate_answers,replay,AliasDecisions,MatchedNativePolicy
import scripts.evaluate_native_fastpath as native

def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def rows(path):return [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines() if s]
def cache(path):return {r['key']:r for r in rows(path)}

def native_task(case):
    cs=[dict(id='img1',label='第一张'),dict(id='img2',label='第二张')]
    selected=cs[case.get('selected',0)]['id'] if case.get('selected',0) is not None else None
    selected=explicit_target(case['text'],cs) or selected
    return dict(id=case['id'],text=case['text'],confirmed={},context=dict(semantic=dict(selected=selected,selection=None,candidates=cs)))

def prepare(out):
    out.mkdir(parents=True,exist_ok=True)
    if (out/'requests.json').exists():raise ValueError('frozen_input_already_exists')
    diagnostic,fixtures=cases();requests={};index=[]
    for profile in ('primary','enriched'):
        for case in diagnostic:
            req=request_for(formal_task(case),profile,state_for(case)['context']);key=signature(req)
            requests[key]=req;index.append(dict(id=case['id'],profile=profile,key=key))
    for case in fixtures:
        req=request_for(native_task(case));key=signature(req);requests[key]=req
        index.append(dict(id=case['id'],profile='native',key=key))
    write(out/'dataset.json',dict(diagnostic=diagnostic,native=fixtures,index=index))
    write(out/'requests.json',requests)
    sources=['scripts/jev_laya_matched.py','scripts/evaluate_jev_laya_matched.py','scripts/score_laya_formal.py','scripts/decision_answer_contract.py',
        'scripts/evaluate_native_fastpath.py','scripts/evaluate_chat_harness.py','scripts/chat_action_contract.py',
        'miniclaw_web/clarification_policy.py','miniclaw_web/decisions.py','miniclaw_web/hermes_clarification_adapter.py','plugins/miniclaw-files/__init__.py']
    saved=out/'executed';saved.mkdir();manifest={}
    for path in sources:
        raw=(ROOT/path).read_bytes();(saved/path.replace('/','__')).write_bytes(raw);manifest[path]=hashlib.sha256(raw).hexdigest()
    write(saved/'manifest.json',manifest)
    print(json.dumps(dict(diagnostic_cases=len(diagnostic),native_cases=len(fixtures),unique_requests=len(requests))))

def jev(out,remaining_only=False):
    requests=json.loads((out/'requests.json').read_text(encoding='utf-8'))
    cfg=JevConfig.from_env({**dotenv_values(ROOT/'.hermes/.env'),**os.environ})
    cfg.max_calls=200;cfg.budget_micro_usd=100000
    if not cfg.key:raise ValueError('configured_jev_key_missing')
    decisions=JevDecisions(Store(out/'jev-isolated'),cfg)
    existing=cache(out/'jev.jsonl') if remaining_only else {}
    with (out/'jev.jsonl').open('a' if remaining_only else 'x',encoding='utf-8') as stream:
        for key,req in requests.items():
            if key in existing:continue  # Includes unknown results: never replay that paid request.
            row=decisions.evaluate('formal-matched-v1',key,'matched comparison',{'revision':'formal-matched-v1'},request=req,question_version='chat-clarification-v1')
            row['key']=key
            if row.get('answers'):
                try:row['answers']=validate_answers(row,req[1])
                except ValueError as e:row.update(status='unavailable',reason=str(e),answers={})
            stream.write(json.dumps(row,ensure_ascii=False)+'\n');stream.flush()
            print(json.dumps(dict(key=key[:12],status=row['status'],ms=row.get('latency_ms'))),flush=True)
            write(out/'jev-ledger.json',decisions.ledger('formal-matched-v1'))
            if row['status'] in ('unknown','unavailable','budget_exhausted'):
                raise ValueError('stop_after_provider_failure:'+str(row.get('reason')))
    write(out/'jev-ledger.json',decisions.ledger('formal-matched-v1'))

def analyze(out):
    data=json.loads((out/'dataset.json').read_text(encoding='utf-8'));models={m:cache(out/f'{m}.jsonl') for m in ('jev','laya')}
    lookup={(r['profile'],r['id']):r['key'] for r in data['index']};detail=[];report={}
    qmap=dict(intent='Q_INTENT',target='Q_TARGET',region='Q_SCOPE',conflict='Q_CONFLICT',reference='Q_REFERENCE_ROLE')
    for profile in ('primary','enriched'):
        report[profile]={}
        for model,cached in models.items():
            heads={};rs=[]
            for case in data['diagnostic']:
                key=lookup[profile,case['id']]
                if any(not c.get(key,{}).get('answers') for c in models.values()):continue
                row=cached[key];answers=row.get('answers',{})
                for head,gold in case['formal_gold'].items():
                    a=answers.get(head,{});p=sorted(a.get('probabilities',{}).values(),reverse=True)
                    high=a.get('confidence',0)>=.85 and len(p)>1 and p[0]-p[1]>=.20
                    h=heads.setdefault(head,dict(total=0,correct=0,accepted=0,accepted_correct=0))
                    h['total']+=1;h['correct']+=a.get('choice')==gold;h['accepted']+=high;h['accepted_correct']+=high and a.get('choice')==gold
                expected_qs=[qmap[q] for q in case['gold']['questions']]
                task=formal_task(case);result=replay(task,row);alternative=replay(task,row,probability_gate=True)
                got=[q['template'] for q in result['questions']]
                record=dict(id=case['id'],profile=profile,model=model,text=case['text'],gold=case['formal_gold'],answers=answers,
                    replay=result,expected_questions=expected_qs,questions_match=got==expected_qs,
                    missed_questions=bool(set(expected_qs)-set(got)),extra_questions=bool(set(got)-set(expected_qs)),
                    intent_match=result['intent']==case['formal_gold'].get('intent') if 'intent' in case['formal_gold'] else None,
                    probability_gate=alternative)
                detail.append(record);rs.append(record)
            report[profile][model]=dict(heads=heads,rule_intent_correct=sum(r['intent_match'] is True for r in rs),
                rule_intent_total=sum(r['intent_match'] is not None for r in rs),question_match=sum(r['questions_match'] for r in rs),
                missed_questions=sum(r['missed_questions'] for r in rs),extra_questions=sum(r['extra_questions'] for r in rs),
                cases=len(rs),excluded_cases=len(data['diagnostic'])-len(rs),probability_gate_question_match=sum([q['template'] for q in r['probability_gate']['questions']]==r['expected_questions'] for r in rs))
    report['runtime']={m:dict(requests=len(rs),valid=sum(bool(r.get('answers')) for r in rs),unknown=sum(r['status']=='unknown' for r in rs),median_ms=statistics.median(r['latency_ms'] for r in rs),
        valid_median_ms=statistics.median(r['latency_ms'] for r in rs if r.get('answers')),
        p95_ms=sorted(r['latency_ms'] for r in rs)[int(.95*(len(rs)-1))],input_tokens=sum(r.get('input_tokens',0) for r in rs),
        estimated_usd=sum(r.get('estimated_micro_usd',0) for r in rs)/1e6) for m,c in models.items() if (rs:=list(c.values()))}
    report['paired_profile_comparison']={}
    for model in models:
        selected=[r for r in detail if r['model']==model]
        primary={r['id']:r for r in selected if r['profile']=='primary'}
        enriched={r['id']:r for r in selected if r['profile']=='enriched'}
        common=set(primary)&set(enriched)
        by_head={}
        for head in ('intent','answer_relation','scope'):
            ids=[i for i in common if head in primary[i]['gold']]
            by_head[head]=dict(total=len(ids),primary=sum(primary[i]['answers'][head]['choice']==primary[i]['gold'][head] for i in ids),
                enriched=sum(enriched[i]['answers'][head]['choice']==enriched[i]['gold'][head] for i in ids))
        report['paired_profile_comparison'][model]=dict(cases=len(common),heads=by_head)
    write(out/'diagnostic-detail.json',detail);write(out/'diagnostic-report.json',report)
    print(json.dumps(report,ensure_ascii=False))

def run_native(out):
    path=out/'native';path.mkdir(exist_ok=True)
    if (path/'flows.jsonl').exists():raise ValueError('existing_native_run_no_paid_replay')
    data=json.loads((out/'dataset.json').read_text(encoding='utf-8'));models={m:AliasDecisions(cache(out/f'{m}.jsonl')) for m in ('jev','laya')}
    # Require complete cached evidence before any paid main-model call.
    for case in data['native']:
        req=request_for(native_task(case))
        for dec in models.values():dec.evaluate(request=req)
    env={**dotenv_values(ROOT/'.hermes/.env'),**os.environ};key=env.get('DEEPSEEK_API_KEY')
    if not key:raise ValueError('main_key_missing')
    isolated=path/'isolated';isolated.mkdir(exist_ok=True);os.environ['HERMES_HOME']=str(isolated)
    (isolated/'config.yaml').write_text('memory:\n  memory_enabled: false\n  user_profile_enabled: false\nauxiliary:\n  title_generation:\n    enabled: false\n  background_review:\n    enabled: false\n',encoding='utf-8')
    service=Clarifications(Store(isolated));budget=Budget(path/'main-ledger.json',usd=.50,max_calls=180)
    from hermes_state import SessionDB
    original=native.plugin_tools
    def typed(workspace):
        schemas,handlers=original(workspace);item=schemas[0]['function']['parameters']['properties']['questions']['items']
        for field in ('id','template'):item['properties'][field]['enum']+=['Q_EXECUTION','Q_CONFLICT','Q_REFERENCE_ROLE']
        return schemas,handlers
    collected=[]
    with patch.object(native,'plugin_tools',side_effect=typed),SessionDB(db_path=isolated/'history.db') as db,httpx.Client(timeout=45,trust_env=False) as client:
        for rep in range(2):
            for i,case in enumerate(data['native']):
                arms=('jev','laya') if (rep+i)%2==0 else ('laya','jev')
                for arm in arms:
                    row=native.run_case(case,arm,rep,client,key,service,models[arm],budget,db,path,
                        hold_unresolved_target=True,clear_discussion=True,policy_factory=MatchedNativePolicy)
                    collected.append(row)
                    with (path/'flows.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
                    print(json.dumps({k:row[k] for k in ('id','arm','repeat','joint_match','first_question','terminal','main_calls')}),flush=True)
                    write(path/'report.json',summarize_native(collected,'in_progress'))
    write(path/'report.json',summarize_native(collected,'complete'))

def summarize_native(collected,status):
    report=dict(status=status,arms={})
    for arm in ('jev','laya'):
        rs=[r for r in collected if r['arm']==arm]
        if not rs:continue
        report['arms'][arm]=dict(flows=len(rs),joint_correct=sum(r['joint_match'] for r in rs),
            effect_correct=sum(r['effect_match'] for r in rs),question_correct=sum(r['question_match'] for r in rs),
            main_calls=sum(r['main_calls'] for r in rs),median_ms=statistics.median(r['latency_ms'] for r in rs),
            pixel_checks=sum(r['pixel_match'] is True for r in rs),preserved=sum(r['originals_preserved'] for r in rs),
            duplicates=sum(r['duplicate_probe'] is True for r in rs),waiting_blocks=sum(r['waiting_probe'] is True for r in rs),
            failed=[dict(id=r['id'],repeat=r['repeat'],question=r['first_question'],terminal=r['terminal']) for r in rs if not r['joint_match']])
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=('prepare','jev','jev-remaining','analyze','native'));p.add_argument('out',type=Path)
    args=p.parse_args();dict(prepare=prepare,jev=jev,**{'jev-remaining':lambda out:jev(out,remaining_only=True)},analyze=analyze,native=run_native)[args.phase](args.out.resolve())
