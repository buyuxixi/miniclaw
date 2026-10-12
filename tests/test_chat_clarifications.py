"""Real SQLite transitions and Hermes tool rounds; external inference is counted."""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'hermes-agent')]
from miniclaw_web.store import Store
from miniclaw_web.clarifications import Clarifications, ClarificationConflict
from miniclaw_web.clarification_policy import ClarificationPolicy, question
from miniclaw_web.decisions import JevDecisions, JevConfig
from miniclaw_web.hermes_clarification_adapter import HermesClarificationAdapter


@pytest.fixture
def service(tmp_path):
    return Clarifications(Store(tmp_path / '.hermes'))


def pending(service, owner='chat'):
    task = service.start(owner, '保存一份方案')
    identifier = service.prepare(task['id'], [question('Q_CHANGE', '什么颜色？', ['红色','蓝色'])], 'tool', 'call-question')
    service.seal(task['id'], owner, 4)
    return task, service.request(identifier)


def test_answer_is_atomic_deduplicated_and_owned(service):
    task, item = pending(service)
    with pytest.raises(ClarificationConflict):
        service.answer(['other'], item['id'], item['version'], {'Q_CHANGE':'红色'}, 'wrong-owner')
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: service.answer(['chat'], item['id'], item['version'], {'Q_CHANGE':'红色'}, 'submission'), range(4)))
    assert all(r['status'] == 'answered' for r in results)
    assert len(service.jobs()) == 1
    assert service.task(task['id'])['status'] == 'resume_queued'
    with pytest.raises(ClarificationConflict):
        service.answer(['chat'], item['id'], item['version'], {'Q_CHANGE':'蓝色'}, 'other-submission')


def test_timeout_never_selects_default(service):
    task, item = pending(service)
    service.clock = lambda: item['deadline'] + 1
    assert service.list(['chat'])[0]['status'] == 'timed_out'
    assert service.task(task['id'])['status'] == 'aborted'
    assert not service.jobs()
    with pytest.raises(ClarificationConflict):
        service.answer(['chat'], item['id'], item['version'], {'Q_CHANGE':'红色'}, 'late')


def test_answer_timeout_race_has_one_winner(service):
    _, item = pending(service)
    service.clock = lambda: item['deadline']
    with ThreadPoolExecutor(max_workers=2) as pool:
        expire = pool.submit(service.list, ['chat'])
        answer = pool.submit(service.answer, ['chat'], item['id'], item['version'], {'Q_CHANGE':'红色'}, 'race')
        expire.result()
        with pytest.raises(ClarificationConflict):
            answer.result()
    assert not service.jobs()


def test_cancel_stops_queued_resume_and_revision_keeps_task(service):
    task, item = pending(service)
    service.answer(['chat'], item['id'], item['version'], {'Q_CHANGE':'红色'}, 'submission')
    service.cancel(['chat'], item['id'], superseded=True)
    assert not service.jobs()
    revised = service.start('chat', '改为蓝色')
    assert revised['id'] == task['id']
    assert service.request(item['id'])['status'] == 'superseded'


def test_new_topic_is_not_an_answer(service):
    _, item = pending(service)
    with pytest.raises(ClarificationConflict):
        service.start('chat', '另外聊一下天气')
    assert service.request(item['id'])['status'] == 'pending'


def test_restart_retains_pending_and_answered_queue(service):
    task, item = pending(service)
    reopened = Clarifications(Store(service.store.home))
    reopened.recover(lambda owner: [])
    assert reopened.list(['chat'])[0]['id'] == item['id']
    reopened.answer(['chat'], item['id'], item['version'], {'Q_CHANGE':'红色'}, 'submission')
    again = Clarifications(Store(service.store.home))
    again.recover(lambda owner: [])
    assert again.claim('submission') is True
    assert again.claim('submission') is False
    assert again.task(task['id'])['status'] == 'running'


def test_prepared_crash_requires_paired_and_closed_history(service):
    task = service.start('chat', '保存方案')
    identifier = service.prepare(task['id'], [question('Q_CHANGE','颜色？')], 'tool', 'call-question')
    service.recover(lambda owner: [dict(role='tool', tool_call_id='call-question'), dict(role='assistant', display_metadata={'clarification_id':identifier})])
    assert service.request(identifier)['status'] == 'pending'


