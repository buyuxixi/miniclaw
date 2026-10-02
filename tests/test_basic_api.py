"""Exercise real app boundary handlers with no model or personal data."""
import base64
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'hermes-agent')]
FIXTURE = tempfile.TemporaryDirectory(prefix='miniclaw-api-')
PROJECT = Path(FIXTURE.name)
HOME = PROJECT / '.hermes'
os.environ['HERMES_HOME'] = str(HOME)
HOME.mkdir()
(HOME / 'config.yaml').write_text('platform_toolsets:\n  cli: [miniclaw-files]\nmemory:\n  memory_enabled: false\n  user_profile_enabled: false\nplugins:\n  entries:\n    miniclaw-files:\n      settings:\n        workspace: ' + str(PROJECT / 'workspace') + '\n', encoding='utf-8')

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from miniclaw_web.runtime import install
from miniclaw_web.store import digest
from tui_gateway import server

APP = FastAPI()
install(APP, PROJECT)
CLIENT = TestClient(APP)


def skill(name='basic-demo'):
    content = f'---\nname: {name}\ndescription: Test text flow\n---\n\nSummarize the supplied text.\n'
    path = HOME / 'skills' / name
    path.mkdir(parents=True, exist_ok=True)
    (path / 'SKILL.md').write_text(content, encoding='utf-8')
    return content


