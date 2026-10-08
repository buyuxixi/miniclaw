"""Task-specific models, credential routing and immutable request receipts."""
import base64
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
import httpx
from PIL import Image
from miniclaw_web.canvas import Canvas
from miniclaw_web.canvas_document import png
from miniclaw_web.image_provider import generate_image, edit_image
from miniclaw_web.media_models import catalog, resolve
from miniclaw_web.store import Store
from miniclaw_web.studio import Studio
from miniclaw_web.studio_video import StudioVideo
from tests.test_canvas import Held

ROOT=Path(__file__).resolve().parents[1]
KEYS={'DASHSCOPE_API_KEY':'bailian-fixture','MINIMAX_API_KEY':'mini-fixture','MINIMAX_API':''}

class StudioModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name);self.held=Held()
        self.canvas=Canvas(self.store,self.held);self.studio=Studio(self.store,self.canvas,ROOT)
        self.workspace='models-fixture'
        state=dict(assets=[dict(id='image-one',name='产品',file='source.png')],
            shots=[dict(id='shot-one',name='登场',mode='first',first='image-one',refs=[],duration=5,prompt='保持产品轮廓',videoProvider='minimax',videoModel='MiniMax-Hailuo-2.3-Fast')],
            notes=[],messages=[],saved=[],sequence=[],facts='',edits={})
        self.record=self.studio.workspaces.save(self.workspace,dict(request_id='initial-models',revision=0,state=state))
        self.studio.budget(self.workspace,10)
        self.video=StudioVideo(self.studio,ROOT,executor=self.held);self.studio._video=self.video
        self.env=patch.dict(os.environ,KEYS);self.env.start()
    def tearDown(self):self.env.stop();self.tmp.cleanup()
    def image_request(self,task='edit',model='qwen-image-edit-plus',provider='dashscope'):
        return dict(request_id='image-model-one',revision=self.record['revision'],object='image-one',task=task,provider=provider,model=model,prompt='保留文字，调整背景')
    def test_catalog_filters_tasks_and_does_not_return_keys(self):
        self.assertNotIn('mini-fixture',json.dumps(catalog()));self.assertNotIn('bailian-fixture',json.dumps(catalog()))
        with self.assertRaises(ValueError):resolve('edit','minimax','image-01')
        with self.assertRaises(ValueError):resolve('generate','dashscope','qwen-image-edit-plus')
    def test_image_receipt_pins_model_and_is_idempotent(self):
        request=self.image_request();result=self.studio.submit_image(self.workspace,request)
        self.assertEqual(result,self.studio.submit_image(self.workspace,request));self.assertEqual(len(self.held.calls),1)
        with self.assertRaises(ValueError):self.studio.submit_image(self.workspace,{**request,'model':'qwen-image-edit-max'})
        with patch('miniclaw_web.canvas.edit_image',return_value=(png(Image.new('RGB',(24,24))), 'edit-id',{})) as provider:
            with patch.dict(os.environ,{'MINICLAW_IMAGE_MODEL':'qwen-image-edit-max'}):self.held.run()
            self.assertEqual(provider.call_args.kwargs['model'],'qwen-image-edit-plus')
        self.assertEqual(self.studio.image_request(self.workspace,request['request_id'])['state'],'succeeded')
    def test_generation_reuses_canvas_and_adopted_image_can_be_edited(self):
        state=copy.deepcopy(self.record['state']);state['assets'][0].update(pending=True,file=None)
        self.record=self.studio.workspaces.save(self.workspace,dict(request_id='pending-image',revision=1,state=state))
        request=self.image_request('generate','image-01','minimax');meta=self.studio.submit_image(self.workspace,request)
        with patch('miniclaw_web.image_provider.generate_image',return_value=(png(Image.new('RGB',(72,128),'red')),'mini-id',{'provider':'minimax','model':'image-01'})) as provider:
            self.held.run();self.assertEqual(provider.call_args.kwargs,{'provider':'minimax','model':'image-01'})
        result=self.studio.image_request(self.workspace,request['request_id']);self.assertEqual((result['width'],result['height']),(72,128))
        state=copy.deepcopy(self.record['state']);state['assets'][0].update(file=result['output'],pending=False)
        self.record=self.studio.workspaces.save(self.workspace,dict(request_id='adopt-new-image',revision=2,state=state))
        opened=self.studio.open(self.workspace,'image-one');self.assertEqual(opened['project'],meta['project'])
        request={**self.image_request(), 'request_id':'edit-generated-image'};edited=self.studio.submit_image(self.workspace,request)
        job=self.canvas.job(edited['project'],edited['job']);self.assertEqual(job['source_id'],result['output_id'])
    def test_all_image_edit_choices_reach_official_http_payload_without_default_override(self):
        pixels=png(Image.new('RGB',(24,24),'white'));seen=[]
        def transport(req):
            if req.method=='POST':
                self.assertEqual(req.url.host,'dashscope.aliyuncs.com')
                self.assertEqual(req.url.path,'/api/v1/services/aigc/multimodal-generation/generation')
                payload=json.loads(req.content);seen.append(payload)
                self.assertEqual(len(payload['input']['messages']),1)
                content=payload['input']['messages'][0]['content']
                self.assertTrue(content[0]['image'].startswith('data:image/png;base64,'))
                self.assertEqual(content[1],{'text':'保留文字，调整背景'})
                return httpx.Response(200,json={'request_id':'fixture-'+payload['model'],'output':{'choices':[{'message':{'content':[{'image':'https://fixture.oss-cn-beijing.aliyuncs.com/result.png'}]}}]}})
            self.assertNotIn('authorization',req.headers)
            return httpx.Response(200,content=pixels)
        factory=lambda **kwargs:httpx.Client(transport=httpx.MockTransport(transport))
        def real_adapter(raw,mime,prompt,**kwargs):
            return edit_image(raw,mime,prompt,client_factory=factory,**kwargs)
        choices=['qwen-image-2.0-pro','qwen-image-2.0','qwen-image-edit-max','qwen-image-edit-plus']
        with patch.dict(os.environ,{'MINICLAW_IMAGE_BASE_URL':'https://dashscope.aliyuncs.com','MINICLAW_IMAGE_MODEL':'qwen-image-edit-max'}),patch('miniclaw_web.canvas.edit_image',side_effect=real_adapter):
            for index,model in enumerate(choices):
                request={**self.image_request(model=model),'request_id':'routing-image-'+str(index)}
                receipt=self.studio.submit_image(self.workspace,request);self.held.run()
                result=self.studio.image_request(self.workspace,request['request_id'])
                self.assertEqual(result['state'],'succeeded');self.assertEqual(result['model'],model)
                job=self.canvas.job(receipt['project'],receipt['job']);self.assertEqual(job['provider_request_id'],'fixture-'+model)
                self.assertEqual(seen[-1]['model'],model)
        self.assertEqual([p['model'] for p in seen],choices)
    def test_generation_adapters_route_correct_key_and_protocol(self):
        pixels=png(Image.new('RGB',(8,8)));seen=[]
        def transport(req):
            if req.method=='POST':
                seen.append((req.url.host,req.url.path,req.headers['authorization'],json.loads(req.content)))
                if '/image_generation' in req.url.path:
                    return httpx.Response(200,json={'base_resp':{'status_code':0},'id':'mini-id','data':{'image_base64':[base64.b64encode(pixels).decode()]}})
                return httpx.Response(200,json={'request_id':'bailian-id','output':{'choices':[{'message':{'content':[{'image':'https://fixture.oss-cn-beijing.aliyuncs.com/result.png'}]}}]}})
            self.assertNotIn('authorization',req.headers)
            return httpx.Response(200,content=pixels)
        factory=lambda **kwargs:httpx.Client(transport=httpx.MockTransport(transport))
        generate_image('生成产品背景',provider='minimax',model='image-01',client_factory=factory)
        generate_image('生成产品背景',provider='dashscope',model='qwen-image-max',client_factory=factory)
        self.assertEqual(seen[0][1:3],('/v1/image_generation','Bearer mini-fixture'))
        self.assertEqual(seen[0][3]['response_format'],'base64')
        self.assertEqual(seen[1][2],'Bearer bailian-fixture');self.assertEqual(seen[1][3]['model'],'qwen-image-max')
        self.assertEqual(seen[1][3]['input']['messages'][0]['content'],[{'text':'生成产品背景'}])
    def test_selected_video_model_routes_and_replay_does_not_change(self):
        request=dict(request_id='video-selected-model',revision=1,shot='shot-one')
        job=self.video.submit(self.workspace,request);self.assertEqual(job['model'],'MiniMax-Hailuo-2.3-Fast')
        seen=[]
        def transport(req):
            seen.append((req.url.path,req.headers['authorization'],json.loads(req.content)))
            raise httpx.ReadTimeout('fixture')
        self.video.client_factory=lambda **kwargs:httpx.Client(transport=httpx.MockTransport(transport))
        self.video._run(job['id']);self.assertEqual(seen[0][0],'/v1/video_generation');self.assertEqual(seen[0][2]['model'],job['model'])
        state=copy.deepcopy(self.record['state']);state['shots'][0].update(videoProvider='dashscope',videoModel='wan2.2-i2v-flash')
        self.studio.workspaces.save(self.workspace,dict(request_id='switch-video-model',revision=1,state=state))
        self.assertEqual(self.video.submit(self.workspace,request)['model'],'MiniMax-Hailuo-2.3-Fast')
        self.assertEqual(len(seen),1)
    def test_h3_uses_v2_for_first_frame_and_reference_images(self):
        for mode in ('first','reference'):
            state=copy.deepcopy(self.record['state']);state['shots'][0].update(mode=mode,refs=['image-one'],videoModel='MiniMax-H3')
            self.record=self.studio.workspaces.save(self.workspace,dict(request_id='select-h3-'+mode,revision=self.record['revision'],state=state))
            request=dict(request_id='h3-video-'+mode,revision=self.record['revision'],shot='shot-one');seen=[]
            def transport(req):
                seen.append(req)
                return httpx.Response(200,json={'task_id':'fixture-h3'}) if req.method=='POST' else httpx.Response(200,json={'task':{'status':'failed'}})
            self.video.client_factory=lambda **kwargs:httpx.Client(transport=httpx.MockTransport(transport))
            job=self.video.submit(self.workspace,request);self.video._run(job['id'])
            self.assertEqual(seen[0].url.path,'/v2/video_generation');self.assertEqual(seen[1].url.path,'/v2/query/video_generation/fixture-h3')
            body=json.loads(seen[0].content);self.assertEqual(body['duration'],5)
            self.assertEqual(body['content'][1]['role'],'first_frame' if mode=='first' else 'reference_image')
            self.assertIn('url',body['content'][1]['image_url']);self.assertEqual(seen[0].headers['authorization'],'Bearer mini-fixture')
    def test_unsupported_combination_is_rejected_before_queue_or_reservation(self):
        with self.assertRaises(ValueError):self.studio.submit_image(self.workspace,self.image_request('edit','image-01','minimax'))
        self.assertEqual(self.held.calls,[]);self.assertEqual(self.studio.budget(self.workspace)['reserved'],0)

    def test_h3_success_downloads_exact_provider_cdn_without_credentials(self):
        from miniclaw_web.minimax_video import checked_download
        state=copy.deepcopy(self.record['state']);state['shots'][0]['videoModel']='MiniMax-H3'
        self.record=self.studio.workspaces.save(self.workspace,dict(request_id='select-h3-success',revision=1,state=state))
        url='https://algeng-video-infer.oss-cn-shanghai.aliyuncs.com/result.mp4'
        self.assertEqual(checked_download(url),url)
        with self.assertRaises(ValueError):checked_download('https://other.oss-cn-shanghai.aliyuncs.com/result.mp4')
        def transport(req):
            if req.method=='POST':return httpx.Response(200,json={'task_id':'h3-success'})
            if '/query/' in req.url.path:return httpx.Response(200,json={'task':{'status':'succeeded','content':{'url':url}}})
            self.assertNotIn('authorization',req.headers)
            return httpx.Response(200,content=b'provider-video')
        def transcode(command,**kwargs):
            Path(command[-1]).write_bytes(b'transcoded-video');return Mock(returncode=0)
        self.video.client_factory=lambda **kwargs:httpx.Client(transport=httpx.MockTransport(transport))
        job=self.video.submit(self.workspace,dict(request_id='h3-download',revision=self.record['revision'],shot='shot-one'))
        with patch('miniclaw_web.studio_video.binaries',return_value=('ffmpeg','ffprobe')),patch('miniclaw_web.studio_video.probe',return_value={'duration':5,'width':768,'height':1364}),patch('miniclaw_web.studio_video.subprocess.run',side_effect=transcode):
            self.video._run(job['id'])
        self.assertEqual(self.video.list(self.workspace)[0]['state'],'succeeded')

if __name__=='__main__':unittest.main()
