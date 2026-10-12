"""Recovery through the real Hermes loop and SDK; HTTP is local and never billed."""
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'hermes-agent')]
from miniclaw_web.chat_recovery import ChatRecovery, RecoveryPolicy, RecoveryStopped
from miniclaw_web.store import Store
from miniclaw_web.clarifications import Clarifications
from miniclaw_web.clarification_policy import ClarificationPolicy
from miniclaw_web.decisions import JevDecisions, JevConfig
from miniclaw_web.hermes_clarification_adapter import HermesClarificationAdapter


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    home = tmp_path / '.hermes'
    store = Store(home)
    monkeypatch.setenv('HERMES_HOME', str(home))
    monkeypatch.setenv('DASHSCOPE_API_KEY', 'ambient-must-not-leak')
    (home / '.env').write_text('DASHSCOPE_API_KEY=scoped-backup\nDEEPSEEK_API_KEY=scoped-primary\n', encoding='utf-8')
    (home / 'config.yaml').write_text(yaml.safe_dump({
        'model': {'default': 'deepseek-flash', 'provider': 'deepseek'},
        'agent': {'api_max_retries': 3, 'auto_recovery_cycles': 0},
        'memory': {'memory_enabled': False, 'user_profile_enabled': False},
        'auxiliary': {'title_generation': {'enabled': False}, 'background_review': {'enabled': False}},
    }), encoding='utf-8')
    from agent.secret_scope import build_profile_secret_scope, set_secret_scope, reset_secret_scope
    from run_agent import AIAgent
    from hermes_state import SessionDB
    token = set_secret_scope(build_profile_secret_scope(home), profile_home=str(home))
    calls, replies = [], []

    def http(_transport, request):
        if request.method != 'POST' or not request.url.path.endswith('/chat/completions'):
            return httpx.Response(200, json={'data': []}, request=request)
        payload = json.loads(request.read())
        calls.append((request.url.host, request.headers.get('authorization'), payload))
        status = replies.pop(0) if replies else 200
        if status == 'timeout':
            raise httpx.ReadTimeout('network timeout', request=request)
        if status == 'slow':
            time.sleep(.3)
            status = 200
        if status == 'drop':
            chunk = {'id': 'test', 'object': 'chat.completion.chunk', 'created': 1, 'model': payload['model'],
                     'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': '半段回复'}, 'finish_reason': None}]}
            class DroppedStream(httpx.SyncByteStream):
                def __iter__(self):
                    yield ('data: ' + json.dumps(chunk) + '\n\n').encode()
                    raise httpx.ReadError('stream dropped', request=request)
            return httpx.Response(200, stream=DroppedStream(), headers={'content-type': 'text/event-stream'}, request=request)
        if status != 200:
            return httpx.Response(status, json={'error': {'message': 'insufficient balance' if status == 402 else 'temporarily unavailable', 'type': 'provider_error'}}, request=request)
        message = {'role': 'assistant', 'content': '完成。'}
        if payload.get('stream'):
            chunk = {'id': 'test', 'object': 'chat.completion.chunk', 'created': 1, 'model': payload['model'],
                     'choices': [{'index': 0, 'delta': message, 'finish_reason': 'stop'}]}
            return httpx.Response(200, content=('data: ' + json.dumps(chunk) + '\n\ndata: [DONE]\n\n').encode(),
                                  headers={'content-type': 'text/event-stream'}, request=request)
        return httpx.Response(200, json={'id': 'test', 'object': 'chat.completion', 'created': 1, 'model': payload['model'],
            'choices': [{'index': 0, 'message': message, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 3, 'total_tokens': 13}}, request=request)

    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', http)
    with patch('model_tools.get_tool_definitions', return_value=[]), patch('model_tools.check_toolset_requirements', return_value={}):
        db = SessionDB(db_path=home / 'state.db')
        agent = AIAgent(api_key='scoped-primary', base_url='https://primary.test/v1', provider='deepseek', requested_provider='deepseek',
                        model='deepseek-flash', quiet_mode=True, skip_context_files=True, skip_memory=True,
                        session_id='chat', session_db=db, max_iterations=8,
                        fallback_model=[{'provider': 'custom', 'model': 'qwen-plus', 'base_url': 'https://backup.test/v1', 'key_env': 'DASHSCOPE_API_KEY', 'api_mode': 'chat_completions'}])
    agent._cached_system_prompt = 'You are helpful.'
    agent.compression_enabled = False
    agent.save_trajectories = False
    agent._disable_streaming = True
    # Hermes startup loads launch-home .env; assert subsequent routed calls do
    # not union the bound profile's keys into the process environment.
    monkeypatch.setenv('DASHSCOPE_API_KEY', 'ambient-must-not-leak')
    service = Clarifications(store)
    policy = ClarificationPolicy(JevDecisions(store, JevConfig(key='')))
    recovery_policy = RecoveryPolicy(backoff_seconds=.001, max_backoff_seconds=.002)

    def turn(text='讨论方案', history=None, limits=None, context=None):
        task = service.start('chat', text)
        recovery = ChatRecovery(store, task['id'], agent, limits or recovery_policy)
        adapter = HermesClarificationAdapter(service, policy, {'agent': agent, 'session_key': 'chat'}, task['id'], recovery=recovery)
        agent._hosted_turn_adapter = adapter
        if context:
            adapter.trace.application_context(context)
        result = agent.run_conversation(text + (context or ''), conversation_history=history)
        adapter.finish(result, 'chat')
        return result, recovery

    yield agent, calls, replies, turn
    agent.close()
    db.close()
    reset_secret_scope(token)


def test_transport_retry_and_scoped_fallback_then_restore(runtime):
    agent, calls, replies, turn = runtime
    replies.extend([503, 503, 503, 200])
    result, recovery = turn()
    assert result['completed'] and not result.get('failed')
    assert [c[0] for c in calls] == ['primary.test'] * 3 + ['backup.test']
    assert [c[1] for c in calls] == ['Bearer scoped-primary'] * 3 + ['Bearer scoped-backup']
    assert os.environ['DASHSCOPE_API_KEY'] == 'ambient-must-not-leak'
    assert recovery.snapshot()['requests'] == 4
    assert recovery.snapshot()['retries'] == 3  # two retries + fallback
    assert all(c[2]['max_tokens'] <= 4096 for c in calls)
    second, _ = turn('继续讨论方案', result['messages'])
    assert second['completed']
    assert calls[-1][0] == 'primary.test' and calls[-1][1] == 'Bearer scoped-primary'
    assert agent._cached_system_prompt == 'You are helpful.'


def test_balance_exhaustion_switches_without_primary_retry(runtime):
    _, calls, replies, turn = runtime
    replies.extend([402, 200])
    result, _ = turn()
    assert result['completed']
    assert [c[0] for c in calls] == ['primary.test', 'backup.test']


def test_request_budget_applies_across_provider_and_keeps_user_history(runtime):
    _, calls, replies, turn = runtime
    replies.extend([503] * 20)
    result, recovery = turn(limits=RecoveryPolicy(max_model_requests=4, backoff_seconds=.001, max_backoff_seconds=.002))
    assert result['failed'] and result['failure_reason'] == 'request_budget'
    assert len(calls) == recovery.snapshot()['requests'] == 4
    assert any(m['role'] == 'user' for m in result['messages'])
    assert '已收到的回复' in result['error'] and 'provider_error' not in result['error']


def test_sdk_streaming_also_uses_recovery(runtime):
    agent, calls, replies, turn = runtime
    agent._disable_streaming = False
    replies.extend([503, 200])
    result, recovery = turn()
    assert result['completed'] and len(calls) == 2
    assert all(c[2]['stream'] for c in calls)
    assert recovery.snapshot()['retries'] == 1


def test_stream_network_retries_are_not_multiplied_by_inner_loop(runtime):
    agent, calls, replies, turn = runtime
    agent._disable_streaming = False
    replies.extend(['timeout', 'timeout', 'timeout', 200])
    result, recovery = turn()
    assert result['completed']
    assert [c[0] for c in calls] == ['primary.test'] * 3 + ['backup.test']
    assert recovery.snapshot()['requests'] == len(calls)


def test_stream_drop_preserves_partial_text_without_regeneration(runtime):
    agent, calls, replies, turn = runtime
    agent._disable_streaming = False
    received = []
    agent.stream_delta_callback = received.append
    replies.append('drop')
    result, _ = turn()
    assert result['failed'] and result['failure_reason'] == 'stream_interrupted'
    assert result['partial'] and result['final_response'] == '半段回复'
    assert len(calls) == 1 and '半段回复' in received
    assert any(m['role'] == 'assistant' and m['content'] == '半段回复' for m in agent._session_db.get_messages('chat'))


def test_bad_parameters_do_not_retry_or_switch(runtime):
    _, calls, replies, turn = runtime
    replies.append(400)
    result, _ = turn()
    assert result['failed'] and len(calls) == 1
    assert '参数' in result['error']


def test_token_budget_stops_before_first_http_request(runtime):
    _, calls, _, turn = runtime
    result, _ = turn(limits=RecoveryPolicy(max_reserved_tokens=1))
    assert result['failed'] and result['failure_reason'] == 'token_budget'
    assert not calls


def test_network_timeout_and_shared_retry_cap(runtime):
    _, calls, replies, turn = runtime
    replies.extend(['timeout', 'timeout', 200])
    result, recovery = turn(limits=RecoveryPolicy(max_recovery_attempts=1, backoff_seconds=.001))
    assert result['failed'] and result['failure_reason'] == 'retry_budget'
    assert len(calls) == 2 and recovery.snapshot()['retries'] == 1


def test_task_deadline_interrupts_an_active_provider_call(runtime):
    _, calls, replies, turn = runtime
    replies.append('slow')
    result, _ = turn(limits=RecoveryPolicy(task_timeout_seconds=.05))
    assert result['failed'] and result['failure_reason'] == 'task_timeout'
    assert len(calls) == 1


def test_missing_backup_key_never_borrows_ambient_credentials(runtime, monkeypatch):
    from agent.secret_scope import set_secret_scope, reset_secret_scope
    _, calls, replies, turn = runtime
    monkeypatch.setenv('OPENAI_API_KEY', 'wrong-service-secret')
    token = set_secret_scope({'DEEPSEEK_API_KEY': 'scoped-primary', 'DASHSCOPE_API_KEY': ''})
    try:
        replies.append(402)
        result, _ = turn()
        assert result['failed'] and len(calls) == 1
        assert '额度' in result['error']
    finally:
        reset_secret_scope(token)


def test_no_backup_and_both_services_exhausted_stop(runtime):
    _, calls, replies, turn = runtime
    replies.extend([402, 402])
    result, recovery = turn()
    assert result['failed'] and len(calls) == 2
    assert recovery.snapshot()['requests'] == 2
    assert '额度' in result['error']


def local_recovery(tmp_path, limits=None):
    agent = SimpleNamespace(_interrupt_requested=False, _emit_status=lambda _: None)
    agent.interrupt = lambda **_: setattr(agent, '_interrupt_requested', True)
    recovery = ChatRecovery(Store(tmp_path), 'task', agent, limits)
    recovery.start()
    return recovery


def test_read_retry_bounded_and_budget_survives_resume(tmp_path):
    recovery = local_recovery(tmp_path, RecoveryPolicy(backoff_seconds=.001, max_recovery_attempts=1))
    calls = []
    def read():
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError()
        return '{"success":true}'
    assert recovery.read_tool('read', read) == '{"success":true}'
    recovery.finish({})
    resumed = local_recovery(tmp_path, RecoveryPolicy(backoff_seconds=.001, max_recovery_attempts=1))
    try:
        with pytest.raises(RecoveryStopped, match='retry_budget'):
            resumed.read_tool('read', lambda: (_ for _ in ()).throw(TimeoutError()))
        assert resumed.snapshot()['retries'] == 1
    finally:
        resumed.finish({})


@pytest.mark.parametrize('receipt', ['{"error":"超时"}', '{"outcome_uncertain":true}', 'not-json'])
def test_uncertain_write_is_recorded_and_never_automatically_replayed(tmp_path, receipt):
    service = Clarifications(Store(tmp_path))
    task = service.start('chat', '保存方案')
    policy = ClarificationPolicy(JevDecisions(service.store, JevConfig(key='')))
    service.configure(task['id'], intent='execute_change')
    agent = SimpleNamespace(max_iterations=10)
    adapter = HermesClarificationAdapter(service, policy, {'agent': agent}, task['id'])
    calls = []
    adapter.dispatch('miniclaw_save_artifact', {'name': 'a.md'}, 'first', lambda: calls.append(1) or receipt)
    assert service.operation(task['id'], 'miniclaw_save_artifact', {'name': 'a.md'}, {})[1] == 'unknown'
    result = adapter.dispatch('miniclaw_save_artifact', {'name': 'a.md'}, 'again', lambda: calls.append(2))
    assert len(calls) == 1 and 'awaiting_input' in result


def test_retry_after_cannot_exceed_deadline_and_cancel_never_retries(tmp_path):
    recovery = local_recovery(tmp_path)
    try:
        exc = httpx.HTTPStatusError('rate limit', request=httpx.Request('GET', 'https://test'),
                                  response=httpx.Response(429, headers={'retry-after': '600'}))
        assert recovery.delay(exc, 1) == 600
        with pytest.raises(RecoveryStopped, match='task_timeout'):
            recovery.wait(600)
        recovery.agent._interrupt_requested = True
        with pytest.raises(InterruptedError):
            recovery.read_tool('read', lambda: pytest.fail('must not dispatch'))
    finally:
        recovery.finish({})


def test_deadline_stops_active_work_and_timer_cannot_interrupt_next_turn(tmp_path):
    recovery = local_recovery(tmp_path)
    recovery._expire()
    assert recovery.agent._interrupt_requested
    result = {'interrupted': True, 'final_response': 'partial text', 'partial': True}
    recovery.finish(result)
    assert result['failed'] and not result['interrupted'] and '时间上限' in result['error']
    assert result['final_response'] == 'partial text'
    recovery.agent._interrupt_requested = False
    recovery._expire()
    assert not recovery.agent._interrupt_requested


def test_resume_keeps_model_and_active_time_budget(tmp_path):
    limits = RecoveryPolicy(max_model_requests=1)
    first = local_recovery(tmp_path, limits)
    first.agent.provider, first.agent.model = 'deepseek', 'deepseek-flash'
    first.before_request({'messages': [{'role': 'user', 'content': 'hi'}]}, 'step1')
    first.clock = lambda: first.started + 1  # deterministic despite Windows clock granularity
    first.finish({})
    resumed = local_recovery(tmp_path, limits)
    resumed.agent.provider, resumed.agent.model = 'custom', 'qwen-plus'
    try:
        assert resumed.snapshot()['active_seconds'] > 0
        with pytest.raises(RecoveryStopped, match='request_budget'):
            resumed.before_request({'messages': []}, 'step2')
    finally:
        resumed.finish({})


def test_permanent_read_error_does_not_retry(tmp_path):
    recovery = local_recovery(tmp_path)
    calls = []
    try:
        def read():
            calls.append(1)
            raise PermissionError('no permission')
        with pytest.raises(PermissionError):
            recovery.read_tool('read', read)
        assert calls == [1] and recovery.snapshot()['retries'] == 0
    finally:
        recovery.finish({})


def test_host_iteration_limit_does_not_make_unmetered_summary_request(tmp_path):
    import logging
    from agent.turn_finalizer import _resolve_budget_fallback
    recovery = local_recovery(tmp_path)
    agent = recovery.agent
    agent.max_iterations = 1
    agent.iteration_budget = SimpleNamespace(remaining=0)
    agent._hosted_turn_adapter = SimpleNamespace(recovery=recovery)
    agent._handle_max_iterations = lambda *_: pytest.fail('unmetered summary request')
    text, _, _ = _resolve_budget_fallback(agent, final_response=None, api_call_count=1, interrupted=False, failed=False,
        messages=[], _turn_exit_reason='budget_exhausted', _pending_verification_response=None,
        _pending_verification_response_previewed=False, logger=logging.getLogger('test'))
    result = {'completed': True, 'final_response': text}
    recovery.finish(result)
    assert result['failed'] and not result['completed'] and '轮数上限' in result['error']


def test_proposal_is_not_automatically_retried(tmp_path):
    recovery = local_recovery(tmp_path)
    service = Clarifications(recovery.store)
    task = service.start('chat', '讨论方案')
    adapter = HermesClarificationAdapter(service, ClarificationPolicy(JevDecisions(service.store, JevConfig(key=''))),
                                        {'agent': recovery.agent}, task['id'], recovery=recovery)
    calls = []
    try:
        def propose():
            calls.append(1)
            raise TimeoutError()
        with pytest.raises(TimeoutError):
            adapter.dispatch('miniclaw_canvas_propose', {}, 'proposal', propose)
        assert calls == [1]
    finally:
        recovery.finish({})


def test_concurrent_budget_admission_and_no_retry_configuration(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    recovery = local_recovery(tmp_path, RecoveryPolicy(max_model_requests=3))
    def reserve(_):
        try:
            recovery.reserve(model=True)
            return True
        except RecoveryStopped:
            return False
    with ThreadPoolExecutor(max_workers=4) as executor:
        admitted = list(executor.map(reserve, range(8)))
    recovery.finish({})
    assert sum(admitted) == recovery.snapshot()['requests'] == 3
    assert RecoveryPolicy.from_config({'miniclaw': {'chat_recovery': {'max_recovery_attempts': 0}}}).max_recovery_attempts == 0