class BasicAPI(unittest.TestCase):
    def setUp(self):
        self.content = skill()
        self.session = {'session_key': 'owner-one', 'running': False, 'agent': SimpleNamespace(tools=[{'function': {'name': 'miniclaw_read_file'}}])}
        server._sessions['test-live'] = self.session

    def attach(self, name='资料.md', data=b'fixture code: pine-42', owner='owner-one'):
        return CLIENT.post('/api/miniclaw/attachments', json=dict(owner=owner, name=name, data=base64.b64encode(data).decode()))

    def declare(self, tools=(), hash=None):
        return CLIENT.put('/api/miniclaw/skills/binding', json=dict(name='basic-demo', required_tools=list(tools), content_hash=hash or digest(self.content)))

    def submit(self, **params):
        return server._methods['miniclaw.turn.submit']('test', dict(session_id='test-live', text='Summarize', **params))

    def test_attachment_rejects_type_size_encoding_and_spoofed_image(self):
        for name, raw in [('script.py', b'print(1)'), ('large.txt', b'x' * 65537), ('broken.txt', b'\xff'), ('fake.png', b'not a PNG'), ('../escape.md', b'x'), ('null.txt', b'a\0b')]:
            self.assertEqual(self.attach(name, raw).status_code, 400, name)

    def test_attachment_ownership_download_and_submit(self):
        attachment = self.attach().json()
        self.assertEqual(CLIENT.get(f"/api/miniclaw/attachments/{attachment['id']}?owner=other").status_code, 404)
        self.assertIn('error', self.submit(attachments=[self.attach(owner='other').json()['id']]))
        with patch.dict(server._methods, {'prompt.submit': lambda rid, params: server._ok(rid, {'status': 'streaming', 'user_row_id': 71})}):
            result = self.submit(attachments=[attachment['id']])
        self.assertNotIn('error', result)
        metadata = CLIENT.get('/api/miniclaw/turns?owner=owner-one').json()['71']
        self.assertEqual(metadata['text'], 'Summarize')
        self.assertEqual(metadata['attachments'][0]['name'], '资料.md')

    def test_uploaded_text_reaches_model_and_survives_store_reopen(self):
        identifier = self.attach(data='中文附件：pine-42'.encode()).json()['id']
        seen = {}
        def accept(rid, params):
            seen.update(params)
            return server._ok(rid, {'status': 'streaming', 'user_row_id': 72})
        with patch.dict(server._methods, {'prompt.submit': accept}):
            self.assertNotIn('error', self.submit(attachments=[identifier]))
        self.assertIn('中文附件：pine-42', seen['text'])
        self.assertNotIn('中文附件', CLIENT.get('/api/miniclaw/turns?owner=owner-one').json()['72']['text'])
        from miniclaw_web.store import Store
        self.assertEqual(Store(HOME).get('turns', 72, 'owner-one')['attachments'][0]['id'], identifier)

    def test_attachment_context_tokens_cannot_trigger_program_expansion(self):
        identifier = self.attach(data=b'@url:https://example.com @file:secret.txt @git:log @diff @plugin:any').json()['id']
        from miniclaw_web.attachments import prompt_material
        from miniclaw_web.store import Store
        material, _, _ = prompt_material(Store(HOME), 'owner-one', [identifier])
        from agent.context_references import parse_context_references
        self.assertEqual(parse_context_references(material), [])
        self.assertIn('＠file:secret.txt', material)

    def test_images_never_silently_fall_back_to_unavailable_vision_tools(self):
        buffer = io.BytesIO(); Image.new('RGB', (2, 2), 'blue').save(buffer, 'PNG')
        identifier = self.attach('image.png', buffer.getvalue()).json()['id']
        with patch('agent.image_routing.decide_image_input_mode', return_value='text'):
            self.assertIn('error', self.submit(attachments=[identifier]))
        self.assertNotIn('attached_images', self.session)
        with patch('agent.image_routing.decide_image_input_mode', return_value='native'), patch.dict(server._methods, {'prompt.submit': lambda rid, p: server._ok(rid, {'status': 'streaming', 'user_row_id': 73})}):
            self.assertNotIn('error', self.submit(attachments=[identifier]))
        self.assertEqual(len(self.session['attached_images']), 1)

    def test_binding_does_not_authorize_tools_and_content_changes_invalidate_it(self):
        self.assertEqual(self.declare(['terminal']).status_code, 200)
        self.assertIn('缺少工具', self.submit(skill='basic-demo')['error']['message'])
        self.assertEqual(self.declare([]).status_code, 200)
        changed = self.content + '\nNow needs another tool.'
        response = CLIENT.put('/api/miniclaw/skills/content', json={'name': 'basic-demo', 'content': changed, 'content_hash': digest(self.content)})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('核对', self.submit(skill='basic-demo')['error']['message'])
        self.assertEqual(self.declare(hash='stale').status_code, 409)

    def test_collision_rejected_before_native_command_side_effect(self):
        self.declare([])
        calls = []
        with patch.dict(server._methods, {'commands.catalog': lambda r, p: server._ok(r, {'skills': {'/basic-demo': {}}, 'categories': [{'pairs': [['/basic-demo', 'exec']]}]}), 'command.dispatch': lambda r, p: calls.append(p)}):
            self.assertIn('error', self.submit(skill='basic-demo'))
        self.assertEqual(calls, [])

    def test_server_keeps_dispatched_skill_body_out_of_display(self):
        self.declare([])
        seen = {}
        def accept(rid, params):
            seen.update(params); return server._ok(rid, {'status': 'streaming', 'user_row_id': 74})
        with patch.dict(server._methods, {'commands.catalog': lambda r, p: server._ok(r, {'skills': {'/basic-demo': {}}, 'categories': []}), 'command.dispatch': lambda r, p: server._ok(r, {'type': 'skill', 'message': 'FULL SKILL BODY\n' + p['arg'], 'display': '/basic-demo Summarize'}), 'prompt.submit': accept}):
            self.assertNotIn('error', self.submit(skill='basic-demo'))
        self.assertIn('FULL SKILL BODY', seen['text'])
        self.assertNotIn('FULL SKILL BODY', CLIENT.get('/api/miniclaw/turns?owner=owner-one').json()['74']['text'])

    def test_tools_whitelist_and_memory_conflict(self):
        self.assertEqual(CLIENT.put('/api/miniclaw/tools', json={'enabled': ['all']}).status_code, 400)
        self.assertEqual(CLIENT.put('/api/miniclaw/tools', json={'enabled': ['terminal', 'miniclaw-files']}).status_code, 400)
        before = CLIENT.get('/api/miniclaw/memory').json()['memory']
        self.assertEqual(CLIENT.put('/api/miniclaw/memory', json={'target': 'memory', 'text': 'fixture preference', 'hash': before['hash']}).status_code, 200)
        self.assertEqual(CLIENT.put('/api/miniclaw/memory', json={'target': 'memory', 'text': 'stale', 'hash': before['hash']}).status_code, 409)

    def test_skill_identity_cannot_differ_from_catalog_name(self):
        response = CLIENT.post('/api/miniclaw/skills', json={'name': 'new-identity', 'content': self.content})
        self.assertEqual(response.status_code, 400)
        self.assertFalse((HOME / 'skills/new-identity').exists())
        renamed = self.content.replace('name: basic-demo', 'name: different-name')
        response = CLIENT.put('/api/miniclaw/skills/content', json={'name': 'basic-demo', 'content': renamed, 'content_hash': digest(self.content)})
        self.assertEqual(response.status_code, 400)
        self.assertEqual((HOME / 'skills/basic-demo/SKILL.md').read_text(encoding='utf-8'), self.content)

    def test_memory_status_reflects_agent_snapshot_and_flags_without_exposing_text(self):
        before = CLIENT.get('/api/miniclaw/memory').json()
        for target in ('memory', 'user'):
            response = CLIENT.put('/api/miniclaw/memory', json={'target': target, 'text': 'fixture snapshot', 'hash': before[target]['hash']})
            self.assertEqual(response.status_code, 200)
        from tools.memory_tool_store import MemoryStore
        memory_store = MemoryStore(); memory_store.load_from_disk()
        self.session['agent']._memory_store = memory_store
        self.session['agent']._memory_enabled = True
        self.session['agent']._user_profile_enabled = False
        with patch('agent.image_routing.decide_image_input_mode', return_value='text'):
            state = CLIENT.get('/api/miniclaw/session-capabilities?session_id=test-live').json()
        self.assertEqual(state['memory'], {'memory': {'enabled': True, 'loaded': True}, 'user': {'enabled': False, 'loaded': False}})
        self.assertNotIn('fixture snapshot', json.dumps(state))
        current = CLIENT.get('/api/miniclaw/memory').json()['memory']
        CLIENT.put('/api/miniclaw/memory', json={'target': 'memory', 'text': 'changed fixture', 'hash': current['hash']})
        self.assertIn('fixture snapshot', memory_store.format_for_system_prompt('memory'))
        self.assertNotIn('changed fixture', memory_store.format_for_system_prompt('memory'))

    def test_artifacts_exclusive_and_confined(self):
        spec = importlib.util.spec_from_file_location('fixture_files', ROOT / 'plugins/miniclaw-files/__init__.py'); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        workspace = PROJECT / 'workspace'; workspace.mkdir(exist_ok=True)
        ctx = SimpleNamespace(get_config=lambda *args: str(workspace))
        result = lambda name, text='hello': json.loads(mod._save_artifact(ctx, {'name': name, 'content': text}))
        self.assertTrue(result('fixture.md')['success'])
        self.assertFalse(result('fixture.md')['success'])
        self.assertEqual((workspace / 'artifacts/fixture.md').read_text(), 'hello')
        downloaded = CLIENT.get('/api/miniclaw/artifacts/fixture.md')
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded.content, b'hello')
        self.assertIn('filename=', downloaded.headers['content-disposition'])
        self.assertEqual(CLIENT.get('/api/miniclaw/artifacts/code.py').status_code, 400)
        self.assertEqual(CLIENT.get('/api/miniclaw/artifacts/missing.md').status_code, 404)
        for name in ['../escape.md', 'code.py', '.env', 'a/b.txt']:
            self.assertFalse(result(name)['success'])

    def test_accepted_turn_display_failure_is_not_reported_as_rejected(self):
        from miniclaw_web.store import Store
        with patch.dict(server._methods, {'prompt.submit': lambda rid, p: server._ok(rid, {'status': 'streaming', 'user_row_id': 75})}), patch.object(Store, 'put', side_effect=OSError('fixture disk failure')):
            result = self.submit()
        self.assertNotIn('error', result)
        self.assertEqual(result['result']['status'], 'streaming')
        self.assertIn('请勿重复发送', result['result']['warning'])

    def test_skills_attribution_preserves_provider_usage_and_total(self):
        from miniclaw_web.context import attribute_skills
        payload = {'categories': [{'id': 'system_prompt', 'tokens': 1000}], 'context_used': 2345, 'estimated_total': 1000, 'context_source': 'provider_usage'}
        result = attribute_skills(payload, {'volatile': '<available_skills>\n- fixture: text\n</available_skills>'})
        self.assertGreater(next(c['tokens'] for c in result['categories'] if c['id'] == 'skills'), 0)
        self.assertEqual(sum(c['tokens'] for c in result['categories']), 1000)
        self.assertEqual(result['context_used'], 2345)
        self.assertEqual(result['estimated_total'], 1000)


if __name__ == '__main__':
    try:
        result = unittest.main(exit=False).result
    finally:
        from hermes_state_registry import close_all_under
        close_all_under(HOME)
        FIXTURE.cleanup()
    raise SystemExit(0 if result.wasSuccessful() else 1)
