"""Shared-state correctness and bounded decision calls, without paid services."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import unittest

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from miniclaw_web.canvas import Conflict
from miniclaw_web.creation import Creation
from miniclaw_web.decisions import JevConfig, JevDecisions
from miniclaw_web.store import Store


def good_response(request):
    body = json.loads(request.content)
    answers = {}
    for key, q in body['questions'].items():
        if q['type'] == 'noul':
            answers[key] = dict(type='noul', noul=.99)
        else:
            choice = {'action': 'replace_visual', 'target': 'shot_02', 'fact_check': 'clear'}[key]
            answers[key] = dict(type='choice', choice=choice, confidence=.99,
                                probabilities={k: 1 if k == choice else 0 for k in q['criteria']})
    return httpx.Response(200, json=dict(model='jev-1.13.0', answers=answers, usage=dict(input_tokens=900, output_tokens=100)))


class CreationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.creation = Creation(self.store)
        self.p = self.creation.create_sample()
        self.serial = 0

    def tearDown(self):
        self.temp.cleanup()

    def command(self, action, args, entrance='director'):
        self.serial += 1
        data = dict(request_id=f'command-{self.serial:04}', revision=self.p['revision'], entrance=entrance, action=action, args=args)
        result = self.creation.command(self.p['id'], data)
        self.p = result['project']
        return result, data

    def ready(self):
        result, _ = self.command('propose', dict(shot_id='shot_02', instruction='只改第二段为瓶口特写', decision_id=None), 'chat')
        prop = result['receipt']['detail']['proposal_id']
        self.command('candidate', dict(proposal_id=prop, media='macro.png'), 'canvas')
        return prop

    def test_three_entrances_only_change_second_shot_and_recover(self):
        untouched = copy.deepcopy([self.p['shots'][0], self.p['shots'][2]])
        original = self.p['shots'][1]['adopted']
        prop = self.ready()
        self.assertEqual(self.p['shots'][1]['adopted'], original)
        self.command('adopt', dict(proposal_id=prop), 'director')
        reread = Creation(Store(self.temp.name)).get(self.p['id'])
        self.assertEqual([reread['shots'][0], reread['shots'][2]], untouched)
        self.assertNotEqual(reread['shots'][1]['adopted'], original)
        self.assertEqual({e['entrance'] for e in reread['events']}, {'chat', 'canvas', 'director'})
        revision = reread['shots'][1]['revision']
        self.command('restore', dict(shot_id='shot_02', version_id=original), 'chat')
        self.assertEqual(self.p['shots'][1]['adopted'], original)
        self.assertGreater(self.p['shots'][1]['revision'], revision)

    def test_replay_is_idempotent_but_changed_payload_rejected(self):
        _, data = self.command('message', dict(surface='chat', text='只讨论，不采用'))
        result = self.creation.command(self.p['id'], data)
        self.assertTrue(result['replayed'])
        self.assertEqual(len(result['project']['conversations']['chat']), 1)
        data['args']['text'] = '另一条'
        with self.assertRaises(ValueError): self.creation.command(self.p['id'], data)

    def test_conflicting_clients_do_not_overwrite_and_cross_project_ids_fail(self):
        old = self.p['revision']
        self.command('message', dict(surface='director', text='先保留旧版'))
        with self.assertRaises(Conflict):
            self.creation.command(self.p['id'], dict(request_id='other-client', revision=old, entrance='canvas', action='restore', args={}))
        with self.assertRaises(ValueError): self.command('propose', dict(shot_id='foreign', instruction='改图', decision_id=None))
        self.assertEqual(self.creation.get(self.p['id'])['revision'], self.p['revision'])

    def test_late_candidate_cannot_replace_newer_adoption(self):
        first, second = self.ready(), self.ready()
        self.command('adopt', dict(proposal_id=first))
        before = copy.deepcopy(self.p)
        with self.assertRaises(Conflict): self.command('adopt', dict(proposal_id=second))
        self.assertEqual(self.creation.get(self.p['id']), before)
        self.assertEqual(next(p for p in before['proposals'] if p['id'] == second)['status'], 'ready')

    def test_decision_is_advisory_and_cached_across_restart(self):
        calls = []
        def handler(request):
            calls.append(request)
            return good_response(request)
        transport = httpx.MockTransport(handler)
        service = JevDecisions(self.store, JevConfig(key='private-test-key'), transport)
        result = service.evaluate('sample', 'request-001', '只改第二段', self.p)
        self.assertEqual(result['status'], 'suggested')
        self.assertEqual(self.creation.get(self.p['id']), self.p)
        replay = JevDecisions(self.store, JevConfig(key='private-test-key'), transport).evaluate('sample', 'request-001', '只改第二段', self.p)
        self.assertEqual(replay, result)
        self.assertEqual(len(calls), 1)
        self.assertNotIn('private-test-key', json.dumps(result))

    def test_timeout_never_replays_and_preserves_budget(self):
        calls = []
        def timeout(request):
            calls.append(1)
            raise httpx.ReadTimeout('private provider data')
        service = JevDecisions(self.store, JevConfig(key='secret'), httpx.MockTransport(timeout))
        result = service.evaluate('sample', 'timeout-001', '改第二段', self.p)
        self.assertEqual(result['status'], 'unknown')
        self.assertGreater(service.ledger('sample')['reserved_usd'], 0)
        service.evaluate('sample', 'timeout-001', '改第二段', self.p)
        self.assertEqual(len(calls), 1)
        self.assertNotIn('private', json.dumps(result))

    def test_concurrent_reservations_respect_call_limit(self):
        service = JevDecisions(self.store, JevConfig(key='secret', max_calls=1), httpx.MockTransport(good_response))
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda i: service.evaluate('scope', f'request-{i}', '改第二段', self.p), (1, 2)))
        self.assertEqual(sorted(r['status'] for r in results), ['budget_exhausted', 'suggested'])
        self.assertEqual(service.ledger('scope')['calls'], 1)

    def test_malformed_or_low_confidence_response_never_becomes_action(self):
        for index, bad in enumerate(('unknown_choice', 'nan', 'low', 'error_body', 'array_probabilities', 'array_answer')):
            def handler(request):
                if bad == 'error_body': return httpx.Response(401, text='secret-key-should-not-escape')
                raw = good_response(request).json()
                if bad == 'unknown_choice': raw['answers']['target']['choice'] = 'foreign-shot'
                if bad == 'nan': raw['answers']['target']['confidence'] = -1
                if bad == 'low': raw['answers']['target']['confidence'] = .1
                if bad == 'array_probabilities': raw['answers']['target']['probabilities'] = list(raw['answers']['target']['probabilities'])
                if bad == 'array_answer': raw['answers']['target'] = []
                return httpx.Response(200, json=raw)
            service = JevDecisions(self.store, JevConfig(key='secret'), httpx.MockTransport(handler))
            result = service.evaluate('validation', f'request-{index}', '改第二段', self.p)
            self.assertEqual(result['status'], 'needs_review' if bad == 'low' else 'unavailable')
            self.assertNotIn('secret-key', json.dumps(result))
        self.assertEqual(self.creation.get(self.p['id']), self.p)


if __name__ == '__main__': unittest.main(verbosity=2)
