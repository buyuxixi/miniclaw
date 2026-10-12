"""Both a fresh pinned checkout and an existing v1/v2 installation can install v3."""
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_pinned_patch_sequence_and_reverse_check(tmp_path):
    patches = [ROOT / 'patches/hermes-chat-clarification-v1.patch', ROOT / 'patches/hermes-chat-recovery-v2.patch', ROOT / 'patches/hermes-chat-trace-v3.patch']
    files = {name for patch in patches for name in re.findall(r'^diff --git a/(\S+) b/', patch.read_text(encoding='utf-8'), re.M)}
    for name in files:
        content = subprocess.run(['git', 'show', f'HEAD:{name}'], cwd=ROOT / 'hermes-agent', capture_output=True, check=True).stdout
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    for patch in patches:
        subprocess.run(['git', 'apply', '--check', str(patch)], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(['git', 'apply', str(patch)], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(['git', 'apply', '--reverse', '--check', str(patch)], cwd=tmp_path, check=True, capture_output=True)
    assert 'HOSTED_TURN_ADAPTER_VERSION = 3' in (tmp_path / 'agent/turn_tool_round.py').read_text()
