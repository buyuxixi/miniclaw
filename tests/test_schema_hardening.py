import copy
import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from miniclaw_web.media_storage import migrate_schema
from miniclaw_web.store import Store
from miniclaw_web.studio_projects import StudioProjects
from miniclaw_web.video_workspace import VideoWorkspace
from miniclaw_web.canvas import Canvas


def state(text='original'):
    return dict(assets=[],shots=[],notes=[],messages=[],saved=[],sequence=[],edits={},facts=text,narration='')


class HardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
        self.store=Store(self.home);self.workspaces=VideoWorkspace(self.store)
        self.projects=StudioProjects();self.projects.store=self.store
    def tearDown(self):self.temp.cleanup()

    def test_versions_are_immutable_and_heads_and_parents_cannot_cross_items(self):
        with self.store.connect() as db:
            a=self.store.versions.append(db,'scope','one','text',{'text':'one'},'one')
            b=self.store.versions.append(db,'scope','two','text',{'text':'two'},'two')
        item=self.store.versions.item_id('scope','one','text')
        bad=[('UPDATE media_heads SET revision_id=? WHERE item_id=?',(b,item)),
             ('INSERT INTO media_revisions VALUES (?,?,?,?,?,?,?)',('wrong-parent',item,b,'a'*64,'{}','bad',1)),
             ('UPDATE media_revisions SET data=? WHERE id=?',('{}',a)),
             ('DELETE FROM media_revisions WHERE id=?',(a,)),
             ('INSERT INTO bindings VALUES (?,?)',(None,'{}')),
             ('INSERT INTO bindings VALUES (?,?)',('bad-json','not json')),
             ('INSERT INTO studio_limits VALUES (?,?)',('workspace',-1)),
             ('INSERT INTO studio_links VALUES (?,?)',('missing-workspace','chat'))]
        for sql,args in bad:
            with self.subTest(sql=sql),self.assertRaises(sqlite3.IntegrityError):
                with self.store.connect() as db:db.execute(sql,args)
        with self.store.connect() as db:
            self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())
            self.assertEqual(db.execute('SELECT revision_id FROM media_heads WHERE item_id=?',(item,)).fetchone()[0],a)

    def test_catalog_pages_search_and_replace_save_are_transactional(self):
        for i in range(14):
            self.workspaces.save('workspace-'+str(i),dict(request_id='create-0001',revision=0,state=state()))
            with self.store.connect() as db:
                db.execute('INSERT INTO studio_projects VALUES (?,?,?)',('workspace-'+str(i),'Project '+str(i),'{}'))
                db.execute('INSERT INTO studio_links VALUES (?,?)',('workspace-'+str(i),'chat-'+str(i%2)))
        page=self.projects.project_list(page=2,page_size=6)
        self.assertEqual((page['total'],len(page['items']),page['page']),(14,6,2))
        self.assertEqual(len(self.projects.project_list(owner='chat-1')),7)
        self.assertEqual(self.projects.project_list(page=1,q='Project 13')['items'][0]['id'],'workspace-13')
        self.assertEqual(self.projects.project_list(page=999,page_size=6)['page'],3)
        record=self.workspaces.get('workspace-13')
        updated=copy.deepcopy(record['state']);updated['notes']=[dict(id='note-one',title='plan',text='second version')]
        self.workspaces.save('workspace-13',dict(request_id='replace-0002',revision=1,state=updated))
        self.assertEqual(self.projects.project_info('workspace-13')['notes'],1)
        self.assertEqual(self.projects.project_info('workspace-13')['revision'],2)
        with self.store.connect() as db:
            db.execute('BEGIN')
            db.execute('UPDATE video_workspaces SET data=? WHERE id=?',(json.dumps({**record,'revision':99}),'workspace-13'))
            self.assertEqual(db.execute('SELECT revision FROM workspace_catalog WHERE workspace=?',('workspace-13',)).fetchone()[0],99)
            db.rollback()
        self.assertEqual(self.projects.project_info('workspace-13')['revision'],2)

    def test_version_pages_are_small_scoped_and_detail_retains_complete_content(self):
        for i in range(43):
            with self.store.connect() as db:self.store.versions.append(db,'scope','facts','text',{'text':str(i)+'x'*10000},'text')
        first=self.store.versions.page('scope','facts',page=1,page_size=20)
        last=self.store.versions.page('scope','facts',page=3,page_size=20)
        self.assertEqual((first['total'],len(first['items']),len(last['items'])),(43,20,3))
        self.assertTrue(all(len(v['data']['text'])==220 for v in first['items']))
        self.assertGreater(len(self.store.versions.detail('scope',first['items'][0]['id'])['data']['text']),10000)
        with self.assertRaises(ValueError):self.store.versions.detail('other',first['items'][0]['id'])
        self.assertFalse(self.store.versions.capacity('scope')['automatic_cleanup'])
        self.assertEqual(self.store.versions.capacity('scope')['versions'],43)
        with self.assertRaises(ValueError):self.store.versions.page('scope',page_size=101)

    def test_version_categories_filter_before_pagination_and_remain_scoped(self):
        rows=[('image-one','image'),('facts','text'),('note-one','note'),('narration','text'),('shot-one','prompt'),('shot-one','video'),('render','render')]
        for scope in ['scope','other']:
            for target,kind in rows:
                with self.store.connect() as db:self.store.versions.append(db,scope,target,kind,{'text':'content','id':target},'saved')
        for category,count in {'all':7,'image':1,'copy':2,'narration':1,'video':2,'render':1}.items():
            page=self.store.versions.page('scope',category=category,page_size=1)
            self.assertEqual(page['total'],count)
            self.assertEqual(len(page['items']),1)
            last=self.store.versions.page('scope',category=category,page=count,page_size=1)
            self.assertEqual(last['page'],count)
        self.assertEqual(self.store.versions.page('scope',target='shot-one',category='image')['total'],0)
        with self.assertRaises(ValueError):self.store.versions.page('scope',category="x' OR 1=1")

    def test_lookup_indexes_exist(self):
        queries=[('attachments','owner'),('turns','owner'),('image_jobs','owner'),('canvas_jobs','project'),('canvas_plans','project'),('creator_jobs','project'),('studio_video_jobs','workspace'),('studio_video_renders','workspace'),('studio_reservations','workspace'),('media_grants','object_id')]
        with self.store.connect() as db:
            for table,column in queries:
                plan=' '.join(r[3] for r in db.execute('EXPLAIN QUERY PLAN SELECT * FROM '+table+' WHERE '+column+'=?',('scope',)))
                self.assertIn('USING INDEX' if table!='studio_reservations' else 'USING',plan)

    def test_canvas_context_requires_its_project_link_and_pins_document_version(self):
        canvas=Canvas(self.store);one=canvas.create();two=canvas.create()
        self.workspaces.save('workspace-one',dict(request_id='request-0001',revision=0,state=state()))
        with self.store.connect() as db:
            db.execute('INSERT INTO video_precision_links VALUES (?,?,?)',('workspace-one','image-one',json.dumps({'project':one['id']})))
        row,version=canvas.context_reference(one['id'],0,'workspace-one')
        self.assertEqual(row['id'],one['id']);self.assertTrue(version)
        with self.assertRaisesRegex(ValueError,'不属于'):canvas.context_reference(two['id'],0,'workspace-one')
        with self.assertRaises(sqlite3.IntegrityError):
            with self.store.connect() as db:db.execute('UPDATE video_precision_links SET data=?',(json.dumps({'project':'missing-canvas'}),))

    def test_bad_legacy_migration_rolls_back_all_ddl_and_keeps_backup(self):
        schema=Path(__file__).resolve().parents[1]/'miniclaw_web/schema'
        with tempfile.TemporaryDirectory() as directory:
            with closing(sqlite3.connect(Path(directory)/'miniclaw.sqlite3')) as db:
                db.executescript((schema/'000_business_legacy.sql').read_text())
                source=(schema/'001_media_storage.sql').read_text()
                db.executescript(source)
                db.execute('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,checksum TEXT,applied_at REAL)')
                db.execute('INSERT INTO schema_migrations VALUES (1,?,0)',(hashlib.sha256(source.encode()).hexdigest(),))
                db.execute('INSERT INTO video_workspaces VALUES (?,?)',('workspace-one',json.dumps(dict(id='workspace-one',revision=1,state=state()))))
                db.execute('INSERT INTO studio_links VALUES (?,?)',('missing-workspace','chat'))
                db.commit()
                with self.assertRaisesRegex(ValueError,'迁移已回滚'):migrate_schema(db)
                self.assertEqual(db.execute('SELECT count(*) FROM studio_links').fetchone()[0],1)
                self.assertFalse(db.execute('SELECT 1 FROM schema_migrations WHERE version=2').fetchone())
                self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name='workspace_catalog' OR name LIKE '%_v2'").fetchone())
                self.assertEqual(db.execute('PRAGMA foreign_keys').fetchone()[0],1)
            backup=next((Path(directory)/'backups').glob('schema-v2-*.sqlite3'))
            with closing(sqlite3.connect(backup)) as db:self.assertEqual(db.execute('SELECT count(*) FROM studio_links').fetchone()[0],1)


if __name__=='__main__':unittest.main()
