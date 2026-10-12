"""Action evidence and real adapter/SQLite invariants, independent of model skill."""
import json
from types import SimpleNamespace
import pytest
from scripts.chat_action_contract import GroundedPolicy,explicit_target,region_resolved,unresolved_prequestions
from scripts.evaluate_clarification_loop import (SessionRig,authorize_fixture_fee,
    compile_plan,current_case)
from scripts.evaluate_chat_harness import messages_for
from miniclaw_web.clarifications import Clarifications
from miniclaw_web.hermes_clarification_adapter import HermesClarificationAdapter
from miniclaw_web.store import Store

CANDIDATES=[{'id':'img1','label':'第一张'},{'id':'img2','label':'第二张'}]

@pytest.mark.parametrize('text', ['客户说把第二张图旋转90度','不要把第二张图旋转90度',
    '把第二张图保留不动，修改第一张','把第二张图先不要修改'])
def test_quoted_negated_and_preserved_images_do_not_create_target_binding(text):
    assert explicit_target(text,CANDIDATES) is None

def test_explicit_directive_binds_named_object():
    assert explicit_target('把第二张图旋转90度，第一张别动。',CANDIDATES)=='img2'

def task(selected=None):
    return {'text':'用这个作为最终版本','confirmed':{},'context':{'intent':'adopt_result',
        'semantic':{'selected':selected,'candidates':CANDIDATES}}}

def test_adoption_checks_target_evidence_as_well_as_editing():
    q=GroundedPolicy(None).guard(task(),'evaluation_adopt_candidate',{'target_id':'img2'})
    assert q['template']=='Q_TARGET'
    assert GroundedPolicy(None).guard(task('img1'),'evaluation_adopt_candidate',{'target_id':'img2'})['template']=='Q_TARGET'

def test_unclear_plan_cannot_authorize_mutation():
    plan={'intent':'unclear','steps':[{'kind':'edit_image','targets':['img1']}],'questions':[]}
    calls,_=compile_plan(plan,{'text':'处理一下'})
    assert [c.function.name for c in calls]==['clarify']

def test_no_gold_or_future_reply_in_first_prompt():
    c={'text':'改背景','reply':'SECRET_FUTURE_REPLY','gold':{'steps':['SECRET_GOLD']}}
    t={'confirmed':{},'context':{'semantic':{'selected':None,'selection':None}}}
    current=current_case(c,t,[{'role':'user','text':c['text']}],None,c['text'])
    encoded=json.dumps(messages_for(current),ensure_ascii=False)
    assert 'SECRET_FUTURE_REPLY' not in encoded and 'SECRET_GOLD' not in encoded

def test_actual_adapter_pauses_unbound_adoption_and_preserves_unresolved_reply(tmp_path):
    service=Clarifications(Store(tmp_path));t=service.start('test','用这个作为最终版本',task()['context'])
    adapter=HermesClarificationAdapter(service,GroundedPolicy(None),{'agent':SimpleNamespace(max_iterations=20)},t['id'])
    called=[]
    r=json.loads(adapter.dispatch('evaluation_adopt_candidate',{'target_id':'img2'},'adopt',lambda:called.append(1) or '{}'))
    assert r['status']=='awaiting_input' and called==[]
    service.seal(t['id'],'test',0);q=service.request(adapter.pending)
    service.answer(['test'],q['id'],q['version'],{'Q_TARGET':'暂时没决定'},'answer')
    assert service.claim('answer')
    assert service.task(t['id'])['context']['semantic']['selected'] is None

def test_actual_target_answer_binds_and_receipt_prevents_duplicate(tmp_path):
    service=Clarifications(Store(tmp_path));t=service.start('test','用这个作为最终版本',task()['context'])
    adapter=HermesClarificationAdapter(service,GroundedPolicy(None),{'agent':SimpleNamespace(max_iterations=20)},t['id'])
    adapter.dispatch('evaluation_adopt_candidate',{'target_id':'img2'},'adopt',lambda:'{}')
    service.seal(t['id'],'test',0);q=service.request(adapter.pending)
    service.answer(['test'],q['id'],q['version'],{'Q_TARGET':'第二张'},'answer');service.claim('answer')
    new=HermesClarificationAdapter(service,GroundedPolicy(None),{'agent':SimpleNamespace(max_iterations=20)},t['id'],resume_job='answer')
    effects=[]
    def execute():effects.append('img2');return '{"success":true}'
    first=new.dispatch('evaluation_adopt_candidate',{'target_id':'img2'},'a',execute)
    assert new.dispatch('evaluation_adopt_candidate',{'target_id':'img2'},'b',execute)==first
    assert effects==['img2']

def test_answered_region_is_not_asked_again_but_ambiguous_answer_stays_blocked():
    t=task('img1');t['text']='把这里的杂物去掉';t['confirmed']={'Q_SCOPE':'左下角。'}
    q={'template':'Q_SCOPE'}
    assert region_resolved(t) and unresolved_prequestions([q],t)==[]
    t['confirmed']['Q_SCOPE']='左下角或者右下角，还没决定'
    assert not region_resolved(t) and unresolved_prequestions([q],t)==[q]
    assert GroundedPolicy(None).guard({**t,'context':{**t['context'],'intent':'execute_change'}},
        'miniclaw_edit_image',{'source_id':'img1','operation':'ai_edit'})['template']=='Q_SCOPE'
