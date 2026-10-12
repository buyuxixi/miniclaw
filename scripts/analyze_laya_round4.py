"""Paired replacement evidence, independently calibrated labels, and content audit."""
import argparse
from collections import Counter,defaultdict
import json
import math
from pathlib import Path
import statistics
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'hermes-agent')]
from scripts.evaluate_jev_laya_matched import cache,write,rows,native_task
from scripts.formal_seven_gates import key,apply_gates
from scripts.formal_seven_label_gates import apply_labels
from scripts.jev_laya_matched import replay,request_for
from scripts.analyze_laya_formal_round3 import task_for

def expected_questions(row):
    g=row['expected'];s=json.loads(row['request'][0]);result=[]
    # A specified contradiction needs conflict resolution, not a second generic intent question.
    if g['conflict']=='present':return ['Q_CONFLICT']
    if g['intent']=='unclear':result.append('Q_INTENT')
    if g['intent'] in ('execute_change','adopt_result'):
        if g['target']=='ambiguous' and not s['selected']:result.append('Q_TARGET')
        if g['scope']=='selected_region' and not s['selected']:result.append('Q_SCOPE')
    return result

def accepted(row,head):
    if 'selective_acceptance' in row:return bool(row['selective_acceptance'].get(head))
    a=row.get('answers',{}).get(head,{});p=sorted(a.get('probabilities',{}).values(),reverse=True)
    return bool(a.get('confidence',0)>=.85 and len(p)>1 and p[0]-p[1]>=.2)

def wilson(correct,total):
    if not total:return None
    z=1.96;p=correct/total;den=1+z*z/total
    middle=(p+z*z/(2*total))/den
    half=z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/den
    return [round(middle-half,4),round(middle+half,4)]

def summarize(items):
    if not items:return dict(cases=0)
    heads={}
    for head in items[0]['gold']:
        labels=sorted({r['gold'][head] for r in items}|{r['prediction']['answers'][head]['choice'] for r in items})
        per_label={};f1s=[];fam_scores=defaultdict(list);accepted_families=defaultdict(list)
        for label in labels:
            tp=sum(r['gold'][head]==label and r['prediction']['answers'][head]['choice']==label for r in items)
            pred=sum(r['prediction']['answers'][head]['choice']==label for r in items);gold=sum(r['gold'][head]==label for r in items)
            chosen=[r for r in items if accepted(r['prediction'],head) and r['prediction']['answers'][head]['choice']==label]
            f1=2*tp/(pred+gold) if pred+gold else 0.;f1s.append(f1)
            per_label[label]=dict(gold=gold,predicted=pred,correct=tp,f1=round(f1,4),accepted=len(chosen),
                accepted_correct=sum(r['gold'][head]==label for r in chosen),accepted_families=len({r['family'] for r in chosen}))
        for r in items:
            correct=r['gold'][head]==r['prediction']['answers'][head]['choice'];fam_scores[r['family']].append(correct)
            if accepted(r['prediction'],head):accepted_families[r['family']].append(correct)
        ac=sum(all(v) for v in accepted_families.values())
        heads[head]=dict(total=len(items),correct=sum(sum(v) for v in fam_scores.values()),macro_f1=round(statistics.mean(f1s),4),
            family_mean_accuracy=round(statistics.mean(sum(v)/len(v) for v in fam_scores.values()),4),
            accepted=sum(v['accepted'] for v in per_label.values()),accepted_correct=sum(v['accepted_correct'] for v in per_label.values()),
            accepted_families=len(accepted_families),accepted_families_all_correct=ac,
            family_all_correct_wilson_95=wilson(ac,len(accepted_families)),labels=per_label)
    return dict(cases=len(items),families=len({r['family'] for r in items}),heads=heads,
        questions_correct=sum(r['questions_correct'] for r in items),extra_questions=sum(r['extra_questions'] for r in items),
        missed_questions=sum(r['missed_questions'] for r in items),rule_intent_correct=sum(r['rule_intent_correct'] for r in items),
        failures=[dict(id=r['id'],gold=r['gold'],choices={h:a['choice'] for h,a in r['prediction']['answers'].items()},
            expected_questions=r['expected_questions'],questions=r['questions']) for r in items if not r['questions_correct']])

