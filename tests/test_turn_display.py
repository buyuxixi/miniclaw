"""Old display rows recover exact user whitespace, with no context leakage."""
import sys
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'hermes-agent')]
from miniclaw_web.turn_display import recover_skill_layout, read_turn_display


def scaffold(text):
    return ('[IMPORTANT: The user has invoked the "product-video-plan" skill. '
            'The full skill content is loaded below.]\nPRIVATE SKILL BODY\n'
            'The user has provided the following instruction alongside the skill invocation: ' + text)


class TurnDisplay(unittest.TestCase):
    def test_generated_optimization_wrapper_is_hidden_without_history_rewrite(self):
        import json
        from miniclaw_web.director_prompt import SHOT_INTRO
        goal='那怎么改？\n改提示词还是怎么改？'
        original='/product-prompt-optimize\n'+SHOT_INTRO+'\n'+json.dumps({'task':'video','name':'真人清新','current_prompt':'PRIVATE PROMPT','requested_change':goal},ensure_ascii=False)+'\nPRIVATE RULES'
        record={'skill':'product-prompt-optimize','text':original,'attachments':[{'id':'image'}]}
        store=MagicMock();store.turns.return_value={'904':record}
        with patch('hermes_state.SessionDB') as database:
            result=read_turn_display(store,'owner')['904']
        database.assert_not_called()
        self.assertEqual(result['text'],'/product-prompt-optimize\n'+goal)
        self.assertEqual(result['attachments'],record['attachments'])
        self.assertEqual(record['text'],original)

    def test_original_points_and_paragraphs_recovered_without_appended_context(self):
        original = '1.真实素材\n2.年轻化奢华\n3.真人\n4.10s，双镜\n5.保留包装\n\n补充说明。'
        display = {'skill': 'product-video-plan', 'text': '/product-video-plan ' + ' '.join(original.split())}
        self.assertEqual(recover_skill_layout(display, scaffold(original+'\n\nPRIVATE ATTACHMENT DATA')), '/product-video-plan\n'+original)
        self.assertEqual(display['text'], '/product-video-plan ' + ' '.join(original.split()))

    def test_changed_content_and_plain_text_are_not_used_to_reconstruct_display(self):
        display = {'skill': 'product-video-plan', 'text': '/product-video-plan 1.原文 2.保持'}
        for content in [scaffold('1.已改写\n2.保持'), '1.原文\n2.保持', None, scaffold('1.原文')]:
            self.assertEqual(recover_skill_layout(display, content), display['text'])

    def test_new_display_does_not_open_native_history(self):
        store=MagicMock();store.turns.return_value={'1':{'skill':'product-video-plan','text':'/product-video-plan\n1.原文\n2.保持'}}
        with patch('hermes_state.SessionDB') as database:
            self.assertEqual(read_turn_display(store,'owner'),store.turns.return_value)
            database.assert_not_called()

    def test_unavailable_history_keeps_saved_display_and_attachments(self):
        record={'skill':'product-video-plan','text':'/product-video-plan 1.原文 2.保持','attachments':[{'id':'image'}]}
        store=MagicMock();store.turns.return_value={'352':record}
        with patch('hermes_state.SessionDB',side_effect=sqlite3.OperationalError('fixture read failure')):
            with self.assertLogs('miniclaw_web.turn_display',level='WARNING'):
                self.assertEqual(read_turn_display(store,'owner'),{'352':record})

    def test_history_lookup_is_scoped_to_owner_and_user_row(self):
        record={'skill':'product-video-plan','text':'/product-video-plan 1.原文 2.保持','attachments':[{'id':'image'}]}
        store=MagicMock();store.turns.return_value={'352':record}
        with patch('hermes_state.SessionDB') as database:
            db=database.return_value.__enter__.return_value
            db.get_messages_around.return_value={'window':[{'id':352,'role':'assistant','content':scaffold('1.原文\n2.保持')}]}
            self.assertEqual(read_turn_display(store,'owner')['352'],record)
            db.get_messages_around.assert_called_once_with('owner',352,window=0)
            db.get_messages_around.return_value={'window':[{'id':352,'role':'user','content':scaffold('1.原文\n2.保持')}]}
            restored=read_turn_display(store,'owner')['352']
            self.assertEqual(restored['text'],'/product-video-plan\n1.原文\n2.保持')
            self.assertEqual(restored['attachments'],record['attachments'])
            self.assertEqual(record['text'],'/product-video-plan 1.原文 2.保持')


if __name__ == '__main__':
    unittest.main()
