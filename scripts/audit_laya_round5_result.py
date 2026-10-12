"""Evidence consistency audit. Performance failures remain report findings."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import httpx

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def rows(p):return [json.loads(s) for s in p.read_text(encoding='utf-8').splitlines() if s]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def audit(out):
    training=read(out/'training-summary.json');assert training['status']=='completed' and training['actual_updates']==1015 and training['base_unchanged']
    assert training['parameter_audit']['all_output_tensors_finite']
    data=read(out/'data/manifest.json')
    for split,info in data['outputs'].items():assert sha(out/'data'/f'{split}.jsonl')==info['sha256']
    sources=read(out/'source-before-evaluation/manifest.json');changed={f:sha(ROOT/f) for f,h in sources.items() if sha(ROOT/f)!=h}
    assert set(changed)<={'scripts/serve_laya_formal.py','scripts/probe_laya_round5.py'}
    gate_checks={}
    for m in ('round04','round05'):
        test=out/m/'test-detail.json'
        gate_checks[m]={name:(out/m/(name+'-gates.json')).stat().st_mtime_ns<test.stat().st_mtime_ns for name in ('label','consumption')}
        assert all(gate_checks[m].values())
        for name in ('label','consumption'):
            g=read(out/m/(name+'-gates.json'));assert g['frozen_before_test'] and g['calibration_sha256']==data['outputs']['calibration']['sha256']
    flows=[];calls=[];ledger=[]
    for name in ('native','http-native','http-native-repair-input/http-native','raw-native'):
        folder=out/name;assert read(folder/'report.json')['status']=='complete'
        fs=rows(folder/'flows.jsonl');cs=rows(folder/'main-calls.jsonl');ls=read(folder/'main-ledger.json')
        assert len(cs)==len(ls)==sum(r['main_calls'] for r in fs)
        flows+=fs;calls+=cs;ledger+=ls
    assert all(r['status']=='received' for r in calls)
    assert len(calls)<=300 and sum(r['held_usd'] for r in ledger)<=1.2
    assert all(r['originals_preserved'] for r in flows)
    assert all(r['pixel_match'] is True and r['duplicate_probe'] is True for r in flows if r['image_jobs'])
    assert all(r['waiting_probe'] is True for r in flows if r['terminal']=='awaiting_input')
    assert all(not d['decision'].get('jev_fallback',False) for r in flows if r['arm']=='laya' for d in r['decision_records'])
    probe=read(out/'local-http-probe.json');assert probe['all_matched'] and probe['unsupported_count_declined'] and all(probe['unsupported_confirmation_or_version_declined'])
    health={}
    with httpx.Client(timeout=10,trust_env=False) as client:
        for url in ('http://127.0.0.1:9120/','http://127.0.0.1:8767/','http://127.0.0.1:8768/local/runtime','http://127.0.0.1:8769/local/runtime'):
            health[url]=client.get(url).status_code
    assert all(c==200 for c in health.values())
    jev=rows(out/'jev.jsonl');report=dict(status='passed',trained_updates=training['actual_updates'],model_sha256=training['output_sha256'],
        data_frozen=True,gates_written_before_test=gate_checks,primary_evaluation_source_files_unchanged=len(sources)-len(changed),runtime_boundary_repair_sources=changed,actual_main_calls=len(calls),received_main_responses=len(calls),
        ledger_entries=len(ledger),real_flows=len(flows),originals_preserved=sum(r['originals_preserved'] for r in flows),
        pixel_checks=sum(r['pixel_match'] is True for r in flows),duplicate_receipts=sum(r['duplicate_probe'] is True for r in flows),
        native_status=read(out/'native/report.json'),http_native_status=read(out/'http-native/report.json'),http_repair_status=read(out/'http-native-repair-input/http-native/report.json'),raw_native_status=read(out/'raw-native/report.json'),
        jev_cache_status=dict(Counter(r['status'] for r in jev)),jev_physical_calls=read(out/'jev-ledger.json')['calls'],
        health=health,production_provider_changed=False,performance_is_not_asserted_by_this_integrity_audit=True)
    (out/'audit-final.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);audit(p.parse_args().out.resolve())
