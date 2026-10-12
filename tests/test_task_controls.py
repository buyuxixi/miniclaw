"""Human task commands traverse the real application RPC and temporary SQLite."""
import json
import sys
import threading
from contextlib import ExitStack, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'hermes-agent')]
from miniclaw_web.task_controls import task_relation
from miniclaw_web.clarification_policy import question
from miniclaw_web.clarifications import ClarificationConflict


@pytest.mark.parametrize('text,action,payload', [
    ('取消刚才的任务', 'cancel', ''),
    ('请停止当前操作。', 'cancel', ''),
    ('修改需求：只讨论方案，不执行', 'revise', '只讨论方案，不执行'),
    ('我们换个话题：解释一下陶瓷工艺', 'new_topic', '解释一下陶瓷工艺'),
    ('换个话题：TCP 握手是什么？', 'new_topic', 'TCP 握手是什么？'),
    ('换个话题', 'new_topic', ''),
    ('修改需求', 'revise', ''),
    ('cancel current task', 'cancel', ''),
    ('revise requirements: draft only', 'revise', 'draft only'),
])
def test_explicit_task_relation(text, action, payload):
    result = task_relation(text)
    assert result['action'] == action
    assert result['text'] == payload


@pytest.mark.parametrize('text', [
    '不要取消当前任务', '取消任务是什么意思？', '如果取消任务会怎样',
    '文档写着“取消当前任务”', '"取消当前任务"', '我是不是应该取消当前任务？',
    '修改需求的流程是什么', '蓝色', '改成蓝色', '换个话题可以吗？', '换个话题，行吗？',
    '取消任务，再生成三张图',
])
def test_unclear_or_quoted_words_do_not_mutate_task(text):
    assert task_relation(text) is None


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from hermes_state import SessionDB
    from tui_gateway import server
    from tui_gateway.contracts import registry
    from miniclaw_web.runtime import install
    from miniclaw_web.decisions import JevConfig
    from miniclaw_web import canvas_tools, images, overlay
    home = tmp_path / '.hermes'
    home.mkdir()
    (home / 'config.yaml').write_text('memory:\n  memory_enabled: false\n  user_profile_enabled: false\n', encoding='utf-8')
    monkeypatch.setenv('HERMES_HOME', str(home))
    db = SessionDB(db_path=home / 'state.db')
    db.create_session('chat', 'cli')
    agent = SimpleNamespace(run_conversation=lambda *args: None, max_iterations=10, tools=[],
                            _session_messages=[], _last_flushed_db_idx=0)
    session = dict(session_key='chat', agent=agent, running=False, history=[], history_lock=threading.RLock())
    accepted = []
    def accept(rid, params):
        accepted.append(params)
        return server._ok(rid, dict(status='streaming'))
    with ExitStack() as stack:
        stack.enter_context(patch.dict(server._sessions, {'live': session}, clear=True))
        stack.enter_context(patch.dict(server._methods))
        stack.enter_context(patch.dict(registry.METHODS))
        for module, name in ((canvas_tools, '_service'), (images, '_service'), (overlay, '_store')):
            stack.enter_context(patch.object(module, name, getattr(module, name)))
        for name in list(registry.METHODS):
            if name.startswith('miniclaw.'):
                registry.METHODS.pop(name)
        app = FastAPI()
        install(app, tmp_path)
        coordinator = app.state.clarifications
        coordinator.policy.decisions.config = JevConfig(key='')
        monkeypatch.setattr(server, '_sess', lambda params, rid: (session, None))
        monkeypatch.setattr(server, '_session_db', lambda s: nullcontext(db))
        monkeypatch.setattr(server, '_ensure_session_db_row', lambda s: True)
        monkeypatch.setattr(server, '_emit', lambda *args, **kwargs: None)
        server._methods['prompt.submit'] = accept
        yield SimpleNamespace(coordinator=coordinator, session=session, db=db, accepted=accepted, server=server)
    db.close()


def waiting(runtime, context=None):
    service = runtime.coordinator.service
    task = service.start('chat', '修改图片', context or {'versions': {}})
    qid = service.prepare(task['id'], [question('Q_CHANGE', '什么颜色？', ['红色', '蓝色'])], 'tool')
    service.seal(task['id'], 'chat', 1, calls=2)
    return task, service.request(qid)


def submit(runtime, text, **extra):
    return runtime.server._methods['miniclaw.turn.submit'](1, dict(session_id='live', text=text, **extra))