def audit_native(out):
    path=out/'native'
    if not (path/'flows.jsonl').exists():return None
    if not (path/'report.json').exists():return None
    try:
        if json.loads((path/'report.json').read_text(encoding='utf-8')).get('status')!='complete':return None
    except json.JSONDecodeError:return None
    flows=rows(path/'flows.jsonl');calls=rows(path/'main-calls.jsonl');cases={r['id']:r for r in json.loads((out/'native-cases.json').read_text(encoding='utf-8'))}
    by_case=defaultdict(dict);arms={};screen=[]
    # Deliberately a finite screen, not an exhaustive factual correctness grader.
    unsupported=('护眼','不刺眼','亮度可调','亮度调节','续航','认证','零频闪','无频闪','防过敏','杀菌','医疗','不伤眼','柔和光线','光线柔和')
    for r in flows:
        by_case[r['id']][r['arm']]=r
        for artifact in r['artifacts']:
            content=artifact['content'];matches=[w for w in unsupported if w in content]
            # Negative/conditional mentions can be legitimate; preserve full text for manual review.
            screen.append(dict(id=r['id'],arm=r['arm'],file=artifact['name'],matches=matches,content=content,
                evidence_limited_case=r['id'].startswith(('r4-draft-4-','r4-draft-5-'))))
    for arm in ('jev','laya'):
        rs=[r for r in flows if r['arm']==arm]
        arms[arm]=dict(total=len(rs),known_total=sum(not r['id'].startswith('r4-') for r in rs),
            known_correct=sum(r['joint_match'] for r in rs if not r['id'].startswith('r4-')),
            new_total=sum(r['id'].startswith('r4-') for r in rs),new_correct=sum(r['joint_match'] for r in rs if r['id'].startswith('r4-')),
            joint_correct=sum(r['joint_match'] for r in rs),main_calls=sum(r['main_calls'] for r in rs),
            preserved=sum(r['originals_preserved'] for r in rs),pixels=sum(r['pixel_match'] is True for r in rs),
            duplicate_receipts=sum(r['duplicate_probe'] is True for r in rs),waiting=sum(r['waiting_probe'] is True for r in rs),
            artifacts=sum(len(r['artifacts']) for r in rs),failed=[r['id'] for r in rs if not r['joint_match']])
    pairs=[v for v in by_case.values() if set(v)=={'jev','laya'}]
    ledger=json.loads((path/'main-ledger.json').read_text(encoding='utf-8'))
    result=dict(arms=arms,paired=len(pairs),laya_fixed=[v['laya']['id'] for v in pairs if v['laya']['joint_match'] and not v['jev']['joint_match']],
        laya_regressions=[v['laya']['id'] for v in pairs if v['jev']['joint_match'] and not v['laya']['joint_match']],
        physical_main_calls=len(calls),main_responses=sum(r['status']=='received' for r in calls),ledger=ledger,
        content_screen='finite phrases only; positive and negative mentions both flagged, manual evidence review required',
        laya_uses_jev_fallback=False,classification_inferences_reused_not_repeated=True)
    write(out/'content-review.json',screen);return result

