"""Separate untouched new test, known regressions, and native tool evidence."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'hermes-agent')]
from scripts.evaluate_jev_laya_matched import write,cache
from scripts.formal_seven_gates import key,apply_gates
from scripts.jev_laya_matched import replay,formal_task

def task_for(row):
    s=json.loads(row['request'][0]);semantic={k:s.get(k) for k in ('selected','candidates')}
    semantic['selection']='用户圈选的左侧区域' if row['kind']=='region' and s['selected'] else None
    return dict(id=row['id'],text=s['user_request'],confirmed=s['confirmed'],context=dict(semantic=semantic))

def expected_questions(row):
    g=row['expected'];s=json.loads(row['request'][0]);result=[]
    if g['intent']=='unclear':result.append('Q_INTENT')
    if g['conflict']=='present':result.append('Q_CONFLICT')
    if g['intent'] in ('execute_change','adopt_result','generate_media'):
        # A new generated object does not require choosing an existing image.
        if g['target']=='ambiguous' and not s['selected']:result.append('Q_TARGET')
        if g['scope']=='selected_region' and not s['selected']:result.append('Q_SCOPE')
    return result

def summarize(items):
    result={}
    for model in ('jev','round02','round03_raw','round03_gated'):
        rows=[r for r in items if r['model']==model];heads={}
        if not rows:continue
        for head in rows[0]['gold']:
            accepted=[r for r in rows if r.get('accepted',{}).get(head)]
            heads[head]=dict(total=len(rows),correct=sum(r['answers'].get(head,{}).get('choice')==r['gold'][head] for r in rows),
                accepted=len(accepted),accepted_correct=sum(r['answers'][head]['choice']==r['gold'][head] for r in accepted))
        result[model]=dict(cases=len(rows),heads=heads,questions_correct=sum(r['questions_correct'] for r in rows),
            extra_questions=sum(r['extra_questions'] for r in rows),missed_questions=sum(r['missed_questions'] for r in rows),
            rule_intent_correct=sum(r['replay']['intent']==r['gold']['intent'] for r in rows))
    return result

def analyze(out):
    old=ROOT/'.codex/verification/jev-laya-matched-2026-10-11'
    raw=json.loads((out/'data/review.json').read_text(encoding='utf-8'))
    caches=dict(jev=cache(out/'jev.jsonl'),round02=cache(out/'round02/scores.jsonl'),round03_raw=cache(out/'round03/scores.jsonl'))
    gates=json.loads((out/'round03/gates.json').read_text(encoding='utf-8'))
    caches['round03_gated']={k:apply_gates(v,gates) for k,v in caches['round03_raw'].items()}
    report=dict(new_test={},known_regression={},limitations=['author-labelled synthetic samples; two binding states and profiles within each phrase family are correlated',
        'raw Jev uses current production confidence threshold; Laya selective gates fitted independently on calibration primary only',
        'pre-model replay is diagnostic; resume classification is skipped by actual adapter',
        'native tool success does not certify text factual accuracy'])
    detail=[];excluded=[]
    for profile in ('primary','enriched'):
        paired=[]
        for row in raw:
            if row['split']!='test' or row['profile']!=profile:continue
            ident=key(row['request'])
            if any(not c.get(ident,{}).get('answers') for c in caches.values()):excluded.append(row['id']);continue
            for model,cached in caches.items():
                pred=cached[ident];expected=expected_questions(row);result=replay(task_for(row),pred)
                qs=[q['template'] for q in result['questions']]
                acceptance=pred.get('selective_acceptance')
                if acceptance is None:
                    acceptance={}
                    for head,a in pred['answers'].items():
                        probabilities=sorted(a['probabilities'].values(),reverse=True)
                        acceptance[head]=a['confidence']>=.85 and probabilities[0]-probabilities[1]>=.2
                entry=dict(id=row['id'],kind=row['kind'],profile=profile,model=model,gold=row['expected'],answers=pred['answers'],
                    replay=result,expected_questions=expected,questions_correct=qs==expected,
                    extra_questions=bool(set(qs)-set(expected)),missed_questions=bool(set(expected)-set(qs)),accepted=acceptance)
                detail.append(entry);paired.append(entry)
        report['new_test'][profile]=summarize(paired)
    report['excluded_new_test_cases']=excluded
    old_data=json.loads((old/'dataset.json').read_text(encoding='utf-8'));index={(r['profile'],r['id']):r['key'] for r in old_data['index']}
    qmap=dict(intent='Q_INTENT',target='Q_TARGET',region='Q_SCOPE',conflict='Q_CONFLICT')
    for profile in ('primary','enriched'):
        report['known_regression'][profile]={}
        for model,cached in caches.items():
            rs=[]
            for case in old_data['diagnostic']:
                ident=index[profile,case['id']]
                if any(not c.get(ident,{}).get('answers') for c in caches.values()):continue
                pred=cached[ident];result=replay(formal_task(case),pred);qs=[q['template'] for q in result['questions']]
                expected=[qmap[q] for q in case['gold']['questions']];g=case['formal_gold']
                rs.append(dict(id=case['id'],questions_correct=qs==expected,extra=bool(set(qs)-set(expected)),missed=bool(set(expected)-set(qs)),
                    intent_correct=pred['answers']['intent']['choice']==g.get('intent') if 'intent' in g else None))
            report['known_regression'][profile][model]=dict(cases=len(rs),raw_intent_correct=sum(r['intent_correct'] is True for r in rs),
                raw_intent_total=sum(r['intent_correct'] is not None for r in rs),questions_correct=sum(r['questions_correct'] for r in rs),
                extra=sum(r['extra'] for r in rs),missed=sum(r['missed'] for r in rs))
    if (out/'native/report.json').exists():report['native']=json.loads((out/'native/report.json').read_text(encoding='utf-8'))
    if (out/'aux-native/report.json').exists():report['auxiliary_native']=json.loads((out/'aux-native/report.json').read_text(encoding='utf-8'))
    report['calibration']=gates
    write(out/'analysis.json',report);write(out/'test-analysis-detail.json',detail)
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);analyze(p.parse_args().out)
