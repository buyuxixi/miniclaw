import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from PIL import Image

from miniclaw_web.attachment_routes import routes
from miniclaw_web.attachment_uploads import AttachmentUploads, MAX_DOCUMENT, PART_SIZE, UploadError
from miniclaw_web.store import Store


class Documents:
    def __init__(self):
        self.jobs = {}
        self.calls = 0
        self.fail_once = False

    def enqueue(self, identifier, owner):
        self.calls += 1
        if self.fail_once:
            self.fail_once = False
            raise OSError('interrupted enqueue')
        self.jobs.setdefault((identifier, owner), {'parse_status': 'queued'})
        return self.status(identifier, owner)

    def status(self, identifier, owner):
        if (identifier, owner) not in self.jobs:
            raise ValueError('job missing')
        return self.jobs[identifier, owner]


class UploadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.store = Store(self.home)
        self.now = [1000.0]
        self.documents = Documents()
        self.uploads = AttachmentUploads(self.store, self.documents, clock=lambda: self.now[0])

    def tearDown(self):
        self.temp.cleanup()

    def part(self, upload, number, raw, owner='chat'):
        return self.uploads.put_part(upload['id'], owner, number, raw, hashlib.sha256(raw).hexdigest())

    def upload(self, name, raw, request='request-one'):
        item = self.uploads.init('chat', name, len(raw), request)
        for number, offset in enumerate(range(0, len(raw), self.uploads.part_size)):
            self.part(item, number, raw[offset:offset + self.uploads.part_size])
        return item

    def assert_error(self, status, function, *args):
        with self.assertRaises(UploadError) as error:
            function(*args)
        self.assertEqual(error.exception.status, status)

    def test_large_text_resumes_out_of_order_after_store_reopen_and_keeps_original(self):
        raw = b'a' * PART_SIZE + b'final row\n'
        item = self.uploads.init('chat', 'large.md', len(raw), 'resume')
        self.part(item, 1, raw[PART_SIZE:])
        self.uploads = AttachmentUploads(Store(self.home), self.documents, clock=lambda: self.now[0])
        resumed = self.uploads.init('chat', 'large.md', len(raw), 'resume')
        self.assertEqual(resumed['id'], item['id'])
        self.assertEqual(resumed['parts'][0]['part_no'], 1)
        self.part(item, 0, raw[:PART_SIZE])
        result = self.uploads.complete(item['id'], 'chat')
        record = self.store.get('attachments', result['id'], 'chat')
        self.assertEqual(result['kind'], 'document')
        self.assertIsNone(record['text'])
        self.assertEqual(Path(record['path']).read_bytes(), raw)
        self.assertEqual(record['object_id'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(self.uploads.status(item['id'], 'chat')['state'], 'completed')

    def test_request_and_part_retries_are_idempotent_and_content_conflicts_rejected(self):
        item = self.uploads.init('chat', 'facts.csv', 4, 'stable-request')
        self.assert_error(409, self.uploads.init, 'chat', 'facts.csv', 5, 'stable-request')
        self.part(item, 0, b'1,2\n')
        self.part(item, 0, b'1,2\n')
        self.assertEqual(len(self.uploads.status(item['id'], 'chat')['parts']), 1)
        self.assert_error(409, self.part, item, 0, b'3,4\n')
        first = self.uploads.complete(item['id'], 'chat')
        self.documents.jobs[(first['id'], 'chat')] = {'parse_status': 'ready', 'chunks': 1}
        second = self.uploads.complete(item['id'], 'chat')
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(second['parse_status'], 'ready')
        self.assertEqual(self.documents.calls, 1)
        status = self.uploads.init('chat', 'facts.csv', 4, 'stable-request')
        self.assertEqual(status['parts'], [{'part_no': 0, 'size': 4, 'sha256': hashlib.sha256(b'1,2\n').hexdigest()}])
        self.assertFalse((self.uploads.root / item['id']).exists())
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM attachments').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM media_revisions').fetchone()[0], 1)
        self.assertEqual(self.uploads.status(item['id'], 'chat')['attachment']['parse_status'], 'ready')

    def test_every_read_and_mutation_checks_owner(self):
        item = self.uploads.init('chat', 'facts.txt', 3, 'owned')
        for operation, args in (
            (self.uploads.status, (item['id'], 'other')),
            (self.uploads.complete, (item['id'], 'other')),
            (self.uploads.cancel, (item['id'], 'other')),
            (self.uploads.put_part, (item['id'], 'other', 0, b'abc', hashlib.sha256(b'abc').hexdigest())),
        ):
            self.assert_error(404, operation, *args)
        self.assertEqual(self.uploads.status(item['id'], 'chat')['state'], 'uploading')

    def test_type_size_name_and_request_limits(self):
        for name, size in [('old.xls', 1), ('old.doc', 1), ('../facts.txt', 1), ('C:secret.csv', 1),
                           ('empty.pdf', 0), ('large.png', 5 * 1024 * 1024 + 1),
                           ('large.pdf', MAX_DOCUMENT + 1), ('facts.txt', True)]:
            self.assert_error(400, self.uploads.init, 'chat', name, size, 'invalid')
        self.assert_error(400, self.uploads.init, 'chat', 'facts.txt', 1, 'bad request')
        largest = self.uploads.init('chat', 'largest.pdf', MAX_DOCUMENT, 'largest')
        self.assertEqual(largest['size'], 50 * 1024 * 1024)

    def test_active_reservation_is_released_by_cancel_and_expiry_cleans_staging(self):
        self.uploads.max_active, self.uploads.max_active_bytes = 1, 10
        item = self.uploads.init('chat', 'one.txt', 10, 'one')
        self.assert_error(429, self.uploads.init, 'chat', 'two.txt', 1, 'two')
        self.part(item, 0, b'0123456789')
        self.uploads.cancel(item['id'], 'chat')
        self.assertFalse((self.uploads.root / item['id']).exists())
        next_item = self.uploads.init('chat', 'two.txt', 1, 'two')
        self.part(next_item, 0, b'a')
        self.now[0] += self.uploads.ttl + 1
        self.assertEqual(self.uploads.cleanup(), 1)
        self.assertEqual(self.uploads.status(next_item['id'], 'chat')['state'], 'expired')
        self.assertFalse((self.uploads.root / next_item['id']).exists())
        self.assert_error(409, self.uploads.complete, next_item['id'], 'chat')

    def test_missing_parts_invalid_checksum_and_disk_corruption_never_publish(self):
        item = self.uploads.init('chat', 'facts.txt', 4, 'incomplete')
        self.assert_error(409, self.uploads.complete, item['id'], 'chat')
        self.assert_error(400, self.uploads.put_part, item['id'], 'chat', 0, b'abcd', '0' * 64)
        self.assert_error(400, self.part, item, 1, b'a')
        self.assert_error(400, self.part, item, 0, b'a')
        self.part(item, 0, b'abcd')
        part = next((self.uploads.root / item['id']).glob('*.part'))
        part.write_bytes(b'fake')
        self.assert_error(409, self.uploads.complete, item['id'], 'chat')
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM file_objects').fetchone()[0], 0)

    def test_fake_document_and_binary_text_rejected_before_object_publish(self):
        for number, (name, raw) in enumerate([('fake.pdf', b'not PDF'), ('fake.docx', b'not Office'),
                                              ('broken.txt', b'\xff'), ('binary.csv', b'a\0b')]):
            item = self.upload(name, raw, f'fake-{number}')
            self.assert_error(400, self.uploads.complete, item['id'], 'chat')
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM file_objects').fetchone()[0], 0)

    def test_small_utf8_text_crosses_part_boundaries_without_becoming_document(self):
        self.uploads.part_size = 4
        raw = '中文𐀀资料'.encode()
        item = self.upload('facts.md', raw)
        result = self.uploads.complete(item['id'], 'chat')
        self.assertEqual(result['kind'], 'text')
        self.assertEqual(self.store.get('attachments', result['id'], 'chat')['text'], raw.decode())
        self.assertEqual(self.documents.calls, 1)

    def test_office_type_and_image_content_are_verified(self):
        for extension, required in (('docx', 'word/document.xml'), ('xlsx', 'xl/workbook.xml')):
            raw = io.BytesIO()
            with zipfile.ZipFile(raw, 'w') as package:
                package.writestr('[Content_Types].xml', '<Types/>')
                package.writestr(required, '<document/>')
            item = self.upload(f'facts.{extension}', raw.getvalue(), extension)
            self.assertEqual(self.uploads.complete(item['id'], 'chat')['kind'], 'document')
        raw = io.BytesIO()
        Image.new('RGB', (8, 8), 'red').save(raw, format='PNG')
        item = self.upload('image.png', raw.getvalue(), 'image')
        self.assertEqual(self.uploads.complete(item['id'], 'chat')['kind'], 'image')
        spoof = self.upload('spoof.jpg', raw.getvalue(), 'spoof')
        self.assert_error(400, self.uploads.complete, spoof['id'], 'chat')

    def test_parser_enqueue_interruption_keeps_attachment_and_retry_repairs_job(self):
        item = self.upload('facts.csv', b'a,b\n1,2\n')
        self.documents.fail_once = True
        with self.assertRaises(OSError):
            self.uploads.complete(item['id'], 'chat')
        self.assertEqual(self.store.get('attachments', item['id'], 'chat')['kind'], 'document')
        result = self.uploads.complete(item['id'], 'chat')
        self.assertEqual(result['parse_status'], 'queued')
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM attachments').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM media_revisions').fetchone()[0], 1)

    def test_completed_transfer_feeds_real_csv_parser_and_exact_calculation(self):
        from miniclaw_web.documents import DocumentService
        documents = DocumentService(self.store, autostart=False)
        try:
            self.uploads.documents = documents
            item = self.upload('sales.csv', b'product,quantity\na,2\nb,3\n')
            result = self.uploads.complete(item['id'], 'chat')
            self.assertEqual(result['parse_status'], 'queued')
            documents._execute(item['id'], 'chat')
            saved = self.uploads.status(item['id'], 'chat')['attachment']
            self.assertEqual(saved['parse_status'], 'ready')
            computed = documents.aggregate(item['id'], 'chat', operation='sum', column='quantity')
            self.assertTrue(computed['complete'])
            self.assertEqual(float(computed['groups'][0]['value']), 5)
        finally:
            documents.shutdown()

    def test_parser_queue_full_preserves_original_and_completion_retry_does_not_duplicate(self):
        from miniclaw_web.documents import DocumentService
        documents = DocumentService(self.store, autostart=False)
        try:
            self.uploads.documents = documents
            queued = []
            for number in range(100):
                item = self.upload(f'queued-{number}.csv', b'a,b\n1,2\n', f'queue-{number}')
                queued.append(self.uploads.complete(item['id'], 'chat')['id'])
            last = self.upload('last.csv', b'a,b\n3,4\n', 'queue-overflow')
            with self.assertRaises(ValueError):
                self.uploads.complete(last['id'], 'chat')
            record = self.store.get('attachments', last['id'], 'chat')
            self.assertEqual(record['object_id'], hashlib.sha256(b'a,b\n3,4\n').hexdigest())
            with self.store.connect() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM attachments').fetchone()[0], 101)
                self.assertEqual(db.execute('SELECT count(*) FROM document_parses').fetchone()[0], 100)
            documents._execute(queued[0], 'chat')
            result = self.uploads.complete(last['id'], 'chat')
            self.assertEqual(result['id'], last['id'])
            self.assertEqual(result['parse_status'], 'queued')
            with self.store.connect() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM attachments').fetchone()[0], 101)
                self.assertEqual(db.execute('SELECT count(*) FROM media_revisions').fetchone()[0], 101)
                self.assertEqual(db.execute('SELECT count(*) FROM document_parses').fetchone()[0], 101)
        finally:
            documents.shutdown()

    def test_real_http_auth_origin_checksum_limits_and_cross_owner(self):
        from hermes_cli.web_server import _SESSION_TOKEN, auth_middleware
        app = FastAPI()
        app.middleware('http')(auth_middleware)

        async def body(request: Request):
            value = await request.json()
            if not isinstance(value, dict):
                raise HTTPException(400)
            return value

        app.include_router(routes(self.uploads, body), prefix='/api/miniclaw')
        client = TestClient(app)
        path = '/api/miniclaw/uploads'
        payload = {'owner': 'chat', 'name': 'facts.csv', 'size': 4, 'request_id': 'http'}
        self.assertEqual(client.post(path, json=payload).status_code, 401)
        client.headers['Authorization'] = 'Bearer ' + _SESSION_TOKEN
        self.assertEqual(client.post(path, json=payload, headers={'Origin': 'https://evil.example'}).status_code, 403)
        response = client.post(path, json=payload)
        self.assertEqual(response.status_code, 200)
        identifier = response.json()['id']
        self.assertEqual(client.get(f'{path}/{identifier}?owner=other').status_code, 404)
        part_path = f'{path}/{identifier}/parts/0?owner=chat'
        self.assertEqual(client.put(part_path, content=b'1,2\n').status_code, 400)
        self.assertEqual(client.put(part_path, content=b'x' * (PART_SIZE + 1)).status_code, 413)
        checksum = hashlib.sha256(b'1,2\n').hexdigest()
        self.assertEqual(client.put(part_path, content=b'1,2\n', headers={'X-Part-SHA256': checksum}).status_code, 200)
        result = client.post(f'{path}/{identifier}/complete', json={'owner': 'chat'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['parse_status'], 'queued')
        self.assertEqual(client.delete(f'{path}/{identifier}?owner=chat').status_code, 409)

    def test_http_initialization_persists_owner_before_creating_upload(self):
        calls = []

        def persist_owner(owner):
            with self.store.connect() as db:
                calls.append((owner, db.execute('SELECT count(*) FROM attachment_uploads').fetchone()[0]))

        async def body(request):
            return await request.json()

        app = FastAPI()
        app.include_router(routes(self.uploads, body, persist_owner=persist_owner))
        client = TestClient(app)
        payload = {'owner': 'chat', 'name': 'facts.csv', 'size': 4, 'request_id': 'persist-session'}
        self.assertEqual(client.post('/uploads', json={'owner': 'chat'}).status_code, 400)
        self.assertEqual(calls, [])
        result = client.post('/uploads', json=payload)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(calls, [('chat', 0)])
        self.assertEqual(self.uploads.status(result.json()['id'], 'chat')['state'], 'uploading')

    def test_http_owner_persistence_failure_never_creates_upload(self):
        async def body(request):
            return await request.json()

        for exception, status in ((UploadError(404, 'session missing'), 404),
                                  (OSError('session database unavailable'), 503)):
            with self.subTest(status=status):
                def persist_owner(owner):
                    raise exception

                app = FastAPI()
                app.include_router(routes(self.uploads, body, persist_owner=persist_owner))
                client = TestClient(app)
                payload = {'owner': 'chat', 'name': 'facts.csv', 'size': 4, 'request_id': 'persist-failure'}
                self.assertEqual(client.post('/uploads', json=payload).status_code, status)
                with self.store.connect() as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM attachment_uploads').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