def test_cancel_before_context_validation_persists_receipt_without_model(runtime):
    task, item = waiting(runtime)
    result = submit(runtime, '取消当前任务', skill='missing-skill', studio_context={'workspace': 'deleted'})
    assert 'error' not in result, result
    assert result['result']['task_control']['no_model'] is True
    assert runtime.coordinator.service.task(task['id'])['status'] == 'aborted'
    assert runtime.coordinator.service.request(item['id'])['status'] == 'canceled'
    assert not runtime.accepted
    rows = runtime.db.get_messages('chat')
    assert [row['role'] for row in rows] == ['user', 'assistant']
    assert rows[0]['content'] == '取消当前任务'
    assert rows[0]['id'] == result['result']['user_row_id']
    assert runtime.session['agent']._last_flushed_db_idx == len(runtime.session['history'])
    assert runtime.session['agent']._session_messages[-1]['content'] == rows[-1]['content']


def test_revision_with_new_body_reuses_task_and_budget(runtime):
    task, item = waiting(runtime)
    result = submit(runtime, '修改需求：只讨论方案，不执行')
    assert 'error' not in result, result
    assert result['result']['task_control']['no_model'] is False
    adapter = runtime.session['agent']._hosted_turn_adapter
    assert adapter.task_id == task['id']
    revised = runtime.coordinator.service.task(task['id'])
    assert revised['used_calls'] == 2
    assert revised['text'] == '只讨论方案，不执行'
    assert len(runtime.accepted) == 1
    assert runtime.coordinator.service.request(item['id'])['status'] == 'superseded'


def test_new_topic_ends_old_task_without_carrying_stale_project(runtime):
    task, _ = waiting(runtime)
    result = submit(runtime, '换个话题：讲一下茶叶', skill='missing', studio_context={'workspace': 'gone'})
    assert 'error' not in result, result
    assert runtime.coordinator.service.task(task['id'])['status'] == 'aborted'
    new_id = runtime.session['agent']._hosted_turn_adapter.task_id
    assert new_id != task['id']
    assert runtime.coordinator.service.task(new_id)['used_calls'] == 0
    assert len(runtime.accepted) == 1
    assert 'gone' not in runtime.accepted[0]['text']


def test_revision_without_body_waits_for_next_real_message(runtime):
    task, _ = waiting(runtime)
    result = submit(runtime, '修改需求')
    assert result['result']['task_control']['no_model'] is True
    assert runtime.coordinator.service.task(task['id'])['status'] == 'revising'
    assert not runtime.accepted
    result = submit(runtime, '现在直接水平翻转图片')
    assert 'error' not in result, result
    assert runtime.session['agent']._hosted_turn_adapter.task_id == task['id']


def test_control_prefix_does_not_turn_discussion_into_an_execution_request(runtime):
    task, _ = waiting(runtime)
    result = submit(runtime, '修改需求：解释一下颜色搭配')
    assert 'error' not in result, result
    revised = runtime.coordinator.service.task(task['id'])
    intent, _, _ = runtime.coordinator.policy.classify(revised)
    assert intent == 'discuss'
    assert revised['text'] == '解释一下颜色搭配'


@pytest.mark.parametrize('mode', ['one_message', 'two_messages', 'card'])
def test_revision_keeps_owned_material_for_both_text_and_card_entry(runtime, mode):
    import base64
    from miniclaw_web.attachments import upload
    attachment = upload(runtime.coordinator.store, 'chat', 'facts.txt',
                        base64.b64encode('用户提供的商品事实'.encode()).decode())
    task, item = waiting(runtime, {'versions': {}, 'attachments': [attachment['id']]})
    if mode == 'card':
        runtime.coordinator.service.cancel(['chat'], item['id'], superseded=True)
    elif mode == 'two_messages':
        assert 'error' not in submit(runtime, '修改需求')
    text = '修改需求：只写一份介绍' if mode == 'one_message' else '只写一份介绍'
    result = submit(runtime, text, attachments=[])
    assert 'error' not in result, result
    revised = runtime.coordinator.service.task(task['id'])
    assert revised['context']['attachments'] == [attachment['id']]
    assert revised['used_calls'] == 2
    assert '用户提供的商品事实' in runtime.accepted[-1]['text']


def test_separate_revision_uses_new_explicit_attachment_instead_of_old_material(runtime):
    import base64
    from miniclaw_web.attachments import upload
    refs = [upload(runtime.coordinator.store, 'chat', name,
                   base64.b64encode(content.encode()).decode()) for name, content in
            [('old.txt', '旧资料正文'), ('new.txt', '新资料正文')]]
    task, _ = waiting(runtime, {'versions': {}, 'attachments': [refs[0]['id']]})
    submit(runtime, '修改需求')
    result = submit(runtime, '只写新的介绍', attachments=[refs[1]['id']])
    assert 'error' not in result, result
    assert runtime.coordinator.service.task(task['id'])['context']['attachments'] == [refs[1]['id']]
    assert '新资料正文' in runtime.accepted[-1]['text']
    assert '旧资料正文' not in runtime.accepted[-1]['text']


