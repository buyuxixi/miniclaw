"""Revised requirements supersede old answers without discarding task receipts."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'hermes-agent')]
from miniclaw_web.clarification_policy import question
from miniclaw_web.clarification_routes import ClarificationCoordinator
from miniclaw_web.clarifications import ClarificationConflict
from miniclaw_web.decisions import JevConfig, JevDecisions
from miniclaw_web.hermes_clarification_adapter import HermesClarificationAdapter
from miniclaw_web.store import Store


@pytest.fixture
def coordinator(tmp_path, monkeypatch):
    home = tmp_path / '.hermes'
    monkeypatch.setenv('HERMES_HOME', str(home))
    store = Store(home)
    from hermes_state import SessionDB
    with SessionDB(db_path=home / 'state.db') as db:
        db.create_session('chat', 'cli')
    studio = SimpleNamespace(decisions=JevDecisions(store, JevConfig(key='')))
    return ClarificationCoordinator(store, SimpleNamespace(), studio, SimpleNamespace())


def later_pending(service, approval, context=None):
    """A second pending card exposes the normal UI's revise action."""
    task = service.start('chat', '讨论方案', context or {'versions': {}})
    first = service.prepare(task['id'], [question('Q_EXECUTION', '是否执行？',
                            ['确认执行', '只整理方案'])], 'hook')
    service.seal(task['id'], 'chat', 1, calls=1)
    item = service.request(first)
    service.answer(['chat'], first, item['version'], {'Q_EXECUTION': approval}, 'first-answer')
    assert service.claim('first-answer')
    second = service.prepare(task['id'], [{'question': '结果需要什么长度？',
                             'choices': ['简短', '详细']}], 'tool', 'second-question')
    service.seal(task['id'], 'chat', 3, calls=1)
    return service.task(task['id']), service.request(second)


@pytest.mark.parametrize('approval,new_text,executions', [
    ('确认执行', '只讨论方案，不执行', 0),
    ('只整理方案', '现在直接翻转图片', 1),
])
def test_revised_request_supersedes_old_execution_answer(coordinator, approval, new_text, executions):
    service = coordinator.service
    task, pending = later_pending(service, approval)
    assert pending['status'] == 'pending'
    agent = SimpleNamespace(max_iterations=10, tools=[{'function': {'name': 'miniclaw_edit_image'}}])
    session = {'session_key': 'chat', 'agent': agent}
    # The real coordinator permits this ordinary Chat task; it did not protect
    # against stale confirmations before the revision fix.
    coordinator.validate(task, session)
    service.cancel(['chat'], pending['id'], superseded=True)
    revised = service.start('chat', new_text, {'versions': {}})
    assert revised['id'] == task['id']
    assert revised['used_calls'] == 2
    assert 'Q_EXECUTION' not in revised['confirmed']
    intent, _, _ = coordinator.policy.classify(revised)
    service.configure(task['id'], intent=intent)
    coordinator.validate(service.task(task['id']), session)
    adapter = HermesClarificationAdapter(service, coordinator.policy, session, task['id'],
                                        validate=coordinator.validate)
    called = []
    result = json.loads(adapter.dispatch('miniclaw_edit_image', {'source_id': 'a', 'operation': 'flip'},
                                        'revised-call', lambda: called.append(1) or '{"success":true}'))
    assert len(called) == executions
    assert result.get('success', False) is bool(executions)


def test_revision_invalidates_target_slots_and_keeps_receipts_and_budgets(coordinator):
    service = coordinator.service
    old_context = {'versions': {'source': 'v1'}, 'semantic': {'selected': 'a'}}
    task, pending = later_pending(service, '确认执行', old_context)
    with service.store.connect() as db:
        row = service._task(db, task['id'])
        row['confirmed'].update(Q_TARGET='旧目标', target_id='a', Q_SCOPE='局部',
                                Q_REFERENCE_ROLE='只作参考', Q_CONFLICT='旧要求', Q_INTENT='直接执行修改')
        row['max_calls'] = 8
        service._write_task(db, row)
    operation, _, _ = service.operation(task['id'], 'miniclaw_save_artifact', {'name': 'saved.md'}, {'source': 'v1'})
    service.operation_result(operation, 'succeeded', '{"success":true,"id":"saved"}')
    service.cancel(['chat'], pending['id'], superseded=True)
    new_context = {'versions': {'source': 'v2'}, 'semantic': {'selected': 'b'}}
    revised = service.start('chat', '修改新目标', new_context)
    assert revised['id'] == task['id']
    assert revised['context']['semantic']['selected'] == 'b'
    assert revised['confirmed'] == {}
    assert (revised['used_calls'], revised['max_calls']) == (2, 8)
    reused_id, status, saved = service.operation(task['id'], 'miniclaw_save_artifact', {'name': 'saved.md'}, {'source': 'v1'})
    assert reused_id == operation
    assert status == 'succeeded'
    assert json.loads(saved['result'])['id'] == 'saved'