def test_unsealed_crash_and_ambiguous_resume_do_not_replay(service):
    task = service.start('chat', '保存方案')
    identifier = service.prepare(task['id'], [question('Q_CHANGE','颜色？')], 'tool', 'call-question')
    service.recover(lambda owner: [])
    assert service.task(task['id'])['status'] == 'reconciling'
    assert service.request(identifier)['status'] == 'prepared'
    service.finish(task['id'], 'failed')
    task, item = pending(service)
    service.answer(['chat'], item['id'], item['version'], {'Q_CHANGE':'红色'}, 'submission')
    service.claim('submission')
    service.recover(lambda owner: [dict(role='user', display_metadata={'resume_job_id':'submission'})])
    assert service.task(task['id'])['status'] == 'reconciling'
    assert not service.jobs()


def test_operations_reserve_before_dispatch_and_preserve_unknown(service):
    task = service.start('chat', '生成图片')
    first = service.operation(task['id'], 'paid', {'source':'v1'}, {'version':'v1'})
    second = service.operation(task['id'], 'paid', {'source':'v1'}, {'version':'v1'})
    assert first[1] == 'new' and second[1] == 'reserved'
    service.recover(lambda owner: [])
    assert service.operation(task['id'], 'paid', {'source':'v1'}, {'version':'v1'})[1] == 'unknown'


def test_completed_operation_reuses_receipt(service):
    task = service.start('chat', '保存方案')
    policy = ClarificationPolicy(JevDecisions(service.store, JevConfig(key='')))
    service.configure(task['id'], intent='execute_change')
    adapter = HermesClarificationAdapter(service, policy, {'agent':SimpleNamespace(max_iterations=10)}, task['id'])
    called = []
    result = adapter.dispatch('miniclaw_save_artifact', {'name':'a.md'}, 'first', lambda: called.append(1) or '{"success":true}')
    assert adapter.dispatch('miniclaw_save_artifact', {'name':'a.md'}, 'second', lambda: called.append(2)) == result
    assert called == [1]


def tool_call(name, identifier, args):
    return SimpleNamespace(id=identifier, type='function', function=SimpleNamespace(name=name, arguments=json.dumps(args)))


def response(calls=None, text=''):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text, tool_calls=calls), finish_reason='tool_calls' if calls else 'stop')], model='test/model', usage=None)


@pytest.fixture
def native(service, monkeypatch):
    monkeypatch.setenv('HERMES_HOME', str(service.store.home))
    (service.store.home / 'config.yaml').write_text('memory:\n  memory_enabled: false\n  user_profile_enabled: false\nauxiliary:\n  title_generation:\n    enabled: false\n  background_review:\n    enabled: false\n', encoding='utf-8')
    from hermes_state import SessionDB
    from run_agent import AIAgent
    from tools.clarify_tool import CLARIFY_SCHEMA
    tools = [dict(type='function', function=CLARIFY_SCHEMA), dict(type='function', function=dict(name='miniclaw_save_artifact',description='save',parameters={'type':'object','properties':{'name':{'type':'string'}}}))]
    with patch('model_tools.get_tool_definitions', return_value=tools), patch('model_tools.check_toolset_requirements', return_value={}), patch('agent.process_bootstrap.OpenAI'):
        db = SessionDB(db_path=service.store.home / 'state.db')
        agent = AIAgent(api_key='test-key',base_url='https://openrouter.ai/api/v1/',model='test/model',
                        quiet_mode=True,skip_context_files=True,skip_memory=True,session_id='chat',session_db=db,max_iterations=10)
    agent._cached_system_prompt = 'You are helpful.'
    agent.compression_enabled = False
    agent.save_trajectories = False
    agent.client = MagicMock()
    yield agent, db
    agent.close(); db.close()


