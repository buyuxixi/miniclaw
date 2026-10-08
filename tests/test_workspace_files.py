import importlib.util
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location('workspace_files', Path(__file__).resolve().parents[1] / 'plugins/miniclaw-files/__init__.py')
files = importlib.util.module_from_spec(spec)
spec.loader.exec_module(files)


def test_missing_binary_and_hidden_resources_have_distinct_errors_without_host_paths():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        ctx = SimpleNamespace(get_config=lambda *_: str(root))
        (root / 'binary.bin').write_bytes(b'\xff\xfe\x00')
        result = lambda path, op=files._read: json.loads(files._handler(ctx, op, {'path': path}))
        missing = result('missing.txt')
        binary = result('binary.bin')
        hidden = result('.hermes/skills/canvas-editor', files._list)
        outside = result('../outside.txt')
        assert 'Path not found' in missing['error']
        assert 'not valid UTF-8' in binary['error']
        assert 'skill_view' in hidden['error']
        assert 'outside' in outside['error']
        for value in (missing, binary, hidden, outside):
            assert value['success'] is False
            assert folder not in value['error']
