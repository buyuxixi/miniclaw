"""Real Hermes/SDK execution observed in SQLite, with local fault injection only."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_chat_recovery import runtime
from miniclaw_web.chat_trace import ChatTrace, TraceStore, scrub
from miniclaw_web.trace_routes import routes
from miniclaw_web.chat_recovery import ChatRecovery, RecoveryPolicy
from miniclaw_web.clarifications import Clarifications
from miniclaw_web.clarification_policy import ClarificationPolicy
from miniclaw_web.decisions import JevDecisions, JevConfig
from miniclaw_web.hermes_clarification_adapter import HermesClarificationAdapter
from miniclaw_web.store import Store


def steps(agent):
    return TraceStore(agent._hosted_turn_adapter.trace.store).page(['chat'])['steps']


def test_trace_observes_each_physical_retry_fallback_and_restoration(runtime):
    agent, calls, replies, turn = runtime
    replies.extend([503, 503, 503, 200])
    with patch.object(agent, '_invoke_api_request_error_hook', wraps=agent._invoke_api_request_error_hook) as errors:
        result, recovery = turn()
    rows = steps(agent)
    models = [r for r in rows if r['kind'] == 'model']
    decisions = [r for r in rows if r['kind'] == 'recovery']
    assert result['completed']
    assert len(models) == len(calls) == recovery.snapshot()['requests'] == 4
    assert [r['status'] for r in models] == ['failed', 'failed', 'failed', 'completed']
    assert [r['attempt'] for r in models] == [1, 2, 3, 1]
    assert len({r['id'] for r in models}) == 4
    assert models[0]['request_id'] == models[1]['request_id'] == models[2]['request_id']
    assert [r['attributes']['action'] for r in decisions] == ['retry', 'retry', 'fallback']
    assert all(r['duration_ms'] >= 0 and r['ended_at'] >= r['started_at'] for r in models)
    assert errors.call_count == 3  # Hosted recovery must not bypass the native error observer.
    assert [c.kwargs['reason'] for c in errors.call_args_list] == [r['attributes']['reason'] for r in models[:3]]
    assert models[-1]['input_tokens'] == 10 and models[-1]['output_tokens'] == 3
    assert models[0].get('input_tokens') is None
    assert models[-1]['attributes']['call_role'] == 'fallback'
    assert all(r.get('turn_id') == models[-1]['turn_id'] for r in rows)
    assert next(r for r in rows if r['kind'] == 'task')['status'] == 'completed'
    assert next(r for r in rows if r['kind'] == 'assistant')['attributes']['message_id'] > 0
    encoded = json.dumps(rows)
    assert 'scoped-primary' not in encoded and 'scoped-backup' not in encoded
    assert 'You are helpful.' not in encoded  # No hidden prompt captured.
    second, _ = turn('继续讨论', result['messages'])
    assert second['completed'] and [r for r in steps(agent) if r['kind'] == 'model'][-1]['provider'] == 'deepseek'


def test_trace_billing_has_one_primary_attempt_and_one_fallback(runtime):
    agent, _, replies, turn = runtime
    replies.extend([402, 200])
    result, _ = turn()
    rows = steps(agent)
    models = [r for r in rows if r['kind'] == 'model']
    assert result['completed'] and len(models) == 2
    assert models[0]['attributes']['reason'] == 'billing'
    assert [r['attributes']['action'] for r in rows if r['kind'] == 'recovery'] == ['fallback']


def test_explicit_application_context_is_separate_ordered_and_redacted(runtime):
    from miniclaw_web.clarification_routes import RULE_NOTE
    agent, calls, _, turn = runtime
    added = '\n引用数据：token=context-test-secret；profile=scoped-primary\n' + RULE_NOTE
    result, _ = turn('请整理方案', context=added)
    rows = steps(agent)
    user = next(r for r in rows if r['kind'] == 'input')
    context = next(r for r in rows if r['kind'] == 'context')
    model = next(r for r in rows if r['kind'] == 'model')
    assert result['completed'] and len(calls) == 1
    assert user['sequence'] < context['sequence'] < model['sequence']
    assert context['attributes']['context_source'] == 'application'
    assert context['task_id'] == user['task_id'] == model['task_id']
    assert context['turn_id'] == model['turn_id']
    assert context['status'] == 'completed' and '本轮澄清规则' in context['content']
    assert 'context-test-secret' not in json.dumps(context) and 'scoped-primary' not in json.dumps(context)
    assert user['content'] == '请整理方案'
    assert [m['content'] for m in model['input']['messages'] if m['role'] == 'user'] == ['请整理方案']
    assert [m['content'] for m in calls[0][2]['messages'] if m['role'] == 'user'] == ['请整理方案' + added]
    assert 'You are helpful.' not in json.dumps(rows)


def test_trace_network_timeout_stops_at_shared_retry_cap(runtime):
    agent, calls, replies, turn = runtime
    replies.extend(['timeout', 'timeout', 200])
    result, recovery = turn(limits=RecoveryPolicy(max_recovery_attempts=1, backoff_seconds=.001))
    rows = steps(agent)
    models = [r for r in rows if r['kind'] == 'model']
    decisions = [r for r in rows if r['kind'] == 'recovery']
    task = next(r for r in rows if r['kind'] == 'task')
    assert result['failed'] and result['failure_reason'] == 'retry_budget'
    assert len(models) == len(calls) == recovery.snapshot()['requests'] == 2
    assert [r['status'] for r in models] == ['failed', 'failed']
    assert [r['attempt'] for r in models] == [1, 2]
    assert [(r['attributes']['action'], r['attributes']['reason']) for r in decisions] == [
        ('retry', 'timeout'), ('stop', 'retry_budget')]
    assert task['status'] == 'failed' and task['attributes']['reason'] == 'retry_budget'
    assert task['attributes']['budget']['retries'] == 1
    assert task['error'] == result['error'] and '自动恢复次数上限' in task['error']
    assert '已收到的回复' in task['error']
    assert all(c[0] == 'primary.test' for c in calls)  # No extra fallback beyond the shared budget.


def test_trace_task_deadline_records_stop_and_terminal_failure(runtime):
    agent, calls, replies, turn = runtime
    replies.append('slow')
    result, recovery = turn(limits=RecoveryPolicy(task_timeout_seconds=.05))
    rows = steps(agent)
    models = [r for r in rows if r['kind'] == 'model']
    task = next(r for r in rows if r['kind'] == 'task')
    stop = next(r for r in rows if r['kind'] == 'recovery' and r['attributes']['action'] == 'stop')
    assert result['failed'] and not result['completed'] and result['failure_reason'] == 'task_timeout'
    assert len(models) == len(calls) == recovery.snapshot()['requests'] == 1
    assert stop['attributes']['reason'] == 'task_timeout'
    assert stop['started_at'] <= task['ended_at']
    assert task['status'] == 'failed' and task['attributes']['reason'] == 'task_timeout'
    assert task['error'] == result['error'] and '执行时间上限' in task['error']
    assert not any(r['status'] == 'running' for r in rows)
    # A late transport response must not turn the overall task into a success.
    assert models[0]['ended_at'] <= task['ended_at']


def test_trace_both_providers_exhausted_preserves_failure_and_guidance(runtime):
    agent, calls, replies, turn = runtime
    replies.extend([402, 402])
    result, recovery = turn()
    rows = steps(agent)
    models = [r for r in rows if r['kind'] == 'model']
    decisions = [r for r in rows if r['kind'] == 'recovery']
    task = next(r for r in rows if r['kind'] == 'task')
    assert result['failed'] and not result['completed'] and result['failure_reason'] == 'billing'
    assert len(models) == len(calls) == recovery.snapshot()['requests'] == 2
    assert [c[0] for c in calls] == ['primary.test', 'backup.test']
    assert [r['status'] for r in models] == ['failed', 'failed']
    assert [r['attempt'] for r in models] == [1, 1]
    assert [r['attributes']['reason'] for r in models] == ['billing', 'billing']
    assert [(r['attributes']['action'], r['attributes']['reason']) for r in decisions] == [
        ('fallback', 'billing'), ('stop', 'billing')]
    assert task['status'] == 'failed' and task['attributes']['reason'] == 'billing'
    assert task['error'] == result['error'] and '额度' in task['error'] and '请检查' in task['error']
    assert '已收到的回复' in task['error'] and 'insufficient balance' not in task['error']


def test_stream_drop_records_failed_attempt_and_persisted_partial(runtime):
    agent, calls, replies, turn = runtime
    agent._disable_streaming = False
    agent.stream_delta_callback = lambda _: None
    replies.append('drop')
    result, _ = turn()
    rows = steps(agent)
    assert result['failed'] and len(calls) == 1
    model = next(r for r in rows if r['kind'] == 'model')
    assert model['status'] == 'failed' and model['attributes']['reason'] == 'stream_interrupted'
    assistant = next(r for r in rows if r['kind'] == 'assistant')
    assert assistant['content'] == '半段回复' and assistant['attributes']['partial']
    assert assistant['attributes']['message_id'] > 0
    assert model.get('input_tokens') is None and model.get('output_tokens') is None


def test_stream_success_keeps_unreported_usage_unknown(runtime):
    agent, _, _, turn = runtime
    agent._disable_streaming = False
    turn()
    model = next(r for r in steps(agent) if r['kind'] == 'model')
    assert model['status'] == 'completed'
    assert model['input_tokens'] is None and model['output_tokens'] is None


def test_budget_rejection_has_no_fabricated_model_request(runtime):
    agent, calls, _, turn = runtime
    turn(limits=RecoveryPolicy(max_reserved_tokens=1))
    rows = steps(agent)
    assert not calls and not any(r['kind'] == 'model' for r in rows)
    assert next(r for r in rows if r['kind'] == 'task')['status'] == 'failed'
    assert next(r for r in rows if r['kind'] == 'recovery')['attributes']['reason'] == 'token_budget'


def adapter(tmp_path, text='讨论方案', recovery=True):
    store = Store(tmp_path)
    service = Clarifications(store)
    task = service.start('chat', text)
    agent = SimpleNamespace(max_iterations=10, _interrupt_requested=False)
    agent._emit_status = lambda _: None
    agent.interrupt = lambda **_: setattr(agent, '_interrupt_requested', True)
    recover = ChatRecovery(store, task['id'], agent, RecoveryPolicy(backoff_seconds=.001, max_backoff_seconds=.002)) if recovery else None
    host = HermesClarificationAdapter(service, ClarificationPolicy(JevDecisions(store, JevConfig(key=''))),
                                      {'agent': agent}, task['id'], recovery=recover)
    if recover:
        recover.start()
    return host, service, task


def test_read_retry_has_separate_spans_with_same_tool_call_id(tmp_path):
    host, _, _ = adapter(tmp_path)
    calls = []
    def read():
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError('temporary')
        return '{"success":true,"content":"read result"}'
    try:
        host.dispatch('miniclaw_read_file', {'path': 'a.txt'}, 'call-read', read)
        rows = TraceStore(host.service.store).page(['chat'])['steps']
        tools = [r for r in rows if r['kind'] == 'tool']
        assert [r['status'] for r in tools] == ['failed', 'completed']
        assert [r['attempt'] for r in tools] == [1, 2]
        assert all(r['attributes']['call_id'] == 'call-read' and r['attributes']['executed'] for r in tools)
        assert next(r for r in rows if r['kind'] == 'recovery')['attributes']['next_attempt'] == 2
    finally:
        host.recovery.finish({})


def test_unknown_write_records_receipt_and_second_call_is_not_execution(tmp_path):
    host, service, task = adapter(tmp_path, '保存方案', recovery=False)
    service.configure(task['id'], intent='execute_change')
    calls = []
    host.dispatch('miniclaw_save_artifact', {'name': 'a.md'}, 'first', lambda: calls.append(1) or '{"error":"超时"}')
    host.dispatch('miniclaw_save_artifact', {'name': 'a.md'}, 'again', lambda: calls.append(2))
    rows = TraceStore(service.store).page(['chat'])['steps']
    executed = [r for r in rows if r['kind'] == 'tool' and r['attributes']['executed']]
    skipped = [r for r in rows if r['kind'] == 'tool' and not r['attributes']['executed']]
    assert len(calls) == len(executed) == 1 and executed[0]['status'] == 'unknown'
    assert executed[0]['operation_id'] and skipped[0]['status'] == 'waiting'
    reconcile = next(r for r in rows if r['kind'] == 'recovery' and r['attributes']['action'] == 'reconcile')
    assert reconcile['attributes']['operation_id'] == executed[0]['operation_id']


def test_trace_is_observer_and_failed_storage_does_not_repeat_write(tmp_path, monkeypatch):
    host, service, task = adapter(tmp_path, '保存方案', recovery=False)
    service.configure(task['id'], intent='execute_change')
    # Actual SQLite observation failure, while the authoritative operation store remains usable.
    with service.store.connect() as db:
        db.execute('DROP TABLE chat_trace_steps')
    calls = []
    result = host.dispatch('miniclaw_save_artifact', {'name': 'a.md'}, 'first', lambda: calls.append(1) or '{"success":true}')
    assert result == '{"success":true}' and calls == [1] and host.trace.disabled
    host.dispatch('miniclaw_save_artifact', {'name': 'a.md'}, 'again', lambda: calls.append(2))
    assert calls == [1]


def test_redaction_of_nested_json_inline_credentials_and_signed_urls(tmp_path):
    store = TraceStore(Store(tmp_path))
    trace = ChatTrace(store, {'id': 'task', 'owner': 'chat', 'text': 'hi'}, SimpleNamespace(api_key='known-key-123'))
    trace.event('tool', 'read', input={'Authorization': 'Bearer header-secret', 'password': 'short',
                'json': '{"nested":{"cookie":"cookie-secret","api_key":"other-secret"}}',
                'url': 'https://files.test/a?X-Amz-Signature=signature-secret&token=token-secret&plain=1',
                'data': 'inline known-key-123 and Bearer bearer-secret'})
    with store.store.connect() as db:
        raw = '\n'.join(r[0] for r in db.execute('SELECT data FROM chat_trace_steps'))
    for secret in ('known-key-123', 'header-secret', 'short', 'cookie-secret', 'other-secret', 'signature-secret', 'token-secret', 'bearer-secret'):
        assert secret not in raw
    assert 'plain=1' in raw and '[已脱敏]' in raw


def test_record_is_bounded_for_nested_large_payloads_and_reports_truncation(tmp_path):
    store = TraceStore(Store(tmp_path))
    trace = ChatTrace(store, {'id': 'task', 'owner': 'chat', 'text': 'hi'}, SimpleNamespace())
    identifier = trace.event('tool', 'read', input={str(k): ['汉' * 16000] * 80 for k in range(80)})
    with store.store.connect() as db:
        raw = db.execute('SELECT data FROM chat_trace_steps WHERE id=?', (identifier,)).fetchone()[0]
    assert len(raw.encode('utf-8')) <= 120000
    assert json.loads(raw)['attributes']['truncated'] is True


def test_trace_page_scopes_session_and_pages_without_overlap(tmp_path, monkeypatch):
    from hermes_state import SessionDB
    home = tmp_path / '.hermes'
    monkeypatch.setenv('HERMES_HOME', str(home))
    store = TraceStore(Store(home))
    with SessionDB(db_path=home / 'state.db') as db:
        db.create_session('chat', 'cli')
        db.create_session('other', 'cli')
    trace = ChatTrace(store, {'id': 't1', 'owner': 'chat', 'text': 'hello'}, SimpleNamespace())
    trace.event('recovery', '准备重试')
    ChatTrace(store, {'id': 't2', 'owner': 'other', 'text': 'private'}, SimpleNamespace())
    app = FastAPI()
    app.include_router(routes(store), prefix='/api/miniclaw')
    with TestClient(app) as client:
        first = client.get('/api/miniclaw/traces', params={'owner': 'chat', 'limit': 2}).json()
        assert first['has_more'] and len(first['steps']) == 2
        second = client.get('/api/miniclaw/traces', params={'owner': 'chat', 'limit': 2, 'before': first['next_before']}).json()
        assert len(second['steps']) == 1 and not second['has_more']
        rows = second['steps'] + first['steps']
        assert all(r['session_id'] == 'chat' and r['updated_at'] >= r['started_at'] for r in rows)
        assert [r['sequence'] for r in rows] == sorted({r['sequence'] for r in rows})
        assert client.get('/api/miniclaw/traces?owner=missing').status_code == 404
        assert client.get('/api/miniclaw/traces?owner=chat&limit=1001').status_code == 422
        assert client.get('/api/miniclaw/traces?owner=chat&before=0').status_code == 422


def test_restart_reconciles_unsettled_spans_without_invented_duration(tmp_path):
    store = TraceStore(Store(tmp_path))
    trace = ChatTrace(store, {'id': 'task', 'owner': 'chat', 'text': 'hi'}, SimpleNamespace())
    tool = trace.tool_start('save', {}, 'call', 1, 'operation')
    TraceStore(store.store).recover()
    rows = store.page(['chat'])['steps']
    unresolved = next(r for r in rows if r['id'] == tool)
    assert unresolved['status'] == 'unknown' and unresolved['ended_at'] is None and unresolved['duration_ms'] is None
    assert unresolved['attributes']['reason'] == 'process_restart'
    assert next(r for r in rows if r['kind'] == 'input')['status'] == 'completed'


def test_large_request_keeps_ids_outcome_usage_and_budget(tmp_path):
    store = TraceStore(Store(tmp_path))
    trace = ChatTrace(store, {'id': 'task', 'owner': 'chat', 'text': 'hi'}, SimpleNamespace())
    identifier = trace.tool_start('save', {str(i): 'x' * 16000 for i in range(4)}, 'call-1', 2, 'operation-1')
    trace.tool_end(identifier, error=TimeoutError('known failure'), operation_id='operation-1')
    row = next(r for r in store.page(['chat'])['steps'] if r['id'] == identifier)
    assert row['attempt'] == 2 and row['operation_id'] == 'operation-1' and row['attributes']['call_id'] == 'call-1'
    assert row['status'] == 'unknown' and row['error'] == 'known failure' and row['attributes']['truncated']
    assert row['duration_ms'] >= 0


def test_long_ordinary_text_redaction_does_not_block_agent(tmp_path):
    import time
    store = TraceStore(Store(tmp_path))
    trace = ChatTrace(store, {'id': 'task', 'owner': 'chat', 'text': 'hi'}, SimpleNamespace())
    began = time.monotonic()
    identifier = trace.tool_start('read', {'text': 'A' * 16000}, 'call', 1)
    elapsed = time.monotonic() - began
    assert identifier and elapsed < 1  # Regression was > 15 s of regex backtracking.


@pytest.mark.parametrize('result,status', [({'error': 'permission denied'}, 'failed'),
    ({'success': False}, 'failed'), ({'status': 'not_executed'}, 'interrupted'),
    ({'state': 'unknown'}, 'unknown'), ({'status': 'awaiting_input'}, 'waiting')])
def test_nonexecuted_tools_do_not_claim_success(tmp_path, result, status):
    store = TraceStore(Store(tmp_path))
    trace = ChatTrace(store, {'id': 'task', 'owner': 'chat', 'text': 'hi'}, SimpleNamespace())
    trace.skipped_tool('save', {}, 'call', result)
    tool = next(r for r in store.page(['chat'])['steps'] if r['kind'] == 'tool')
    assert tool['status'] == status and tool['attributes']['executed'] is False


def test_real_sdk_model_tool_retry_model_chain_is_linked(runtime, monkeypatch):
    import httpx
    agent, calls, _, turn = runtime
    schema = {'type': 'function', 'function': {'name': 'miniclaw_read_file', 'description': 'read local text',
              'parameters': {'type': 'object', 'properties': {'path': {'type': 'string'}}}}}
    agent.tools = [schema]
    agent.valid_tool_names.add('miniclaw_read_file')
    messages = [
        {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'call-read', 'type': 'function',
         'function': {'name': 'miniclaw_read_file', 'arguments': '{"path":"a.txt"}'}}]},
        {'role': 'assistant', 'content': '已读完。'}]
    def http(transport, request):
        payload = json.loads(request.read())
        calls.append((request.url.host, request.headers.get('authorization'), payload))
        message = messages.pop(0)
        return httpx.Response(200, json={'id': 'test', 'object': 'chat.completion', 'created': 1, 'model': payload['model'],
            'choices': [{'index': 0, 'message': message, 'finish_reason': 'tool_calls' if message.get('tool_calls') else 'stop'}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 3, 'total_tokens': 13}}, request=request)
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', http)
    with patch('model_tools.handle_function_call', side_effect=[TimeoutError('temporary read failure'), '{"success":true,"content":"file text"}']) as execute:
        result, _ = turn()
    rows = steps(agent)
    assert result['completed'] and len(calls) == 2 and execute.call_count == 2
    models = [r for r in rows if r['kind'] == 'model']
    tools = [r for r in rows if r['kind'] == 'tool']
    assert len(models) == 2 and [r['status'] for r in tools] == ['failed', 'completed']
    assert all(r['attributes']['call_id'] == 'call-read' and r['turn_id'] == models[0]['turn_id'] for r in tools)
    assert any(m['role'] == 'tool' and m['tool_call_id'] == 'call-read' for m in agent._session_db.get_messages('chat'))
    assert next(r for r in rows if r['kind'] == 'assistant')['attributes']['message_id'] > 0


def test_real_request_keeps_host_instructions_but_trace_uses_original_public_input(runtime):
    from miniclaw_web.clarification_routes import RULE_NOTE
    agent, calls, _, turn = runtime
    original = '讨论这个引用字符串，逐字保留用户正文：' + RULE_NOTE
    internal = '\nPRIVATE_HOST_PROJECT_CONTEXT\nPRIVATE_DIRECTOR_RULES' + RULE_NOTE
    store = Store(Path(agent._session_db.db_path).parent)
    service = Clarifications(store)
    task = service.start('chat', original)
    recovery = ChatRecovery(store, task['id'], agent, RecoveryPolicy(backoff_seconds=.001, max_backoff_seconds=.002))
    host = HermesClarificationAdapter(service, ClarificationPolicy(JevDecisions(store, JevConfig(key=''))),
                                      {'agent': agent, 'session_key': 'chat'}, task['id'], recovery=recovery)
    agent._hosted_turn_adapter = host
    agent.tools = [{'type': 'function', 'function': {'name': 'miniclaw_read_file', 'description': 'PRIVATE_TOOL_SCHEMA_RULES',
                   'parameters': {'type': 'object', 'properties': {}}}}]
    agent.valid_tool_names.add('miniclaw_read_file')
    result = agent.run_conversation(original + internal, persist_user_display_metadata=host.metadata())
    host.finish(result, 'chat')
    model = next(r for r in steps(agent) if r['kind'] == 'model')
    traced_user = next(m for m in model['input']['messages'] if m['role'] == 'user')
    assert traced_user['content'] == original  # A user quoting RULE_NOTE must remain intact.
    assert calls[0][2]['messages'][-1]['content'] == original + internal  # Agent behavior is untouched.
    assert 'PRIVATE_HOST_PROJECT_CONTEXT' not in json.dumps(steps(agent))
    assert 'PRIVATE_DIRECTOR_RULES' not in json.dumps(steps(agent))
    assert 'PRIVATE_TOOL_SCHEMA_RULES' not in json.dumps(steps(agent))
    assert model['attributes']['input_projection'] == 'public_conversation'
    next_result, _ = turn('继续讨论', result['messages'])
    assert next_result['completed']
    last = [r for r in steps(agent) if r['kind'] == 'model'][-1]
    assert last['input']['messages'][0]['content'] == original
    assert 'PRIVATE_HOST_PROJECT_CONTEXT' not in json.dumps(last)


def test_user_api_sidecar_and_unknown_internal_context_are_not_persisted(tmp_path):
    store = TraceStore(Store(tmp_path))
    task = Clarifications(store.store).start('chat', '公开原文')
    agent = SimpleNamespace(provider='deepseek', model='test', _strip_think_blocks=lambda text: text)
    trace = ChatTrace(store, task, agent)
    trace.capture_public_messages([{'role': 'user', 'content': '公开原文', 'api_content': '公开原文\nPRIVATE_PREFETCH_CONTEXT'}])
    trace.model_start({'messages': [{'role': 'system', 'content': 'PRIVATE_SYSTEM'}, {'role': 'developer', 'content': 'PRIVATE_DEVELOPER'},
                      {'role': 'user', 'content': '公开原文\nPRIVATE_PREFETCH_CONTEXT'},
                      {'role': 'user', 'content': 'PRIVATE_SYNTHETIC_NUDGE'}]}, 'turn:api:1', {})
    model = next(r for r in store.page(['chat'])['steps'] if r['kind'] == 'model')
    assert model['input']['messages'][0]['content'] == '公开原文'
    assert model['input']['messages'][1]['content'] == '[公开输入未记录；应用上下文已省略]'
    assert 'PRIVATE_' not in json.dumps(model)


def test_clarification_tool_control_instruction_is_omitted_without_mutating_result(tmp_path):
    store = TraceStore(Store(tmp_path))
    trace = ChatTrace(store, {'id': 'task', 'owner': 'chat', 'text': 'hi'}, SimpleNamespace())
    result = {'status': 'awaiting_input', 'task_id': 'task', 'clarification_id': 'question',
              'instructions': 'No answer has been supplied. Resume only after a real user answer.'}
    trace.skipped_tool('clarify', {}, 'call', result)
    tool = next(r for r in store.page(['chat'])['steps'] if r['kind'] == 'tool')
    assert 'instructions' not in tool['output'] and 'instructions' in result
    assert trace.public_tool_result({'instructions': '用户提供的操作说明'}) == {'instructions': '用户提供的操作说明'}


def test_plain_credentials_and_supplier_signed_query_params_are_redacted(tmp_path):
    store = TraceStore(Store(tmp_path))
    trace = ChatTrace(store, {'id': 'task', 'owner': 'chat', 'text': 'hi'}, SimpleNamespace())
    trace.event('tool', 'read', output={'token': 'external-oauth-value', 'key': 'external-storage-key',
                'signature': 'signed-secret', 'X-Amz-Security-Token': 'aws-security-secret',
                'inline': 'result={"key":"inline-key-secret","token":"inline-token-secret"}',
                'url': 'https://files.test/a?key=query-key-secret&X-Amz-Credential=aws-credential-secret&X-Amz-Security-Token=aws-token-secret&plain=1'})
    with store.store.connect() as db:
        raw = '\n'.join(row[0] for row in db.execute('SELECT data FROM chat_trace_steps'))
    for secret in ('external-oauth-value', 'external-storage-key', 'signed-secret', 'aws-security-secret',
                   'inline-key-secret', 'inline-token-secret', 'query-key-secret', 'aws-credential-secret', 'aws-token-secret'):
        assert secret not in raw
    assert 'plain=1' in raw
