"""Joint calibration, opt-in production wiring, and authoritative saved-answer recovery."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock
import httpx
import pytest
ROOT = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(ROOT), str(ROOT/'hermes-agent')]
from miniclaw_web.clarification_policy import chat_request, high, question, ClarificationPolicy
from miniclaw_web.candidate_clarification_policy import CandidateClarificationPolicy
from miniclaw_web.chat_decisions import chat_policy
from miniclaw_web.laya_formal import canonical_request, LayaFormalDecisions
from scripts.formal_seven_joint_gates import fit_joint, apply_joint, inference_request


def sample(family, conflict=False):
    context = dict(selected='img1', candidates=[dict(id='img1', label='A'), dict(id='img2', label='B')])
    req = chat_request('操作请求', context, {})
    gold = dict(intent='unclear' if conflict else 'execute_change', target='img1', scope='whole_object',
        reference_role='primary', conflict='present' if conflict else 'none', answer_relation='unclear', fact_review='clear')
    pred = {'answers': {}}
    for h, q in req[1].items():
        choice = 'execute_change' if h == 'intent' else gold[h]
        pred['answers'][h] = dict(type='choice', choice=choice, confidence=.99,
            probabilities={k: .99 if k == choice else .01/(len(q['criteria'])-1) for k in q['criteria']})
    return dict(family=family, request=req, expected=gold, prediction=pred)


def test_joint_conflict_mask_enables_execution_without_gold_based_runtime_filter():
    samples = [sample(f'conflict-{i}', True) for i in range(4) for _ in range(2)] + [sample(f'action-{i}') for i in range(4) for _ in range(2)]
    gates = fit_joint(samples)
    assert gates['questions']['intent']['labels']['execute_change']['accepted'] == 8
    conflict = apply_joint(samples[0]['prediction'], gates, samples[0]['request'])
    normal = apply_joint(samples[-1]['prediction'], gates, samples[-1]['request'])
    assert high(conflict, 'conflict') == 'present' and high(conflict, 'intent') is None and high(conflict, 'target') is None
    assert high(normal, 'intent') == 'execute_change' and high(normal, 'target') == 'img1'
    # Runtime request has no labels; masking solely depends on accepted predictions.
    assert 'expected' not in json.loads(samples[0]['request'][0])
    decisions = SimpleNamespace(evaluate=lambda *a, **kw: deepcopy(conflict))
    task = dict(id='a', text='请执行修改', confirmed={}, context=dict(semantic=json.loads(samples[0]['request'][0])))
    intent, _, qs = CandidateClarificationPolicy(decisions).classify(task)
    assert intent == 'unclear' and [q['template'] for q in qs] == ['Q_CONFLICT']


def test_opaque_version_projection_preserves_request_and_memo_revision():
    req = chat_request('解释图片', dict(selected=None, candidates=[], versions='a'*64), {})
    original = deepcopy(req); canonical, _ = canonical_request(req)
    gates = dict(version_projection='opaque-sha256-to-null-v1', candidate_counts=[0,1,2,3,4])
    projected = inference_request(canonical, gates)
    assert json.loads(projected[0])['target_versions'] is None and req == original
    assert json.loads(canonical[0])['target_versions'] == 'a'*64
    for bad in ('version instructions', {'ignore': 'versions'}, 'A'*64, 3):
        state = json.loads(canonical[0]); state['target_versions'] = bad
        with pytest.raises(ValueError): inference_request((json.dumps(state), canonical[1]), gates)
    with pytest.raises(ValueError): inference_request(canonical, dict(candidate_counts=[0]))
    calls=[]
    dec=LayaFormalDecisions(checkpoint_sha256='c'*64, transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(503)))
    dec.evaluate('s', 'same', '', {'revision': 1}, request=req)
    changed=chat_request('解释图片', dict(selected=None,candidates=[],versions='b'*64), {})
    with pytest.raises(ValueError, match='same_id_changed_input'): dec.evaluate('s','same','',{'revision':1},request=changed)
    assert len(calls)==1 and json.loads(calls[0].content)['request'][0] == req[0]


def test_opt_in_factory_and_real_coordinator_default_are_independent_of_studio(tmp_path, monkeypatch):
    from miniclaw_web.clarification_routes import ClarificationCoordinator
    from miniclaw_web.store import Store
    default = MagicMock()
    assert type(chat_policy(default, {})) is ClarificationPolicy
    for env in ({'MINICLAW_CHAT_DECISION_PROVIDER': 'other'},):
        with pytest.raises(ValueError): chat_policy(default, env)
    assert isinstance(chat_policy(default, {'MINICLAW_CHAT_DECISION_PROVIDER':'laya'}), CandidateClarificationPolicy)
    monkeypatch.setenv('MINICLAW_CHAT_DECISION_PROVIDER', 'laya')
    monkeypatch.setenv('MINICLAW_LAYA_CHECKPOINT_SHA256', 'a'*64)
    monkeypatch.setenv('MINICLAW_LAYA_GATE_SHA256', 'b'*64)
    studio = SimpleNamespace(decisions=default)
    coordinator=ClarificationCoordinator(Store(tmp_path/'home'), None, studio, None)
    assert isinstance(coordinator.policy, CandidateClarificationPolicy)
    assert isinstance(coordinator.policy.decisions, LayaFormalDecisions)
    assert studio.decisions is default and default.mock_calls == []


def test_unsupported_host_input_abstains_and_does_not_keyword_promote_or_use_jev():
    dec = LayaFormalDecisions(checkpoint_sha256='a'*64, transport=httpx.MockTransport(lambda r: pytest.fail('must not POST malformed request')))
    task = dict(id='a', text='请旋转图片90度', confirmed={}, context=dict(semantic=dict(selected=None,candidates=[dict(id='none',label='A')])))
    intent, row, qs = CandidateClarificationPolicy(dec).classify(task)
    assert intent == 'unclear' and row['reason']=='unsupported_host_request' and not row['jev_fallback'] and not qs
    task['context']['intent']=intent
    assert CandidateClarificationPolicy(dec).guard(task,'miniclaw_edit_image',{})['template']=='Q_EXECUTION'


def test_saved_target_reply_survives_restart_and_resume_never_reclassifies(tmp_path):
    from miniclaw_web.store import Store
    from miniclaw_web.clarifications import Clarifications
    from miniclaw_web.hermes_clarification_adapter import HermesClarificationAdapter
    service=Clarifications(Store(tmp_path/'home'))
    task=service.start('chat','请把这张图旋转90度。',dict(attachments=['a','b'], semantic=dict(selected=None,candidates=[dict(id='a',label='玻璃杯'),dict(id='b',label='铜铃')]),versions={}))
    service.configure(task['id'],intent='execute_change')
    item=service.prepare(task['id'],[question('Q_TARGET','选哪张？',['玻璃杯','铜铃'])],'preclassifier')
    service.seal(task['id'],'chat',0); item=service.request(item)
    service.answer(['chat'],item['id'],item['version'],{'Q_TARGET':'铜铃'},'answer')
    reopened=Clarifications(Store(service.store.home)); assert reopened.claim('answer')
    assert reopened.task(task['id'])['context']['semantic']['selected']=='b'
    dec=MagicMock(); policy=CandidateClarificationPolicy(dec)
    adapter=HermesClarificationAdapter(reopened,policy,{'agent':SimpleNamespace(max_iterations=10)},task['id'],resume_job='answer')
    assert adapter.before_model([]) is None and dec.mock_calls == []
    writes=[]
    result=json.loads(adapter.dispatch('miniclaw_edit_image',{'source_id':'a','operation':'rotate','params':{'angle':90}},'wrong',lambda: writes.append('wrong')))
    assert result['executed'] is False and not writes
    args={'source_id':'b','operation':'rotate','params':{'angle':90}}
    execute=lambda: writes.append('right') or '{"success":true}'
    first=adapter.dispatch('miniclaw_edit_image',args,'ok',execute)
    assert adapter.dispatch('miniclaw_edit_image',args,'again',execute)==first and writes==['right']


def test_model_target_choice_never_binds_actual_object(tmp_path):
    row=sample('action'); row['prediction']['answers']['target']['choice']='img2'
    dec=SimpleNamespace(evaluate=lambda *a,**kw: row['prediction'])
    task=dict(id='a',text='请旋转图片90度',confirmed={},context=dict(semantic=dict(selected='img1',candidates=[dict(id='img1',label='A'),dict(id='img2',label='B')])))
    CandidateClarificationPolicy(dec).classify(task)
    assert task['context']['semantic']['selected']=='img1' and task['confirmed']=={}


@pytest.mark.parametrize('answer,labels', [('尚未选好',['杯子','铜铃']),('同名图片',['同名图片','同名图片'])])
def test_unresolved_or_duplicate_name_answer_does_not_bind(tmp_path,answer,labels):
    from miniclaw_web.store import Store
    from miniclaw_web.clarifications import Clarifications
    service=Clarifications(Store(tmp_path/'home'))
    task=service.start('chat','修改图片',dict(semantic=dict(selected=None,candidates=[dict(id='a',label=labels[0]),dict(id='b',label=labels[1])])))
    from miniclaw_web.clarification_policy import target_choices
    choices=target_choices(task['context']['semantic']['candidates'])
    item=service.prepare(task['id'],[question('Q_TARGET','选哪张？',choices)],'preclassifier')
    service.seal(task['id'],'chat',0); item=service.request(item)
    service.answer(['chat'],item['id'],item['version'],{'Q_TARGET':answer},'answer')
    assert service.task(task['id'])['context']['semantic']['selected'] is None
    assert 'target_id' not in service.task(task['id'])['confirmed']
    if len(set(labels)) != len(labels): assert choices==['a','b']


def test_laya_coordinator_still_rejects_stale_canvas_before_write(tmp_path,monkeypatch):
    from miniclaw_web.store import Store
    from miniclaw_web.clarification_routes import ClarificationCoordinator
    from miniclaw_web.clarifications import ClarificationConflict
    from miniclaw_web.hermes_clarification_adapter import HermesClarificationAdapter
    from hermes_state import SessionDB
    monkeypatch.setenv('MINICLAW_CHAT_DECISION_PROVIDER','laya')
    monkeypatch.setenv('MINICLAW_LAYA_CHECKPOINT_SHA256','a'*64)
    monkeypatch.setenv('MINICLAW_LAYA_GATE_SHA256','b'*64)
    layer={'id':'layer','value':'before'}
    canvas=SimpleNamespace(get=lambda _:dict(document=dict(layers=[deepcopy(layer)])),selection=lambda _:None)
    coordinator=ClarificationCoordinator(Store(tmp_path/'home'),None,SimpleNamespace(decisions=MagicMock()),canvas)
    with SessionDB(db_path=coordinator.store.home/'state.db') as db: db.create_session('chat','cli')
    context=dict(canvas_turn=dict(project_id='project',layer_id='layer'),intent='execute_change',required_tools=[])
    context['versions']=coordinator.versions(context)
    task=coordinator.service.start('chat','执行修改',context)
    session=dict(session_key='chat',agent=SimpleNamespace(max_iterations=10,tools=[]))
    coordinator.validate(task,session)
    layer['value']='after'
    adapter=HermesClarificationAdapter(coordinator.service,coordinator.policy,session,task['id'],validate=coordinator.validate,resume_job='saved-answer')
    writes=[]
    with pytest.raises(ClarificationConflict,match='已改变'):
        adapter.dispatch('miniclaw_save_artifact',{'name':'draft.md'},'write',lambda: writes.append(1))
    assert not writes
