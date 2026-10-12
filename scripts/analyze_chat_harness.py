"""Offline controlled replay of saved answers; no inference or business tools."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.evaluate_chat_harness import (ARMS, DATASET, QUESTIONS, common_gate,
    score, state_for, task_for, validate_plan)
from miniclaw_web.clarification_policy import ClarificationPolicy

OUT=ROOT/'.codex/verification/chat-harness-comparison-2026-10-11'
# Concrete evaluation tool args, applied identically to all arms. The initial
# run erroneously mapped this deterministic rotate request to paid ai_edit.
LOCAL_IMAGE_OPERATIONS={'14':{'operation':'rotate','params':{'angle':90}}}

def operational_plan(row,case):
    if row.get('preclassifier_questions'):
        return deepcopy(row['pre_gate_plan']),'early_clarification'
    record=row.get('planner',{})
    if record.get('http_status')!=200 or record.get('finish_reason')!='stop':
        return None,'inference_unavailable'
    try:
        raw=json.loads(record['raw_content'])
        # Matches the actual adapter invariant: clarification anywhere in a
        # batch suspends all mutations. Do not discard the strict failure record.
        if (isinstance(raw,dict) and isinstance(raw.get('questions'),list)
                and raw['questions'] and len(raw['questions'])<=3
                and all(isinstance(q,str) and q in QUESTIONS for q in raw['questions'])):
            raw['steps']=[]
            return validate_plan(raw,state_for(case)),'clarification_priority'
        return validate_plan(raw,state_for(case)),'valid_plan'
    except (ValueError,KeyError,TypeError):
        return None,'invalid_contract'

def uniform_gate(plan,row,case):
    if plan is None:return None,None
    plan=common_gate(plan,state_for(case))
    task=task_for(case)
    task['context']['intent']=row.get('legacy_intent',plan['intent']) if row['arm']==ARMS[0] else plan['intent']
    policy=ClarificationPolicy(None)
    for step in plan['steps']:
        mapping={'edit_image':('miniclaw_edit_image',LOCAL_IMAGE_OPERATIONS.get(case['id'],{'operation':'ai_edit'})),
                 'generate_image':('miniclaw_canvas_ai',{}),
                 # The plan-only fixture has no real video tool call arguments.
                 'generate_video':('evaluation_generate_video',{}),
                 'adopt_candidate':('miniclaw_canvas_apply',{})}
        if step['kind'] not in mapping:continue
        name,args=mapping[step['kind']]
        guard=policy.guard(task,name,args)
        if guard:
            return {'intent':plan['intent'],'steps':[],'questions':['execution']},guard
    return plan,None

def analyze(out=OUT):
    cases={c['id']:c for c in json.loads(DATASET.read_text(encoding='utf-8'))['cases']}
    source=out/'cases.jsonl';rows=[json.loads(l) for l in source.read_text(encoding='utf-8').splitlines()]
    if len(rows)!=108 or len({(r['arm'],r['id']) for r in rows})!=108:
        raise ValueError('incomplete_or_duplicated_run')
    derived=[]
    for row in rows:
        case=cases[row['id']];plan,normalization=operational_plan(row,case)
        gated,guard=uniform_gate(plan,row,case)
        derived.append({'id':row['id'],'arm':row['arm'],'normalization':normalization,
            'operational_plan':plan,'controlled_plan':gated,'controlled_guard':guard,
            'operational_score':score(plan,case['gold']),'controlled_score':score(gated,case['gold'])})
    summary={}
    for arm in ARMS:
        subset=[r for r in derived if r['arm']==arm]
        summary[arm]={kind:{k:sum(r[kind][k] for r in subset) for k in subset[0][kind]}
                      for kind in ('operational_score','controlled_score')}
        summary[arm]['operational_failed_ids']=[r['id'] for r in subset if not r['operational_score']['joint_match']]
        summary[arm]['controlled_failed_ids']=[r['id'] for r in subset if not r['controlled_score']['joint_match']]
    original=json.loads((out/'report.json').read_text(encoding='utf-8'))
    b={r['id']:r for r in derived if r['arm']==ARMS[1]}
    c={r['id']:r for r in derived if r['arm']==ARMS[2]}
    paired={'C_only_correct':[i for i in b if c[i]['operational_score']['joint_match'] and not b[i]['operational_score']['joint_match']],
            'B_only_correct':[i for i in b if b[i]['operational_score']['joint_match'] and not c[i]['operational_score']['joint_match']]}
    main_low=sum(s['main_estimated_usd_range'][0] for s in original['summary'].values())
    main_high=sum(s['main_estimated_usd_range'][1] for s in original['summary'].values())
    report={'status':'complete_controlled_replay','external_calls':0,'business_tools_executed':0,
        'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'dataset_sha256':hashlib.sha256(DATASET.read_bytes()).hexdigest(),
        'execution_script_sha256':hashlib.sha256((out/'executed-evaluator.py').read_bytes()).hexdigest(),
        'summary':summary,'paired_B_C':paired,
        'costs':{'main_calls':sum(s['planner_calls'] for s in original['summary'].values()),
            'main_estimated_usd_range':[round(main_low,8),round(main_high,8)],
            'jev_actual_requests':original['jev_ledger']['calls'],
            'jev_estimated_usd':original['jev_ledger']['estimated_usd'],
            'price_source':'https://api-docs.deepseek.com/quick_start/pricing/',
            'price_checked_on':'2026-10-11','local_GPU_energy_not_priced':True},
        'method_corrections':['Retain original strict results; derive separate clarification-priority replay matching the existing adapter invariant.',
            'Apply identical existing ClarificationPolicy.guard to all arms; A uses preclassifier intent, B/C use planner intent.',
            'Rotate request 14 uses local rotate args in all arms; initial all-ai_edit mapping was inaccurate.'],
        'limitations':['Gold is author-labelled synthetic development data, not reviewed or blind.',
            'Exact contracts penalize wording/taxonomy choices: 03 answer_general vs analyze_plan; 06 additional revise_requirements before write_plan. Do not equate all contract misses with harmful actions.',
            'Controlled gate counts compare desired UX to legacy paid-confirmation policy; not pure model accuracy.',
            'Replays only ClarificationPolicy.guard and fixture state gate, not the full Hermes adapter, operation ledger, tool schemas or video backend.',
            'No actual media generation, cancellation, write, or strong/weak language-model routing; those require subsequent isolated integration testing.',
            'One call per case/arm; +1 case for C over B does not establish a reproducible or significant gain.']}
    (out/'controlled-cases.json').write_text(json.dumps(derived,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'controlled-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return report

if __name__=='__main__':analyze()
