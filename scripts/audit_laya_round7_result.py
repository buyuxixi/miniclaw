"""Frozen training/calibration boundaries, paid ledgers and real tool evidence."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'hermes-agent')]
from scripts.evaluate_jev_laya_matched import write
from scripts.decision_answer_contract import validate_answers
from scripts.formal_seven_gates import key


def audit(out):
    import httpx
    def read(p):return json.loads(p.read_text(encoding='utf-8'))
    def rows(p):return [json.loads(s) for s in p.read_text(encoding='utf-8').splitlines() if s]
    def sha(p):
        with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
    data=read(out/'data/review.json');fresh=read(out/'data/fresh.json');manifest=read(out/'data/manifest.json');training=read(out/'training-summary.json')
    freeze=read(out/'gate-freeze.json');repair=read(out/'dispatch-only-repair.json');intent_repair=read(out/'intent-repair.json');runtimefreeze=read(out/'native-runtime-freeze.json')
    assert training['status']=='completed' and training['data']['optimizer_updates']==630 and training['data']['rows_read']==720
    assert training['actual_updates']==630 and training['parameter_audit']['all_output_tensors_finite'] and training['parameter_audit']['changed_tensor_count']>0
    assert training['base_unchanged'] and sha(Path(training['base'])/'model.safetensors')==training['base_sha256']
    assert sha(Path('D:/model/laya-business-advisory/round-07-formal-seven/model.safetensors'))==training['output_sha256']
    assert training['dataset_manifest']==manifest
    for split,info in manifest['outputs'].items():assert sha(out/'data'/f'{split}.jsonl')==info['sha256']
    assert manifest['source_sha256']==sha(ROOT/'scripts/build_laya_formal_round7.py')
    assert len({key(r['request']) for r in fresh})==len(fresh)
    textsets={s:{json.loads(r['request'][0])['user_request'] for r in data if r['split']==s} for s in manifest['outputs']}
    for a in textsets:
        for b in textsets:
            if a!=b:assert not textsets[a]&textsets[b],(a,b)
    old=ROOT/'.codex/verification/laya-formal-round5-2026-10-11/data/review.json'
    assert sha(old)==manifest['previous_review_sha256']
    oldtrain={key(r['request']) for r in read(old) if r['split']=='train'}
    replay=[r for r in data if r['source']=='round05-train-replay']
    assert len(replay)==400 and all(r['split']=='train' and key(r['request']) in oldtrain for r in replay)
    for p,h in freeze['sources'].items():
        current=sha(ROOT/p)
        if current!=h:
            matching=repair if p==repair['source_path'] else intent_repair
            assert p==matching['source_path'] and matching['status']=='passed' and h==matching['original_sha256'] and current==matching['current_sha256']
    assert sha(out/'source-before-missing-name-guard/hermes_clarification_adapter.py')==repair['original_sha256']
    assert freeze['test_scored'] is False
    for model,h in freeze['gates'].items():
        p=out/model/'joint-gates.json';g=read(p);assert sha(p)==h and g['frozen_before_test']
        assert p.stat().st_mtime_ns<(out/model/'test-detail.json').stat().st_mtime_ns
        assert g['calibration_sha256']==manifest['outputs']['calibration']['sha256'] and g['confirmation_profiles']==['none','execute','draft','target']
        assert g['checkpoint_sha256']==sha(Path(f'D:/model/laya-business-advisory/round-{model[-2:]}-formal-seven/model.safetensors'))
        for rules in g['questions'].values():
            for rule in rules['labels'].values():assert rule['accepted']>=8 and rule['families']>=4 and rule['errors']==0
        scored=rows(out/model/'scores.jsonl');by={r['key']:r for r in scored};assert len(by)==len(scored)
        for r in fresh:
            if r['split']!='train':validate_answers(by[key(r['request'])],r['request'][1])
    assert runtimefreeze['before_first_flow'] and runtimefreeze['cases_sha256']==sha(out/'native-cases.json')
    for p,h in runtimefreeze['sources'].items():
        if p==intent_repair['source_path']:assert h==intent_repair['original_sha256'] and sha(ROOT/p)==intent_repair['current_sha256']
        else:assert sha(ROOT/p)==h
    fs=rows(out/'native/flows.jsonl');calls=rows(out/'native/main-calls.jsonl');ledger=read(out/'native/main-ledger.json');report=read(out/'native/report.json')
    assert report['status']=='complete' and len(fs)==36 and len({(r['id'],r['arm']) for r in fs})==36
    assert len(calls)==len(ledger)==sum(r['main_calls'] for r in fs) and len(calls)<=100 and sum(r['held_usd'] for r in ledger)<=.50
    assert all(r['status']=='received' for r in calls)
    assert all(r['originals_preserved'] for r in fs)
    assert all(r['pixel_match'] is True and r['duplicate_probe'] is True for r in fs if r['image_jobs'])
    assert all(r['waiting_probe'] is True for r in fs if r['terminal']=='awaiting_input')
    for r in fs:
        assert len(r['decision_records'])==1
        if r['arm']=='laya':
            d=r['decision_records'][0]['decision'];assert d['provider']=='laya-local' and not d['jev_fallback'] and not d['grants_permission']
            assert d['checkpoint_sha256']==training['output_sha256'] and d['gate_sha256']==freeze['gates']['round07']
    jev=rows(out/'jev.jsonl');requests=read(out/'jev-requests.json');jl=read(out/'jev-ledger.json')
    assert len(jev)==len({r['key'] for r in jev})==len(requests)==jl['calls']==337
    assert jl['estimated_usd']<=.10 and jl['calls']<=400
    for r in jev:
        if r.get('answers'):validate_answers(r,requests[r['key']][1])
    probe=read(out/'live-probe.json');assert probe['status']=='passed' and probe['max_probability_delta']==0 and probe['paid_model_calls']==0
    assert all(probe['confirmation_pixels'][x] for x in ('actual_saved_answer','actual_image_job','pixels_match','original_unchanged'))
    assert intent_repair['frozen_question_comparisons']==2878 and intent_repair['classifier_probabilities_and_gates_unchanged']
    assert sha(out/'source-before-intent-repair/candidate_clarification_policy.py')==intent_repair['original_sha256']
    trial=out/'intent-repair-trial/native';repair_flows=rows(trial/'flows.jsonl');repair_calls=rows(trial/'main-calls.jsonl');repair_ledger=read(trial/'main-ledger.json')
    assert read(trial/'report.json')['status']=='complete' and len(repair_flows)==2 and all(r['joint_match'] and r['pixel_match'] and r['originals_preserved'] and r['duplicate_probe'] for r in repair_flows)
    assert len(repair_calls)==len(repair_ledger)==sum(r['main_calls'] for r in repair_flows)==4 and all(r['status']=='received' for r in repair_calls)
    assert len(calls)+len(repair_calls)<=100 and sum(r['held_usd'] for r in ledger+repair_ledger)<=.50
    assert read(out/'coordinator-probe.json')['status']=='passed'
    health={}
    with httpx.Client(timeout=10,trust_env=False) as c:
        for url in ('http://127.0.0.1:9120/','http://127.0.0.1:8767/','http://127.0.0.1:8768/local/runtime','http://127.0.0.1:8769/local/runtime','http://127.0.0.1:8770/local/runtime','http://127.0.0.1:8771/local/runtime'):health[url]=c.get(url).status_code
        live=c.get('http://127.0.0.1:8771/local/runtime').json()
    assert all(v==200 for v in health.values()) and live['checkpoint_sha256']==training['output_sha256'] and live['gate_sha256']==freeze['gates']['round07']
    pairs={}
    for r in fs:pairs.setdefault(r['id'],{})[r['arm']]=r
    differences=dict(pairs=len(pairs),wins=[i for i,p in pairs.items() if p['laya']['joint_match'] and not p['jev']['joint_match']],regressions=[i for i,p in pairs.items() if p['jev']['joint_match'] and not p['laya']['joint_match']])
    write(out/'native/paired-differences.json',differences)
    write(out/'native/content-candidates.json',[dict(id=r['id'],arm=r['arm'],**a) for r in fs for a in r['artifacts']])
    result=dict(status='passed',train=720,calibration=320,test=320,valid_classifier_pairs=read(out/'analysis.json')['paired'],optimizer_updates=630,
        gates_frozen_before_test=True,shared_dispatch_repair_disclosed=True,training_base_unchanged=True,jev_calls=337,jev_statuses=dict(Counter(r['status'] for r in jev)),jev_estimated_usd=jl['estimated_usd'],
        real_flows=len(fs),actual_main_calls=len(calls),main_estimated_usd=sum(r['held_usd'] for r in ledger),pixel_checks=sum(r['pixel_match'] is True for r in fs),
        originals_preserved=len(fs),duplicate_receipts=sum(r['duplicate_probe'] is True for r in fs),waiting_write_blocks=sum(r['waiting_probe'] is True for r in fs),
        http_profiles=len(probe['checks']),actual_confirmation_pixel_check=True,production_default_changed=False,health=health,
        shared_intent_repair_disclosed=True,repair_trial_flows=2,repair_trial_main_calls=4,total_actual_main_calls=len(calls)+4,total_main_estimated_usd=sum(r['held_usd'] for r in ledger+repair_ledger),
        performance_failures_preserved=[dict(id=r['id'],arm=r['arm'],terminal=r['terminal']) for r in fs if not r['joint_match']])
    write(out/'audit-final.json',result);print(json.dumps(result))

if __name__=='__main__':audit(Path(sys.argv[1]).resolve())