def test_compressed_revision_with_old_material_preserves_task_until_owned_reupload(runtime):
    import base64
    from miniclaw_web.attachments import upload
    old = upload(runtime.coordinator.store, 'chat', 'facts.txt', base64.b64encode(b'old facts').decode())
    task, _ = waiting(runtime, {'versions': {}, 'attachments': [old['id']]})
    runtime.db.end_session('chat', 'compression')
    runtime.db.create_session('child', 'cli', parent_session_id='chat')
    runtime.session['session_key'] = 'child'
    result = submit(runtime, '修改需求：只写介绍')
    assert 'error' in result
    assert '重新上传' in result['error']['message']
    assert runtime.coordinator.service.task(task['id'])['status'] == 'revising'
    assert runtime.coordinator.service.task(task['id'])['used_calls'] == 2
    assert not runtime.accepted
    new = upload(runtime.coordinator.store, 'child', 'new.txt', base64.b64encode(b'current facts').decode())
    result = submit(runtime, '只写介绍', attachments=[new['id']])
    assert 'error' not in result, result
    revised = runtime.coordinator.service.task(task['id'])
    assert revised['owner'] == 'child' and revised['used_calls'] == 2
    assert runtime.session['agent']._hosted_turn_adapter.task_id == task['id']
    assert revised['context']['attachments'] == [new['id']]


def test_ambiguous_input_preserves_pending_question_and_does_not_make_answer(runtime):
    task, item = waiting(runtime)
    result = submit(runtime, '改成蓝色')
    assert result['result']['task_control']['action'] == 'clarify'
    assert runtime.coordinator.service.task(task['id'])['status'] == 'awaiting_input'
    assert runtime.coordinator.service.request(item['id'])['status'] == 'pending'
    assert not runtime.db.get_messages('chat')
    assert not runtime.accepted


def test_control_rejects_attachments_without_canceling_task(runtime):
    task, _ = waiting(runtime)
    result = submit(runtime, '取消当前任务', attachments=['unused'])
    assert 'error' in result
    assert runtime.coordinator.service.task(task['id'])['status'] == 'awaiting_input'
    assert not runtime.accepted


def test_recording_failure_does_not_claim_cancellation_was_rejected(runtime, monkeypatch):
    task, _ = waiting(runtime)
    monkeypatch.setattr(runtime.coordinator, 'record_control', lambda *args: (_ for _ in ()).throw(OSError('disk')))
    result = submit(runtime, '取消当前任务')
    assert 'error' not in result
    assert result['result']['warning']
    assert runtime.coordinator.service.task(task['id'])['status'] == 'aborted'


def test_resume_dispatch_and_control_are_serialized(runtime):
    _, item = waiting(runtime)
    runtime.coordinator.service.answer(['chat'], item['id'], item['version'], {'Q_CHANGE':'红色'}, 'answer')
    # A resume that already claimed the task cannot be silently superseded.
    runtime.coordinator.service.claim('answer')
    runtime.session['running'] = True
    with pytest.raises(ClarificationConflict):
        runtime.coordinator.control(runtime.session, '取消当前任务')


def test_control_does_not_cross_session_ownership(runtime, monkeypatch):
    task, _ = waiting(runtime)
    monkeypatch.setattr(runtime.coordinator, 'owners', lambda session: ['another-chat'])
    assert runtime.coordinator.control(runtime.session, '取消当前任务') is None
    assert runtime.coordinator.service.task(task['id'])['status'] == 'awaiting_input'


def test_another_client_waits_until_cancel_receipt_is_durable(runtime, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    waiting(runtime)
    entered, release, second_started, second_finished = (threading.Event() for _ in range(4))
    original = runtime.coordinator.record_control
    def delayed_record(*args):
        entered.set()
        assert release.wait(3)
        return original(*args)
    monkeypatch.setattr(runtime.coordinator, 'record_control', delayed_record)
    def next_turn():
        second_started.set()
        result = submit(runtime, '解释一下茶叶')
        second_finished.set()
        return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(submit, runtime, '取消当前任务')
        assert entered.wait(3)
        second = pool.submit(next_turn)
        assert second_started.wait(3)
        try:
            assert not second_finished.wait(.1)
            assert not runtime.accepted
        finally:
            release.set()
        assert 'error' not in first.result(3)
        assert 'error' not in second.result(3)
    assert len(runtime.accepted) == 1
    assert [row['role'] for row in runtime.db.get_messages('chat')] == ['user', 'assistant']
