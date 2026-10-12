"""Real pixels and transactions for the original canvas/Hermes integration."""
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from miniclaw_web.store import Store
from miniclaw_web.canvas import Canvas, Conflict
from miniclaw_web.studio import Studio, routes
from tests.test_canvas import Held

ROOT=Path(__file__).resolve().parents[1]

class StudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name);self.held=Held()
        self.canvas=Canvas(self.store,executor=self.held);self.studio=Studio(self.store,self.canvas,ROOT)
        self.workspace='workspace-fixture'
        state={'assets':[{'id':'image-one','name':'商品原图','file':'source.png'}],
               'shots':[{'id':'shot-one','name':'开场','mode':'first','first':'image-one','refs':[]},
                        {'id':'shot-two','name':'特写','mode':'first','first':'image-one','refs':[]},
                        {'id':'shot-three','name':'结尾','mode':'first','first':'another','refs':[]}],
               'edits':{},'notes':[],'messages':[],'saved':[],'sequence':[],'facts':'产品外观以原图为准'}
        self.record=self.studio.workspaces.save(self.workspace,{'request_id':'initial-fixture','revision':0,'state':state})
        self.studio.link(self.workspace,'owner-one')
        self.meta=self.studio.open(self.workspace,'image-one')
        app=FastAPI()
        async def body(request,cap=None):return await request.json()
        app.include_router(routes(self.studio,body,lambda _: {'session_key':'owner-one'},lambda _:None))
        self.client=TestClient(app)
    def tearDown(self):self.tmp.cleanup()
    def test_canonical_canvas_route_serves_relative_assets_and_legacy_links(self):
        for url in (f'/p/{self.workspace}',f'/studio/index.html?workspace={self.workspace}'):
            response=self.client.get(url)
            self.assertEqual(response.status_code,200)
            self.assertIn('<base href="/studio/">',response.text)
            self.assertIn('tokens.css?v=',response.text)
            self.assertIn('interaction.js?v=',response.text)
            self.assertNotIn('workbench.css',response.text)
        self.assertEqual(self.client.get('/studio/tokens.css').status_code,200)
        self.assertEqual(self.client.get('/p/invalid!').status_code,400)

    def test_binary_image_upload_object_authorization_and_range(self):
        import hermes_cli.web_server as server
        token=server._SESSION_TOKEN
        data=io.BytesIO();Image.new('RGB',(32,48),'green').save(data,format='PNG');raw=data.getvalue()
        url=f'/api/workspaces/{self.workspace}/assets/upload?name=product.png'
        self.assertEqual(self.client.post(url,content=raw).status_code,401)
        result=self.client.post(url,content=raw,headers={'X-Hermes-Session-Token':token})
        self.assertEqual(result.status_code,200,result.text)
        media=result.json();self.assertNotIn('data:image/',media['file'])
        self.assertEqual(self.client.get(media['file']).status_code,401)
        self.client.cookies.set('studio_media',token,path='/studio/media')
        response=self.client.get(media['file'],headers={'Range':'bytes=0-7'})
        self.assertEqual(response.status_code,206);self.assertEqual(response.content,raw[:8])
        self.assertEqual(response.headers['content-range'],f'bytes 0-7/{len(raw)}')
        self.assertEqual(self.client.get(media['file'],headers={'Origin':'https://foreign.example'}).status_code,403)
        meta=self.studio.precision.open({'workspace':self.workspace,'object_id':'new-object','file':media['file']})
        self.assertEqual(meta['width'],32)
        with self.assertRaises(ValueError):self.studio.precision.open({'workspace':'different-workspace','object_id':'new-object','file':media['file']})

    def test_file_only_restore_opens_exact_old_pixels_and_preserves_previous_draft(self):
        original=self.canvas.export(self.meta['project'])
        first=self.studio.workspaces.versions(self.workspace,'image-one')[0]['id']
        row=self.canvas.get(self.meta['project']);doc=copy.deepcopy(row['document'])
        doc['layers'][0]['rotation']=45
        changed=self.canvas.save(row['id'],row['revision'],doc,'旋转工作图')
        current=self.studio.workspaces.restore_version(self.workspace,{'request_id':'restore-file-v1','revision':1,'version_id':first})
        opened=self.studio.open(self.workspace,'image-one')
        self.assertNotEqual(opened['project'],changed['id'])
        self.assertEqual(self.canvas.export(opened['project']),original)
        self.assertEqual(self.canvas.get(changed['id'])['document'],doc)

    def test_layered_restore_initializes_once_and_preserves_later_work(self):
        row=self.canvas.get(self.meta['project']);doc=copy.deepcopy(row['document']);doc['layers'][0]['rotation']=15
        row=self.canvas.save(row['id'],row['revision'],doc,'旋转十五度')
        preview=self.client.post(f"/api/precision/full/{row['id']}/preview",json={'revision':row['revision']}).json()
        adopted=self.studio.command(self.workspace,{'request_id':'adopt-layered-v1','revision':1,'action':'adopt','args':{'object':'image-one','source':'source.png','project':row['id'],'revision':row['revision'],'asset':preview['output_id']}})
        version=self.studio.workspaces.versions(self.workspace,'image-one')[0]['id']
        newer=copy.deepcopy(doc);newer['layers'][0]['rotation']=30
        row=self.canvas.save(row['id'],row['revision'],newer,'旋转三十度')
        self.studio.workspaces.restore_version(self.workspace,{'request_id':'restore-layered-v1','revision':adopted['revision'],'version_id':version})
        opened=self.studio.open(self.workspace,'image-one')
        self.assertEqual(self.canvas.get(opened['project'])['document'],doc)
        row=self.canvas.get(opened['project']);row=self.canvas.save(row['id'],row['revision'],newer,'旧版分支继续')
        self.studio.open(self.workspace,'image-one')
        self.assertEqual(self.canvas.get(opened['project'])['document'],newer)
    def test_multi_image_selection_is_normal_and_each_reference_has_its_own_working_document(self):
        state=copy.deepcopy(self.record['state'])
        state['assets'].append({'id':'image-two','name':'细节参考','file':'macro.png'})
        state['shots'][0].update(mode='reference',refs=['image-one','image-two'])
        self.record=self.studio.workspaces.save(self.workspace,{'request_id':'multi-reference','revision':1,'state':state})
        url=f'/api/workspaces/{self.workspace}/editing-target'
        choices=self.client.post(url,json={'target':'shot-one','session_id':'live'}).json()
        self.assertTrue(choices['selection_required'])
        self.assertEqual([a['id'] for a in choices['assets']],['image-one','image-two'])
        self.assertEqual(self.client.post(url,json={'target':'shot-one','session_id':'live','asset':'another'}).status_code,400)
        first=self.studio.open(self.workspace,'shot-one','image-one')
        second=self.studio.open(self.workspace,'shot-one','image-two')
        self.assertNotEqual(first['project'],second['project'])
        self.assertEqual(self.studio.open(self.workspace,'shot-one','image-one')['project'],first['project'])
        candidate=self.client.post(f"/api/precision/full/{first['project']}/preview",json={'revision':first['revision']}).json()
        result=self.studio.command(self.workspace,{'request_id':'multi-adopt','revision':2,'action':'adopt','args':{'object':'image-one','shot':'shot-one','source':'source.png','project':first['project'],'revision':candidate['revision'],'asset':candidate['output_id']}})
        self.assertEqual(result['state']['shots'][0]['refs'][1],'image-two')
        self.assertEqual(result['state']['shots'][1],state['shots'][1])
        self.assertEqual(result['state']['assets'][1],state['assets'][1])
        adopted=result['state']['shots'][0]['refs'][0]
        reopened=self.studio.open(self.workspace,'shot-one',adopted)
        self.assertEqual(reopened['project'],first['project'])
        self.assertEqual(reopened['revision'],first['revision'])
        self.assertEqual(self.studio.open(self.workspace,'shot-one','image-two')['project'],second['project'])
    def test_empty_shot_and_note_allow_discussion_without_image_error(self):
        state=copy.deepcopy(self.record['state']);state['shots'][0]['first']=None
        state['notes'].append({'id':'note-one','name':'创作方向','text':'保留主体'})
        self.studio.workspaces.save(self.workspace,{'request_id':'discussion-targets','revision':1,'state':state})
        for target in ['shot-one','note-one']:
            self.assertTrue(self.studio.open(self.workspace,target)['discussion_only'])
        with self.assertRaises(ValueError):self.studio.open(self.workspace,'removed-object')
    def preview(self):
        row=self.canvas.get(self.meta['project'])
        return self.client.post(f"/api/precision/full/{row['id']}/preview",json={'revision':row['revision']}).json()
    def adopt(self,candidate,revision=None,request_id='adoption-fixture'):
        return {'request_id':request_id,'revision':revision or self.record['revision'],'action':'adopt',
                'args':{'object':'image-one','source':'source.png','project':candidate['project'],
                        'revision':candidate['revision'],'asset':candidate['output_id']}}
    def test_shared_canvas_instance_and_chat_snapshot(self):
        self.assertIs(self.studio.precision.canvas,self.canvas)
        data=self.studio.context({'workspace':self.workspace,'target':'shot-two','revision':1},'owner-one')
        self.assertEqual(data['target']['id'],'shot-two');self.assertEqual(data['requirements'],'产品外观以原图为准')
        reference=next(v for v in data['content_versions'] if v['target']=='facts')
        self.assertEqual(self.store.versions.detail(self.workspace,reference['version_id'])['data']['text'],data['requirements'])
        with self.assertRaises(ValueError):self.studio.context({'workspace':self.workspace,'target':'shot-two','revision':1},'other-owner')
        with self.assertRaises(Conflict):self.studio.link(self.workspace,'other-owner')

    def test_version_api_pages_summaries_and_scoped_details(self):
        page=self.client.get(f'/api/workspaces/{self.workspace}/versions?page_size=2').json()
        self.assertEqual(len(page['items']),2);self.assertGreater(page['total'],2)
        reference=page['items'][0]
        detail=self.client.get(f'/api/workspaces/{self.workspace}/versions/'+reference['id'])
        self.assertEqual(detail.status_code,200)
        self.assertEqual(self.client.get('/api/workspaces/different-workspace/versions/'+reference['id']).status_code,400)
        self.assertEqual(self.client.get(f'/api/workspaces/{self.workspace}/versions?page_size=101').status_code,400)
        projects=self.client.get('/api/workspaces?page=1&page_size=6').json()
        self.assertEqual(projects['items'][0]['id'],self.workspace)
        self.assertEqual(self.client.get('/api/workspaces?page=0').status_code,400)
        self.assertFalse(self.client.get(f'/api/workspaces/{self.workspace}/storage').json()['automatic_cleanup'])
    def test_adopted_asset_and_shot_open_the_same_layered_working_document(self):
        # A director opened before editing may already have a legacy shot draft.
        old=self.studio.open(self.workspace,'shot-one')
        candidate=self.preview()
        adopted=self.studio.command(self.workspace,self.adopt(candidate))
        direct=self.studio.open(self.workspace,'image-one')
        shot=self.studio.open(self.workspace,'shot-one')
        self.assertEqual(shot['project'],direct['project'])
        self.assertEqual(shot['project'],candidate['project'])
        self.assertNotEqual(old['project'],shot['project'])
        self.assertEqual(shot['layer'],direct['layer'])
        self.assertEqual(adopted['state']['assets'][0]['file'],shot['source'])
    def test_context_keeps_free_chat_tools_but_rejects_direct_canvas_mutation(self):
        from miniclaw_web.canvas_tools import planning_guard, canvas_tool, set_service
        from tui_gateway import server
        from types import SimpleNamespace
        names=['miniclaw_canvas_view','miniclaw_canvas_apply']
        row=self.canvas.get(self.meta['project'])
        self.canvas.metadata(row['id'],row['revision'],chat_id='owner-one')
        session={'session_key':'owner-one','agent':SimpleNamespace(tools=[{'function':{'name':n}} for n in names]),'miniclaw_canvas_turn':{'mode':'context','project_id':row['id'],'layer_id':row['document']['layers'][0]['id']}}
        set_service(self.canvas)
        try:
            with patch.object(server,'_sessions',{'fixture':session}):
                self.assertIsNone(planning_guard('miniclaw_read_file','owner-one'))
                response=json.loads(canvas_tool('miniclaw_canvas_view',{},'owner-one'))
                self.assertEqual(response['layers'][0]['asset_id'],row['document']['layers'][0]['asset_id'])
                self.assertIn('error',json.loads(canvas_tool('miniclaw_canvas_apply',{},'owner-one')))
                session['miniclaw_canvas_turn']['mode']='plan'
                self.assertEqual(planning_guard('miniclaw_read_file','owner-one')['action'],'block')
        finally:set_service(None)
    def test_source_pixels_preserved_and_atomic_adoption_affects_only_references(self):
        original=Path(self.canvas.asset(self.meta['project'],self.canvas.get(self.meta['project'])['document']['layers'][0]['asset_id'])['path']).read_bytes()
        candidate=self.preview();request=self.adopt(candidate)
        result=self.studio.command(self.workspace,request)
        self.assertTrue(result['state']['assets'][0]['file'].startswith('/api/precision'))
        self.assertEqual(result['state']['assets'][0]['originalFile'],'source.png')
        self.assertTrue(result['state']['shots'][0]['inputReview']);self.assertTrue(result['state']['shots'][1]['inputReview'])
        self.assertEqual(result['state']['shots'][2],self.record['state']['shots'][2])
        self.assertEqual(result,self.studio.command(self.workspace,request))
        self.assertEqual(original,Path(self.canvas.asset(self.meta['project'],self.canvas.get(self.meta['project'])['document']['layers'][0]['asset_id'])['path']).read_bytes())
    def test_forged_asset_cross_project_or_stale_document_not_adopted(self):
        candidate=self.preview();other=self.canvas.create('另一个项目');raw=io.BytesIO();Image.new('RGB',(20,20),'red').save(raw,'PNG')
        foreign=self.canvas.add_asset(other['id'],raw.getvalue(),'foreign.png')
        request=self.adopt(candidate);request['args']['asset']=foreign['id']
        with self.assertRaises(ValueError):self.studio.command(self.workspace,request)
        row=self.canvas.get(candidate['project']);self.canvas.save(row['id'],row['revision'],row['document'],'更新')
        with self.assertRaises(Conflict):self.studio.command(self.workspace,self.adopt(candidate))
        self.assertEqual(self.studio.workspaces.get(self.workspace)['revision'],1)
    def test_project_conflict_preserves_newer_edit_and_candidate(self):
        candidate=self.preview();state=copy.deepcopy(self.record['state']);state['facts']='新要求'
        self.studio.workspaces.save(self.workspace,{'request_id':'newer-fixture','revision':1,'state':state})
        with self.assertRaises(Conflict):self.studio.command(self.workspace,self.adopt(candidate))
        self.assertEqual(self.studio.workspaces.get(self.workspace)['state']['facts'],'新要求')
        self.canvas.asset(candidate['project'],candidate['output_id'])
    def test_restore_increments_version_and_preserves_candidate(self):
        candidate=self.preview();adopted=self.studio.command(self.workspace,self.adopt(candidate))
        restored=self.studio.command(self.workspace,{'request_id':'restore-fixture','revision':adopted['revision'],'action':'restore',
                                  'args':{'object':'image-one','source':adopted['state']['assets'][0]['file']}})
        self.assertEqual(restored['revision'],3);self.assertEqual(restored['state']['assets'][0]['file'],'source.png')
        self.canvas.asset(candidate['project'],candidate['output_id'])
    def test_shot_local_adoption_forks_input_and_preserves_other_shots(self):
        meta=self.studio.open(self.workspace,'shot-two')
        candidate=self.client.post(f"/api/precision/full/{meta['project']}/preview",json={'revision':meta['revision']}).json()
        request=self.adopt(candidate);request['args']['shot']='shot-two'
        result=self.studio.command(self.workspace,request)
        self.assertEqual(result['state']['shots'][0],self.record['state']['shots'][0])
        self.assertEqual(result['state']['shots'][2],self.record['state']['shots'][2])
        self.assertNotEqual(result['state']['shots'][1]['first'],'image-one')
        self.assertEqual(result['state']['assets'][0]['file'],'source.png')
    def test_paid_generation_requires_allowance_and_duplicate_does_not_reserve_twice(self):
        row=self.canvas.get(self.meta['project']);layer=row['document']['layers'][0]
        with patch('miniclaw_web.canvas.provider_status',return_value={'configured':True}):
            args=(row['id'],row['revision'],layer['id'],'降低背景亮度','cloud-fixture')
            with self.assertRaises(ValueError):self.canvas.submit(*args,region=False)
            self.studio.budget(self.workspace,1)
            first=self.canvas.submit(*args,region=False);again=self.canvas.submit(*args,region=False)
            self.assertEqual(first['id'],again['id']);self.assertEqual(self.studio.budget(self.workspace)['reserved'],1)
            self.assertEqual(len(self.held.calls),1)
    def test_budget_can_increase_after_ten_reservations_without_resetting_usage(self):
        with self.store.connect() as db:
            db.executemany('INSERT INTO studio_reservations VALUES (?,?)',[(self.workspace,'used-'+str(i)) for i in range(10)])
        self.studio.budget(self.workspace,10)
        endpoint='/api/workspaces/'+self.workspace+'/budget'
        response=self.client.post(endpoint,json={'calls':30})
        self.assertEqual(response.status_code,200)
        self.assertEqual((response.json()['limit'],response.json()['reserved'],response.json()['remaining']),(30,10,20))
        self.assertEqual(response.json()['max_calls'],1000)
        self.assertEqual(self.client.get(endpoint).json()['limit'],30)
        row=self.canvas.get(self.meta['project']);layer=row['document']['layers'][0]
        with patch('miniclaw_web.canvas.provider_status',return_value={'configured':True}):
            self.canvas.submit(row['id'],row['revision'],layer['id'],'降低背景亮度','after-ten-fixture',region=False)
        self.assertEqual(self.studio.budget(self.workspace)['reserved'],11)
        restarted=Studio(self.store,self.canvas,ROOT)
        self.assertEqual(restarted.budget(self.workspace)['remaining'],19)
        self.assertEqual(len(self.held.calls),1)
        self.client.post(endpoint,json={'calls':5})
        self.assertEqual(self.studio.budget(self.workspace)['reserved'],11)
        self.assertEqual(self.studio.budget(self.workspace)['remaining'],0)
    def test_budget_validation_rejects_invalid_input_without_changing_allowance(self):
        self.studio.budget(self.workspace,30)
        endpoint='/api/workspaces/'+self.workspace+'/budget'
        for calls in [None,True,'30',-1,1.5,1001]:
            with self.subTest(calls=calls):
                self.assertEqual(self.client.post(endpoint,json={'calls':calls}).status_code,400)
                self.assertEqual(self.studio.budget(self.workspace)['limit'],30)
        for calls in [0,1000]:
            self.assertEqual(self.client.post(endpoint,json={'calls':calls}).status_code,200)
    def test_unknown_submission_budget_survives_restart(self):
        with self.store.connect() as db:db.execute('INSERT INTO studio_reservations VALUES (?,?)',(self.workspace,'unknown-fixture'))
        self.studio.budget(self.workspace,1)
        restarted=Studio(self.store,self.canvas,ROOT)
        self.assertEqual(restarted.budget(self.workspace)['remaining'],0)
    def test_confirmed_local_preview_recovers_without_duplicate_document_changes(self):
        row=self.canvas.get(self.meta['project'])
        plan=self.canvas.plans.propose(row['id'],row['revision'],row['document']['layers'][0]['id'],
            '整体压暗','保留构图',[{'action':'adjust','params':{'brightness':-.05}}])
        self.canvas.plans.preview(row['id'],plan['id'],row['revision'])
        request={'revision':row['revision'],'kind':'plan','id':plan['id']}
        first=self.studio.apply_preview(row['id'],request)
        self.assertEqual(first,self.studio.apply_preview(row['id'],request))
        self.assertEqual(first['revision'],row['revision']+1)
        self.canvas.save(row['id'],first['revision'],first['document'],'继续调整')
        with self.assertRaises(Conflict):self.studio.apply_preview(row['id'],request)
    def retained_job(self):
        row=self.canvas.get(self.meta['project'])
        image=io.BytesIO();Image.new('RGBA',(row['document']['width'],row['document']['height']),'red').save(image,format='PNG')
        output=self.canvas.add_asset(row['id'],image.getvalue(),'retained.png')
        layer=row['document']['layers'][0]
        job={'id':'retained-fixture','project':row['id'],'revision':row['revision'],'layer_id':layer['id'],
             'source_id':layer['asset_id'],'state':'succeeded','output':output,'created':1}
        with self.store.connect() as db:db.execute('INSERT INTO canvas_jobs VALUES (?,?,?)',(job['id'],row['id'],json.dumps(job)))
        return row,job
    def test_retained_job_can_be_compared_after_local_edits_without_changing_work(self):
        row,job=self.retained_job();doc=copy.deepcopy(row['document'])
        doc['layers'][0]['rotation']=15;doc['background']='#ffffff'
        current=self.canvas.save(row['id'],row['revision'],doc,'后续本地调整')
        with self.assertRaises(Conflict):self.studio.apply_preview(row['id'],{'revision':job['revision'],'kind':'job','id':job['id']})
        comparison=self.studio.compare_job(row['id'],{'revision':current['revision'],'job':job['id']})
        self.assertEqual(self.canvas.get(row['id']),current)
        self.assertEqual(Path(self.canvas.asset(row['id'],comparison['before_output'].split('/')[-1])['path']).read_bytes(),self.canvas.export(row['id']))
        request={'revision':comparison['revision'],'kind':'comparison','id':comparison['comparison']['id']}
        adopted=self.studio.apply_preview(row['id'],request)
        self.assertEqual(adopted['document']['layers'][0]['asset_id'],job['output']['id'])
        self.assertEqual(adopted['document']['layers'][0]['rotation'],15)
        self.assertEqual(adopted['document']['background'],'#ffffff')
        self.assertEqual(self.studio.apply_preview(row['id'],request),adopted)
        self.assertEqual(self.canvas.export(row['id'],seq=current['cursor']),Path(self.canvas.asset(row['id'],comparison['before_output'].split('/')[-1])['path']).read_bytes())
    def test_refreshed_comparison_still_rejects_new_edits_and_unreviewed_assets(self):
        row,job=self.retained_job()
        comparison=self.studio.compare_job(row['id'],{'revision':row['revision'],'job':job['id']})
        doc=copy.deepcopy(row['document']);doc['layers'][0]['opacity']=.5
        current=self.canvas.save(row['id'],row['revision'],doc,'比较后再次编辑')
        request={'revision':comparison['revision'],'kind':'comparison','id':comparison['comparison']['id']}
        with self.assertRaises(Conflict):self.studio.apply_preview(row['id'],request)
        self.assertEqual(self.canvas.get(row['id']),current)
        with self.assertRaises(Conflict):self.studio.compare_job(row['id'],{'revision':row['revision'],'job':job['id']})
        with self.assertRaises(ValueError):self.studio.apply_preview(row['id'],{'revision':current['revision'],'kind':'comparison','id':job['output']['id']})
    def test_retained_comparison_adopts_to_shot_and_reads_back_without_regeneration(self):
        row,job=self.retained_job()
        # A shot has its own editing link; only that shot should change.
        with self.store.connect() as db:
            data=db.execute('SELECT data FROM video_precision_links WHERE workspace=? AND object_id=?',(self.workspace,'image-one')).fetchone()[0]
            db.execute('INSERT INTO video_precision_links VALUES (?,?,?)',(self.workspace,'shot-shot-one',data))
        self.canvas.metadata(row['id'],row['revision'],name='工作图改名')
        current=self.canvas.get(row['id'])
        response=self.client.post(f"/api/precision/full/{row['id']}/compare-job",json={'revision':current['revision'],'job':job['id']})
        self.assertEqual(response.status_code,200,response.text)
        comparison=response.json()
        applied=self.studio.apply_preview(row['id'],{'revision':comparison['revision'],'kind':'comparison','id':comparison['comparison']['id']})
        output=self.client.post(f"/api/precision/full/{row['id']}/preview",json={'revision':applied['revision']}).json()
        request=self.adopt(output);request['args']['shot']='shot-one'
        saved=self.studio.command(self.workspace,request)
        read=self.studio.workspaces.get(self.workspace)
        self.assertEqual(saved['revision'],read['revision'])
        self.assertNotEqual(read['state']['shots'][0]['first'],'image-one')
        self.assertEqual(read['state']['shots'][1]['first'],'image-one')
        self.assertEqual(read['state']['assets'][0]['file'],'source.png')
        self.assertEqual(len(self.held.calls),0)
    def test_legacy_preview_and_document_routes_preserve_cas_before_studio_adoption(self):
        from miniclaw_web.canvas_routes import routes as canvas_routes
        async def body(request,cap=None):return await request.json()
        self.client.app.include_router(canvas_routes(self.canvas,body,lambda _: {},lambda _:None),prefix='/api/miniclaw')
        row,job=self.retained_job();doc=copy.deepcopy(row['document']);doc['layers'][0]['rotation']=15
        current=self.canvas.save(row['id'],row['revision'],doc,'后续本地调整')
        compared=copy.deepcopy(current['document']);compared['layers'][0]['asset_id']=job['output']['id']
        path=f"/api/miniclaw/canvas/projects/{row['id']}"
        response=self.client.post(path+'/preview',json={'revision':current['revision'],'document':compared})
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.content.startswith(b'\x89PNG'))
        self.assertEqual(self.canvas.get(row['id']),current)
        saved=self.client.put(path+'/document',json={'revision':current['revision'],'document':compared,'label':'采用已比较的修图结果'})
        self.assertEqual(saved.status_code,200,saved.text)
        self.assertEqual(json.dumps(saved.json()['document']),json.dumps(compared))
        self.assertEqual(self.client.put(path+'/document',json={'revision':current['revision'],'document':doc}).status_code,409)
        output=self.client.post(f"/api/precision/full/{row['id']}/preview",json={'revision':saved.json()['revision']}).json()
        adopted=self.studio.command(self.workspace,self.adopt(output))
        self.assertEqual(self.studio.workspaces.get(self.workspace)['state']['assets'][0]['file'],output['output'])
        self.assertEqual(adopted['state']['shots'][2],self.record['state']['shots'][2])
        self.assertEqual(len(self.held.calls),0)
    def test_idea_source_is_read_from_native_owner_and_repeated_saves_do_not_duplicate(self):
        self.studio.message_reader=lambda owner,message:'原生回复' if owner=='owner-one' and message==34 else (_ for _ in ()).throw(ValueError('原回复不存在'))
        request={'request_id':'idea-fixture','revision':1,'action':'idea','args':{'owner':'owner-one','message':34}}
        result=self.studio.command(self.workspace,request)
        self.assertEqual(result['state']['notes'][0]['text'],'原生回复')
        self.assertEqual(result,self.studio.command(self.workspace,request))
        request.update(request_id='idea-again-fixture',revision=result['revision'])
        self.assertEqual(len(self.studio.command(self.workspace,request)['state']['notes']),1)
        request.update(request_id='idea-foreign-fixture',revision=3);request['args']['owner']='foreign'
        with self.assertRaises(ValueError):self.studio.command(self.workspace,request)
    def test_prompt_adoption_rejects_changed_basis_even_with_latest_revision(self):
        self.studio.message_reader=lambda owner,message:'```studio-plan\n'+json.dumps({'shots':[{'name':'开场','duration':5,'prompt':'泥膜持续流动'}]})+'\n```'
        record=self.studio.workspaces.get(self.workspace)
        request={'request_id':'prompt-fixture','revision':record['revision'],'action':'shot-plan','args':{'owner':'owner-one','message':34,'shot':'shot-one','expected_prompt':'过时的提示词'}}
        with self.assertRaises(Conflict):self.studio.command(self.workspace,request)
        request['args']['expected_prompt']=record['state']['shots'][0].get('prompt','')
        result=self.studio.command(self.workspace,request)
        self.assertEqual(result['state']['shots'][0]['prompt'],'泥膜持续流动')
        self.assertEqual(self.studio.command(self.workspace,request),result)
    def test_version_endpoint_filters_categories_and_rejects_invalid_category(self):
        response=self.client.get(f'/api/workspaces/{self.workspace}/versions?category=video&page_size=1')
        self.assertEqual(response.status_code,200)
        self.assertTrue(all(v['kind'] in ('prompt','video') for v in response.json()['items']))
        self.assertEqual(self.client.get(f'/api/workspaces/{self.workspace}/versions?category=foreign').status_code,400)
        self.assertEqual(self.client.get('/studio/interaction.js').status_code,200)
        self.assertIn('interaction.js?v=',self.client.get('/studio/index.html').text)
    def test_creator_mapping_is_explicit_repeatable_and_preserves_full_requirements(self):
        from miniclaw_web.creator import Creator
        creator=Creator(self.store,ROOT);source=creator.create('旧商品项目')
        original=io.BytesIO();Image.new('RGB',(32,48),'green').save(original,format='PNG')
        incoming=Path(self.tmp.name)/'fixture.png';incoming.write_bytes(original.getvalue())
        source=creator.import_file(source['id'],source['revision'],'source','fixture.png',incoming)
        source=creator.patch(source['id'],{'revision':source['revision'],'facts':'有依据的产品事实','constraints':'不得改包装文字'})
        mapped=self.studio.import_creator(creator,source['id'],source['revision'])
        self.assertEqual(mapped['id'],'creator-'+source['id'])
        self.assertEqual(mapped,self.studio.import_creator(creator,source['id'],source['revision']))
        self.assertEqual(mapped['state']['shots'],[])
        self.assertEqual(len(mapped['state']['assets']),1)
        imported=mapped['state']['assets'][0]['file'].split('/')
        with Image.open(self.canvas.asset(imported[4],imported[6])['path']) as pixels:
            self.assertEqual(pixels.size,(32,48));self.assertEqual(pixels.convert('RGB').getpixel((4,4)),(0,128,0))
        self.assertEqual(creator._asset_path(source,'source').read_bytes(),original.getvalue())
        self.assertEqual(mapped['state']['notes'][0]['text'],'有依据的产品事实')
        self.assertEqual(creator.get(source['id'])['revision'],source['revision'])
    def test_cross_origin_write_and_invalid_actions_are_rejected(self):
        response=self.client.post(f'/api/workspaces/{self.workspace}/commands',json={},headers={'Origin':'https://evil.test'})
        self.assertEqual(response.status_code,403)
        response=self.client.post(f'/api/workspaces/{self.workspace}/commands',json={'request_id':'invalid-fixture','revision':1,'action':'shell','args':{}})
        self.assertEqual(response.status_code,400)
    def test_static_source_changes_refresh_the_browser_script_version(self):
        response=self.client.get('/studio/index.html')
        self.assertEqual(response.status_code,200)
        self.assertIn('integration.js?v=',response.text)
        self.assertEqual(self.client.get('/studio/integration.js').headers['cache-control'],'no-store')
    def test_migration_refuses_active_destination_before_recovery_changes_it(self):
        from scripts.migrate_studio import migrate
        with tempfile.TemporaryDirectory() as destination:
            other=Store(destination);project=Canvas(other,executor=Held()).create()
            with other.connect() as db:db.execute('INSERT INTO canvas_jobs VALUES (?,?,?)',('active-destination',project['id'],json.dumps({'state':'queued'})))
            with self.assertRaisesRegex(ValueError,'正式工作区'):
                migrate(self.tmp.name,destination,ROOT,apply=True)
            with other.connect() as db:
                self.assertEqual(json.loads(db.execute('SELECT data FROM canvas_jobs').fetchone()[0])['state'],'queued')
            self.assertFalse((Path(destination)/'studio-migration-backup').exists())

if __name__=='__main__':unittest.main()
