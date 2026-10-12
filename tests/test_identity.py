"""Verify native identity loading and preservation without model calls."""
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'hermes-agent')]

from agent.prompt_builder import DEFAULT_AGENT_IDENTITY
from agent.system_prompt import _identity_parts
from miniclaw_web.identity import install_identity


def test_fresh_identity_loads_in_native_system_slot_without_memory(monkeypatch):
    with tempfile.TemporaryDirectory() as directory:
        home = Path(directory)
        monkeypatch.setenv('HERMES_HOME', str(home))
        assert install_identity(ROOT, home) == 'installed'
        agent = SimpleNamespace(load_soul_identity=False, skip_context_files=False,
                                _session_db=SimpleNamespace(db_path=str(home / 'state.db')))
        parts, loaded = _identity_parts(agent, None)
        assert loaded
        assert parts == [(ROOT / 'SOUL.md').read_text(encoding='utf-8').strip()]
        assert install_identity(ROOT, home) == 'unchanged'


def test_stock_identity_is_backed_up_and_replaced():
    with tempfile.TemporaryDirectory() as directory:
        home = Path(directory)
        original = DEFAULT_AGENT_IDENTITY + '\n'
        (home / 'SOUL.md').write_text(original, encoding='utf-8')
        assert install_identity(ROOT, home) == 'installed'
        assert (home / 'identity-backups/hermes-default.md').read_text(encoding='utf-8') == original
        assert (home / 'SOUL.md').read_text(encoding='utf-8') == (ROOT / 'SOUL.md').read_text(encoding='utf-8')


def test_custom_identity_is_preserved():
    with tempfile.TemporaryDirectory() as directory:
        home = Path(directory)
        (home / 'SOUL.md').write_text('My custom persona', encoding='utf-8')
        assert install_identity(ROOT, home) == 'custom-preserved'
        assert (home / 'SOUL.md').read_text(encoding='utf-8') == 'My custom persona'
