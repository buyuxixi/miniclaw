import base64
import copy
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from PIL import Image
from miniclaw_web.store import Store
from miniclaw_web.video_workspace import VideoWorkspace
from miniclaw_web.canvas import Canvas, Conflict
from miniclaw_web.media_storage import MediaStorage, LocalObjects
from miniclaw_web.storage_migration import migrate


def image():
    out=io.BytesIO();Image.new('RGB',(24,32),'green').save(out,format='PNG');return out.getvalue()


def state():
    return dict(assets=[],shots=[],notes=[],messages=[],saved=[],sequence=[],edits={},facts='事实',narration='口播')


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name);self.store=Store(self.home)
    def tearDown(self):self.temp.cleanup()

    def test_large_stream_dedup_and_backend_cache(self):
        class Stream:
            remaining=201*1024*1024
            def read(self,size):
                if not self.remaining:return b''
                count=min(size,self.remaining);self.remaining-=count;return b'v'*count
        first=self.store.media.put_stream(Stream(),'video/mp4')
        second=self.store.media.put_stream(Stream(),'video/mp4')
        self.assertEqual(first['id'],second['id']);self.assertEqual(first['bytes'],201*1024*1024)
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM file_objects').fetchone()[0],1)
        self.assertEqual(self.store.media.materialize(first['id']).stat().st_size,first['bytes'])
        # A backend with no local path models an OSS adapter; materialize verifies bytes.
        class Remote:
            def __init__(self):self.data={}
            def publish(self,key,source,sha256,size):self.data[key]=source.read_bytes()
            def open(self,key):return io.BytesIO(self.data[key])
            def size(self,key):return len(self.data[key])
        remote=Remote();cloud=MediaStorage(self.store,{'oss':remote},'oss')
        obj=cloud.put_bytes(b'cloud object','text/plain')
        self.assertEqual(cloud.materialize(obj['id']).read_bytes(),b'cloud object')
        remote.data[obj['storage_key']]=b'corrupted'
        cloud.materialize(obj['id']).unlink()
        with self.assertRaises(OSError):cloud.materialize(obj['id'])

    def test_replay_exact_snapshot_and_movement_no_content_version(self):
        ws=VideoWorkspace(self.store);value=state()
        value['assets']=[{'id':'a1','file':'data:image/png;base64,'+base64.b64encode(image()).decode(),'x':0,'y':0}]
        request={'request_id':'request-0001','revision':0,'state':value}
        first=ws.save('workspace-one',request)
        self.assertTrue(first['state']['assets'][0]['file'].startswith('/studio/media/objects/'))
        moved=copy.deepcopy(first['state']);moved['assets'][0]['x']=500
        ws.save('workspace-one',{'request_id':'request-0002','revision':1,'state':moved})
        self.assertEqual(ws.save('workspace-one',request),first)
        self.assertEqual(len(ws.versions('workspace-one','a1')),1)
        with self.store.connect() as db:
            receipt=db.execute('SELECT data FROM video_workspace_receipts LIMIT 1').fetchone()[0]
            self.assertEqual(set(json.loads(receipt)),{'snapshot_id'})
            self.assertFalse(db.execute("SELECT 1 FROM workspace_snapshots WHERE instr(data,'data:image/')>0").fetchone())

    def test_text_restore_branch_and_scope_and_cas(self):
        ws=VideoWorkspace(self.store);current=ws.save('workspace-one',{'request_id':'request-0001','revision':0,'state':state()})
        v1=ws.versions('workspace-one','facts')[0]['id']
        nextstate=copy.deepcopy(current['state']);nextstate['facts']='第二版'
        current=ws.save('workspace-one',{'request_id':'request-0002','revision':1,'state':nextstate})
        v2=ws.versions('workspace-one','facts')[0]['id']
        current=ws.restore_version('workspace-one',{'request_id':'restore-0001','revision':2,'version_id':v1})
        nextstate=copy.deepcopy(current['state']);nextstate['facts']='新分支'
        ws.save('workspace-one',{'request_id':'request-0003','revision':3,'state':nextstate})
        versions=ws.versions('workspace-one','facts')
        self.assertEqual(len(versions),3);self.assertEqual(versions[0]['parent_id'],v1)
        self.assertIn(v2,[v['id'] for v in versions])
        with self.assertRaises(Conflict):ws.restore_version('workspace-one',{'request_id':'restore-0002','revision':1,'version_id':v2})
        ws.save('workspace-two',{'request_id':'request-0001','revision':0,'state':state()})
        with self.assertRaises(ValueError):ws.restore_version('workspace-two',{'request_id':'restore-0001','revision':1,'version_id':v2})

    def test_document_branch_survives_bounded_undo(self):
        canvas=Canvas(self.store);row=canvas.create();v1=canvas.versions(row['id'])[0]['id']
        doc=copy.deepcopy(row['document']);doc['background']='#ff0000';row=canvas.save(row['id'],0,doc)
        v2=canvas.versions(row['id'])[0]['id']
        row=canvas.restore_version(row['id'],row['revision'],v1)
        doc=copy.deepcopy(row['document']);doc['background']='#0000ff';row=canvas.save(row['id'],row['revision'],doc)
        versions=canvas.versions(row['id']);self.assertEqual(versions[0]['parent_id'],v1)
        self.assertIn(v2,[v['id'] for v in versions])
        self.assertEqual(Image.open(io.BytesIO(canvas.export(row['id'],version_id=v2))).getpixel((0,0))[:3],(255,0,0))
        canvas.executor.shutdown(wait=True)

    def test_legacy_migration_backup_replay_hash_and_idempotency(self):
        ws=VideoWorkspace(self.store);value=state()
        value['assets']=[dict(id='a1',file='data:image/png;base64,'+base64.b64encode(image()).decode())]
        record=dict(id='workspace-one',revision=1,state=value,events=[],updated_at=10)
        with self.store.connect() as db:
            db.execute('INSERT INTO video_workspaces VALUES (?,?)',('workspace-one',json.dumps(record)))
            db.execute('INSERT INTO video_workspace_receipts VALUES (?,?,?,?)',('workspace-one','request-0001','signature',json.dumps(record)))
        report=migrate(self.home,True)
        with closing(sqlite3.connect(Path(report['backup'])/'miniclaw.sqlite3')) as db:
            self.assertIn('data:image/',db.execute('SELECT data FROM video_workspaces').fetchone()[0])
        with self.store.connect() as db:
            signature,raw=db.execute('SELECT signature,data FROM video_workspace_receipts').fetchone()
            self.assertEqual(signature,'signature');saved=self.store.versions.receipt(db,raw)
            self.assertEqual(saved['revision'],1)
            count=db.execute('SELECT count(*) FROM media_revisions').fetchone()[0]
        identifier=saved['state']['assets'][0]['file'].rsplit('/',1)[1]
        self.assertEqual(self.store.media.materialize(identifier).read_bytes(),image())
        migrate(self.home,True)
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM media_revisions').fetchone()[0],count)


if __name__=='__main__':unittest.main()
