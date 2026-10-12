import tempfile
import unittest
from pathlib import Path

from miniclaw_web.store import Store
from miniclaw_web.studio_projects import StudioProjects
from miniclaw_web.video_workspace import VideoWorkspace


def state():
    return dict(assets=[],shots=[],notes=[],messages=[],saved=[],sequence=[],edits={},facts='',narration='')


class ArchiveLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(Path(self.temp.name))
        self.workspaces=VideoWorkspace(self.store)
        self.projects=StudioProjects();self.projects.store=self.store
        for name in ('project-alpha','project-beta'):
            self.workspaces.save(name,dict(request_id='create-0001',revision=0,state=state()))
    def tearDown(self):self.temp.cleanup()

    def test_archive_hides_project_and_restores_it(self):
        self.assertEqual({p['id'] for p in self.projects.project_list()},{'project-alpha','project-beta'})
        self.assertTrue(self.projects.set_archived('project-alpha',True)['archived'])
        self.assertEqual([p['id'] for p in self.projects.project_list()],['project-beta'])
        self.assertEqual([p['id'] for p in self.projects.project_list(archived=True)],['project-alpha'])
        self.assertEqual(self.workspaces.get('project-alpha')['revision'],1)
        self.assertFalse(self.projects.set_archived('project-alpha',False)['archived'])
        self.assertEqual(len(self.projects.project_list()),2)
        with self.assertRaises(ValueError):self.projects.set_archived('missing',True)

    def test_library_shares_one_object_across_projects(self):
        obj=self.store.media.put_bytes(b'\x89PNG\r\n\x1a\n'+b'0'*64,'image/png')
        with self.store.connect() as db:db.execute('INSERT INTO media_grants VALUES (?,?)',('project-alpha',obj['id']))
        url=self.store.media.url(obj['id'])
        with self.assertRaises(ValueError):self.projects.library_add('project-beta',url,'绿泥')
        item=self.projects.library_add('project-alpha',url,'绿泥 主图')
        self.assertEqual((item['id'],item['kind'],item['source']),(obj['id'],'image','project-alpha'))
        self.assertEqual(self.projects.library_list('主图')[0]['url'],url)
        self.assertEqual(self.projects.library_use('project-beta',obj['id'])['url'],url)
        with self.store.connect() as db:
            self.assertTrue(db.execute('SELECT 1 FROM media_grants WHERE scope=? AND object_id=?',('project-beta',obj['id'])).fetchone())
            self.assertEqual(db.execute('SELECT count(*) FROM file_objects').fetchone()[0],1)
        self.projects.library_remove(obj['id'])
        self.assertEqual(self.projects.library_list(),[])
        with self.assertRaises(ValueError):self.projects.library_use('project-beta',obj['id'])

    def test_collect_adds_saved_pictures_and_skips_unsaved(self):
        self.projects.workspaces=self.workspaces
        obj=self.store.media.put_bytes(b'\x89PNG\r\n\x1a\n'+b'1'*64,'image/png')
        record=self.workspaces.get('project-alpha');s=record['state']
        s['assets']=[dict(id='a1',name='正面',file=self.store.media.url(obj['id']),x=0,y=0,w=1,h=1),
                     dict(id='a2',name='旧文件',file='macro.png',x=0,y=0,w=1,h=1)]
        self.workspaces.save('project-alpha',dict(request_id='assets-0002',revision=1,state=s))
        added=self.projects.library_collect('project-alpha')
        self.assertEqual([i['name'] for i in added],['正面'])


if __name__=='__main__':unittest.main()
