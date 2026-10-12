"""Human naming, confirmation priority, strict profile boundary and actual adapter persistence."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'hermes-agent')]
from miniclaw_web.literal_image_target import bind_named_attachment,named_operation
from miniclaw_web.clarification_policy import chat_request,question
from miniclaw_web.candidate_clarification_policy import CandidateClarificationPolicy
from scripts.formal_seven_joint_gates import inference_request


def task(text='请把「铜杯」旋转90度。'):
    return dict(id='task',text=text,confirmed={},context=dict(attachments=['a','b'],semantic=dict(selected='b',candidates=[dict(id='a',label='铜杯'),dict(id='b',label='编织篮')]),versions={}))


def test_full_affirmative_name_overrides_old_selection_only_for_owned_unique_image():
    t=task();original=deepcopy(t)
    context=bind_named_attachment(t)
    assert context['semantic']['selected']=='a' and t==original
    t['context']['attachments']=['b']
    assert bind_named_attachment(t)['semantic']['selected'] is None
    t=task();t['context']['semantic']['candidates'][1]['label']='铜杯'
    assert bind_named_attachment(t)['literal_target']['status']=='unresolved'
    assert bind_named_attachment(task('请把「不存在」旋转90度。'))['semantic']['selected'] is None


@pytest.mark.parametrize('text',['解释“请把「铜杯」旋转90度”的意思。','只写请把「铜杯」旋转90度的方案。','不要把「铜杯」旋转90度。','有人说：把「铜杯」旋转90度。','请把「铜杯」旋转90度，同时保持全部像素不变。','将「铜杯」当参考，旋转另一张图。'])
def test_quotes_negations_reference_and_compound_do_not_bind(text):
    assert bind_named_attachment(task(text)) is None


def test_saved_answer_wins_over_old_named_request_and_draft_blocks_binding():
    t=task();t['confirmed']={'Q_TARGET':'b','target_id':'b'}
    assert bind_named_attachment(t) is None
    t['confirmed']={'Q_EXECUTION':'只整理方案'}
    assert bind_named_attachment(t) is None
    dec=MagicMock();dec.evaluate.return_value=dict(status='unavailable',answers={})
    intent,_,qs=CandidateClarificationPolicy(dec).classify(t)
    assert intent=='draft' and not qs


def test_unresolved_identity_retains_only_accepted_execution_intent():
    from scripts.analyze_laya_round5 import Fixed
    t=task('请把「不存在」旋转90度。');t['context']=bind_named_attachment(t)
    def prediction(confidence):
        return dict(status='suggested',answers=dict(intent=dict(choice='execute_change',confidence=confidence,probabilities=dict(execute_change=.99,unclear=.01))))
    for confidence,expected in ((1.,'execute_change'),(0.,'unclear')):
        intent,_,qs=CandidateClarificationPolicy(Fixed(prediction(confidence))).classify(t)
        assert intent==expected and [q['template'] for q in qs]==['Q_TARGET']
        assert t['context']['semantic']['selected'] is None


def test_confirmed_profile_projection_preserves_real_answer_and_declines_legacy_gate():
    t=task();state=t['context']['semantic']
    req=chat_request(t['text'],dict(state,versions='c'*64),{'Q_TARGET':'编织篮','target_id':'b'})
    gates=dict(version='formal-seven-joint-v2',version_projection='opaque-sha256-to-null-v1',candidate_counts=[0,1,2,3,4],confirmation_profiles=['none','execute','draft','target'])
    projected=inference_request(req,gates)
    assert json.loads(projected[0])['confirmed']=={'Q_TARGET':'编织篮','target_id':'b'}
    assert json.loads(projected[0])['target_versions'] is None and json.loads(req[0])['target_versions']=='c'*64
    with pytest.raises(ValueError):inference_request(req,dict(gates,version='formal-seven-joint-v1'))
    for bad in ({'Q_EXECUTION':True},{'Q_EXECUTION':'随便做'},{'Q_SCOPE':'我说的这里'},{'Q_TARGET':'铜杯','target_id':'b'},{'Q_TARGET':'编织篮','target_id':'b','hidden':'execute'}):
        with pytest.raises(ValueError):inference_request(chat_request(t['text'],state,bad),gates)


def test_real_adapter_persists_binding_before_model_classification_and_blocks_wrong_source(tmp_path):
    from miniclaw_web.store import Store
    from miniclaw_web.clarifications import Clarifications
    from miniclaw_web.hermes_clarification_adapter import HermesClarificationAdapter
    service=Clarifications(Store(tmp_path/'home'));t=task();saved=service.start('chat',t['text'],t['context'])
    seen=[]
    class Policy:
        def classify(self,value):seen.append(value);return 'execute_change',dict(answers={}),[]
        def guard(self,*args):return None
    adapter=HermesClarificationAdapter(service,Policy(),dict(agent=SimpleNamespace(max_iterations=10)),saved['id'])
    assert adapter.before_model([]) is None and seen[0]['context']['semantic']['selected']=='a'
    assert service.task(saved['id'])['context']['semantic']['selected']=='a'
    calls=[]
    result=json.loads(adapter.dispatch('miniclaw_edit_image',dict(source_id='b',operation='rotate',params=dict(angle=90)),'wrong',lambda:calls.append(1)))
    assert result['executed'] is False and not calls
    # Existing genuine reply remains authoritative on the resume path.
    service.configure(saved['id'],semantic=t['context']['semantic'])
    resumed=HermesClarificationAdapter(service,Policy(),dict(agent=SimpleNamespace(max_iterations=10)),saved['id'],resume_job='actual-answer')
    resumed.before_model([])
    assert len(seen)==1 and service.task(saved['id'])['context']['semantic']['selected']=='b'


def test_real_execution_confirmation_resumes_original_params_without_reclassification(tmp_path):
    from miniclaw_web.store import Store
    from miniclaw_web.clarifications import Clarifications
    from miniclaw_web.hermes_clarification_adapter import HermesClarificationAdapter
    from scripts.run_laya_round7_comparison import Round7NativePolicy
    service=Clarifications(Store(tmp_path/'home'))
    t=task('请把这张图旋转180度。');saved=service.start('chat',t['text'],t['context']);service.configure(saved['id'],intent='unclear')
    item=service.prepare(saved['id'],[question('Q_EXECUTION','确认执行？',['确认执行','只整理方案'])],'hook')
    service.seal(saved['id'],'chat',0);item=service.request(item)
    service.answer(['chat'],item['id'],item['version'],{'Q_EXECUTION':'确认执行'},'execution-answer');assert service.claim('execution-answer')
    service.configure(saved['id'],latest_user_reply='确认执行')
    dec=MagicMock();policy=Round7NativePolicy('laya',{},None,dec,'trial')
    adapter=HermesClarificationAdapter(service,policy,dict(agent=SimpleNamespace(max_iterations=10)),saved['id'],resume_job='execution-answer')
    assert adapter.before_model([]) is None and dec.mock_calls==[]
    writes=[];args=dict(source_id='b',operation='rotate',params=dict(angle=180))
    result=adapter.dispatch('miniclaw_edit_image',args,'operation',lambda:writes.append('right') or '{"success":true}')
    assert json.loads(result)['success'] and writes==['right']
    assert adapter.dispatch('miniclaw_edit_image',args,'again',lambda:writes.append('duplicate'))==result and writes==['right']
    wrong=Round7NativePolicy('laya',{},None,dec,'trial').guard(service.task(saved['id']),'miniclaw_edit_image',dict(source_id='b',operation='rotate',params=dict(angle=90)))
    assert wrong is not None


def test_real_coordinator_begin_binds_named_owned_attachment_and_keeps_default_provider(tmp_path,monkeypatch):
    from miniclaw_web.store import Store
    from miniclaw_web.clarification_routes import ClarificationCoordinator
    from hermes_state import SessionDB
    monkeypatch.setenv('HERMES_HOME',str(tmp_path/'home'));monkeypatch.setenv('MINICLAW_CHAT_DECISION_PROVIDER','jev')
    default=MagicMock();coordinator=ClarificationCoordinator(Store(tmp_path/'home'),None,SimpleNamespace(decisions=default),None)
    with SessionDB(db_path=coordinator.store.home/'state.db') as db:db.create_session('chat','cli')
    session=dict(session_key='chat',agent=SimpleNamespace(max_iterations=10,tools=[]))
    saved=coordinator.begin(session,'请把「竹编篮」旋转90度。',{},None,[dict(id='a',name='白瓷杯',kind='image'),dict(id='b',name='竹编篮',kind='image')])
    assert saved['context']['semantic']['selected']=='b' and len(saved['context']['semantic']['versions'])==64
    assert coordinator.policy.decisions is default and default.mock_calls==[]


def test_missing_name_cannot_fall_back_to_only_uploaded_image_then_real_reply_can_bind(tmp_path):
    from miniclaw_web.store import Store
    from miniclaw_web.clarifications import Clarifications
    from miniclaw_web.hermes_clarification_adapter import HermesClarificationAdapter
    service=Clarifications(Store(tmp_path/'home'))
    context=dict(attachments=['a'],semantic=dict(selected='a',candidates=[dict(id='a',label='铜杯')]),versions={})
    saved=service.start('chat','请把「不存在」旋转90度。',context)
    class Policy:
        def classify(self,value):return 'execute_change',dict(answers={}),[]
        def guard(self,*args):return None
    adapter=HermesClarificationAdapter(service,Policy(),dict(agent=SimpleNamespace(max_iterations=10)),saved['id'])
    adapter.before_model([]);writes=[];args=dict(source_id='a',operation='rotate',params=dict(angle=90))
    response=json.loads(adapter.dispatch('miniclaw_edit_image',args,'try',lambda:writes.append(1)))
    assert response['status']=='awaiting_input' and not writes
    service.seal(saved['id'],'chat',0);item=service.request(adapter.pending)
    service.answer(['chat'],item['id'],item['version'],{'Q_TARGET':'铜杯'},'real-answer');assert service.claim('real-answer')
    resumed=HermesClarificationAdapter(service,Policy(),dict(agent=SimpleNamespace(max_iterations=10)),saved['id'],resume_job='real-answer')
    resumed.before_model([])
    result=resumed.dispatch('miniclaw_edit_image',args,'ok',lambda:writes.append(1) or '{"success":true}')
    assert json.loads(result)['success'] and writes==[1]
