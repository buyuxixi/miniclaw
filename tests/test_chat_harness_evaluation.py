"""Protect the experiment from label leakage, invented metrics and real execution."""
import json
from pathlib import Path
import pytest
from scripts.evaluate_chat_harness import Budget, common_gate, messages_for, score, state_for, validate_plan

def test_gold_and_metadata_never_reach_planner():
    c={'text':'讨论方案','category':'SECRET_CATEGORY','gold':{'steps':['SECRET_GOLD']}}
    encoded=json.dumps(messages_for(c),ensure_ascii=False)
    assert 'SECRET_GOLD' not in encoded and 'SECRET_CATEGORY' not in encoded and 'gold' not in encoded

def test_short_reply_preserves_pending_context():
    c={'text':'可以','context':{'pending_question':{'text':'是否修图'},'pending_steps':[{'kind':'edit_image','targets':['img2']}]}}
    assert '是否修图' in json.dumps(messages_for(c),ensure_ascii=False)

def test_invalid_targets_and_combined_blocking_plan_rejected():
    state=state_for({'text':'改图'})
    with pytest.raises(ValueError):validate_plan({'intent':'execute_change','steps':[{'kind':'edit_image','targets':['unknown']}],'questions':[]},state)
    with pytest.raises(ValueError):validate_plan({'intent':'execute_change','steps':[{'kind':'edit_image','targets':['img1']}],'questions':['target']},state)

@pytest.mark.parametrize('context,question', [({'paid_budget_available':False},'budget'),({'prior_paid_unknown':True},'paid_retry'),({'draft_only':True},'execution')])
def test_common_gate_blocks_concrete_mutating_plan(context,question):
    state=state_for({'text':'生成视频','context':context})
    plan={'intent':'generate_media','steps':[{'kind':'generate_video','targets':[]}],'questions':[]}
    assert common_gate(plan,state)['steps']==[]
    assert common_gate(plan,state)['questions']==[question]
    assert plan['steps']  # gate does not erase the original evidence

def test_missing_output_cannot_be_scored_as_correct_read_only():
    assert not score(None,{'steps':['analyze_plan'],'questions':[],'targets':[]})['joint_match']

def test_order_and_target_errors_fail_even_when_execution_label_matches():
    gold={'steps':['optimize_video_prompt','generate_video'],'questions':[],'targets':[]}
    plan={'intent':'generate_media','steps':[{'kind':'generate_video','targets':[]},{'kind':'optimize_video_prompt','targets':[]}],'questions':[]}
    assert not score(plan,gold)['joint_match']
    plan={'intent':'execute_change','steps':[{'kind':'edit_image','targets':['img2']}],'questions':[]}
    assert not score(plan,{'steps':['edit_image'],'questions':[],'targets':['img1']})['joint_match']

def test_budget_is_persistent_and_rejects_before_network(tmp_path):
    b=Budget(tmp_path/'ledger.json',usd=.1,max_calls=1);b.reserve(messages_for({'text':'hello'}),100)
    b=Budget(tmp_path/'ledger.json',usd=.1,max_calls=1)
    with pytest.raises(ValueError,match='main_budget_exhausted'):b.reserve([],100)

def test_all_frozen_cases_have_unambiguous_well_formed_contracts():
    from scripts.evaluate_chat_harness import DATASET
    cases=json.loads(DATASET.read_text(encoding='utf-8'))['cases']
    assert len(cases)==36 and len({c['id'] for c in cases})==36
    for c in cases:
        g=c['gold'];plan={'intent':'unclear','steps':[{'kind':k,'targets':g['targets'] if k in {'edit_image','adopt_candidate'} else []} for k in g['steps']],'questions':g['questions']}
        validate_plan(plan,state_for(c))

def test_controlled_replay_prioritizes_questions_without_rewriting_raw():
    from scripts.analyze_chat_harness import operational_plan
    raw={'intent':'execute_change','steps':[{'kind':'edit_image','targets':[]}],'questions':['target']}
    row={'planner':{'http_status':200,'finish_reason':'stop','raw_content':json.dumps(raw)}}
    plan,method=operational_plan(row,{'text':'改背景'})
    assert plan['steps']==[] and plan['questions']==['target']
    assert method=='clarification_priority' and json.loads(row['planner']['raw_content'])['steps']

def test_same_paid_confirmation_gate_applies_to_every_arm():
    from scripts.analyze_chat_harness import uniform_gate
    from scripts.evaluate_chat_harness import ARMS
    case={'id':'07','text':'把第二张背景改白'}
    plan={'intent':'execute_change','steps':[{'kind':'edit_image','targets':['img2']}],'questions':[]}
    for arm in ARMS:
        result,guard=uniform_gate(plan,{'arm':arm,'legacy_intent':'execute_change'},case)
        assert result['questions']==['execution'] and guard['template']=='Q_EXECUTION'

def test_local_rotate_is_not_mislabelled_as_paid_ai_edit():
    from scripts.analyze_chat_harness import uniform_gate
    case={'id':'14','text':'能帮我把第一张图旋转90度吗？'}
    plan={'intent':'execute_change','steps':[{'kind':'edit_image','targets':['img1']}],'questions':[]}
    result,guard=uniform_gate(plan,{'arm':'B_main_only'},case)
    assert result==plan and guard is None