def test_real_hermes_mixed_batch_yields_with_paired_persistent_results(service, native):
    agent, db = native
    task = service.start('chat', '保存方案')
    policy = ClarificationPolicy(JevDecisions(service.store, JevConfig(key='')))
    adapter = HermesClarificationAdapter(service, policy, {'agent':agent,'session_key':'chat'}, task['id'])
    agent._hosted_turn_adapter = adapter
    agent.client.chat.completions.create.side_effect = [response([
        tool_call('miniclaw_save_artifact','mutate',{'name':'a.md'}),
        tool_call('clarify','ask',{'question':'什么颜色？','choices':['红色','蓝色']})])]
    with patch('model_tools.handle_function_call') as external:
        result = agent.run_conversation('保存方案', persist_user_display_metadata=adapter.metadata())
    assert result.get('awaiting_input') and not result.get('error') and not result.get('interrupted')
    assert agent.client.chat.completions.create.call_count == 1
    assert external.call_count == 0
    rows = db.get_messages('chat')
    tools = [m for m in rows if m['role'] == 'tool']
    assert {m['tool_call_id'] for m in tools} == {'mutate','ask'}
    assert all('user_response' not in m['content'] for m in tools)
    assert json.loads(tools[0]['content'])['status'] == 'not_executed_awaiting_input'
    assert rows[-1]['role'] == 'assistant'
    adapter.finish(result, 'chat')
    item = service.list(['chat'])[0]
    service.answer(['chat'],item['id'],item['version'],{item['questions'][0]['id']:'红色'},'answer')
    assert service.claim('answer')
    resumed = HermesClarificationAdapter(service, policy, {'agent':agent,'session_key':'chat'}, task['id'], resume_job='answer')
    agent._hosted_turn_adapter = resumed
    agent.client.chat.completions.create.side_effect = [response(text='已继续整理红色方案。')]
    result2 = agent.run_conversation('真实回答：红色。继续未完成步骤。', conversation_history=result['messages'], persist_user_display_metadata=resumed.metadata())
    resumed.finish(result2, 'chat')
    assert service.task(task['id'])['status'] == 'completed'
    assert len([r for r in db.get_messages('chat') if (r.get('display_metadata') or {}).get('resume_job_id') == 'answer']) == 1
    assert agent._cached_system_prompt == 'You are helpful.'


def test_real_hook_clarification_stops_without_model_followup(service, native):
    agent, _ = native
    task = service.start('chat', '讨论一下怎么做')
    policy = ClarificationPolicy(JevDecisions(service.store, JevConfig(key='')))
    adapter = HermesClarificationAdapter(service,policy,{'agent':agent,'session_key':'chat'},task['id'])
    agent._hosted_turn_adapter = adapter
    # Unknown mutation cannot escape a discussion turn, even if Jev is missing.
    agent.valid_tool_names.add('miniclaw_canvas_ai')
    agent.client.chat.completions.create.side_effect = [response([tool_call('miniclaw_canvas_ai','paid',{'prompt':'red'})])]
    with patch('model_tools.handle_function_call') as external:
        result = agent.run_conversation('讨论一下怎么做')
    assert result.get('awaiting_input')
    assert agent.client.chat.completions.create.call_count == 1 and external.call_count == 0


def test_real_preclassifier_clarifies_before_first_model_call(service, native):
    agent, db = native
    task = service.start('chat','帮我修改图片',{'semantic':{'candidates':[{'id':'a','label':'第一张'},{'id':'b','label':'第二张'}]}})
    adapter = HermesClarificationAdapter(service,ClarificationPolicy(JevDecisions(service.store,JevConfig(key=''))),{'agent':agent,'session_key':'chat'},task['id'])
    agent._hosted_turn_adapter = adapter
    result = agent.run_conversation('帮我修改图片')
    assert result.get('awaiting_input')
    assert agent.client.chat.completions.create.call_count == 0
    assert [m['role'] for m in db.get_messages('chat')] == ['user','assistant']


def test_real_gateway_releases_turn_and_resumes_original_task(service, native, monkeypatch):
    import time
    from fastapi import FastAPI
    from tui_gateway import server
    from tui_gateway.contracts import registry
    from miniclaw_web.runtime import install
    agent, db = native
    events = []
    def build(sid, key, **kwargs):
        agent.session_id = key
        agent._session_db_created = False
        return agent
    monkeypatch.setattr(server, '_make_agent', build)
    monkeypatch.setattr(server, '_emit', lambda name,sid=None,payload=None: events.append((name,sid,payload or {})))
    # Restore the real global method table and session pool after this app fixture.
    with patch.dict(server._sessions, {}, clear=True), patch.dict(server._methods), patch.dict(registry.METHODS):
        for name in list(registry.METHODS):
            if name.startswith('miniclaw.'): registry.METHODS.pop(name)
        app = FastAPI()
        install(app, service.store.home.parent)
        coordinator = app.state.clarifications
        coordinator.policy.decisions.config = JevConfig(key='')
        created = server._methods['session.create'](1,dict(source='desktop',follow_profile_config=True,eager_build=True))
        assert 'error' not in created, created
        sid = created['result']['session_id']
        session = server._sessions[sid]
        agent.client.chat.completions.create.side_effect = [response([tool_call('clarify','question',{'questions':[{'question':'什么颜色？','choices':['红色','蓝色']}]})])]
        accepted = server._methods['miniclaw.turn.submit'](2,dict(session_id=sid,text='保存方案'))
        assert 'error' not in accepted, accepted
        until = time.monotonic()+15
        while session.get('running') and time.monotonic()<until: time.sleep(.02)
        assert not session.get('running')
        complete = [p for n,s,p in events if n=='message.complete']
        assert complete[-1]['status'] == 'awaiting_input', complete
        listed = server._methods['miniclaw.clarification.list'](3,dict(session_id=sid))
        item = listed['result']['requests'][0]
        original_task = coordinator.service.task(item['task_id'])
        assert original_task['status'] == 'awaiting_input'
        agent.client.chat.completions.create.side_effect = [response(text='按红色继续整理完成。')]
        answered = server._methods['miniclaw.clarification.answer'](4,dict(session_id=sid,clarification_id=item['id'],expected_version=item['version'],answers={item['questions'][0]['id']:'红色'},client_submission_id='gateway-answer'))
        assert 'error' not in answered, answered
        coordinator.dispatch()
        until = time.monotonic()+15
        while session.get('running') and time.monotonic()<until: time.sleep(.02)
        assert coordinator.service.task(item['task_id'])['status'] == 'completed'
        rows = db.get_messages(session['session_key'])
        assert sum((r.get('display_metadata') or {}).get('resume_job_id') == 'gateway-answer' for r in rows) == 1
        assert sum(r['role']=='user' for r in rows) == 2
        assert agent.client.chat.completions.create.call_count == 2


