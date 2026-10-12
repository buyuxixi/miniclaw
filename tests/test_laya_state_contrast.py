from copy import deepcopy
from scripts.build_laya_state_contrast import dataset,advice_context
from scripts.evaluate_chat_harness import score
from scripts.evaluate_laya_state_contrast import summarize
from scripts.analyze_laya_state_contrast import observed_plan
from scripts.evaluate_laya_state_ablation import hint


def test_paired_inputs_change_state_without_leaking_labels():
    rows=dataset()['planning']
    assert len(rows)==32 and len({r['id'] for r in rows})==32
    for family in {r['family'] for r in rows}:
        a,b=[r for r in rows if r['family']==family]
        assert a['text']==b['text'] and a['context']!=b['context']
        assert 'gold' not in advice_context(a) and 'categories' not in advice_context(a)


def test_confirmed_region_does_not_invent_a_selection():
    case=next(c for c in dataset()['planning'] if c['id']=='answered-region-1')
    state=advice_context(case)
    assert state['selection'] is None and state['region_bound']
    assert state['confirmed']['Q_SCOPE']=='左下角'


def test_identical_short_replies_preserve_distinct_pending_purposes():
    rows=[c for c in dataset()['planning'] if c['family']=='pending-purpose']
    a,b=map(advice_context,rows)
    assert a['pending_task']['steps']==['optimize_narration']
    assert b['pending_task']['steps']==['generate_video']


def test_pair_audit_counts_improvement_and_harm_without_call_savings():
    cases=dataset()['planning'][:2]
    rows=[]
    for c in cases:
        expected={'intent':'execute_change','steps':[{'kind':k,'targets':c['gold']['targets']} for k in c['gold']['steps']],
                  'questions':c['gold']['questions']}
        wrong=deepcopy(expected)
        wrong.update(steps=[],questions=['intent'])
        for arm in ('main','laya_advisory'):
            plan=expected if (c['id'].endswith('-0'))==(arm=='laya_advisory') else wrong
            rows.append(dict(id=c['id'],repeat=0,arm=arm,metrics=score(plan,c['gold']),
                             response={'status':'valid','usage':{'total_tokens':10},'latency_ms':100}))
    result=summarize(rows,cases)
    assert result['corrected']==1 and result['harmed']==1
    assert result['arms']['main']['flows']==result['arms']['laya_advisory']['flows']==2


def test_raw_audit_keeps_unnecessary_question_in_invalid_mixed_output():
    record={'response':{'raw_content':'{"steps":[{"kind":"analyze_plan","targets":[]}],"questions":["target"]}'}}
    result=observed_plan(record,{'steps':['analyze_plan'],'questions':[],'targets':[]})
    assert result['unnecessary_questions'] and result['mixed_question_and_step']


def test_question_with_edit_proposal_is_not_confused_with_actual_execution():
    record={'response':{'raw_content':'{"steps":[{"kind":"edit_image","targets":["img1"]}],"questions":["target"]}'}}
    result=observed_plan(record,{'steps':[],'questions':['target'],'targets':[]})
    assert result['ungrounded_target_proposal'] and not result['missing_questions']


def test_neutral_control_removes_scores_without_altering_cached_full_hint():
    full={'categories':['image'],'clarification':'none','intent':None,'execution_authorized':False}
    assert hint('main',full) is None
    assert hint('neutral',full)['categories']==[] and hint('neutral',full)['clarification'] is None
    assert hint('category_only',full)['categories']==['image'] and hint('category_only',full)['clarification'] is None
    assert hint('clarification_only',full)['categories']==[] and hint('clarification_only',full)['clarification']=='none'
    assert full['categories']==['image'] and full['clarification']=='none'
