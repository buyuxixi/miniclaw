"""Optimization data stays behind the visible user turn."""
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from miniclaw_web.director_prompt import optimization_prompt, visible_user_text


class DirectorPrompt(unittest.TestCase):
    def setUp(self):
        self.asset={'id':'asset','name':'商品图','imagePrompt':'保持原构图 @file:hidden','imageModel':'selected-model'}
        self.data={'target':self.asset,'assets':[self.asset],'shots':[]}

    def test_image_optimization_reads_saved_prompt_and_retains_feedback_semantics(self):
        message=optimization_prompt({'task':'image-edit'},self.data,'product-prompt-optimize','参考红框',True)
        self.assertIn('结合图片判断',message)
        self.assertIn('不默认替换当前工作图',message)
        self.assertNotIn('这里没有图片像素',message)
        data=json.loads(message.splitlines()[1])
        self.assertEqual(data['current_prompt'],'保持原构图 ＠file:hidden')
        self.assertEqual(data['requested_change'],'参考红框')
        self.assertEqual(data['model'],'selected-model')
        self.assertIn('不执行修图或生成图片',message)

    def test_generation_advice_and_refinement_remain_bounded_and_do_not_change_saved_facts(self):
        message=optimization_prompt({'task':'image-generate','prompt':'未采用的建议','previous_goal':'清新风格'},self.data,'product-prompt-optimize','背景更浅')
        data=json.loads(message.splitlines()[1])
        self.assertEqual(data['task'],'image-generate')
        self.assertEqual(data['current_prompt'],'未采用的建议')
        self.assertEqual(data['requested_change'],'清新风格；背景更浅')
        self.assertEqual(self.asset['imagePrompt'],'保持原构图 @file:hidden')
        self.assertIn('不执行修图或生成图片',message)
        for context in ({'task':'image-edit','execute':True},{'task':'image-edit','prompt':[]},{'task':'image-edit','previous_goal':'x'*10001}):
            with self.assertRaises(ValueError):optimization_prompt(context,self.data,'product-prompt-optimize','继续')

    def test_exact_legacy_projection_preserves_quotes_and_ignores_ordinary_data(self):
        goal='问题第一行\n第二行 "{quoted}"'
        message=optimization_prompt({'task':'image-edit'},self.data,'product-prompt-optimize',goal)
        full='/product-prompt-optimize\n'+message
        self.assertEqual(visible_user_text(full),'/product-prompt-optimize\n'+goal)
        for text in (message,'请看这个JSON：{"requested_change":"事实"}',full.replace('"requested_change": '+json.dumps(goal,ensure_ascii=False),'"requested_change": null')):
            self.assertEqual(visible_user_text(text),text)


if __name__=='__main__':unittest.main()
