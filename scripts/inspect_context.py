"""Read-only Hermes replay inspection; never sends a model request."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
os.environ['HERMES_HOME'] = str(ROOT / '.hermes')
sys.path.insert(0, str(ROOT / 'hermes-agent'))
from hermes_state import SessionDB
from agent.replay_cleanup import canonicalize_replay_history


def inspect(session_id, full=False):
    db = SessionDB(db_path=ROOT / '.hermes/state.db', read_only=True)
    try:
        tip = db.resolve_resume_session_id(session_id)
        session = db.get_session(tip)
        if not session:
            raise ValueError('Session not found')
        model, display = db.get_resume_conversations(tip)
        cleaned = canonicalize_replay_history(model)
        selected = {row.get('_row_id') for row in model}
        rows = db._read_all('SELECT id, role, active, compacted, _compressed_summary, '
                            'length(content) AS chars, tool_call_id, tool_name FROM messages '
                            'WHERE session_id=? ORDER BY id', (tip,))
        prompt = session.get('system_prompt') or ''
        report = {
            'kind': 'database_replay_not_captured_api_request',
            'requested_id': session_id, 'resolved_id': tip,
            'model_called': False,
            'system_prompt': {'hash': session.get('system_prompt_hash'), 'chars': len(prompt)},
            'model_before_cleanup_count': len(model), 'model_after_cleanup_count': len(cleaned),
            'display_before_projection_count': len(display),
            'current_session_rows': [{**dict(row), 'selected_for_model': row['id'] in selected}
                                     for row in rows],
            'model_history': cleaned if full else [
                {'row_id': m.get('_row_id'), 'role': m.get('role'),
                 'chars': len(str(m.get('content') or '')),
                 'summary': bool(m.get('_compressed_summary')),
                 'tool_calls': m.get('tool_calls'), 'tool_call_id': m.get('tool_call_id')}
                for m in cleaned],
        }
        if full:
            report['system_prompt']['text'] = prompt
        return report
    finally:
        db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session_id')
    parser.add_argument('--full', action='store_true', help='Include prompt and complete model replay bodies')
    parser.add_argument('--output', type=Path, help='Save UTF-8 JSON for the editor')
    args = parser.parse_args()
    text = json.dumps(inspect(args.session_id, args.full), ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding='utf-8')
        print(f'Saved read-only replay report: {args.output.resolve()}')
    else:
        print(text)
