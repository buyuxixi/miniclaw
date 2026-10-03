"""Image execution, ownership, job lifecycle and provider wire contract."""
import base64
import io
import json
import os
import sys
import tempfile
import unittest
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'hermes-agent')]
import httpx
from PIL import Image
from miniclaw_web.store import Store
from miniclaw_web.attachments import upload
from miniclaw_web.images import ImageJobs, image_tool, local_edit, set_service, validate
from miniclaw_web.image_provider import checked_endpoint, checked_result_url, edit_image


def fixture():
    stream = io.BytesIO()
    image = Image.new('RGBA', (120, 80), (80, 120, 160, 140))
    image.putpixel((0, 0), (220, 10, 20, 0)); image.save(stream, 'PNG')
    return stream.getvalue()


class HeldExecutor:
    def __init__(self): self.calls = []
    def submit(self, function, *args):
        future = Future(); self.calls.append((function, args, future)); return future
    def run(self):
        function, args, future = self.calls.pop(0)
        function(*args); future.set_result(None)


class ImageEditing(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name))
        self.source = upload(self.store, 'owner-a', 'original.png', base64.b64encode(fixture()).decode())
        self.executor = HeldExecutor(); self.jobs = ImageJobs(self.store, self.executor)

    def tearDown(self): self.temp.cleanup()

    def submit(self, **kwargs):
        return self.jobs.submit('owner-a', kwargs.get('source', self.source['id']), kwargs.get('operation', 'adjust'), kwargs.get('params', {'brightness': .25}), kwargs.get('request', 'fixture-request-one'))

    def test_real_pixels_alpha_dimensions_and_source_are_preserved(self):
        before = fixture()
        adjusted = Image.open(io.BytesIO(local_edit(before, 'adjust', {'brightness': .25})))
        self.assertEqual(adjusted.size, (120, 80)); self.assertEqual(adjusted.getpixel((2, 2)), (100, 150, 200, 140))
        for op, params, size in [('crop', {'ratio': '1:1'}, (80, 80)), ('rotate', {'angle': 90}, (80, 120)), ('resize', {'width': 64, 'height': 32}, (64, 32))]:
            self.assertEqual(Image.open(io.BytesIO(local_edit(before, op, params))).size, size)
        flipped = Image.open(io.BytesIO(local_edit(before, 'flip', {'direction': 'horizontal'})))
        self.assertEqual(flipped.getpixel((119, 0)), (220, 10, 20, 0))
        self.assertEqual(before, fixture())

    def test_validation_rejects_nonfinite_unknown_and_outside_crop(self):
        cases = [('adjust', {'brightness': float('nan')}), ('adjust', {'brightness': True}), ('adjust', {'brightness': 2}),
                 ('resize', {'width': 100000, 'height': 64}), ('rotate', {'angle': 45}), ('crop', {'ratio': 'bad'}),
                 ('crop', {'ratio': '1:1', 'rect': {}}), ('ai_edit', {'prompt': ''}), ('adjust', {'path': 'secret'})]
        for op, params in cases:
            with self.assertRaises(ValueError, msg=str((op, params))): validate(op, params)
        with self.assertRaises(ValueError): local_edit(fixture(), 'crop', {'rect': {'x': 100, 'y': 0, 'width': 80, 'height': 50}})

    def test_owner_idempotency_and_immutable_version_chain(self):
        record = self.submit()
        self.assertEqual(record['state'], 'queued'); self.assertNotIn('owner', record)
        self.assertEqual(self.submit()['id'], record['id']); self.assertEqual(len(self.executor.calls), 1)
        with self.assertRaises(ValueError): self.submit(params={'brightness': .5})
        with self.assertRaises(ValueError): self.jobs.submit('owner-b', self.source['id'], 'adjust', {'brightness': .1}, 'cross-owner-request')
        self.executor.run(); done = self.jobs.get('owner-a', record['id'])
        self.assertEqual(done['state'], 'succeeded'); self.assertNotEqual(done['output']['id'], self.source['id'])
        with self.assertRaises(ValueError): self.jobs.get('owner-b', record['id'])
        self.assertEqual(self.jobs.history('')['jobs'], [])
        version = self.submit(source=done['output']['id'], operation='crop', params={'ratio': '1:1'}, request='fixture-request-two')
        self.executor.run()
        self.assertEqual(self.jobs.get('owner-a', version['id'])['root_id'], self.source['id'])
        self.assertEqual(Path(self.store.get('attachments', self.source['id'], 'owner-a')['path']).read_bytes(), fixture())
        self.assertEqual(len(self.store.images('owner-a')), 3)

    def test_busy_cancellation_failure_and_restart_do_not_replay(self):
        record = self.submit()
        with self.assertRaises(ValueError): self.submit(request='different-request')
        self.jobs.cancel('owner-a', record['id']); self.executor.run()
        self.assertEqual(self.jobs.get('owner-a', record['id'])['state'], 'canceled'); self.assertEqual(len(self.store.images('owner-a')), 1)
        bad = self.submit(operation='crop', params={'rect': {'x': 110, 'y': 0, 'width': 80, 'height': 50}}, request='bad-crop-request')
        self.executor.run(); self.assertEqual(self.jobs.get('owner-a', bad['id'])['state'], 'failed')
        pending = self.submit(request='restart-request')
        restarted = ImageJobs(self.store, HeldExecutor())
        self.assertEqual(restarted.get('owner-a', pending['id'])['state'], 'failed')
        self.assertEqual(restarted.executor.calls, [])
        self.executor.run()
        self.assertEqual(restarted.get('owner-a', pending['id'])['state'], 'failed')
        self.assertEqual(len(self.store.images('owner-a')), 1)

    def test_cancel_after_cloud_submit_discards_result_without_overwriting_state(self):
        with patch.dict(os.environ, {'DASHSCOPE_API_KEY': 'fixture-secret'}):
            record = self.submit(operation='ai_edit', params={'prompt': 'test'}, request='cloud-cancel-request')
        def cloud(*args):
            self.jobs.cancel('owner-a', record['id'])
            return fixture(), 'provider-request'
        with patch('miniclaw_web.images.edit_image', side_effect=cloud): self.executor.run()
        self.assertEqual(self.jobs.get('owner-a', record['id'])['state'], 'canceled')
        self.assertEqual(len(self.store.images('owner-a')), 1)

    def test_tool_owner_comes_from_trusted_agent_context_and_loaded_schema(self):
        from tui_gateway import server
        session = {'session_key': 'owner-a', 'agent': SimpleNamespace(session_id='trusted-agent', tools=[{'function': {'name': name}} for name in ('miniclaw_image_list', 'miniclaw_edit_image', 'miniclaw_image_status')])}
        set_service(self.jobs)
        with patch.dict(server._sessions, {'fixture-image-session': session}, clear=True):
            result = json.loads(image_tool('miniclaw_image_list', {}, 'trusted-agent'))
            self.assertEqual(result['images'][0]['id'], self.source['id'])
            self.assertFalse(json.loads(image_tool('miniclaw_image_list', {'owner': 'owner-a'}, 'trusted-agent'))['success'])
            self.assertFalse(json.loads(image_tool('miniclaw_image_list', {}, 'untrusted-agent'))['success'])
            session['agent'].tools = []
            self.assertFalse(json.loads(image_tool('miniclaw_image_list', {}, 'trusted-agent'))['success'])


