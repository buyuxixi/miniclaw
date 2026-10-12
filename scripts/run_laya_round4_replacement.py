"""Bounded Jev evidence and real native replacement; no production switching."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'hermes-agent')]
import httpx
from dotenv import dotenv_values
from scripts.formal_seven_gates import key
from scripts.formal_seven_label_gates import apply_labels
from scripts.evaluate_jev_laya_matched import write,cache,native_task,summarize_native
from scripts.jev_laya_matched import request_for,AliasDecisions,MatchedNativePolicy
from scripts.evaluate_chat_harness import Budget
from miniclaw_web.clarifications import Clarifications
from miniclaw_web.store import Store
import scripts.evaluate_native_fastpath as native

def fetch(out):
    from miniclaw_web.decisions import JevConfig,JevDecisions
    from scripts.decision_answer_contract import validate_answers
    cfg=JevConfig.from_env({**dotenv_values(ROOT/'.hermes/.env'),**os.environ});cfg.max_calls=600;cfg.budget_micro_usd=100000
    if not cfg.key:raise ValueError('jev_not_configured')
    dec=JevDecisions(Store(out/'jev-isolated'),cfg);done=cache(out/'jev.jsonl');consecutive=0
    requests=json.loads((out/'jev-requests.json').read_text(encoding='utf-8'))
    with (out/'jev.jsonl').open('a',encoding='utf-8') as stream:
        for ident,req in requests.items():
            if ident in done:continue
            row=dec.evaluate('round4-formal-v1',ident,'same-condition replacement evaluation',{'revision':'round4-formal-v1'},
                request=req,question_version='chat-clarification-v1');row['key']=ident
            if row.get('answers'):
                try:row['answers']=validate_answers(row,req[1])
                except ValueError as error:row.update(status='unavailable',reason=str(error),answers={})
            stream.write(json.dumps(row,ensure_ascii=False)+'\n');stream.flush();done[ident]=row
            write(out/'jev-ledger.json',dec.ledger('round4-formal-v1'))
            print(json.dumps(dict(key=ident[:12],status=row['status'],ms=row.get('latency_ms'))),flush=True)
            if row.get('answers'):consecutive=0
            else:consecutive+=1
            if row['status']=='budget_exhausted' or consecutive>=3:raise ValueError('stop_budget_or_three_independent_failures_no_repeat')
    write(out/'jev-ledger.json',dec.ledger('round4-formal-v1'))

def native_run(out):
    path=out/'native';path.mkdir(exist_ok=True)
    if (path/'flows.jsonl').exists():raise ValueError('paid_run_exists_no_replay')
    gates=json.loads((out/'round04/label-gates.json').read_text(encoding='utf-8'))
    stats=json.loads((out/'round04/summary.json').read_text(encoding='utf-8'))
    if gates['checkpoint_sha256']!=stats['checkpoint_sha256']:raise ValueError('gate_checkpoint_mismatch')
    raw=cache(out/'round04/scores.jsonl');jev=cache(out/'jev.jsonl')
    models=dict(jev=AliasDecisions(jev),laya=AliasDecisions({k:apply_labels(r,gates) for k,r in raw.items()}))
    fixtures=json.loads((out/'native-cases.json').read_text(encoding='utf-8'));excluded=[];paired=[]
    for case in fixtures:
        req=request_for(native_task(case))
        if all(model.evaluate(request=req).get('answers') for model in models.values()):paired.append(case)
        else:excluded.append(case['id'])
    write(path/'excluded.json',dict(ids=excluded,total=len(fixtures),paired=len(paired),reason='missing actual classifier response; not re-requested'))
    if not paired:raise ValueError('no_paired_native_cases')
    env={**dotenv_values(ROOT/'.hermes/.env'),**os.environ};secret=env.get('DEEPSEEK_API_KEY')
    if not secret:raise ValueError('main_not_configured')
    isolated=path/'isolated';isolated.mkdir(exist_ok=True);os.environ['HERMES_HOME']=str(isolated)
    (isolated/'config.yaml').write_text('memory:\n  memory_enabled: false\n  user_profile_enabled: false\nauxiliary:\n  title_generation:\n    enabled: false\n  background_review:\n    enabled: false\n',encoding='utf-8')
    service=Clarifications(Store(isolated));budget=Budget(path/'main-ledger.json',usd=1.6,max_calls=480)
    sources=['scripts/run_laya_round4_replacement.py','scripts/formal_seven_label_gates.py','scripts/evaluate_native_fastpath.py',
        'scripts/jev_laya_matched.py','scripts/decision_fastpath.py','scripts/chat_action_contract.py',
        'miniclaw_web/clarification_policy.py','miniclaw_web/hermes_clarification_adapter.py','plugins/miniclaw-files/__init__.py']
    saved=path/'source-before-run';saved.mkdir();hashes={}
    for source in sources:
        data=(ROOT/source).read_bytes();hashes[source]=hashlib.sha256(data).hexdigest();(saved/source.replace('/','__')).write_bytes(data)
    write(saved/'manifest.json',hashes)
    from hermes_state import SessionDB
    original=native.plugin_tools
    def typed(workspace):
        schemas,handlers=original(workspace);item=schemas[0]['function']['parameters']['properties']['questions']['items']
        for field in ('id','template'):item['properties'][field]['enum']+=['Q_EXECUTION','Q_CONFLICT','Q_REFERENCE_ROLE']
        return schemas,handlers
    collected=[]
    with patch.object(native,'plugin_tools',side_effect=typed),SessionDB(db_path=isolated/'history.db') as db,httpx.Client(timeout=45,trust_env=False) as client:
        for i,case in enumerate(paired):
            arms=('jev','laya') if i%2==0 else ('laya','jev')
            for arm in arms:
                row=native.run_case(case,arm,0,client,secret,service,models[arm],budget,db,path,
                    hold_unresolved_target=True,clear_discussion=True,policy_factory=MatchedNativePolicy)
                collected.append(row)
                with (path/'flows.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
                write(path/'report.json',dict(summarize_native(collected,'in_progress'),excluded=excluded,
                    laya_uses_jev_fallback=False,raw_classifier_scored_once=True,production_changed=False))
                print(json.dumps({k:row[k] for k in ('id','arm','joint_match','first_question','main_calls','terminal')}),flush=True)
    write(path/'report.json',dict(summarize_native(collected,'complete'),excluded=excluded,laya_uses_jev_fallback=False,
        raw_classifier_scored_once=True,production_changed=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=('jev','native'));p.add_argument('out',type=Path);a=p.parse_args()
    dict(jev=fetch,native=native_run)[a.phase](a.out.resolve())
