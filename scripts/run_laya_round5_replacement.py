"""Bounded paid baselines and real workflows; no production writes or hidden Jev."""
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
from scripts.evaluate_jev_laya_matched import write,cache,native_task,summarize_native
from scripts.jev_laya_matched import AliasDecisions,request_for
from scripts.formal_seven_consumption_gates import apply_consumption
from scripts.operational_clarification_policy import OperationalClarificationPolicy
from scripts.evaluate_chat_harness import Budget
from scripts.formal_seven_gates import key
from miniclaw_web.store import Store
from miniclaw_web.clarifications import Clarifications
import scripts.evaluate_native_fastpath as native

def fetch(out):
    from miniclaw_web.decisions import JevConfig,JevDecisions
    from scripts.decision_answer_contract import validate_answers
    cfg=JevConfig.from_env({**dotenv_values(ROOT/'.hermes/.env'),**os.environ});cfg.max_calls=450;cfg.budget_micro_usd=100000
    if not cfg.key:raise ValueError('jev_not_configured')
    dec=JevDecisions(Store(out/'jev-isolated'),cfg);done=cache(out/'jev.jsonl');consecutive=0;scope='round5-formal-v1'
    requests=json.loads((out/'jev-requests.json').read_text(encoding='utf-8'))
    with (out/'jev.jsonl').open('a',encoding='utf-8') as stream:
        for ident,req in requests.items():
            if ident in done:continue
            row=dec.evaluate(scope,ident,'frozen same-input comparison',{'revision':scope},request=req,question_version='chat-clarification-v1');row['key']=ident
            if row.get('answers'):
                try:row['answers']=validate_answers(row,req[1])
                except ValueError as e:row.update(status='unavailable',reason=str(e),answers={})
            stream.write(json.dumps(row,ensure_ascii=False)+'\n');stream.flush();done[ident]=row
            write(out/'jev-ledger.json',dec.ledger(scope));print(json.dumps(dict(key=ident[:12],status=row['status'])),flush=True)
            consecutive=0 if row.get('answers') else consecutive+1
            if row['status']=='budget_exhausted' or consecutive>=3:raise ValueError('stop_budget_or_three_independent_failures_no_retry')
    write(out/'jev-ledger.json',dec.ledger(scope))

class OperationalNativePolicy(native.NativePolicy):
    def classify(self,task):
        intent,result,qs=OperationalClarificationPolicy(self.decisions).classify(task)
        self.records.append(dict(decision=result,shortcut_question=qs[0] if qs else None))
        return intent,result,qs
    def guard(self,task,name,args):
        return OperationalClarificationPolicy(self.decisions).guard(task,name,args) or native.NativePolicy.guard(self,task,name,args)

def run_native(out,http=False):
    path=(out/('http-native' if http else 'native')).resolve();path.mkdir(exist_ok=True)
    if (path/'flows.jsonl').exists():raise ValueError('paid_run_exists_no_replay')
    gates=json.loads((out/'round05/consumption-gates.json').read_text(encoding='utf-8'));scores=cache(out/'round05/scores.jsonl')
    requests=json.loads((out/'requests.json').read_text(encoding='utf-8'))
    models=dict(jev=AliasDecisions(cache(out/'jev.jsonl')),laya=AliasDecisions({k:apply_consumption(r,gates,requests[k]) for k,r in scores.items() if k in requests}))
    cases=json.loads((out/'native-cases.json').read_text(encoding='utf-8'));paired=[];excluded=[]
    if http:
        from miniclaw_web.laya_formal import LayaFormalDecisions
        models=dict(laya=LayaFormalDecisions('http://127.0.0.1:8769',gates['checkpoint_sha256'],gate_sha256=hashlib.sha256((out/'round05/consumption-gates.json').read_bytes()).hexdigest()))
        cases=[c for c in cases if c['id'] in ('r5-rotate-a-0','r5-flip-a-None','r5-quote-a-None','r5-draft-a-0')]
        if len(cases)!=4:raise ValueError('http_smoke_cases_missing')
    for c in cases:
        req=request_for(native_task(c))
        if http or all(m.evaluate(request=req).get('answers') for m in models.values()):paired.append(c)
        else:excluded.append(c['id'])
    write(path/'excluded.json',dict(ids=excluded,total=len(cases),paired=len(paired)))
    env={**dotenv_values(ROOT/'.hermes/.env'),**os.environ};secret=env.get('DEEPSEEK_API_KEY')
    if not secret:raise ValueError('main_not_configured')
    isolated=path/'isolated';isolated.mkdir();os.environ['HERMES_HOME']=str(isolated)
    (isolated/'config.yaml').write_text('memory:\n  memory_enabled: false\n  user_profile_enabled: false\nauxiliary:\n  title_generation:\n    enabled: false\n  background_review:\n    enabled: false\n',encoding='utf-8')
    service=Clarifications(Store(isolated));budget=Budget(path/'main-ledger.json',usd=.1 if http else 1.,max_calls=24 if http else 300)
    from hermes_state import SessionDB
    original=native.plugin_tools
    def typed(workspace):
        schemas,handlers=original(workspace);item=schemas[0]['function']['parameters']['properties']['questions']['items']
        for field in ('id','template'):item['properties'][field]['enum']+=['Q_EXECUTION','Q_CONFLICT','Q_REFERENCE_ROLE']
        return schemas,handlers
    collected=[]
    with patch.object(native,'plugin_tools',side_effect=typed),SessionDB(db_path=isolated/'history.db') as db,httpx.Client(timeout=45,trust_env=False) as client:
        for i,c in enumerate(paired):
            for arm in (('laya',) if http else ('jev','laya') if i%2==0 else ('laya','jev')):
                row=native.run_case(c,arm,0,client,secret,service,models[arm],budget,db,path,hold_unresolved_target=True,clear_discussion=True,policy_factory=OperationalNativePolicy)
                collected.append(row)
                with (path/'flows.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
                write(path/'report.json',dict(summarize_native(collected,'in_progress'),excluded=excluded,jev_fallback=False,shared_policy='operational-ablation',production_changed=False))
                print(json.dumps({k:row[k] for k in ('id','arm','joint_match','first_question','main_calls','terminal')}),flush=True)
    write(path/'report.json',dict(summarize_native(collected,'complete'),excluded=excluded,jev_fallback=False,shared_policy='operational-ablation',production_changed=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=('jev','native','http-native'));p.add_argument('out',type=Path);a=p.parse_args();dict(jev=fetch,native=run_native,**{'http-native':lambda out:run_native(out,http=True)})[a.phase](a.out.resolve())
