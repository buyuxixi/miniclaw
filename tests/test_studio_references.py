"""Canvas citations carry real pixels, preserve snapshots, and never open editors."""
import base64
import copy
import io
import unittest
from unittest.mock import patch

from PIL import Image
from tests import test_studio


class ReferenceTests(unittest.TestCase):
    setUp = test_studio.StudioTests.setUp
    tearDown = test_studio.StudioTests.tearDown
    # Reuse the isolated real store/canvas fixture, not its inherited test suite.
    def context(self, ids, **overrides):
        return self.studio.context({'workspace': self.workspace, 'revision': 1, 'target': '', 'references': ids, **overrides}, 'owner-one')

    def test_shot_and_image_have_real_ordered_pixels_without_editing(self):
        before = copy.deepcopy(self.canvas.get(self.meta['project']))
        with patch.object(self.studio, 'open', side_effect=AssertionError('reference must not edit')), patch.object(self.studio.precision, 'open', side_effect=AssertionError('reference must not edit')):
            context = self.context(['shot-one', 'image-one'])
        refs = context['references']
        self.assertEqual([r['kind'] for r in refs], ['shot', 'image'])
        self.assertEqual(len(context['_reference_paths']), 1)
        self.assertEqual(refs[0]['images'][0]['image_index'], 1)
        self.assertEqual(refs[0]['images'][0]['file'], refs[1]['images'][0]['file'])
        with Image.open(context['_reference_paths'][0]) as pixels:
            self.assertGreater(pixels.width, 0)
        self.assertEqual(self.canvas.get(self.meta['project']), before)
        self.assertEqual(self.canvas.jobs(self.meta['project']), [])

    def test_snapshot_stays_readable_after_the_node_changes(self):
        old = self.context(['image-one'])['references'][0]['images'][0]['file']
        raw = io.BytesIO(); Image.new('RGB', (8, 9), 'blue').save(raw, format='PNG')
        state = copy.deepcopy(self.record['state'])
        state['assets'][0]['file'] = 'data:image/png;base64,' + base64.b64encode(raw.getvalue()).decode()
        self.studio.workspaces.save(self.workspace, {'revision': 1, 'request_id': 'update-source', 'state': state})
        new = self.context(['image-one'], revision=2)['references'][0]['images'][0]['file']
        self.assertNotEqual(old, new)
        old_object = self.store.media.materialize(old.rsplit('/', 1)[1])
        self.assertTrue(old_object.is_file())
        with Image.open(self.store.media.materialize(new.rsplit('/', 1)[1])) as pixels:
            self.assertEqual(pixels.size, (8, 9))

    def test_rejects_invalid_deleted_cross_owner_and_ambiguous_edit_references(self):
        for ids in (['missing'], ['image-one'] * 2, ['image-one'] * 7, 'image-one', [None]):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                self.context(ids)
        with self.assertRaises(ValueError):
            self.context(['shot-one', 'image-one'], target='shot-two')
        focused = self.context(['shot-one', 'image-one'], target='shot-one')
        self.assertTrue(focused['references'][0]['current'])
        self.assertFalse(focused['references'][1]['current'])
        with self.assertRaises(ValueError):
            self.studio.context({'workspace': self.workspace, 'revision': 1, 'references': ['image-one']}, 'other-owner')
        with self.assertRaises(ValueError):
            self.context(['image-one'], path='C:/private/image.png')
        with self.assertRaises(ValueError):
            self.context(['image-one'], revision=0)

    def test_precision_image_must_belong_to_the_conversation(self):
        other = self.canvas.create('foreign image')
        raw = io.BytesIO(); Image.new('RGB', (8, 9), 'blue').save(raw, format='PNG')
        asset = self.canvas.add_asset(other['id'], raw.getvalue(), 'image.png')
        state = copy.deepcopy(self.record['state'])
        state['assets'][0]['file'] = self.studio.precision.file_url(other['id'], asset['id'])
        self.studio.workspaces.save(self.workspace, {'revision': 1, 'request_id': 'foreign-source', 'state': state})
        with self.assertRaisesRegex(ValueError, '不属于'):
            self.context(['image-one'], revision=2)
