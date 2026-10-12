"""Preserve original user layout in old display sidecars, without rewriting history."""
import logging
import re
import sqlite3
from .director_prompt import visible_user_text


def recover_skill_layout(display, content):
    from agent.skill_commands import extract_user_instruction_from_skill_message
    prefix = '/' + display['skill']
    text = display['text']
    if not text.startswith(prefix + ' ') or '\n' in text:
        return text
    # Only accept actual skill scaffolding. Plain user text is not metadata.
    if not isinstance(content, str) or not content.startswith('[IMPORTANT: The user has invoked the '):
        return text
    instruction = extract_user_instruction_from_skill_message(content)
    if not instruction:
        return text
    visible = text[len(prefix) + 1:].split()
    tokens = list(re.finditer(r'\S+', instruction))
    # Recover ONLY the prefix already present in the display sidecar. Runtime
    # attachment/context data appended after it must never enter the bubble.
    if not visible or [t.group() for t in tokens[:len(visible)]] != visible:
        return text
    original = instruction[:tokens[len(visible) - 1].end()]
    return prefix + '\n' + original


def read_turn_display(store, owner):
    records = {key: {**record, 'text': visible_user_text(record.get('text', ''))}
               for key, record in store.turns(owner).items()}
    legacy = {key: record for key, record in records.items()
              if record.get('skill') and '\n' not in record.get('text', '')}
    if not legacy:
        return records
    from hermes_state import SessionDB
    try:
        with SessionDB(read_only=True) as db:
            for key, record in legacy.items():
                rows = db.get_messages_around(owner, int(key), window=0).get('window', [])
                row = next((r for r in rows if r.get('id') == int(key) and r.get('role') == 'user'), None)
                if row:
                    records[key] = {**record, 'text': recover_skill_layout(record, row.get('content'))}
    except sqlite3.Error:
        logging.getLogger(__name__).warning('Original turn layout unavailable; using saved display', exc_info=True)
    return records