def test_rest_service_guard_blocks_pending_business_task(service):
    task = service.start('chat','生成候选',{'canvas_turn':{'project_id':'p'},'studio_context':{'workspace':'w'}})
    identifier = service.prepare(task['id'],[question('Q_EXECUTION','确认？')],'hook')
    service.seal(task['id'],'chat',1)
    for scope in ({'owner':'chat'},{'project':'p'},{'workspace':'w'}):
        with pytest.raises(ClarificationConflict): service.guard_manual(**scope)
    service.guard_manual(workspace='unrelated')
    service.cancel(['chat'],identifier)
    service.guard_manual(project='p')


def test_paid_retry_requires_new_consent_and_success_reuses_old_receipt(service):
    task = service.start('chat','确认生成一张图片')
    first = service.operation(task['id'],'miniclaw_canvas_ai',{'prompt':'red'},{},paid=True)
    assert first[1] == 'new'
    service.operation_result(first[0],'succeeded','{"id":"existing-job","state":"running"}')
    assert service.operation(task['id'],'miniclaw_canvas_ai',{'prompt':'red'},{},paid=True)[1] == 'succeeded'
    assert service.operation(task['id'],'miniclaw_canvas_ai',{'prompt':'retry red'},{},paid=True)[1] == 'needs_consent'
    identifier = service.prepare(task['id'],[question('Q_EXECUTION','再生成一次？',['确认执行','只整理方案'])],'hook')
    service.seal(task['id'],'chat',1)
    item = service.request(identifier)
    service.answer(['chat'],identifier,item['version'],{'Q_EXECUTION':'确认执行'},'retry-consent')
    service.claim('retry-consent')
    assert service.operation(task['id'],'miniclaw_canvas_ai',{'prompt':'retry red'},{},paid=True)[1] == 'new'


def test_declining_execution_cannot_become_a_default_answer(service):
    task = service.start('chat','讨论方案')
    identifier = service.prepare(task['id'],[question('Q_EXECUTION','执行？',['确认执行','只整理方案'])],'hook')
    service.seal(task['id'],'chat',1)
    item = service.request(identifier)
    service.answer(['chat'],identifier,item['version'],{'Q_EXECUTION':'只整理方案'},'decline')
    service.claim('decline')
    adapter = HermesClarificationAdapter(service,ClarificationPolicy(JevDecisions(service.store,JevConfig(key=''))),{'agent':SimpleNamespace(max_iterations=10)},task['id'],resume_job='decline')
    external = MagicMock()
    result = json.loads(adapter.dispatch('miniclaw_canvas_ai',{'prompt':'red'},'paid',external))
    assert result['executed'] is False and not adapter.pending
    external.assert_not_called()