def analyze(out):
    review=json.loads((out/'data/review.json').read_text(encoding='utf-8'))
    base=dict(jev=cache(out/'jev.jsonl'),round03_raw=cache(out/'round03/scores.jsonl'),round04_raw=cache(out/'round04/scores.jsonl'))
    profiles=json.loads((out/'round04/profile-gates.json').read_text(encoding='utf-8'))
    result=dict(new_test={},excluded={},known_round3={},goal='Laya replacement of Jev decision recognition, not main planner',
        limitations=['synthetic author labels; variants and binding states correlated within base families',
            'balanced challenge distribution is not measured production distribution',
            'shared formal rule fallback remains; not every predicted head consumed by real flow',
            'no paid media or production gateway UI; pixel/file/receipt verification does not certify facts'])
    detail=[]
    for profile in ('primary','enriched'):
        models=dict(base)
        models['round04_global_gated']={k:apply_gates(r,profiles[profile]['global_gates']) for k,r in base['round04_raw'].items()}
        models['round04_label_gated']={k:apply_labels(r,profiles[profile]['label_gates']) for k,r in base['round04_raw'].items()}
        groups=defaultdict(list);excluded=[]
        for r in review:
            if r['split']!='test' or r['profile']!=profile:continue
            ident=key(r['request'])
            if any(not c.get(ident,{}).get('answers') for c in models.values()):excluded.append(r['id']);continue
            expected=expected_questions(r)
            for label,cached in models.items():
                pred=cached[ident];played=replay(task_for(r),pred);qs=[q['template'] for q in played['questions']]
                item=dict(id=r['id'],family=r['family'],kind=r['kind'],model=label,profile=profile,gold=r['expected'],prediction=pred,
                    expected_questions=expected,questions=qs,questions_correct=qs==expected,
                    extra_questions=bool(set(qs)-set(expected)),missed_questions=bool(set(expected)-set(qs)),
                    rule_intent_correct=played['intent']==r['expected']['intent'],replay=played)
                groups[label].append(item);detail.append(item)
        result['new_test'][profile]={label:summarize(items) for label,items in groups.items()};result['excluded'][profile]=excluded
    old=json.loads((ROOT/'.codex/verification/laya-formal-round3-2026-10-11/data/review.json').read_text(encoding='utf-8'))
    for profile in ('primary','enriched'):
        result['known_round3'][profile]={}
        for label,store in base.items():
            paired=[r for r in old if r['split']=='test' and r['profile']==profile and all(c.get(key(r['request']),{}).get('answers') for c in base.values())]
            result['known_round3'][profile][label]=dict(cases=len(paired),intent_correct=sum(store[key(r['request'])]['answers']['intent']['choice']==r['expected']['intent'] for r in paired))
    fixtures=json.loads((out/'native-cases.json').read_text(encoding='utf-8'));result['native_rule_diagnostic']={}
    for label,store in dict(base,round04_global_gated={k:apply_gates(r,profiles['primary']['global_gates']) for k,r in base['round04_raw'].items()},
        round04_label_gated={k:apply_labels(r,profiles['primary']['label_gates']) for k,r in base['round04_raw'].items()}).items():
        vals=[]
        for case in fixtures:
            ident=key(request_for(native_task(case)))
            if any(not c.get(ident,{}).get('answers') for c in base.values()):continue
            play=replay(native_task(case),store[ident]);qs=[q['template'] for q in play['questions']]
            vals.append(dict(id=case['id'],questions=qs,expected=case['gold']['question'],
                first_match=qs==([case['gold']['question']] if case['gold']['question'] else [])))
        result['native_rule_diagnostic'][label]=dict(cases=len(vals),questions_correct=sum(v['first_match'] for v in vals),failures=[v for v in vals if not v['first_match']])
    result['runtime']={label:dict(unique_requests=len(c),valid=sum(bool(r.get('answers')) for r in c.values()),
        median_ms=statistics.median(r['latency_ms'] for r in c.values() if 'latency_ms' in r)) for label,c in base.items()}
    result['native']=audit_native(out)
    write(out/'analysis.json',result);write(out/'test-analysis-detail.json',detail)
    print(json.dumps(dict(test={p:{m:{h:s['heads'][h]['correct'] for h in ('intent','scope','conflict')}|dict(cases=s['cases'],questions=s['questions_correct']) for m,s in v.items()} for p,v in result['new_test'].items()},
        native_diagnostic=result['native_rule_diagnostic'],native=result['native']['arms'] if result['native'] else None),ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);a=p.parse_args();analyze(a.out)