def revise_again(service, task_id, text):
    pending = service.prepare(task_id, [{'question': '补充要求？'}], 'tool')
    service.seal(task_id, 'chat', 1)
    service.cancel(['chat'], pending, superseded=True)
    return service.start('chat', text)


def test_repeated_revisions_replace_unused_paid_consent(coordinator):
    service = coordinator.service
    task = service.start('chat', '生成三张图片')
    assert task['paid_allowance'] == 3
    for _ in range(3):
        task = revise_again(service, task['id'], '生成一张图片')
        assert task['paid_allowance'] == 1
    task = revise_again(service, task['id'], '只讨论方案，不生成')
    assert task['paid_allowance'] == 0
    assert service.operation(task['id'], 'miniclaw_canvas_ai', {'prompt': 'unapproved'}, {}, paid=True)[1] == 'needs_consent'


def test_revision_counts_submitted_paid_steps_and_reuses_their_receipt(coordinator):
    service = coordinator.service
    task = service.start('chat', '生成一张图片')
    args = {'prompt': 'red'}
    operation, status, _ = service.operation(task['id'], 'miniclaw_canvas_ai', args, {}, paid=True)
    assert status == 'new'
    receipt = '{"success":true,"id":"existing-job"}'
    service.operation_result(operation, 'succeeded', receipt)
    task = revise_again(service, task['id'], '生成一张图片')
    assert task['paid_allowance'] == 2  # one submitted call plus one new explicit call
    task = revise_again(service, task['id'], '生成一张图片')
    assert task['paid_allowance'] == 2  # no further call was submitted
    assert service.operation(task['id'], 'miniclaw_canvas_ai', args, {}, paid=True)[2]['result'] == receipt
    task = revise_again(service, task['id'], '只整理方案，不生成')
    assert task['paid_allowance'] == 1
    assert service.operation(task['id'], 'miniclaw_canvas_ai', {'prompt': 'blue'}, {}, paid=True)[1] == 'needs_consent'


@pytest.mark.parametrize('approval,new_text,executions', [
    ('确认执行', '只讨论方案，不执行', 0),
    ('只整理方案', '现在直接翻转图片', 1),
])
def test_real_agent_respects_revised_execution_boundary(coordinator, approval, new_text, executions):
    service = coordinator.service
    task, pending = later_pending(service, approval)
    service.cancel(['chat'], pending['id'], superseded=True)
    revised = service.start('chat', new_text, {'versions': {}})
    from hermes_state import SessionDB
    from run_agent import AIAgent
    from tools.clarify_tool import CLARIFY_SCHEMA
    (service.store.home / 'config.yaml').write_text(
        'memory:\n  memory_enabled: false\n  user_profile_enabled: false\nauxiliary:\n'
        '  title_generation:\n    enabled: false\n  background_review:\n    enabled: false\n', encoding='utf-8')
    tools = [dict(type='function', function=CLARIFY_SCHEMA),
             dict(type='function', function=dict(name='miniclaw_edit_image', description='edit',
                  parameters={'type': 'object', 'properties': {'source_id': {'type': 'string'}, 'operation': {'type': 'string'}}}))]
    with SessionDB(db_path=service.store.home / 'state.db') as db:
        with patch('model_tools.get_tool_definitions', return_value=tools), patch('model_tools.check_toolset_requirements', return_value={}), patch('agent.process_bootstrap.OpenAI'):
            agent = AIAgent(api_key='test-key', base_url='https://openrouter.ai/api/v1/', model='test/model',
                            quiet_mode=True, skip_context_files=True, skip_memory=True, session_id='chat', session_db=db, max_iterations=10)
        try:
            agent._cached_system_prompt = 'You are helpful.'
            agent.compression_enabled = False
            agent.save_trajectories = False
            agent.client = MagicMock()
            call = SimpleNamespace(id='edit', type='function', function=SimpleNamespace(
                name='miniclaw_edit_image', arguments=json.dumps({'source_id': 'a', 'operation': 'flip'})))
            responses = [SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='', tool_calls=[call]), finish_reason='tool_calls')], model='test/model', usage=None),
                         SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='完成', tool_calls=None), finish_reason='stop')], model='test/model', usage=None)]
            agent.client.chat.completions.create.side_effect = responses
            session = {'session_key': 'chat', 'agent': agent}
            adapter = HermesClarificationAdapter(service, coordinator.policy, session, revised['id'], validate=coordinator.validate)
            agent._hosted_turn_adapter = adapter
            with patch('model_tools.handle_function_call', return_value='{"success":true}') as execute:
                result = agent.run_conversation(new_text, persist_user_display_metadata=adapter.metadata())
            adapter.finish(result, 'chat')
            assert execute.call_count == executions
            assert not result.get('error')
            assert agent._cached_system_prompt == 'You are helpful.'
        finally:
            agent.close()


