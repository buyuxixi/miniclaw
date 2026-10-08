"""Real SRT compiler and plugin file boundaries, no model or personal media."""
import base64
import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'hermes-agent')]
from miniclaw_web.overlay import compile_overlay, parse_srt, set_store, TOOL
from miniclaw_web.attachments import upload
from miniclaw_web.store import Store, digest
from tui_gateway import server

SRT = '10\n00:00:00,250 --> 00:00:02,500\n这是一个陶瓷杯。\n\n11\n00:00:03,000 --> 00:00:05,500\n每天一杯，\n慢一点。\n'
CARDS = [{'id': 'card-1', 'kind': 'punch-pill', 'cue_start': 1, 'cue_end': 1, 'params': {'text': '陶瓷杯'}},
         {'id': 'card-2', 'kind': 'quote-lockup', 'cue_start': 2, 'cue_end': 2, 'params': {'quote': '每天一杯，|慢一点。'}}]


class OverlayCompiler(unittest.TestCase):
    def test_real_srt_indices_multiline_bom_and_exact_timestamps(self):
        cues = parse_srt('\ufeff' + SRT.replace('\n', '\r\n'))
        self.assertEqual([c['cue'] for c in cues], [1, 2])
        self.assertEqual([c['original_index'] for c in cues], [10, 11])
        doc = compile_overlay(SRT, CARDS)
        self.assertEqual([(c['start'], c['end']) for c in doc['cards']], [(.25, 2.5), (3, 5.5)])
        self.assertEqual(doc['cards'][1]['params']['author'], '')
        self.assertNotIn('cue_start', doc['cards'][0])

    def test_rejects_bad_blocks_duplicates_overlap_clock_and_nonfinite_syntax(self):
        cases = ['', '1\nNaN --> Infinity\ntext', SRT + '\nBAD', SRT.replace('11\n', '10\n'),
                 SRT.replace('00:00:03,000', '00:00:01,000'), SRT.replace('00:00:02,500', '00:00:00,200'),
                 SRT.replace('00:00:05,500', '00:60:05,500'), 'x' * 65537]
        for text in cases:
            with self.subTest(text=text[:40]), self.assertRaises(ValueError):
                parse_srt(text)

    def test_rejects_unknown_media_timestamps_facts_ranges_and_duplicate_cards(self):
        invalid = []
        for change in [{'start': 0}, {'kind': 'unknown'}, {'cue_end': 3}, {'cue_start': True}, {'cue_start': -1},
                       {'params': {'text': '保温12小时'}}, {'params': {'text': '陶瓷杯', 'src': 'https://example.com/a.mp4'}},
                       {'params': {'text': '陶瓷杯', 'accent': 'url(x)'}}, {'params': {'text': '陶瓷杯', 'position': 'center'}}]:
            card = {**copy.deepcopy(CARDS[0]), **change}; invalid.append([card])
        invalid.extend([[], CARDS * 2, [CARDS[0], {**CARDS[1], 'cue_start': 1}]])
        for cards in invalid:
            with self.subTest(cards=cards), self.assertRaises(ValueError):
                compile_overlay(SRT, cards)

    def test_type_shift_defaults_and_duration_bounds(self):
        card = {'id': 'ending', 'kind': 'type-shift', 'cue_start': 2, 'cue_end': 2, 'params': {'lines': '*每天一杯，|慢一点。'}}
        self.assertEqual(compile_overlay(SRT, [card])['cards'][0]['params']['shiftAtMs'], 1600)
        for invalid in (float('nan'), True, 10000, 4000):
            card['params']['shiftAtMs'] = invalid
            with self.assertRaises(ValueError): compile_overlay(SRT, [card])


class OverlayTool(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name); self.workspace = self.root / 'workspace'; self.workspace.mkdir()
        self.store = Store(self.root / 'home'); set_store(self.store)
        self.source = upload(self.store, 'owner', 'demo.srt', base64.b64encode(SRT.encode()).decode())
        self.session = {'session_key': 'owner', 'agent': SimpleNamespace(tools=[{'function': {'name': TOOL}}]),
                        'miniclaw_overlay_turn': {self.source['id']: digest(SRT)}}
        server._sessions['overlay-test'] = self.session
        spec = importlib.util.spec_from_file_location('overlay_test_plugin', ROOT / 'plugins/miniclaw-files/__init__.py')
        plugin = importlib.util.module_from_spec(spec); spec.loader.exec_module(plugin)
        registered = {}
        plugin.register_overlay(SimpleNamespace(register_tool=lambda **kw: registered.update(kw), get_config=lambda key, default: str(self.workspace)))
        self.handler = registered['handler']

    def tearDown(self):
        server._sessions.pop('overlay-test', None); set_store(None); self.temp.cleanup()

    def invoke(self, **changes):
        args = dict(source_id=self.source['id'], name='demo.json', cards=CARDS); args.update(changes)
        return json.loads(self.handler(args, session_id='owner'))

    def test_real_compile_exclusive_file_creation_and_no_bypass(self):
        saved = self.invoke(); self.assertTrue(saved['success'], saved)
        raw = (self.workspace / 'artifacts/demo.json').read_bytes()
        self.assertEqual(json.loads(raw)['cards'][0]['start'], .25)
        self.assertFalse(self.invoke()['success']); self.assertEqual((self.workspace / 'artifacts/demo.json').read_bytes(), raw)
        for name in ('../escape.json', 'escape.txt', 'x.json.py'):
            self.assertFalse(self.invoke(name=name)['success'])
        self.assertFalse((self.workspace / 'escape.json').exists())

    def test_foreign_stale_previous_turn_and_missing_tool_are_rejected(self):
        foreign = upload(self.store, 'other', 'demo.srt', base64.b64encode(SRT.encode()).decode())
        self.session['miniclaw_overlay_turn'][foreign['id']] = digest(SRT)
        self.assertFalse(self.invoke(source_id=foreign['id'])['success'])
        self.session['miniclaw_overlay_turn'][self.source['id']] = 'stale'
        self.assertFalse(self.invoke()['success'])
        self.session['miniclaw_overlay_turn'] = {}
        self.assertFalse(self.invoke()['success'])
        self.session['agent'].tools = []
        self.assertFalse(self.invoke()['success'])
        self.assertFalse((self.workspace / 'artifacts').exists())


if __name__ == '__main__': unittest.main()
