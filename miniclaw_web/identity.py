"""Install the native identity file without replacing a user's custom persona."""
from pathlib import Path
import shutil


def install_identity(root, home):
    from agent.prompt_builder import DEFAULT_AGENT_IDENTITY
    from utils import atomic_write_text

    source = Path(root) / 'SOUL.md'
    target = Path(home) / 'SOUL.md'
    content = source.read_text(encoding='utf-8')
    if target.exists():
        current = target.read_text(encoding='utf-8')
        if current.strip() == content.strip():
            return 'unchanged'
        if current.strip() != DEFAULT_AGENT_IDENTITY.strip():
            return 'custom-preserved'
        backup = target.parent / 'identity-backups' / 'hermes-default.md'
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            shutil.copyfile(target, backup)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(target, content)
    return 'installed'