def test_resume_revalidates_target_but_not_unrelated_layout(service, monkeypatch):
    from miniclaw_web.clarification_routes import ClarificationCoordinator
    from hermes_state import SessionDB
    monkeypatch.setenv('HERMES_HOME',str(service.store.home))
    with SessionDB(db_path=service.store.home/'state.db') as db: db.create_session('chat','cli')
    layer = {'id':'target','asset_id':'original','x':10}
    other = {'id':'other','asset_id':'other-image','x':20}
    canvas = SimpleNamespace(get=lambda identifier:{'document':{'layers':[layer,other]}},selection=lambda identifier:None)
    studio = SimpleNamespace(decisions=JevDecisions(service.store,JevConfig(key='')))
    coordinator = ClarificationCoordinator(service.store,SimpleNamespace(),studio,canvas)
    context = {'canvas_turn':{'project_id':'p','layer_id':'target'}}
    context['versions'] = json.loads(json.dumps(coordinator.versions(context)))
    task = service.start('chat','修改目标',context)
    session = {'session_key':'chat','agent':SimpleNamespace(tools=[])}
    other['x']=500
    coordinator.validate(service.task(task['id']),session)
    layer['asset_id']='external-replacement'
    with pytest.raises(ClarificationConflict): coordinator.validate(service.task(task['id']),session)


def test_confirmed_attachment_target_cannot_be_replaced_by_model(service):
    task = service.start('chat','帮我修改图片',{'attachments':['a','b'],'semantic':{'candidates':[{'id':'a','label':'第一张'},{'id':'b','label':'第二张'}]}})
    identifier = service.prepare(task['id'],[question('Q_TARGET','修改哪张？',['第一张','第二张'])],'preclassifier')
    service.seal(task['id'],'chat',1)
    item = service.request(identifier)
    service.answer(['chat'],identifier,item['version'],{'Q_TARGET':'第二张'},'target-answer')
    service.claim('target-answer')
    adapter = HermesClarificationAdapter(service,ClarificationPolicy(JevDecisions(service.store,JevConfig(key=''))),{'agent':SimpleNamespace(max_iterations=10)},task['id'],resume_job='target-answer')
    external = MagicMock()
    result = json.loads(adapter.dispatch('miniclaw_edit_image',{'source_id':'a','operation':'flip'},'wrong-target',external))
    assert result['executed'] is False and result['source_id'] == 'b'
    external.assert_not_called()


def test_application_lifespan_starts_and_joins_resume_worker(service, monkeypatch):
    import threading
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from miniclaw_web.runtime import install
    from tui_gateway import server
    from tui_gateway.contracts import registry
    monkeypatch.setenv('HERMES_HOME', str(service.store.home))
    with patch.dict(server._methods), patch.dict(registry.METHODS):
        for name in list(registry.METHODS):
            if name.startswith('miniclaw.'):
                registry.METHODS.pop(name)
        app = FastAPI()
        install(app, service.store.home.parent)
        coordinator = app.state.clarifications
        entered = threading.Event()
        def run():
            entered.set()
            coordinator.closed.wait(5)
        monkeypatch.setattr(coordinator, 'run', run)
        with TestClient(app):
            assert entered.wait(2)
            assert app.state.clarification_worker.is_alive()
        assert coordinator.closed.is_set()
        assert not app.state.clarification_worker.is_alive()


@pytest.mark.parametrize('text,semantic,expected,allowance', [
    ('按方案生成一张候选，不要修改原图', 'generate_media', 'generate_media', 1),
    ('只写生成提示词，不生成图片', 'generate_media', 'draft', 0),
    ('先讨论修改方案，不执行', 'unclear', 'draft', 0),
])
def test_explicit_draft_boundary_outweighs_semantic_confidence(service, text, semantic, expected, allowance):
    result = {'answers': {'intent': {'choice': semantic, 'confidence': .99,
                                   'probabilities': {semantic: .99, 'discuss': .01}}}}
    policy = ClarificationPolicy(SimpleNamespace(evaluate=lambda *a, **k: result))
    task = service.start('chat', text)
    intent, _, pending_questions = policy.classify(task)
    assert intent == expected
    assert pending_questions == []
    assert task['paid_allowance'] == allowance


def test_suspended_batch_remembers_required_mutation_tools(service):
    task = service.start('chat', '修改图片')
    agent = SimpleNamespace(max_iterations=10, tools=[{'function':{'name':'miniclaw_edit_image'}}])
    adapter = HermesClarificationAdapter(service, None, {'agent':agent}, task['id'])
    calls = [SimpleNamespace(id='edit', function=SimpleNamespace(name='miniclaw_edit_image', arguments='{}')),
             SimpleNamespace(id='question', function=SimpleNamespace(name='clarify', arguments='{"question":"颜色？"}'))]
    adapter.prepare_tools(calls)
    assert service.task(task['id'])['context']['required_tools'] == ['miniclaw_edit_image']
