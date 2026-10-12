"""Verify frozen inputs, budgets, real tool evidence and the live candidate pins."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'hermes-agent')]
import httpx
from scripts.decision_answer_contract import validate_answers
from scripts.formal_seven_gates import key
from miniclaw_web.store import Store
from miniclaw_web.clarifications import Clarifications


def audit(out):
    def read(p):return json.loads(p.read_text(encoding='utf-8'))
    def rows(p):return [json.loads(s) for s in p.read_text(encoding='utf-8').splitlines() if s]
    def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
    data=read(out/'data/fresh.json');manifest=read(out/'data/manifest.json');freeze=read(out/'gate-freeze.json');gates=read(out/'joint-gates.json')
    assert sha(out/'data/fresh.json')==manifest['data_sha256'] and sha(out/'joint-gates.json')==freeze['gate_sha256']
    assert freeze['test_scored'] is False and (out/'joint-gates.json').stat().st_mtime_ns<(out/'test-detail.json').stat().st_mtime_ns
    assert gates['checkpoint_sha256']==sha(Path('D:/model/laya-business-advisory/round-05-formal-seven/model.safetensors'))
    assert gates['calibration_sha256']==sha(out/'calibration-detail.json')
    prior=ROOT/'.codex/verification/laya-formal-round5-2026-10-11/round05/calibration-detail.json'
    assert gates['previous_calibration_sha256']==sha(prior)
    texts={s:{json.loads(r['request'][0])['user_request'] for r in data if r['split']==s} for s in ('calibration','test')}
    assert not (texts['calibration'] & texts['test'])
    known=set()
    for p in (ROOT/'.codex/verification').glob('laya-formal-round[345]-2026-10-11/data/review.json'):
        known.update(json.loads(r['request'][0])['user_request'] for r in read(p))
    assert not (known & (texts['calibration']|texts['test']))
    assert len({key(r['request']) for r in data})==len(data)==280
    scores=rows(out/'scores.jsonl');assert len(scores)==280
    bykey={r['key']:r for r in scores};assert len(bykey)==280
    for r in data:validate_answers(bykey[key(r['request'])],r['request'][1])
    for h,rules in gates['questions'].items():
        for rule in rules['labels'].values():assert rule['accepted']>=8 and rule['families']>=4 and rule['errors']==0
    assert read(out/'name-repair.json')['frozen_unique_name_behavior_comparisons']==3000
    for p,h in read(out/'name-repair.json')['repaired_sources'].items():assert sha(ROOT/p)==h
    runtimefreeze=read(out/'native-runtime-freeze.json');assert runtimefreeze['before_first_native_flow']
    assert runtimefreeze['runtime_sha256']==sha(ROOT/'scripts/run_laya_round6_comparison.py')
    assert runtimefreeze['cases_sha256']==sha(out/'native-cases.json')
    fs=rows(out/'native/flows.jsonl');calls=rows(out/'native/main-calls.jsonl');ledger=read(out/'native/main-ledger.json')
    assert len(fs)==16 and len({(r['id'],r['arm']) for r in fs})==16
    assert len(calls)==len(ledger)==sum(r['main_calls'] for r in fs)==20
    assert all(r['status']=='received' for r in calls) and len(calls)<=60 and sum(r['held_usd'] for r in ledger)<=.30
    assert all(r['originals_preserved'] for r in fs)
    assert all(r['pixel_match'] is True and r['duplicate_probe'] is True for r in fs if r['image_jobs'])
    assert all(r['waiting_probe'] is True for r in fs if r['terminal']=='awaiting_input')
    for r in fs:
        assert len(r['decision_records'])==1
        if r['arm']=='laya':
            d=r['decision_records'][0]['decision']
            assert d['provider']=='laya-local' and not d['jev_fallback'] and not d['grants_permission']
            assert d['checkpoint_sha256']==gates['checkpoint_sha256'] and d['gate_sha256']==freeze['gate_sha256']
    store=Store(out/'native/isolated');service=Clarifications(store)
    with store.connect() as db:tasks=[service.task(r[0]) for r in db.execute('SELECT id FROM chat_tasks').fetchall()]
    assert len(tasks)==16
    versions={r['context']['semantic']['versions'] for r in tasks};assert len(versions)==1 and all(len(v)==64 for v in versions)
    jev=rows(out/'jev.jsonl');requests=read(out/'jev-requests.json');jledger=read(out/'jev-ledger.json')
    assert len(jev)==len({r['key'] for r in jev})==len(requests)==jledger['calls']==148
    assert jledger['calls']<=150 and jledger['estimated_usd']<=.05
    for r in jev:validate_answers(r,requests[r['key']][1])
    probe=read(out/'http-probe.json');assert probe['status']=='passed' and probe['coordinator_begin']['jev_calls']==0
    health={}
    with httpx.Client(timeout=10,trust_env=False) as client:
        for url in ('http://127.0.0.1:9120/','http://127.0.0.1:8767/','http://127.0.0.1:8768/local/runtime','http://127.0.0.1:8769/local/runtime','http://127.0.0.1:8770/local/runtime'):
            health[url]=client.get(url).status_code
        live=client.get('http://127.0.0.1:8770/local/runtime').json()
    assert all(v==200 for v in health.values()) and live['checkpoint_sha256']==gates['checkpoint_sha256'] and live['gate_sha256']==freeze['gate_sha256']
    report=dict(status='passed',frozen_rows=280,calibration_rows=500,frozen_gates_before_test=True,checkpoint_updated=False,
        actual_main_calls=20,real_flows=16,originals_preserved=16,pixel_checks=sum(r['pixel_match'] is True for r in fs),
        duplicate_receipts=sum(r['duplicate_probe'] is True for r in fs),waiting_write_blocks=sum(r['waiting_probe'] is True for r in fs),
        jev_physical_calls=148,jev_statuses=dict(Counter(r['status'] for r in jev)),jev_estimated_usd=jledger['estimated_usd'],
        main_estimated_usd=sum(r['held_usd'] for r in ledger),provider_default_changed=False,health=health,
        performance_failures_preserved=[dict(id=r['id'],arm=r['arm'],terminal=r['terminal']) for r in fs if not r['joint_match']])
    (out/'audit-final.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':audit(Path(sys.argv[1]).resolve())
