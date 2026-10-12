"""Audit measured native runs; no model calls, labels or records are changed."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics

def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]

def peak_cost(row):
    u=row.get('usage',{});p=u.get('prompt_tokens',0);o=u.get('completion_tokens',0)
    hit=min(p,max(0,u.get('prompt_cache_hit_tokens',0)))
    return (hit*.006+(p-hit)*.30+o*1.20)/1e6

def main(out):
    flows=read_rows(out/'flows.jsonl');calls=read_rows(out/'main-calls.jsonl')
    report=json.loads((out/'report.json').read_text(encoding='utf-8'))
    arms={}
    for arm in ('main','rules_fast','jev_fast','laya_fast','laya_business'):
        rs=[r for r in flows if r['arm']==arm]
        if not rs:continue
        tags={f'{arm}-{r["repeat"]}-{r["id"]}' for r in rs};api=[r for r in calls if r['tag'] in tags]
        peak=sum(peak_cost(r) for r in api)
        ds=[v['decision'] for r in rs for v in r['decision_records'] if v['decision']]
        known=sum(d.get('estimated_micro_usd',0) for d in ds)/1e6 if arm=='jev_fast' else 0
        waiting=[r['waiting_probe'] for r in rs if r['waiting_probe'] is not None]
        dup=[r['duplicate_probe'] for r in rs if r['duplicate_probe'] is not None]
        arms[arm]={'main_api_requests':len(api),'main_offpeak_estimated_usd':round(peak/2,9),
            'main_peak_estimated_usd':round(peak,9),'decision_known_estimated_usd':known,
            'total_offpeak_known_estimated_usd':round(peak/2+known,9),
            'decision_calls':len(ds),'decision_statuses':dict(Counter(d['status'] for d in ds)),
            'first_turn_zero_main':sum(r['phases'][0]['api_calls']==0 for r in rs),
            'questions':sum(bool(r['phases'][0]['questions']) for r in rs),
            'originals_preserved':sum(r['originals_preserved'] for r in rs),
            'actual_image_jobs':sum(len(r['image_jobs']) for r in rs),
            'pixel_checks':sum(r['pixel_match'] is not None for r in rs),
            'pixel_checks_pass':sum(r['pixel_match'] is True for r in rs),
            'waiting_probes':len(waiting),'waiting_probes_pass':sum(waiting),
            'duplicate_probes':len(dup),'duplicate_probes_pass':sum(dup),
            'actual_artifacts':sum(len(r['artifacts']) for r in rs),
            'main_network_ms':sum(r['main_network_ms'] for r in rs)}
    main_rows={(r['id'],r['repeat']):r for r in flows if r['arm']=='main'}
    paired={}
    for arm in ('rules_fast','jev_fast','laya_fast','laya_business'):
        diffs=[(main_rows[(r['id'],r['repeat'])],r) for r in flows if r['arm']==arm and (r['id'],r['repeat']) in main_rows]
        paired[arm]={'pairs':len(diffs),'main_requests_saved':sum(a['main_calls']-b['main_calls'] for a,b in diffs),
            'median_first_ms_saved':round(statistics.median(a['first_ms']-b['first_ms'] for a,b in diffs)) if diffs else None,
            'median_flow_ms_saved':round(statistics.median(a['latency_ms']-b['latency_ms'] for a,b in diffs)) if diffs else None}
        same=[(a,b) for a,b in diffs if a['joint_match'] and b['joint_match']]
        def cost(r):
            tag=f'{r["arm"]}-{r["repeat"]}-{r["id"]}'
            return sum(peak_cost(c)/2 for c in calls if c['tag']==tag)
        paired[arm]['both_correct']={'pairs':len(same),'main_offpeak_usd':round(sum(cost(a) for a,b in same),9),
            'arm_main_offpeak_usd':round(sum(cost(b) for a,b in same),9),
            'arm_decision_known_usd':sum(v['decision'].get('estimated_micro_usd',0) for a,b in same
                for v in b['decision_records'] if v['decision'])/1e6,
            'main_requests_saved':sum(a['main_calls']-b['main_calls'] for a,b in same)}
    result={'source_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (out/'flows.jsonl',out/'main-calls.jsonl',out/'report.json')},
        'complete':report['status']=='complete','unique_flow_keys':len({(r['id'],r['repeat'],r['arm']) for r in flows}),
        'recorded_requests':len(calls),'received_requests':sum(r['status']=='received' for r in calls),
        'arms':arms,'paired':paired,'jev_ledger':report['jev_ledger'],
        'pricing_basis':'DeepSeek official pricing HTTP200 on 2026-10-11, page saved beside primary audit; Flash cache hit .006/miss .30/output 1.20 per million peak, offpeak half. Sunday is offpeak; estimates not invoices. Jev .042/million confirmed official TypeSafe blog (Oct7 case study) via web on Oct11, known usage only; unknown held ledger separate. Local GPU energy excluded.'}
    (out/'audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('out',type=Path);main(p.parse_args().out)
