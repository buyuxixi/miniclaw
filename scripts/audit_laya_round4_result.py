"""Final evidence consistency and local service validation; no paid requests."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import httpx
from miniclaw_web.clarification_policy import chat_request
from miniclaw_web.laya_formal import LayaFormalDecisions
from scripts.evaluate_jev_laya_matched import write,rows

def audit(out):
    out=out.resolve();analysis=json.loads((out/'analysis.json').read_text(encoding='utf-8'))
    trained=json.loads((out/'training-summary.json').read_text(encoding='utf-8'))
    assert trained['status']=='completed' and trained['actual_updates']==1400 and trained['base_unchanged']
    assert trained['parameter_audit']['all_output_tensors_finite']
    main=[];ledgers=[];flows=[]
    for folder in ('native','http-native','http-native-artifact-repair'):
        main.extend(rows(out/folder/'main-calls.jsonl'))
        ledgers.extend(json.loads((out/folder/'main-ledger.json').read_text(encoding='utf-8')))
        flows.extend(rows(out/folder/'flows.jsonl'))
    assert len(main)==len(ledgers)==sum(r['main_calls'] for r in flows)==266
    assert all(r['status']=='received' for r in main)
    assert analysis['native']['paired']==82 and not analysis['native']['laya_regressions']
    assert all(r['originals_preserved'] for r in flows)
    assert all(r['pixel_match'] is True for r in flows if r['image_jobs'])
    assert all(r['duplicate_probe'] is True for r in flows if r['image_jobs'])
    assert all(r['waiting_probe'] is True for r in flows if r['terminal']=='awaiting_input')
    assert all(not r['decision_records'][0]['decision'].get('jev_fallback',False) for r in flows if r['arm']=='laya_http')
    source=out/'source-final';source.mkdir(exist_ok=True);hashes={}
    paths=['scripts/laya_round4_catalog.py','scripts/build_laya_formal_round4.py','scripts/prepare_laya_round4.py',
        'scripts/formal_seven_label_gates.py','scripts/evaluate_laya_formal_round4.py','scripts/run_laya_round4_replacement.py',
        'scripts/analyze_laya_round4.py','scripts/audit_laya_round4_data.py','scripts/audit_laya_round4_result.py',
        'scripts/serve_laya_formal.py','scripts/probe_laya_formal.py','scripts/run_laya_http_smoke.py',
        'scripts/evaluate_native_fastpath.py','scripts/train_laya_advisory.py','scripts/build_laya_formal_data.py',
        'scripts/formal_seven_gates.py','scripts/jev_laya_matched.py','miniclaw_web/laya_formal.py',
        'miniclaw_web/clarification_policy.py','tests/test_laya_formal_round4.py','tests/test_laya_formal_provider.py']
    for path in paths:
        data=(ROOT/path).read_bytes();hashes[path]=hashlib.sha256(data).hexdigest();(source/path.replace('/','__')).write_bytes(data)
    write(source/'manifest.json',hashes)
    health={}
    with httpx.Client(timeout=10,trust_env=False) as client:
        for url in ('http://127.0.0.1:9120/','http://127.0.0.1:8767/','http://127.0.0.1:8768/local/runtime'):
            response=client.get(url);health[url]=response.status_code;assert response.status_code==200
        invalid=chat_request('解释这张图。',dict(selected=None,candidates=[dict(id='none',label='第一张')]),{})
        response=client.post('http://127.0.0.1:8768/v1/formal',json=dict(question_version='chat-clarification-v1',request=invalid))
        assert response.status_code==422
    req=chat_request('请把这张图旋转90度。',dict(selected='real-object-b',candidates=[dict(id='real-object-a',label='第一张'),dict(id='real-object-b',label='第二张')]),{})
    provider=LayaFormalDecisions(checkpoint_sha256=trained['output_sha256'])
    result=provider.evaluate('final-local-audit','final-probe-0001','unused',dict(revision=1),request=req)
    assert result['status']=='suggested' and not result['jev_fallback']
    report=dict(status='passed',actual_main_calls=len(main),actual_main_responses=len(main),ledger_entries=len(ledgers),
        total_real_flows=len(flows),originals_preserved=sum(r['originals_preserved'] for r in flows),
        pixel_checks=sum(r['pixel_match'] is True for r in flows),duplicate_receipts=sum(r['duplicate_probe'] is True for r in flows),
        comparison_laya_jev_fallback=False,initial_http_smoke=3,initial_http_smoke_total=4,artifact_repair=1,
        final_service_reserved_id_rejected=True,final_service_real_ids_validated=True,health=health,
        local_classification_extra_unpaid_requests=2,model_sha256=trained['output_sha256'],source_files=len(hashes),
        production_provider_changed=False)
    write(out/'audit-final.json',report);print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);a=p.parse_args();audit(a.out)
