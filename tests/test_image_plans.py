"""Real preview pixels, atomic plan application and cloud idempotency; no billing."""
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'hermes-agent')]
from PIL import Image, ImageDraw
from miniclaw_web.canvas import Canvas, Conflict
from miniclaw_web.canvas_document import blank, layer_base, png
from miniclaw_web.store import Store
from tests.test_canvas import Held


class ImagePlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.executor = Held()
        self.canvas = Canvas(Store(self.temp.name), self.executor)
        row = self.canvas.create('方案验证')
        self.id = row['id']
        image = Image.new('RGBA', (80, 60), (70, 100, 140, 255))
        ImageDraw.Draw(image).rectangle((10, 10, 30, 30), fill=(180, 100, 40, 255))
        self.raw = png(image)
        self.asset = self.canvas.add_asset(self.id, self.raw, 'original.png')
        self.layer = layer_base('image', '原图', 80, 60, asset_id=self.asset['id'])
        doc = blank(80, 60); doc['layers'] = [self.layer]
        self.row = self.canvas.save(self.id, 0, doc)

    def tearDown(self):
        self.temp.cleanup()

    def propose(self, steps, preserve='商品形状和纹理'):
        return self.canvas.plans.propose(self.id, self.row['revision'], self.layer['id'], '修正画面', preserve, steps)

    def test_multistep_preview_is_readonly_then_apply_and_restore_are_durable(self):
        plan = self.propose([{'action':'crop_canvas','params':{'x':10,'y':10,'width':50,'height':35}},
                             {'action':'background','params':{'color':'#f2efe7'}}])
        before = self.canvas.get(self.id)
        history = self.canvas.history(self.id)
        result = Image.open(io.BytesIO(self.canvas.plans.preview(self.id, plan['id'], 1)))
        self.assertEqual(result.size, (50,35))
        expected = Image.open(io.BytesIO(self.raw)).crop((10,10,60,45))
        self.assertEqual(result.tobytes(), expected.tobytes())
        self.assertEqual(self.canvas.get(self.id), before)
        self.assertEqual(self.canvas.history(self.id), history)
        saved = self.canvas.plans.apply(self.id, plan['id'], 1)
        self.assertEqual(saved['revision'], 2)
        reopened = Canvas(Store(self.temp.name), Held())
        self.assertEqual(reopened.plans.get(self.id, plan['id'])['state'], 'applied')
        self.assertEqual(reopened.get(self.id)['document'], saved['document'])
        self.assertEqual(Path(self.canvas.asset(self.id, self.asset['id'])['path']).read_bytes(), self.raw)
        self.canvas.restore(self.id, 2, 1)
        self.assertEqual(self.canvas.get(self.id)['document'], before['document'])

    def test_unpreviewed_stale_and_foreign_plans_cannot_apply(self):
        plan = self.propose([{'action':'opacity','params':{'opacity':.5}}])
        with self.assertRaises(ValueError): self.canvas.plans.apply(self.id, plan['id'], 1)
        other = self.canvas.create('其他项目')
        with self.assertRaises(ValueError): self.canvas.plans.preview(other['id'], plan['id'], 0)
        self.canvas.plans.preview(self.id, plan['id'], 1)
        self.canvas.save(self.id,1,self.row['document'])
        with self.assertRaises(Conflict): self.canvas.plans.apply(self.id, plan['id'], 2)

    def test_subject_split_preserves_original_composite_and_subject_pixels(self):
        selection = self.canvas.select(self.id,1,self.layer['id'],'rectangle',[[10,10],[30,30]])
        plan = self.propose([{'action':'split_subject','params':{}},
                             {'action':'ai_edit','params':{'prompt':'只修改背景为深灰展陈，补全空洞','region':False}}])
        before = self.canvas.export(self.id)
        preview = self.canvas.plans.preview(self.id,plan['id'],1)
        self.assertEqual(Image.open(io.BytesIO(preview)).tobytes(),Image.open(io.BytesIO(before)).tobytes())
        saved = self.canvas.plans.apply(self.id,plan['id'],1)
        self.assertEqual(len(saved['document']['layers']),2)
        back, subject = saved['document']['layers']
        self.assertEqual(back['id'], self.layer['id'])
        image = Image.open(self.canvas.asset(self.id,subject['asset_id'])['path'])
        self.assertEqual(image.getpixel((20,20)), Image.open(io.BytesIO(self.raw)).getpixel((20,20)))
        self.assertEqual(image.getpixel((0,0))[3],0)
        self.assertEqual(self.canvas.plans.get(self.id,plan['id'])['state'],'prepared')
        with patch.dict(os.environ,{'DASHSCOPE_API_KEY':'fixture'}):
            job = self.canvas.plans.generate(self.id,plan['id'],2)
        self.assertEqual(job['layer_id'],back['id'])
        self.assertEqual(job['source_id'],back['asset_id'])
        self.assertEqual(len(self.executor.calls),1)
        self.assertEqual(saved['document']['layers'][1],subject)

    def test_solid_background_keeps_subject_pixels_and_restores_original(self):
        self.canvas.select(self.id,1,self.layer['id'],'rectangle',[[10,10],[30,30]])
        plan = self.propose([{'action':'replace_background','params':{'color':'#f2efe7'}}])
        original = Image.open(io.BytesIO(self.raw)).convert('RGBA')
        preview = Image.open(io.BytesIO(self.canvas.plans.preview(self.id,plan['id'],1))).convert('RGBA')
        self.assertEqual(preview.crop((11,11,29,29)).tobytes(), original.crop((11,11,29,29)).tobytes())
        self.assertEqual(preview.getpixel((0,0)),(242,239,231,255))
        self.assertEqual(self.canvas.get(self.id)['revision'],1)
        self.assertEqual(self.executor.calls,[])
        saved = self.canvas.plans.apply(self.id,plan['id'],1)
        reopened = Canvas(Store(self.temp.name),Held())
        self.assertEqual(reopened.get(self.id)['document'],saved['document'])
        self.canvas.restore(self.id,2,1)
        self.assertEqual(self.canvas.get(self.id)['document'],self.row['document'])
        self.assertEqual(Path(self.canvas.asset(self.id,self.asset['id'])['path']).read_bytes(),self.raw)

    def test_solid_background_requires_current_selection_and_cannot_recolor_subject(self):
        action = {'action':'replace_background','params':{'color':'#f2efe7'}}
        with self.assertRaises(ValueError): self.propose([action])
        self.canvas.select(self.id,1,self.layer['id'],'rectangle',[[10,10],[30,30]])
        with self.assertRaises(ValueError): self.propose([action,{'action':'adjust','params':{'brightness':.2}}])
        with self.assertRaises(ValueError): self.propose([action,{'action':'ai_edit','params':{'prompt':'改图','region':False}}])
        with self.assertRaises(ValueError): self.propose([{'action':'move','params':{'x':0,'y':0}},action])
        plan = self.propose([action])
        self.canvas.select(self.id,1,self.layer['id'],'rectangle',[[40,10],[60,30]])
        with self.assertRaises(Conflict): self.canvas.plans.preview(self.id,plan['id'],1)
        self.assertEqual(self.canvas.get(self.id)['revision'],1)

    def test_selection_changes_block_split_even_without_revision_change(self):
        self.canvas.select(self.id,1,self.layer['id'],'rectangle',[[10,10],[30,30]])
        plan = self.propose([{'action':'split_subject','params':{}}])
        self.canvas.select(self.id,1,self.layer['id'],'rectangle',[[40,10],[60,30]])
        with self.assertRaises(Conflict): self.canvas.plans.preview(self.id,plan['id'],1)
        self.assertEqual(self.canvas.get(self.id)['revision'],1)

    def test_registry_rejects_unknown_fields_invalid_actions_ranges_and_ai_sequences(self):
        invalid = [[],[{'action':'upscale','params':{}}],
                   [{'action':'crop_canvas','params':{'x':0,'y':0,'width':90,'height':50}}],
                   [{'action':'crop_canvas','params':{'x':True,'y':0,'width':40,'height':50}}],
                   [{'action':'move','params':{'x':float('nan'),'y':0}}],
                   [{'action':'ai_edit','params':{'prompt':'x','region':False}},{'action':'flip','params':{'direction':'horizontal'}}],
                   [{'action':'flip','params':{'direction':'horizontal'}},{'action':'ai_edit','params':{'prompt':'x','region':True}}],
                   [{'action':'opacity','params':{'opacity':.5,'path':'other.png'}}],
                   [{'action':'split_subject','params':{}}],
                   [{'action':'text','params':{'text':'wrong type target'}}]]
        for steps in invalid:
            with self.subTest(steps=steps), self.assertRaises(ValueError): self.propose(steps)
        self.assertEqual(self.canvas.plans.list(self.id),[])
        self.assertEqual(self.canvas.get(self.id)['revision'],1)

    def test_locks_preview_geometry_and_adjustment_validation(self):
        plan = self.propose([{'action':'adjust','params':{'brightness':.15}}, {'action':'flip','params':{'direction':'horizontal'}}])
        self.canvas.plans.preview(self.id,plan['id'],1)
        self.assertEqual(self.canvas.get(self.id)['document']['layers'][0]['asset_id'],self.asset['id'])
        doc = copy.deepcopy(self.row['document']); doc['layers'][0]['locked']=True
        self.row = self.canvas.save(self.id,1,doc)
        with self.assertRaises(ValueError): self.propose([{'action':'reorder','params':{'position':0}}])
        with self.assertRaises(ValueError): self.propose([{'action':'opacity','params':{'opacity':.5}}])

    def test_atomic_apply_rolls_back_canvas_when_plan_write_fails(self):
        plan = self.propose([{'action':'opacity','params':{'opacity':.7}}])
        self.canvas.plans.preview(self.id,plan['id'],1)
        before = self.canvas.get(self.id)
        with patch.object(self.canvas.plans,'_write',side_effect=OSError('disk')):
            with self.assertRaises(OSError): self.canvas.plans.apply(self.id,plan['id'],1)
        self.assertEqual(self.canvas.get(self.id),before)
        self.assertEqual(self.canvas.plans.get(self.id,plan['id'])['state'],'ready')

    def test_paid_submit_is_explicit_idempotent_cancelable_and_not_replayed_on_restart(self):
        plan = self.propose([{'action':'ai_edit','params':{'prompt':'改善摄影','region':False}}])
        self.assertEqual(self.executor.calls,[])
        with patch.dict(os.environ,{'DASHSCOPE_API_KEY':'fixture'}):
            job = self.canvas.plans.generate(self.id,plan['id'],1)
            self.assertEqual(self.canvas.plans.generate(self.id,plan['id'],1)['id'],job['id'])
        self.assertEqual(len(self.executor.calls),1)
        self.canvas.plans.cancel(self.id,plan['id'])
        self.assertEqual(self.canvas.job(self.id,job['id'])['state'],'canceled')
        with self.assertRaises(ValueError): self.canvas.plans.generate(self.id,plan['id'],1)
        reopened = Canvas(Store(self.temp.name),Held())
        self.assertEqual(reopened.executor.calls,[])

    def test_ai_plan_only_sends_visible_crop_and_preserves_hidden_screenshot_pixels(self):
        source=Image.new('RGBA',(80,160),'red')
        ImageDraw.Draw(source).rectangle((0,50,79,109),fill='green')
        asset=self.canvas.add_asset(self.id,png(source),'screenshot.png')
        doc=blank(80,60)
        layer=layer_base('image','截图',80,160,asset_id=asset['id'],y=-50)
        doc['layers']=[layer]
        self.row=self.canvas.save(self.id,1,doc); self.layer=layer
        plan=self.propose([{'action':'ai_edit','params':{'prompt':'只改可见画面','region':False}}])
        with patch.dict(os.environ,{'DASHSCOPE_API_KEY':'fixture'}):
            job=self.canvas.plans.generate(self.id,plan['id'],2)
        def provider(raw,mime,prompt,**kwargs):
            sent=Image.open(io.BytesIO(raw)).convert('RGBA')
            self.assertEqual(sent.size,(80,60))
            self.assertEqual(sent.getpixel((0,0)),(0,128,0,255))
            return png(Image.new('RGBA',sent.size,'blue')),None
        with patch('miniclaw_web.canvas.edit_image',side_effect=provider): self.executor.run()
        result=self.canvas.job(self.id,job['id'])
        self.assertEqual(result['state'],'succeeded')
        image=Image.open(self.canvas.asset(self.id,result['output']['id'])['path']).convert('RGBA')
        self.assertEqual(image.crop((0,0,80,50)).tobytes(),source.crop((0,0,80,50)).tobytes())
        self.assertEqual(image.crop((0,110,80,160)).tobytes(),source.crop((0,110,80,160)).tobytes())
        self.assertEqual(image.getpixel((30,70)),(0,0,255,255))
        self.assertEqual(self.canvas.get(self.id)['document'],doc)

    def test_text_and_geometry_share_plan_validation_and_are_editable(self):
        doc = copy.deepcopy(self.row['document'])
        text = layer_base('text','标题',80,30,text='原稿',font_size=16,fill='#ffffff')
        doc['layers'].append(text)
        self.row = self.canvas.save(self.id,1,doc)
        plan = self.canvas.plans.propose(self.id,2,text['id'],'改标题','保留商品',[
            {'action':'text','params':{'text':'静看器物'}}, {'action':'move','params':{'x':5,'y':10}}])
        self.canvas.plans.preview(self.id,plan['id'],2)
        saved = self.canvas.plans.apply(self.id,plan['id'],2)
        self.assertEqual(saved['document']['layers'][1]['text'],'静看器物')
        self.assertEqual(saved['document']['layers'][1]['x'],5)

    def test_planning_turn_cannot_bypass_preview_with_direct_execution_tool(self):
        from types import SimpleNamespace
        from miniclaw_web import canvas_tools
        from miniclaw_web.store import digest
        self.row = self.canvas.metadata(self.id,1,chat_id='chat',link=True)
        ctx = {'project_id':self.id,'revision':2,'layer_id':self.layer['id'],'mode':'plan',
               'selection_hash':digest(json.dumps(None,sort_keys=True)),'selection_id':None}
        session = {'session_key':'chat','agent':SimpleNamespace(tools=[{'function':{'name':n}} for n in ('miniclaw_canvas_propose','miniclaw_canvas_ai')]),'miniclaw_canvas_turn':ctx}
        gateway = SimpleNamespace(server=SimpleNamespace(_sessions={'fixture':session}))
        previous = canvas_tools._service
        canvas_tools.set_service(self.canvas)
        try:
            with patch.dict(sys.modules,{'tui_gateway':gateway}):
                for tool in ['terminal','miniclaw_edit_image','miniclaw_read_file','miniclaw_save_artifact','miniclaw_canvas_ai','tool_call']:
                    self.assertEqual(canvas_tools.planning_guard(tool,'chat')['action'],'block')
                self.assertIsNone(canvas_tools.planning_guard('miniclaw_canvas_propose','chat'))
                self.assertIsNone(canvas_tools.planning_guard('skill_view','chat'))
                self.assertIsNone(canvas_tools.planning_guard('terminal','unrelated-chat'))
                result = json.loads(canvas_tools.canvas_tool('miniclaw_canvas_ai',{'prompt':'x','request_id':'example-123','region':False},'chat'))
                self.assertFalse(result['success'])
                self.assertEqual(self.executor.calls,[])
                result = json.loads(canvas_tools.canvas_tool('miniclaw_canvas_propose',{'goal':'提亮','preserve':'纹理','steps':[{'action':'adjust','params':{'brightness':.1}}]},'chat'))
                self.assertTrue(result['success'])
                self.assertEqual(self.canvas.get(self.id)['revision'],2)
                self.assertEqual(result['state'],'proposed')
                ctx['mode']='edit'
                self.assertIsNone(canvas_tools.planning_guard('terminal','chat'))
        finally:
            canvas_tools.set_service(previous)

    def test_rest_proposal_preview_apply_and_validation_use_the_real_service(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from miniclaw_web.canvas_routes import routes
        async def body(request, *args): return await request.json()
        app = FastAPI(); app.include_router(routes(self.canvas,body,lambda _:None,lambda _:None))
        with TestClient(app) as client:
            base = '/canvas/projects/' + self.id + '/plans'
            response = client.post(base,json={'revision':1,'layer_id':self.layer['id'],'goal':'暗一点','preserve':'形状',
                'steps':[{'action':'adjust','params':{'brightness':-.1}}]})
            self.assertEqual(response.status_code,200)
            plan_id = response.json()['id']
            self.assertNotIn('document',client.get(base).json()[0])
            path = base + '/' + plan_id
            self.assertEqual(client.post(path+'/apply',json={'revision':1}).status_code,400)
            response = client.post(path+'/preview',json={'revision':1})
            self.assertEqual(response.headers['content-type'],'image/png')
            self.assertEqual(Image.open(io.BytesIO(response.content)).size,(80,60))
            self.assertEqual(client.post(path+'/apply',json={'revision':1}).status_code,200)
            self.assertEqual(client.post(path+'/preview',json={'revision':1}).status_code,400)
            self.assertEqual(client.post(base,json={'revision':2,'layer_id':self.layer['id'],'goal':'x','preserve':'',
                'steps':[{'action':'upscale','params':{}}]}).status_code,400)


if __name__ == '__main__': unittest.main()
