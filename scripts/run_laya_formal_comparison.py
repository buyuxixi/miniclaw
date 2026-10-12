"""Matched formal-seven analysis and bounded real native tool-flow comparison."""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'hermes-agent')]
import httpx
from dotenv import dotenv_values
from scripts.formal_seven_gates import key,apply_gates,GatedDecisions
from scripts.evaluate_jev_laya_matched import write,cache,rows,native_task,jev,summarize_native
from scripts.jev_laya_matched import request_for,AliasDecisions,MatchedNativePolicy,replay,formal_task
from scripts.evaluate_chat_harness import Budget
from miniclaw_web.clarifications import Clarifications
from miniclaw_web.store import Store
import scripts.evaluate_native_fastpath as native

OLD=ROOT/'.codex/verification/jev-laya-matched-2026-10-11'

def prepare(out):
    if (out/'requests.json').exists():raise ValueError('inputs_frozen')
    data=json.loads((out/'data/review.json').read_text(encoding='utf-8'));old=json.loads((OLD/'dataset.json').read_text(encoding='utf-8'))
    fixtures=deepcopy(old['native'])
    new=[('fresh-rotate','麻烦把这张图旋转90度。','rotate'),('fresh-flip','帮我把这张图水平翻转。','flip'),
         ('fresh-quote','伙伴提议翻转商品照，这次请解释提议背后的考虑。','text'),
         ('fresh-compound','请起草一段新品口播和对应视频提示词，分别注明两部分，合成文本保存，本轮不生成媒体。','artifact')]
    for ident,text,effect in new:
        for selected in (None,1):
            missing=selected is None;action=effect in ('rotate','flip')
            fixtures.append(dict(id=ident+('-missing' if missing else '-bound'),text=text,selected=selected,
                reply='第二张' if action and missing else None,
                gold=dict(question='Q_TARGET' if action and missing else None,effect=effect,target=1),source='fresh_heldout_wording_not_independent_action_family'))
    requests={};jev_requests={}
    # Explicit old regression model inputs are not promoted to new test.
    requests.update(json.loads((OLD/'requests.json').read_text(encoding='utf-8')))
    for row in data:
        if row['split']=='test':requests[key(row['request'])]=row['request'];jev_requests[key(row['request'])]=row['request']
    for case in fixtures:
        req=request_for(native_task(case));requests[key(req)]=req;jev_requests[key(req)]=req
    old_jev=cache(OLD/'jev.jsonl');reused={k:v for k,v in old_jev.items() if k in requests}
    write(out/'requests.json',requests);write(out/'native-cases.json',fixtures)
    # Existing unknown responses are also carried over, never silently retried.
    (out/'jev.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in reused.values()),encoding='utf-8')
    write(out/'jev-requests.json',{k:v for k,v in jev_requests.items() if k not in reused})
    write(out/'manifest.json',dict(frozen_before_evaluation=True,known_regression_source=str(OLD),native_cases=len(fixtures),new_jev_requests=len([k for k in jev_requests if k not in reused]),
        reused_jev=len(reused),source='author synthetic',test_used_for_gate_selection=False))
    print(json.dumps(dict(unique_requests=len(requests),new_jev_requests=len([k for k in jev_requests if k not in reused]),native_cases=len(fixtures))))

def fetch_jev(out):
    # Only frozen new comparison inputs; separate ledger, skip all previously recorded keys.
    from miniclaw_web.decisions import JevConfig,JevDecisions
    from scripts.decision_answer_contract import validate_answers
    cfg=JevConfig.from_env({**dotenv_values(ROOT/'.hermes/.env'),**os.environ});cfg.max_calls=200;cfg.budget_micro_usd=100000
    dec=JevDecisions(Store(out/'jev-isolated'),cfg);done=cache(out/'jev.jsonl')
    requests=json.loads((out/'jev-requests.json').read_text(encoding='utf-8'))
    with (out/'jev.jsonl').open('a',encoding='utf-8') as stream:
        for ident,req in requests.items():
            if ident in done:continue
            row=dec.evaluate('round3-formal-v1',ident,'matched auxiliary comparison',{'revision':'round3-formal-v1'},request=req,question_version='chat-clarification-v1');row['key']=ident
            if row.get('answers'):row['answers']=validate_answers(row,req[1])
            stream.write(json.dumps(row,ensure_ascii=False)+'\n');stream.flush();write(out/'jev-ledger.json',dec.ledger('round3-formal-v1'))
            print(json.dumps(dict(key=ident[:12],status=row['status'],ms=row.get('latency_ms'))),flush=True)
            if row['status'] in ('unknown','unavailable','budget_exhausted'):raise ValueError('stop_after_failure_no_repeat:'+str(row.get('reason')))

def native_run(out,auxiliary=False):
    path=out/('aux-native' if auxiliary else 'native');path.mkdir(exist_ok=True)
    if (path/'flows.jsonl').exists():raise ValueError('paid_run_already_exists')
    trained=cache(out/'round03/scores.jsonl');jev_cache=cache(out/'jev.jsonl');gates=json.loads((out/'round03/gates.json').read_text(encoding='utf-8'))
    checkpoints=json.loads((out/'round03/summary.json').read_text(encoding='utf-8'))
    if gates['checkpoint_sha256']!=checkpoints['checkpoint_sha256']:raise ValueError('calibration_checkpoint_mismatch')
    # Calibrate canonical candidate labels before restoring randomized actual IDs.
    gated_cache={ident:apply_gates(row,gates) for ident,row in trained.items()}
    models=dict(jev=AliasDecisions(jev_cache),round03_raw=AliasDecisions(trained),round03_gated=AliasDecisions(gated_cache))
    policy_factory=MatchedNativePolicy;business_client=None
    if auxiliary:
        laya=AliasDecisions(gated_cache)
        class AuxiliaryPolicy(MatchedNativePolicy):
            def prepare_business(self,task):
                advice=dict(contract='formal-seven',mode='advisory',suggestions={},grants_permission=False,binds_target=False,
                    facts_verified=False)
                if self.arm=='jev_plus_laya':
                    row=laya.evaluate(request=request_for(task))
                    advice['suggestions']={name:a['choice'] for name,a in row['answers'].items() if row['selective_acceptance'].get(name)}
                    self.records.append(dict(decision=row,shortcut_question=None,advisory_only=True))
                self.business_result=dict(advice=advice)
        models=dict(jev_empty=AliasDecisions(jev_cache),jev_plus_laya=AliasDecisions(jev_cache))
        policy_factory=AuxiliaryPolicy;business_client=object()
    fixtures=json.loads((out/'native-cases.json').read_text(encoding='utf-8'))
    for case in fixtures:
        for model in models.values():
            row=model.evaluate(request=request_for(native_task(case)))
            if not row.get('answers'):raise ValueError('missing_comparable_native_evidence:'+case['id'])
    env={**dotenv_values(ROOT/'.hermes/.env'),**os.environ};secret=env.get('DEEPSEEK_API_KEY')
    if not secret:raise ValueError('main_model_key_missing')
    isolated=path/'isolated';isolated.mkdir(exist_ok=True);os.environ['HERMES_HOME']=str(isolated)
    (isolated/'config.yaml').write_text('memory:\n  memory_enabled: false\n  user_profile_enabled: false\nauxiliary:\n  title_generation:\n    enabled: false\n  background_review:\n    enabled: false\n',encoding='utf-8')
    service=Clarifications(Store(isolated));budget=Budget(out/'native/main-ledger.json',usd=.8,max_calls=240)
    from hermes_state import SessionDB
    orig=native.plugin_tools
    def typed(workspace):
        schemas,handlers=orig(workspace);item=schemas[0]['function']['parameters']['properties']['questions']['items']
        for field in ('id','template'):item['properties'][field]['enum']+=['Q_EXECUTION','Q_CONFLICT','Q_REFERENCE_ROLE']
        return schemas,handlers
    collected=[]
    with patch.object(native,'plugin_tools',side_effect=typed),SessionDB(db_path=isolated/'history.db') as db,httpx.Client(timeout=45,trust_env=False) as client:
        for i,case in enumerate(fixtures):
            arms=list(models);offset=i%len(arms);arms=arms[offset:]+arms[:offset]
            for arm in arms:
                row=native.run_case(case,arm,0,client,secret,service,models[arm],budget,db,path,hold_unresolved_target=True,clear_discussion=True,
                    policy_factory=policy_factory,business_client=business_client)
                collected.append(row)
                with (path/'flows.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
                print(json.dumps({k:row[k] for k in ('id','arm','joint_match','first_question','main_calls','terminal')}),flush=True)
                summary={'status':'in_progress','arms':{}}
                for label in models:
                    rs=[r for r in collected if r['arm']==label]
                    if rs:summary['arms'][label]=dict(flows=len(rs),joint_correct=sum(r['joint_match'] for r in rs),main_calls=sum(r['main_calls'] for r in rs),
                        pixel_checks=sum(r['pixel_match'] is True for r in rs),originals_preserved=sum(r['originals_preserved'] for r in rs),
                        artifacts=sum(len(r['artifacts']) for r in rs),waiting_blocks=sum(r['waiting_probe'] is True for r in rs),duplicates=sum(r['duplicate_probe'] is True for r in rs),
                        failed=[dict(id=r['id'],question=r['first_question'],terminal=r['terminal']) for r in rs if not r['joint_match']])
                write(path/'report.json',summary)
    summary['status']='complete';write(path/'report.json',summary)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=('prepare','jev','native','aux'));p.add_argument('out',type=Path);args=p.parse_args()
    dict(prepare=prepare,jev=fetch_jev,native=native_run,aux=lambda out:native_run(out,auxiliary=True))[args.phase](args.out.resolve())
