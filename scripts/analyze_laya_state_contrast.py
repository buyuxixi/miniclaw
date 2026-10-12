"""Audit recorded state experiments; never request models or rewrite their scores."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def observed_plan(record,gold):
    """Diagnostic question/grounding flags even when strict JSON contract failed."""
    try:
        plan=json.loads(record['response']['raw_content'])
        qs=plan['questions'];steps=plan['steps']
        if not isinstance(qs,list) or not isinstance(steps,list):raise ValueError('bad_arrays')
        expected=set(gold['questions']);actual=set(qs)
        # These remain proposed actions, never actual execution. Existing native
        # adapter gives clarify priority if a model emits action and question together.
        return dict(missing_questions=bool(expected-actual),unnecessary_questions=bool(actual-expected),
            mixed_question_and_step=bool(qs and steps),
            ungrounded_target_proposal=('target' in expected and any(s['kind']=='edit_image' for s in steps)),
            compound_step_omission=any(k not in [s['kind'] for s in steps] for k in gold['steps']) if len(gold['steps'])>1 else False)
    except (KeyError,ValueError,TypeError):return dict(unparsed=True)


def native_summary(flows,calls):
    arms={}
    for arm in ('main','laya_business'):
        fs=[f for f in flows if f['arm']==arm]
        cs=[c for c in calls if c['tag'].startswith(arm+'-')]
        ungrounded=0
        for f in fs:
            tag=f'{arm}-{f["repeat"]}-{f["id"]}'
            first=next((c for c in cs if c['tag']==tag),None)
            if not first:continue
            payload=json.loads(next(m['content'] for m in first['request']['messages'] if m['role']=='user'))
            tc=first['choices'][0]['message']['tool_calls'] if first.get('choices') else []
            ungrounded+=payload['context']['selected'] is None and any(t['function']['name']=='miniclaw_edit_image' for t in tc)
        arts=[a for f in fs for a in f['artifacts']]
        compound=[f for f in fs if f['id'].startswith('compound')]
        # Structural evidence of both requested deliverables, not aesthetic quality.
        compound_markers=sum(any('口播' in a['content'] and '提示词' in a['content'] for a in f['artifacts']) for f in compound)
        # Manual review found all eight compound narrations assert unprovided
        # adjustability/eye-comfort properties. Store their identities separately
        # from workflow correctness; these are not accepted product facts.
        unsupported=[dict(id=f['id'],repeat=f['repeat']) for f in compound
                     if any('亮度' in a['content'].split('## 视频')[0] for a in f['artifacts'])]
        arms[arm]=dict(flows=len(fs),correct=sum(f['joint_match'] for f in fs),
            first_turn_ungrounded_edit_attempts=ungrounded,
            unnecessary_first_questions=sum(f['first_question'] is not None and not f['id'].startswith(('rotate-missing','flip-missing','resume-')) for f in fs),
            failed=[dict(id=f['id'],repeat=f['repeat'],question=f['first_question'],terminal=f['terminal']) for f in fs if not f['joint_match']],
            image_jobs=sum(len(f['image_jobs']) for f in fs),
            pixel_checks=sum(f['pixel_match'] is True for f in fs),
            originals_preserved=sum(f['originals_preserved'] for f in fs),
            artifacts=len(arts),compound_cases=len(compound),compound_both_markers=compound_markers,
            compound_unsupported_claims_manual_review=unsupported,
            waiting_probes=sum(f['waiting_probe'] is True for f in fs),
            duplicate_probes=sum(f['duplicate_probe'] is True for f in fs),
            median_flow_ms=statistics.median(f['latency_ms'] for f in fs),
            main_calls=len(cs),received_calls=sum(c['status']=='received' for c in cs),
            prompt_tokens=sum(c.get('usage',{}).get('prompt_tokens',0) for c in cs),
            completion_tokens=sum(c.get('usage',{}).get('completion_tokens',0) for c in cs),
            cache_hit_tokens=sum(c.get('usage',{}).get('prompt_cache_hit_tokens',0) for c in cs))
    idx={(f['id'],f['repeat'],f['arm']):f for f in flows}
    paired=[]
    for f in flows:
        if f['arm']!='main':continue
        b=idx[f['id'],f['repeat'],'laya_business']
        paired.append(dict(id=f['id'],repeat=f['repeat'],corrected=not f['joint_match'] and b['joint_match'],
            harmed=f['joint_match'] and not b['joint_match'],flow_ms_added=b['latency_ms']-f['latency_ms']))
    return dict(arms=arms,paired=paired,corrected=sum(p['corrected'] for p in paired),harmed=sum(p['harmed'] for p in paired),
                median_paired_flow_ms_added=statistics.median(p['flow_ms_added'] for p in paired))


def main(out):
    plan=rows(out/'planning/planning.jsonl')
    data=json.loads((out/'planning/dataset.json').read_text(encoding='utf-8'))
    cases={c['id']:c for c in data['planning']}
    shadow=json.loads((out/'planning/shadow.json').read_text(encoding='utf-8'))
    observed=[dict(id=r['id'],repeat=r['repeat'],arm=r['arm'],flags=observed_plan(r,cases[r['id']]['gold'])) for r in plan]
    flags={arm:{flag:sum(r['flags'].get(flag,False) for r in observed if r['arm']==arm)
        for flag in ('missing_questions','unnecessary_questions','mixed_question_and_step','ungrounded_target_proposal','compound_step_omission','unparsed')}
        for arm in ('main','laya_advisory')}
    mistakes=[]
    accepted_clarification_correct=0
    for ident,result in shadow.items():
        c=cases[ident];gold=c['gold']['questions'][0] if c['gold']['questions'] else 'none'
        hint=result['advice']['clarification']
        accepted_clarification_correct+=hint==gold
        if result['parsed']['clarification']['choice']!=gold or set(result['advice']['categories'])-set(c['categories']):
            mistakes.append(dict(id=ident,expected_clarification=gold,raw_clarification=result['parsed']['clarification']['choice'],
                                 accepted_clarification=hint,expected_categories=c['categories'],accepted_categories=result['advice']['categories']))
    native=native_summary(rows(out/'native/flows.jsonl'),rows(out/'native/main-calls.jsonl'))
    files=['planning/planning.jsonl','planning/dataset.json','planning/gates.json','planning/shadow.json','native/flows.jsonl','native/main-calls.jsonl']
    ablation_path=out/'ablation/planning.jsonl'
    all_usage=[r['response'].get('usage',{}) for r in plan]+[r.get('usage',{}) for r in rows(out/'native/main-calls.jsonl')]
    ablation=None
    if ablation_path.exists():
        extra=rows(ablation_path)
        all_usage += [r['response'].get('usage',{}) for r in extra]
        ablation=json.loads((out/'ablation/summary.json').read_text(encoding='utf-8'))
        files.extend(['ablation/planning.jsonl','ablation/manifest.json'])
    def cost(usage):
        prompt=usage.get('prompt_tokens',0);hit=usage.get('prompt_cache_hit_tokens',0)
        return (hit*.003+(prompt-hit)*.15+usage.get('completion_tokens',0)*.60)/1e6
    expense=sum(cost(u) for u in all_usage)
    audit=dict(source_sha256={name:hashlib.sha256((out/name).read_bytes()).hexdigest() for name in files},
        planning_raw_flags=flags,planning_observations=observed,
        accepted_clarification_correct=accepted_clarification_correct,shadow_mistakes=mistakes,native=native,ablation=ablation,
        expense=dict(main_requests=len(all_usage),offpeak_estimated_usd=round(expense,8),peak_estimated_usd=round(expense*2,8),
            usage_complete=all(bool(u) for u in all_usage),
            source='https://api-docs.deepseek.com/quick_start/pricing/',checked_date='2026-10-11',
            note='Flash official USD per million: offpeak hit .003, miss .15, output .60; peak twice. Estimates from returned usage, not invoices. Local GPU electricity excluded.'),
        limitations=['Raw observation is a separate audit added after observing strict format failures; original scores and labels preserved.',
                     'quote family analyze_plan versus answer_general is an overly strict semantic label distinction; neither entails execution.',
                     'Compound marker check establishes both labelled sections exist, not content quality.',
                     'No new training, recalibration, production switching, or paid media generation. Native auxiliary scoring only on initial request.'])
    (out/'audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(planning_raw_flags=flags,accepted_clarification_correct=accepted_clarification_correct,native=native),ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);main(p.parse_args().out)
