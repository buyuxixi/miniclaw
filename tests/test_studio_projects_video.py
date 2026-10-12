"""Proposal provenance, owner selection and charge-safe video recovery."""
import copy
import base64
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from miniclaw_web.canvas import Canvas,Conflict
from miniclaw_web.store import Store
from miniclaw_web.studio import Studio
from miniclaw_web.studio_video import StudioVideo
from miniclaw_web.studio_projects import project_display_name
from miniclaw_web.attachments import upload
from PIL import Image
from tests.test_canvas import Held
from miniclaw_web.canvas_tools import _turn_session

ROOT=Path(__file__).resolve().parents[1]
PLAN='确认两个镜头。\n```studio-plan\n'+json.dumps({'shots':[{'name':'登场','duration':5,'prompt':'产品保持准确，缓慢推近'},{'name':'定格','duration':5,'prompt':'缓慢拉远，保留文字'}]},ensure_ascii=False)+'\n```'

class StudioPipelineTests(unittest.TestCase):
    def test_display_name_uses_the_idea_instead_of_an_asset_hash(self):
        state={'notes':[{'title':'BUV 小绿泥 · 创作方案'}],'assets':[{'name':'0c90b48dc2e531020c520c008b6dd5d3.jpg'}]}
        self.assertEqual(project_display_name(None,state),'BUV 小绿泥')
        self.assertEqual(project_display_name('我的项目',state),'我的项目')
        self.assertEqual(project_display_name(None,{'assets':state['assets']}),'未命名画布')
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name);self.held=Held();self.canvas=Canvas(self.store,executor=self.held)
        self.studio=Studio(self.store,self.canvas,ROOT);self.studio.message_reader=lambda owner,item:PLAN if owner=='owner-one' and item==17 else (_ for _ in ()).throw(ValueError('原消息不可读'))
        self.request={'request_id':'proposal-fixture','name':'BUV产品','session_id':'live','message':17,'facts':'不出现人物'}
        self.record=self.studio.create_project(self.request,'owner-one');self.workspace=self.record['id']
        self.video=StudioVideo(self.studio,ROOT,executor=self.held);self.studio._video=self.video
    def tearDown(self):self.tmp.cleanup()
    def ready(self):
        state=copy.deepcopy(self.record['state']);state['assets']=[{'id':'product-one','name':'产品','file':'source.png'}];state['shots'][0]['first']='product-one'
        self.record=self.studio.workspaces.save(self.workspace,{'request_id':'add-first-frame','revision':1,'state':state})
        return {'request_id':'video-request-one','revision':2,'shot':state['shots'][0]['id']}
    def test_proposal_creates_only_owned_empty_project_and_two_shots(self):
        self.assertEqual(self.studio.create_project(self.request,'owner-one'),self.record)
        self.assertEqual(len(self.record['state']['shots']),2);self.assertEqual(self.record['state']['assets'],[])
        self.assertTrue(self.record['state']['candidate']['removed']);self.assertEqual(self.record['state']['sequence'],[])
        self.assertEqual(self.record['state']['notes'][0]['source']['messageId'],17)
        self.assertEqual([p['id'] for p in self.studio.list('owner-one')],[self.workspace]);self.assertEqual(self.studio.list('owner-two'),[])
        with self.assertRaises(ValueError):self.studio.create_project({**self.request,'name':'另一个名称'},'owner-one')
        with self.assertRaises(ValueError):self.studio.create_project(self.request,'owner-two')

    def test_plan_carries_owned_prior_images_without_guessing_first_frames(self):
        pixels=io.BytesIO();Image.new('RGB',(40,60),'green').save(pixels,format='PNG')
        image=upload(self.store,'owner-one','产品.png',base64.b64encode(pixels.getvalue()).decode())
        self.store.put('turns',16,{'text':'原始资料','attachments':[image]},'owner-one')
        later_pixels=io.BytesIO();Image.new('RGB',(40,60),'pink').save(later_pixels,format='PNG')
        later=upload(self.store,'owner-one','后来.png',base64.b64encode(later_pixels.getvalue()).decode())
        self.store.put('turns',18,{'text':'稍后上传','attachments':[later]},'owner-one')
        foreign=upload(self.store,'owner-two','他人.png',base64.b64encode(pixels.getvalue()).decode())
        self.store.put('turns',15,{'attachments':[foreign]},'owner-two')
        request={**self.request,'request_id':'plan-with-materials','include_images':True}
        record=self.studio.create_project(request,'owner-one')
        self.assertEqual(len(record['state']['assets']),1)
        asset=record['state']['assets'][0]
        self.assertEqual(asset['source']['attachmentId'],image['id'])
        self.assertEqual(asset['source']['sessionId'],'owner-one')
        self.assertEqual(asset['file'],self.store.media.url(self.store.get('attachments',image['id'],'owner-one')['object_id']))
        self.assertEqual([s['first'] for s in record['state']['shots']],['',''])
        self.assertEqual(record['state']['sequence'],[]);self.assertEqual(self.held.calls,[])
        self.assertEqual(self.studio.create_project(request,'owner-one'),record)
        self.assertEqual(self.studio.workspaces.get(record['id']),record)
    def test_submission_is_idempotent_and_stale_adoption_rejected(self):
        request=self.ready()
        with patch.dict(os.environ,{'DASHSCOPE_API_KEY':'fixture'}):
            job=self.video.submit(self.workspace,request);self.assertEqual(self.video.submit(self.workspace,request),job)
        self.assertEqual(len(self.held.calls),1)
        raw=self.video._get(job['id']);output=Path(self.tmp.name)/'fixture.mp4';output.write_bytes(b'fixture-video');raw.update(state='succeeded',path=str(output));self.video._put(raw)
        state=copy.deepcopy(self.record['state']);state['shots'][0]['prompt']='镜头方向变化'
        self.studio.workspaces.save(self.workspace,{'request_id':'change-direction','revision':2,'state':state})
        self.assertTrue(self.video.list(self.workspace)[0]['stale'])
        with self.assertRaises(Conflict):self.video.adopt(self.workspace,{'request_id':'adopt-stale-video','revision':3,'job':job['id']})
        self.assertEqual(self.studio.workspaces.get(self.workspace)['state']['sequence'],[])
    def test_unknown_submission_never_retries_and_running_poll_survives_restart(self):
        request=self.ready()
        calls=[]
        def transport(req):
            calls.append(req.method)
            raise httpx.ReadTimeout('fixture')
        factory=lambda **kwargs:httpx.Client(transport=httpx.MockTransport(transport))
        self.video.client_factory=factory
        with patch.dict(os.environ,{'DASHSCOPE_API_KEY':'fixture'}):self.video.submit(self.workspace,request);self.video._run(request['request_id'])
        self.assertEqual(calls,['POST']);self.assertEqual(self.video._get(request['request_id'])['state'],'unknown')
        recovered=StudioVideo(self.studio,ROOT,executor=Held(),client_factory=factory)
        recovered.list(self.workspace);self.assertEqual(len(recovered.executor.calls),0)
        with patch.dict(os.environ,{'DASHSCOPE_API_KEY':'fixture'}):
            with self.assertRaises(Conflict):recovered.submit(self.workspace,{**request,'request_id':'replacement-unsafe'})
        job=recovered._get(request['request_id']);job.update(state='running',task_id='provider-known-id');recovered._put(job)
        recovered=StudioVideo(self.studio,ROOT,executor=Held(),client_factory=factory)
        recovered.list(self.workspace);self.assertEqual(len(recovered.executor.calls),1)
        with patch.dict(os.environ,{'DASHSCOPE_API_KEY':'fixture'}):recovered._run(job['id'])
        self.assertEqual(calls,['POST','GET'])
    def test_active_project_turn_wins_over_a_stale_chat_connection(self):
        idle={'session_key':'same-project','running':False}
        active={'session_key':'same-project','running':True,'miniclaw_canvas_turn':{'project_id':'current-image'}}
        self.assertIs(_turn_session({'old':idle,'current':active},'same-project'),active)
        with self.assertRaises(ValueError):_turn_session({'one':active,'two':dict(active)},'same-project')

    def test_minimax_reads_existing_key_and_records_native_billed_duration(self):
        request=self.ready()
        with patch.dict(os.environ,{'MINIMAX_API':'fixture','MINIMAX_API_KEY':'','DASHSCOPE_API_KEY':''}):
            self.assertEqual(self.video.status()['provider'],'minimax')
            job=self.video.submit(self.workspace,request)
        self.assertEqual(job['provider'],'minimax');self.assertEqual(job['model'],'MiniMax-Hailuo-2.3')
        self.assertEqual(job['generation_duration'],6);self.assertEqual(job['duration'],5)
        self.assertEqual(job['resolution'],'768P');self.assertIsNone(job['audit']['estimate_cny'])
        self.assertEqual(job['audit']['quantity'],6)

    def test_minimax_unknown_submission_never_posts_again_after_restart(self):
        request=self.ready();calls=[]
        def transport(req):
            calls.append((req.method,req.url.path))
            if req.method=='POST':raise httpx.ReadTimeout('fixture')
            return httpx.Response(200,json={'base_resp':{'status_code':0},'status':'Processing'})
        self.video.client_factory=lambda **kwargs:httpx.Client(transport=httpx.MockTransport(transport))
        with patch.dict(os.environ,{'MINIMAX_API':'fixture','MINIMAX_API_KEY':''}):
            self.video.submit(self.workspace,request);self.video._run(request['request_id'])
            self.assertEqual(self.video._get(request['request_id'])['state'],'unknown')
            recovered=StudioVideo(self.studio,ROOT,executor=Held(),client_factory=self.video.client_factory)
            recovered.list(self.workspace);self.assertEqual(len(recovered.executor.calls),0)
        self.assertEqual(calls,[('POST','/v1/video_generation')])

    def test_minimax_protocol_download_trim_and_original_task_poll(self):
        request=self.ready();calls=[]
        def transport(req):
            calls.append((req.method,req.url.path))
            if req.method=='POST':
                payload=json.loads(req.content);self.assertEqual(payload['duration'],6);self.assertEqual(payload['model'],'MiniMax-Hailuo-2.3')
                self.assertTrue(payload['first_frame_image'].startswith('data:image/jpeg;base64,'))
                return httpx.Response(200,json={'task_id':'task-known','base_resp':{'status_code':0}})
            if req.url.path=='/v1/query/video_generation':return httpx.Response(200,json={'status':'Success','file_id':'file-known','base_resp':{'status_code':0}})
            if req.url.path=='/v1/files/retrieve':return httpx.Response(200,json={'file':{'download_url':'https://public-cdn-video-data-algeng.oss-cn-wulanchabu.aliyuncs.com/result.mp4'},'base_resp':{'status_code':0}})
            return httpx.Response(200,content=b'fixture')
        self.video.client_factory=lambda **kwargs:httpx.Client(transport=httpx.MockTransport(transport))
        with patch.dict(os.environ,{'MINIMAX_API':'fixture','MINIMAX_API_KEY':''}),patch('miniclaw_web.studio_video.binaries',return_value=('ffmpeg','ffprobe')),patch('miniclaw_web.studio_video.probe',side_effect=[{'duration':6},{'duration':5}]),patch('miniclaw_web.studio_video.subprocess.run') as encode:
            encode.return_value.returncode=0
            def encode_file(args,**kwargs):
                Path(args[-1]).write_bytes(b'encoded-fixture-video')
                return encode.return_value
            encode.side_effect=encode_file
            self.video.submit(self.workspace,request);self.video._run(request['request_id'])
        job=self.video._get(request['request_id']);self.assertEqual(job['state'],'succeeded');self.assertEqual(job['task_id'],'task-known')
        self.assertEqual(job['usage'],{'video_duration':6});self.assertEqual(len([c for c in calls if c[0]=='POST']),1)

    def test_result_layout_roundtrip_rejects_nonfinite_coordinates(self):
        state=copy.deepcopy(self.record['state']);state['canvasLayout']={'video-fixture':{'x':430,'y':520,'hidden':False}}
        result=self.studio.workspaces.save(self.workspace,{'request_id':'layout-roundtrip','revision':1,'state':state})
        self.assertEqual(self.studio.workspaces.get(self.workspace)['state']['canvasLayout'],state['canvasLayout'])
        state['canvasLayout']['video-fixture']['x']=float('inf')
        with self.assertRaises(ValueError):self.studio.workspaces.save(self.workspace,{'request_id':'layout-invalid','revision':2,'state':state})

    def test_older_canvas_client_preserves_saved_result_positions(self):
        state=copy.deepcopy(self.record['state']);state['canvasLayout']={'video-fixture':{'x':430,'y':520}}
        saved=self.studio.workspaces.save(self.workspace,{'request_id':'layout-new-client','revision':1,'state':state})
        old=copy.deepcopy(state);old.pop('canvasLayout');old['facts']='older client edit'
        result=self.studio.workspaces.save(self.workspace,{'request_id':'layout-old-client','revision':saved['revision'],'state':old})
        self.assertEqual(result['state']['canvasLayout'],state['canvasLayout'])

    def test_minimax_cdn_allowlist_does_not_allow_arbitrary_storage_urls(self):
        from miniclaw_web.minimax_video import checked_download
        url='https://public-cdn-video-data-algeng.oss-cn-wulanchabu.aliyuncs.com/result.mp4'
        self.assertEqual(checked_download(url),url)
        for value in ['http://cdn.minimax.io/video','https://evil.aliyuncs.com/video','https://minimax.io.evil.com/video','https://user@cdn.minimax.io/video']:
            with self.assertRaises(ValueError):checked_download(value)

    def test_atomic_adoption_and_no_sample_in_composition(self):
        request=self.ready()
        with patch.dict(os.environ,{'DASHSCOPE_API_KEY':'fixture'}):job=self.video.submit(self.workspace,request)
        raw=self.video._get(job['id']);output=Path(self.tmp.name)/'fixture.mp4';output.write_bytes(b'fixture-video');raw.update(state='succeeded',path=str(output));self.video._put(raw)
        adoption={'request_id':'adopt-current-video','revision':2,'job':job['id']}
        record=self.video.adopt(self.workspace,adoption);self.assertEqual(self.video.adopt(self.workspace,adoption),record)
        self.assertEqual(record['state']['sequence'],[{'shot':job['shot'],'job':job['id'],'duration':5}])
        self.assertEqual(record['state']['assets'],self.record['state']['assets'])
        self.assertEqual(self.video.render_basis(self.workspace)[1][0]['id'],job['id'])
        state=copy.deepcopy(record['state']);state['sequence']=['candidate-01'];self.studio.workspaces.save(self.workspace,{'request_id':'legacy-sample-sequence','revision':3,'state':state})
        with self.assertRaises(ValueError):self.video.render_basis(self.workspace)

    def test_explicit_historical_video_reuse_retains_current_prompt_and_inputs(self):
        request=self.ready()
        with patch.dict(os.environ,{'DASHSCOPE_API_KEY':'fixture','MINIMAX_API':''}):job=self.video.submit(self.workspace,request)
        output=Path(self.tmp.name)/'history.mp4';output.write_bytes(b'fixture-video')
        raw=self.video._get(job['id']);raw.update(state='succeeded',path=str(output));self.video._put(raw)
        state=copy.deepcopy(self.record['state']);state['shots'][0]['prompt']='新镜头要求'
        current=self.studio.workspaces.save(self.workspace,{'request_id':'changed-prompt','revision':2,'state':state})
        body={'request_id':'adopt-old-video','revision':current['revision'],'job':job['id']}
        with self.assertRaises(Conflict):self.video.adopt(self.workspace,body)
        body['use_history']=True
        adopted=self.video.adopt(self.workspace,body)
        self.assertEqual(adopted['state']['shots'],state['shots'])
        self.assertTrue(adopted['state']['sequence'][0]['use_history'])
        self.assertEqual(self.video.render_basis(self.workspace)[1][0]['id'],job['id'])
        self.assertEqual(self.video.adopt(self.workspace,body),adopted)

if __name__=='__main__':unittest.main()
