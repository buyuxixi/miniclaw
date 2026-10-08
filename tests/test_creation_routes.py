"""HTTP boundaries and restart recovery for the isolated creation sample."""
import json
import sqlite3
from pathlib import Path
import sys
import tempfile
import unittest

import httpx
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.creation_lab import make_app
from miniclaw_web.decisions import JevConfig


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name) / 'web'
        (self.folder / 'assets').mkdir(parents=True)
        (self.folder / 'index.html').write_text('__LAB_TOKEN__', encoding='utf-8')
        self.home = Path(self.temp.name) / 'home'
        self.app = make_app(self.folder, self.home, JevConfig(key=''))
        self.client = TestClient(self.app)
        self.headers = {'X-Lab-Token': self.app.state.token, 'Origin': 'http://testserver'}

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def command(self):
        return dict(request_id='route-test-001', revision=0, entrance='chat', action='message', args=dict(surface='chat', text='只讨论，不修改镜头'))

    def test_origin_token_host_and_size(self):
        self.assertEqual(self.client.post('/api/command', json=self.command()).status_code, 403)
        self.assertEqual(self.client.post('/api/command', json=self.command(), headers={**self.headers, 'Origin':'https://foreign.test'}).status_code, 403)
        self.assertEqual(self.client.get('/api/state', headers={'Host':'foreign.test'}).status_code, 400)
        self.assertEqual(self.client.post('/api/command', content='x'*16001, headers=self.headers).status_code, 413)
        self.assertEqual(self.client.post('/api/command', json=[], headers=self.headers).status_code, 400)
        self.assertEqual(self.client.get('/api/state').json()['project']['revision'], 0)

    def test_restart_idempotence_and_conflict(self):
        first = self.client.post('/api/command', json=self.command(), headers=self.headers)
        self.assertEqual(first.status_code, 200)
        app = make_app(self.folder, self.home, JevConfig(key=''))
        with TestClient(app) as second:
            headers = {'X-Lab-Token':app.state.token}
            replay = second.post('/api/command', json=self.command(), headers=headers).json()
            self.assertTrue(replay['replayed'])
            self.assertEqual(len(replay['project']['conversations']['chat']), 1)
            stale = {**self.command(), 'request_id':'new-operation'}
            self.assertEqual(second.post('/api/command', json=stale, headers=headers).status_code, 409)

    def test_unavailable_decision_and_malformed_output(self):
        payload = dict(request_id='decision-001', revision=0, instruction='只改第二镜头', selected='shot_02')
        result = self.client.post('/api/decision', json=payload, headers=self.headers).json()
        self.assertEqual(result['status'], 'unavailable')
        self.app.state.decisions.config = JevConfig(key='secret-test')
        self.app.state.decisions.transport = httpx.MockTransport(lambda r: httpx.Response(200, json={'answers':{'action':[]}}))
        result = self.client.post('/api/decision', json={**payload, 'request_id':'decision-002'}, headers=self.headers).json()
        self.assertEqual(result['reason'], 'invalid_response')
        self.assertNotIn('secret-test', json.dumps(result))
        self.assertEqual(self.client.get('/api/state').json()['project']['revision'], 0)

    def test_interrupted_decision_not_replayed(self):
        service = self.app.state.decisions
        service.config = JevConfig(key='test')
        service.transport = httpx.MockTransport(lambda r: httpx.Response(500))
        snapshot = self.app.state.creation.get('form-01')
        result = service.evaluate('scope', 'interrupted-001', '改第二段', snapshot)
        with service.store.connect() as db:
            result.update(status='pending', created=0)
            db.execute('UPDATE creation_decisions SET data=?', (json.dumps(result),))
        service.transport = httpx.MockTransport(lambda r: self.fail('must not submit again'))
        saved = service.evaluate('scope', 'interrupted-001', '改第二段', snapshot)
        self.assertEqual(saved['status'], 'unknown')
        self.assertEqual(saved['reason'], 'interrupted')
        self.assertGreater(service.ledger('scope')['reserved_usd'], 0)

    def test_cost_budget_rejects_before_provider_call(self):
        service = self.app.state.decisions
        service.config = JevConfig(key='test', budget_micro_usd=1)
        service.transport = httpx.MockTransport(lambda r: self.fail('over-budget request'))
        result = service.evaluate('scope', 'budget-test-001', '改第二段', self.app.state.creation.get('form-01'))
        self.assertEqual(result['status'], 'budget_exhausted')
        self.assertEqual(service.ledger('scope')['calls'], 0)

    def test_receipt_write_failure_rolls_back_project(self):
        creation = self.app.state.creation
        before = creation.get('form-01')
        with creation.store.connect() as db:
            db.execute("CREATE TRIGGER fail_receipt BEFORE INSERT ON creation_operations BEGIN SELECT RAISE(ABORT, 'simulated storage failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            creation.command('form-01', self.command())
        self.assertEqual(creation.get('form-01'), before)
        with creation.store.connect() as db:
            db.execute('DROP TRIGGER fail_receipt')
        self.assertEqual(creation.command('form-01', self.command())['project']['revision'], 1)


if __name__ == '__main__': unittest.main(verbosity=2)
