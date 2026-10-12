"""Chat image handoff keeps bytes, provenance and workspace transactions intact."""
import base64
import copy
import io
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from miniclaw_web.attachments import upload
from miniclaw_web.canvas import Canvas, Conflict
from miniclaw_web.store import Store
from miniclaw_web.studio import Studio, routes
from tests.test_canvas import Held

ROOT=Path(__file__).resolve().parents[1]


class ChatCanvasImageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name)
        self.studio=Studio(self.store,Canvas(self.store,executor=Held()),ROOT)
        self.workspace='chat-image-workspace';self.owner='chat-image-owner'
        state={'assets':[],'shots':[],'notes':[],'messages':[],'saved':[],'sequence':[],'edits':{},'facts':'保留商品事实'}
        self.record=self.studio.workspaces.save(self.workspace,{'request_id':'initial-workspace','revision':0,'state':state})
        self.studio.link(self.workspace,self.owner)
        pixels=io.BytesIO();Image.new('RGB',(40,60),'green').save(pixels,format='PNG')
        self.data=base64.b64encode(pixels.getvalue()).decode()
        self.image=upload(self.store,self.owner,'商品原图.png',self.data)
        self.request={'request_id':'add-chat-image-01','session_id':'live-session','attachment':self.image['id']}
        app=FastAPI()
        async def body(request,cap=None):
            if request.headers.get('x-hermes-session-token')!='fixture':raise HTTPException(401)
            return await request.json()
        def session(identifier):
            if identifier!='live-session':raise HTTPException(404,'会话不存在')
            return {'session_key':self.owner}
        app.include_router(routes(self.studio,body,session,lambda _:None))
        self.client=TestClient(app)
    def tearDown(self):self.tmp.cleanup()
    def test_canvas_lists_and_imports_its_linked_chat_material_without_live_chat(self):
        items=self.client.get(f'/api/workspaces/{self.workspace}/assets/chat').json()
        self.assertEqual([i['id'] for i in items],[self.image['id']])
        self.assertNotIn('path',items[0]);self.assertTrue(items[0]['file'].startswith('/studio/media/objects/'))
        url=f'/api/workspaces/{self.workspace}/assets/import-chat'
        payload={'request_id':'canvas-import-one','attachment':self.image['id']}
        self.assertEqual(self.client.post(url,json=payload).status_code,401)
        self.assertEqual(self.client.post(url,json=payload,headers={'X-Hermes-Session-Token':'fixture','Origin':'https://foreign.example'}).status_code,403)
        response=self.client.post(url,json=payload,headers={'X-Hermes-Session-Token':'fixture'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(self.studio.workspaces.get(self.workspace)['state']['assets']),1)
        self.assertEqual(self.client.post(url,json=payload,headers={'X-Hermes-Session-Token':'fixture'}).json(),response.json())

    def test_canvas_import_rejects_foreign_attachment_and_forged_owner(self):
        foreign=upload(self.store,'owner-two','其他.png',self.data)
        url=f'/api/workspaces/{self.workspace}/assets/import-chat'
        payload={'request_id':'foreign-import-one','attachment':foreign['id']}
        for data in (payload,{**payload,'owner':'owner-two'}):
            self.assertEqual(self.client.post(url,json=data,headers={'X-Hermes-Session-Token':'fixture'}).status_code,400)
        self.assertEqual(self.studio.workspaces.get(self.workspace),self.record)
    def add(self,request=None):return self.studio.add_chat_image(self.workspace,request or self.request,self.owner)
    def test_route_persists_existing_object_and_provenance_without_copying(self):
        before=self.store.get('attachments',self.image['id'],self.owner)
        before.update(image_job_id='fixture-job',parent_id='fixture-parent',root_id='fixture-root')
        self.store.put('attachments',before['id'],before,self.owner)
        with self.store.connect() as db:objects=db.execute('SELECT count(*) FROM file_objects').fetchone()[0]
        response=self.client.post(f'/api/workspaces/{self.workspace}/assets/from-chat',json=self.request,headers={'X-Hermes-Session-Token':'fixture'})
        self.assertEqual(response.status_code,200,response.text);result=response.json()
        self.assertTrue(result['added']);self.assertEqual(result['revision'],2)
        saved=self.studio.workspaces.get(self.workspace);asset=saved['state']['assets'][0]
        self.assertEqual(asset['id'],result['object']);self.assertEqual(asset['name'],'商品原图.png')
        self.assertEqual(asset['file'],self.store.media.url(before['object_id']))
        self.assertEqual(asset['source']['sessionId'],self.owner);self.assertEqual(asset['source']['attachmentId'],self.image['id'])
        self.assertEqual(asset['source']['objectId'],before['object_id']);self.assertEqual(asset['source']['image_job_id'],'fixture-job')
        self.assertEqual(asset['source']['parent_id'],'fixture-parent');self.assertEqual(asset['source']['root_id'],'fixture-root')
        self.assertEqual(self.studio.workspaces.versions(self.workspace,asset['id'])[0]['data']['file'],asset['file'])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM file_objects').fetchone()[0],objects)
            self.assertTrue(db.execute('SELECT 1 FROM media_grants WHERE scope=? AND object_id=?',(self.workspace,before['object_id'])).fetchone())
        self.assertEqual(self.store.get('attachments',self.image['id'],self.owner),before)
    def test_retries_and_same_bytes_never_add_duplicate_nodes_or_revisions(self):
        first=self.add();self.assertEqual(self.add(),first)
        identical=upload(self.store,self.owner,'同一商品的另一文件名.png',self.data)
        second=self.add({**self.request,'request_id':'add-chat-image-02','attachment':identical['id']})
        self.assertFalse(second['added']);self.assertEqual(second['object'],first['object']);self.assertEqual(second['revision'],first['revision'])
        self.assertEqual(len(self.studio.workspaces.get(self.workspace)['state']['assets']),1)
        other_pixels=io.BytesIO();Image.new('RGB',(40,60),'red').save(other_pixels,format='PNG')
        different=upload(self.store,self.owner,'另一张.png',base64.b64encode(other_pixels.getvalue()).decode())
        with self.assertRaises(ValueError):self.add({**self.request,'attachment':different['id']})
    def test_existing_project_object_is_reused(self):
        obj=self.store.get('attachments',self.image['id'],self.owner)['object_id']
        state=copy.deepcopy(self.record['state']);state['assets']=[{'id':'existing-image','name':'已有素材','file':self.store.media.url(obj)}]
        self.studio.workspaces.save(self.workspace,{'request_id':'existing-object-save','revision':1,'state':state})
        result=self.add();self.assertFalse(result['added']);self.assertEqual(result['object'],'existing-image');self.assertEqual(result['revision'],2)
    def test_handoff_after_editing_retains_one_node_and_the_original_source(self):
        first=self.add();state=self.studio.workspaces.get(self.workspace)['state']
        state['assets'][0]['file']='source.png'
        changed=self.studio.workspaces.save(self.workspace,{'request_id':'edit-chat-image-01','revision':first['revision'],'state':state})
        repeated=self.add({**self.request,'request_id':'repeat-chat-image-01'})
        self.assertFalse(repeated['added']);self.assertEqual(repeated['object'],first['object'])
        self.assertEqual(repeated['revision'],changed['revision']);self.assertEqual(len(changed['state']['assets']),1)
        self.assertEqual(changed['state']['assets'][0]['source']['attachmentId'],self.image['id'])
    def test_reused_upload_node_still_deduplicates_after_adopting_a_different_image(self):
        obj=self.store.get('attachments',self.image['id'],self.owner)['object_id']
        original=self.store.media.url(obj)
        state=copy.deepcopy(self.record['state']);state['assets']=[{'id':'existing-image','name':'已有素材','file':original,'source':'upload'}]
        self.studio.workspaces.save(self.workspace,{'request_id':'reused-upload-save','revision':1,'state':state})
        first=self.add();self.assertFalse(first['added'])
        state=self.studio.workspaces.get(self.workspace)['state']
        state['assets'][0].update(file='source.png',versions=[{'file':original}])
        changed=self.studio.workspaces.save(self.workspace,{'request_id':'adopt-reused-image','revision':first['revision'],'state':state})
        repeated=self.add({**self.request,'request_id':'repeat-reused-image'})
        self.assertFalse(repeated['added']);self.assertEqual(repeated['object'],'existing-image')
        self.assertEqual(repeated['revision'],changed['revision'])
        self.assertEqual(self.studio.workspaces.get(self.workspace)['state']['assets'][0]['source'],'upload')
        self.assertEqual(len(self.studio.workspaces.get(self.workspace)['state']['assets']),1)
    def test_owner_link_kind_and_arbitrary_object_are_checked_at_server_boundary(self):
        foreign=upload(self.store,'other-owner','另一会话.png',self.data)
        with self.assertRaises(ValueError):self.add({**self.request,'attachment':foreign['id']})
        with self.assertRaises(ValueError):self.studio.add_chat_image(self.workspace,self.request,'other-owner')
        text=upload(self.store,self.owner,'资料.txt',base64.b64encode('商品资料'.encode()).decode())
        with self.assertRaises(ValueError):self.add({**self.request,'attachment':text['id']})
        row=self.store.get('attachments',text['id'],self.owner);row['kind']='image';self.store.put('attachments',row['id'],row,self.owner)
        with self.assertRaises(ValueError):self.add({**self.request,'attachment':text['id']})
        response=self.client.post(f'/api/workspaces/{self.workspace}/assets/from-chat',json={**self.request,'object_id':'arbitrary'},headers={'X-Hermes-Session-Token':'fixture'})
        self.assertEqual(response.status_code,400)
        self.assertEqual(self.studio.workspaces.get(self.workspace),self.record)
    def test_route_requires_token_same_origin_and_live_session(self):
        url=f'/api/workspaces/{self.workspace}/assets/from-chat'
        self.assertEqual(self.client.post(url,json=self.request).status_code,401)
        self.assertEqual(self.client.post(url,json=self.request,headers={'X-Hermes-Session-Token':'fixture','Origin':'https://foreign.example'}).status_code,403)
        self.assertEqual(self.client.post(url,json={**self.request,'session_id':'missing'},headers={'X-Hermes-Session-Token':'fixture'}).status_code,404)
        for invalid in ({},[],None,''):
            self.assertEqual(self.client.post(url,json={**self.request,'session_id':invalid},headers={'X-Hermes-Session-Token':'fixture'}).status_code,400)
        for field in ('attachment','request_id'):
            for invalid in ({},[],None,'',12):
                self.assertEqual(self.client.post(url,json={**self.request,field:invalid},headers={'X-Hermes-Session-Token':'fixture'}).status_code,400)
        self.assertEqual(self.studio.workspaces.get(self.workspace),self.record)
    def test_append_preserves_latest_edits_and_stale_canvas_save_cannot_overwrite_it(self):
        state=copy.deepcopy(self.record['state']);state['facts']='最新的商品事实';state['notes']=[{'id':'latest-note','text':'未丢失的方案','title':'方案'}]
        latest=self.studio.workspaces.save(self.workspace,{'request_id':'latest-facts-save','revision':1,'state':state})
        self.add();saved=self.studio.workspaces.get(self.workspace)
        self.assertEqual(saved['state']['facts'],state['facts']);self.assertEqual(saved['state']['notes'],state['notes'])
        with self.assertRaises(Conflict):self.studio.workspaces.save(self.workspace,{'request_id':'stale-canvas-save','revision':latest['revision'],'state':state})
        self.assertEqual(self.studio.workspaces.get(self.workspace),saved)
    def test_concurrent_duplicate_handoffs_add_one_node(self):
        with ThreadPoolExecutor(max_workers=2) as executor:
            results=list(executor.map(lambda n:self.add({**self.request,'request_id':f'concurrent-image-{n}'}),range(2)))
        self.assertEqual(results[0]['object'],results[1]['object']);self.assertEqual(sum(r['added'] for r in results),1)
        self.assertEqual(self.studio.workspaces.get(self.workspace)['revision'],2)
        self.assertEqual(len(self.studio.workspaces.get(self.workspace)['state']['assets']),1)