class ProviderContract(unittest.TestCase):
    def test_actual_http_payload_and_download_never_forwards_credentials(self):
        seen = []
        def handler(request):
            seen.append(request)
            if request.method == 'POST':
                return httpx.Response(200, json={'request_id': 'remote-42', 'output': {'choices': [{'message': {'content': [{'image': 'https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/test.png?signature=fixture'}]}}]}})
            return httpx.Response(200, content=fixture())
        transport = httpx.MockTransport(handler)
        factory = lambda **kwargs: httpx.Client(transport=transport, **kwargs)
        with patch.dict(os.environ, {'DASHSCOPE_API_KEY': 'fixture-secret', 'MINICLAW_IMAGE_BASE_URL': 'https://dashscope.aliyuncs.com', 'MINICLAW_IMAGE_MODEL': 'qwen-image-edit-max'}):
            result, request_id = edit_image(fixture(), 'image/png', '只改背景', factory)
        self.assertEqual(request_id, 'remote-42'); self.assertEqual(Image.open(io.BytesIO(result)).size, (120, 80))
        self.assertEqual(seen[0].headers['Authorization'], 'Bearer fixture-secret')
        self.assertNotIn('Authorization', seen[1].headers)
        payload = json.loads(seen[0].content)
        self.assertEqual(payload['parameters']['n'], 1)
        self.assertEqual(payload['input']['messages'][0]['content'][1]['text'], '只改背景')
        self.assertTrue(payload['input']['messages'][0]['content'][0]['image'].startswith('data:image/png;base64,'))

    def test_url_errors_missing_key_and_remote_failure_are_bounded(self):
        for url in ['http://127.0.0.1/image', 'https://evil.example/a', 'https://dashscope.aliyuncs.com@evil.example/a', 'https://bucket.oss-cn-beijing.aliyuncs.com:444/a']:
            with self.assertRaises(ValueError): checked_result_url(url)
        for url in ['http://dashscope.aliyuncs.com', 'https://evil.example', 'https://dashscope.aliyuncs.com/other']:
            with self.assertRaises(ValueError): checked_endpoint(url)
        with patch.dict(os.environ, {'DASHSCOPE_API_KEY': ''}):
            with self.assertRaisesRegex(ValueError, '未配置'): edit_image(fixture(), 'image/png', 'test')
        transport = httpx.MockTransport(lambda request: httpx.Response(401, json={'message': 'fixture-secret should never leak'}))
        with patch.dict(os.environ, {'DASHSCOPE_API_KEY': 'fixture-secret'}):
            with self.assertRaises(ValueError) as error: edit_image(fixture(), 'image/png', 'test', lambda **kwargs: httpx.Client(transport=transport, **kwargs))
        self.assertNotIn('fixture-secret', str(error.exception))


if __name__ == '__main__': unittest.main()
