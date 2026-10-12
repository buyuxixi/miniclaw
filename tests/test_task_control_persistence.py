"""Native Agent flushes must not reappend already durable task-control receipts."""
import sys
import threading
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'hermes-agent')]
from miniclaw_web.clarification_routes import ClarificationCoordinator
from miniclaw_web.decisions import JevConfig, JevDecisions
from miniclaw_web.store import Store


@pytest.fixture
def native_control(tmp_path, monkeypatch):
    home = tmp_path / '.hermes'
    monkeypatch.setenv('HERMES_HOME', str(home))
    store = Store(home)
    (home / 'config.yaml').write_text(
        'memory:\n  memory_enabled: false\n  user_profile_enabled: false\nauxiliary:\n'
        '  title_generation:\n    enabled: false\n  background_review:\n    enabled: false\n', encoding='utf-8')
    from hermes_state import SessionDB
    from run_agent import AIAgent
    with SessionDB(db_path=home / 'state.db') as db:
        db.create_session('chat', 'cli')
        with patch('model_tools.get_tool_definitions', return_value=[]), patch('model_tools.check_toolset_requirements', return_value={}), patch('agent.process_bootstrap.OpenAI'):
            agent = AIAgent(api_key='test-key', base_url='https://openrouter.ai/api/v1/', model='test/model',
                            quiet_mode=True, skip_context_files=True, skip_memory=True, session_id='chat', session_db=db, max_iterations=10)
        try:
            agent._cached_system_prompt = 'You are helpful.'
            agent.compression_enabled = False
            agent.save_trajectories = False
            agent.client = MagicMock()
            session = dict(session_key='chat', agent=agent, running=False, history=[], history_lock=threading.RLock())
            server = SimpleNamespace(_sessions={'live': session}, _emit=lambda *args: None,
                                     _ensure_session_db_row=lambda s: True, _session_db=lambda s: nullcontext(db))
            studio = SimpleNamespace(decisions=JevDecisions(store, JevConfig(key='')))
            coordinator = ClarificationCoordinator(store, server, studio, SimpleNamespace())
            yield SimpleNamespace(agent=agent, session=session, db=db, coordinator=coordinator)
        finally:
            agent.close()


def cancel_pending_task(native):
    service = native.coordinator.service
    task = service.start('chat', 'save proposal', {'versions': {}})
    qid = service.prepare(task['id'], [{'question': 'Which color?'}], 'tool')
    service.seal(task['id'], 'chat', 1)
    control = native.coordinator.control(native.session, 'cancel current task')
    assert control['action'] == 'cancel' and control['no_model']
    row_id = native.coordinator.record_control(native.session, 'cancel current task', control)
    assert service.task(task['id'])['status'] == 'aborted'
    assert service.request(qid)['status'] == 'canceled'
    rows = native.db.get_messages('chat')
    assert [row['role'] for row in rows] == ['user', 'assistant']
    assert rows[0]['id'] == row_id
    assert rows[0]['content'] == 'cancel current task'
    return rows


def test_cancel_receipt_is_not_reappended_by_shutdown_safety_net(native_control):
    native = native_control
    before = cancel_pending_task(native)
    # tui_gateway.session_lifecycle performs this native flush without a
    # conversation_history argument when it shuts down or evicts a session.
    native.agent._persist_session(native.agent._session_messages)
    after = native.db.get_messages('chat')
    assert [(row['id'], row['role'], row['content']) for row in after] == [
        (row['id'], row['role'], row['content']) for row in before]
    native.agent.client.chat.completions.create.assert_not_called()


def test_next_native_turn_and_shutdown_keep_control_receipt_once(native_control):
    native = native_control
    before = cancel_pending_task(native)
    native.agent.client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='Tea is made from leaves.', tool_calls=None), finish_reason='stop')],
        model='test/model', usage=None)
    result = native.agent.run_conversation('Explain tea.', conversation_history=native.session['history'])
    assert not result.get('error')
    native.agent._persist_session(native.agent._session_messages)
    rows = native.db.get_messages('chat')
    assert [row['role'] for row in rows] == ['user', 'assistant', 'user', 'assistant']
    assert [row['id'] for row in rows[:2]] == [row['id'] for row in before]
    assert sum(row['content'] == 'cancel current task' for row in rows) == 1
    assert rows[-1]['content'] == 'Tea is made from leaves.'
    assert native.agent._cached_system_prompt == 'You are helpful.'
    assert native.agent.client.chat.completions.create.call_count == 1
