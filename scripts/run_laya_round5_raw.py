"""Supplementary known-fixture raw-threshold ablation, not new blind evidence."""
import argparse
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'hermes-agent')]
import httpx
from dotenv import dotenv_values
from miniclaw_web.clarifications import Clarifications
from miniclaw_web.store import Store
from scripts.evaluate_jev_laya_matched import cache,write,summarize_native
from scripts.jev_laya_matched import AliasDecisions
from scripts.run_laya_round5_delegated import DelegatingNativePolicy
from scripts.evaluate_chat_harness import Budget
import scripts.evaluate_native_fastpath as native

def run(out):
    path=out/'raw-native';path.mkdir(exist_ok=True)
    if (path/'flows.jsonl').exists():raise ValueError('paid_ablation_exists_no_replay')
    previous=[]
    for name in ('native','http-native','http-native-repair-input/http-native'):
        report=json.loads((out/name/'report.json').read_text(encoding='utf-8'))
        if report['status']!='complete':raise ValueError('prior_runs_must_be_complete_for_global_budget')
        previous+=json.loads((out/name/'main-ledger.json').read_text(encoding='utf-8'))
    remaining_calls=300-len(previous);remaining_usd=1.2-sum(r['held_usd'] for r in previous)
    if remaining_calls<70 or remaining_usd<.2:raise ValueError('insufficient_global_remaining_budget')
    budget=Budget(path/'main-ledger.json',usd=remaining_usd,max_calls=remaining_calls)
    decisions=AliasDecisions(cache(out/'round05/scores.jsonl'))
    cases=json.loads((out/'native-cases.json').read_text(encoding='utf-8'));excluded=json.loads((out/'native/excluded.json').read_text(encoding='utf-8'))['ids'];cases=[c for c in cases if c['id'] not in excluded]
    env={**dotenv_values(ROOT/'.hermes/.env'),**os.environ};secret=env.get('DEEPSEEK_API_KEY')
    if not secret:raise ValueError('main_not_configured')
    isolated=path/'isolated';isolated.mkdir();os.environ['HERMES_HOME']=str(isolated)
    (isolated/'config.yaml').write_text('memory:\n  memory_enabled: false\n  user_profile_enabled: false\nauxiliary:\n  title_generation:\n    enabled: false\n  background_review:\n    enabled: false\n',encoding='utf-8')
    service=Clarifications(Store(isolated))
    from hermes_state import SessionDB
    original=native.plugin_tools
    def typed(workspace):
        schemas,handlers=original(workspace);item=schemas[0]['function']['parameters']['properties']['questions']['items']
        for field in ('id','template'):item['properties'][field]['enum']+=['Q_EXECUTION','Q_CONFLICT','Q_REFERENCE_ROLE']
        return schemas,handlers
    collected=[]
    with patch.object(native,'plugin_tools',side_effect=typed),SessionDB(db_path=isolated/'history.db') as db,httpx.Client(timeout=45,trust_env=False) as client:
        for c in cases:
            row=native.run_case(c,'laya',0,client,secret,service,decisions,budget,db,path,hold_unresolved_target=True,clear_discussion=True,policy_factory=DelegatingNativePolicy)
            collected.append(row)
            with (path/'flows.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
            write(path/'report.json',dict(summarize_native(collected,'in_progress'),supplementary_known_fixture=True,calibration='original .85 confidence and .20 margin, not independently calibrated',jev_fallback=False))
            print(json.dumps({k:row[k] for k in ('id','joint_match','first_question','main_calls','terminal')}),flush=True)
    write(path/'report.json',dict(summarize_native(collected,'complete'),supplementary_known_fixture=True,calibration='original .85 confidence and .20 margin, not independently calibrated',jev_fallback=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);run(p.parse_args().out.resolve())