def compression_tip_session(coordinator):
    from hermes_state import SessionDB
    with SessionDB(db_path=coordinator.store.home / 'state.db') as db:
        db.end_session('chat', 'compression')
        db.create_session('tip', 'cli', parent_session_id='chat')
    session = dict(session_key='tip', running=False,
                   agent=SimpleNamespace(run_conversation=lambda *a: None, tools=[], max_iterations=10))
    coordinator.server._sessions = {'tip-live': session}
    coordinator.server._emit = lambda *args: None
    return session


def test_compression_tip_revision_keeps_task_budget_and_receipt_owner(coordinator):
    service = coordinator.service
    task, pending = later_pending(service, '确认执行')
    args = {'prompt': 'red'}
    operation, status, _ = service.operation(task['id'], 'miniclaw_canvas_ai', args, {}, paid=True)
    assert status == 'new'
    receipt = '{"success":true,"id":"original-paid-job"}'
    service.operation_result(operation, 'succeeded', receipt)
    session = compression_tip_session(coordinator)
    assert set(coordinator.owners(session)) == {'chat', 'tip'}
    control = coordinator.control(session, 'revise requirements: flip image')
    assert control['task_id'] == task['id']
    revised = coordinator.begin(session, control['text'], {}, None, [])
    assert revised['id'] == task['id']
    assert revised['owner'] == 'tip'
    assert revised['used_calls'] == task['used_calls']
    assert revised['max_calls'] == task['max_calls']
    assert revised['paid_allowance'] == 1  # only the already submitted paid call
    assert service.request(pending['id'])['owner'] == 'tip'
    reused_id, reused_status, saved = service.operation(task['id'], 'miniclaw_canvas_ai', args, {}, paid=True)
    assert (reused_id, reused_status, saved['result'], saved['owner']) == (operation, 'succeeded', receipt, 'chat')


@pytest.mark.parametrize('status', ['running', 'resume_queued', 'reconciling'])
def test_compression_ancestor_live_task_blocks_new_business_task(coordinator, status):
    service = coordinator.service
    task = service.start('chat', 'old task', {'versions': {}})
    if status != 'running':
        service.finish(task['id'], status)
    session = compression_tip_session(coordinator)
    with pytest.raises(ClarificationConflict):
        coordinator.begin(session, 'new request', {}, None, [])
    assert service.task(task['id'])['owner'] == 'chat'
    with service.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM chat_tasks').fetchone()[0] == 1


def test_unrelated_owner_cannot_revise_or_take_over_ancestor_task(coordinator):
    service = coordinator.service
    task, pending = later_pending(service, '确认执行')
    service.cancel(['chat'], pending['id'], superseded=True)
    from hermes_state import SessionDB
    with SessionDB(db_path=coordinator.store.home / 'state.db') as db:
        db.create_session('unrelated', 'cli')
    session = dict(session_key='unrelated', running=False,
                   agent=SimpleNamespace(run_conversation=lambda *a: None, tools=[], max_iterations=10))
    assert coordinator.owners(session) == ['unrelated']
    with pytest.raises(ClarificationConflict):
        service.cancel(coordinator.owners(session), pending['id'], superseded=True)
    new = coordinator.begin(session, 'discuss tea', {}, None, [])
    assert new['id'] != task['id']
    assert new['owner'] == 'unrelated'
    assert service.task(task['id'])['owner'] == 'chat'
    assert service.task(task['id'])['status'] == 'revising'


def test_legacy_operation_owner_is_frozen_before_task_moves_to_tip(coordinator):
    service = coordinator.service
    task, pending = later_pending(service, '确认执行')
    args = {'prompt': 'red'}
    operation, _, _ = service.operation(task['id'], 'miniclaw_canvas_ai', args, {}, paid=True)
    service.operation_result(operation, 'succeeded', '{"success":true}')
    # Older local databases predate operation owner snapshots.
    with service.store.connect() as db:
        data = json.loads(db.execute('SELECT data FROM chat_operations WHERE id=?', (operation,)).fetchone()[0])
        data.pop('owner', None)
        db.execute('UPDATE chat_operations SET data=? WHERE id=?', (json.dumps(data), operation))
    session = compression_tip_session(coordinator)
    service.cancel(coordinator.owners(session), pending['id'], superseded=True)
    revised = coordinator.begin(session, 'new request', {}, None, [])
    assert revised['id'] == task['id'] and revised['owner'] == 'tip'
    assert service.operation(task['id'], 'miniclaw_canvas_ai', args, {}, paid=True)[2]['owner'] == 'chat'
