"""Four integration flows using real local Laya HTTP and real hosted tools."""
import argparse
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'hermes-agent')]
import httpx
from dotenv import dotenv_values
from miniclaw_web.laya_formal import LayaFormalDecisions
from miniclaw_web.clarifications import Clarifications
from miniclaw_web.store import Store
from scripts.jev_laya_matched import MatchedNativePolicy
from scripts.evaluate_chat_harness import Budget
from scripts.evaluate_jev_laya_matched import write
import scripts.evaluate_native_fastpath as native

def run(out,artifact_only=False):
    out=out.resolve()
    path=out/('http-native-artifact-repair' if artifact_only else 'http-native');path.mkdir(exist_ok=True)
    if (path/'flows.jsonl').exists():raise ValueError('paid_smoke_exists_no_replay')
    stats=json.loads((out/'round04/summary.json').read_text(encoding='utf-8'))
    decisions=LayaFormalDecisions(checkpoint_sha256=stats['checkpoint_sha256'])
    cases=json.loads((out/'native-cases.json').read_text(encoding='utf-8'))
    selected=[c for c in cases if c['id'] in ('quote-missing','r4-action-0-1','r4-action-2-None','r4-draft-5-1')]
    if artifact_only:selected=[c for c in selected if c['id']=='r4-draft-5-1']
    if len(selected)!=(1 if artifact_only else 4):raise ValueError('missing_smoke_case')
    env={**dotenv_values(ROOT/'.hermes/.env'),**os.environ};secret=env.get('DEEPSEEK_API_KEY')
    if not secret:raise ValueError('main_not_configured')
    isolated=path/'isolated';isolated.mkdir();os.environ['HERMES_HOME']=str(isolated)
    (isolated/'config.yaml').write_text('memory:\n  memory_enabled: false\n  user_profile_enabled: false\nauxiliary:\n  title_generation:\n    enabled: false\n  background_review:\n    enabled: false\n',encoding='utf-8')
    service=Clarifications(Store(isolated));budget=Budget(path/'main-ledger.json',usd=.1,max_calls=24)
    from hermes_state import SessionDB
    orig=native.plugin_tools
    def typed(workspace):
        schemas,handlers=orig(workspace);item=schemas[0]['function']['parameters']['properties']['questions']['items']
        for field in ('id','template'):item['properties'][field]['enum']+=['Q_EXECUTION','Q_CONFLICT','Q_REFERENCE_ROLE']
        return schemas,handlers
    rows=[]
    with patch.object(native,'plugin_tools',side_effect=typed),SessionDB(db_path=isolated/'history.db') as db,httpx.Client(timeout=45,trust_env=False) as client:
        for case in selected:
            row=native.run_case(case,'laya_http',0,client,secret,service,decisions,budget,db,path,
                hold_unresolved_target=True,clear_discussion=True,policy_factory=MatchedNativePolicy)
            rows.append(row)
            with (path/'flows.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
            report=dict(status='in_progress',cases=len(rows),correct=sum(r['joint_match'] for r in rows),
                main_calls=sum(r['main_calls'] for r in rows),actual_local_classification_results=[r['decision_records'] for r in rows],
                jev_fallback=False,production_selected=False)
            write(path/'report.json',report);print(json.dumps({k:row[k] for k in ('id','joint_match','first_question','main_calls','terminal')}),flush=True)
    report['status']='complete';write(path/'report.json',report)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);p.add_argument('--artifact-only',action='store_true');a=p.parse_args();run(a.out,a.artifact_only)
