"""Read only the synthetic browser acceptance sessions; never dump keys/prompts."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / '.hermes' / 'state.db'


def main() -> None:
    with sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        session_ids = {
            name: db.execute(
                'SELECT session_id FROM messages WHERE role = ? AND content LIKE ? ORDER BY id DESC LIMIT 1',
                ('user', marker),
            ).fetchone()['session_id']
            for name, marker in {
                'chat_and_tools': '这是一条普通聊天验收。请记住本次测试代号是青松-42%',
                'independent_and_cancel': '我在另一场对话里指定过一个测试代号。当前这场对话没有提供该代号%',
                'restricted_gui': '受限 Web 工具验收：请先列出教学目录%',
            }.items()
        }
        assert len(set(session_ids.values())) == 3, 'Acceptance sessions must be distinct'
        report = {}
        for name, session_id in session_ids.items():
            rows = list(db.execute(
                'SELECT role,content,tool_calls,tool_call_id,tool_name,api_content FROM messages '
                'WHERE session_id = ? AND active = 1 ORDER BY id', (session_id,),
            ))
            calls = {
                call['id']: call['function']['name']
                for row in rows if row['tool_calls']
                for call in json.loads(row['tool_calls'])
            }
            tools = [row for row in rows if row['role'] == 'tool']
            assert all(row['tool_call_id'] in calls for row in tools), 'Tool result must match a model call ID'
            report[name] = {
                'stored_session_id': session_id,
                'roles': [row['role'] for row in rows],
                'tool_names': [calls[row['tool_call_id']] for row in tools],
                'tool_success': [json.loads(row['content']).get('success') for row in tools],
                'api_content_override_rows': sum(row['api_content'] is not None for row in rows),
            }
            if name == 'chat_and_tools':
                assert {'miniclaw_read_file', 'miniclaw_list_files'} <= set(calls.values())
                assert report[name]['tool_success'] == [True, True, False]
                assert any('青松-42' in (row['content'] or '') for row in rows if row['role'] == 'assistant')
            elif name == 'independent_and_cancel':
                assert not calls
                assert all('青松-42' not in (row['content'] or '') for row in rows)
                assert any('停止按钮验收' in (row['content'] or '') for row in rows if row['role'] == 'user')
            else:
                assert report[name]['tool_names'] == ['miniclaw_list_files', 'miniclaw_read_file']
                assert report[name]['tool_success'] == [True, True]
        report['scope'] = 'Persisted acceptance records only; not a dump of model API request context'
        out = ROOT / '.codex' / 'verification' / 'browser-acceptance-storage.json'
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
