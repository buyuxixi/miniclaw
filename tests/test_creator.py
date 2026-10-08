"""Real compositor integration plus persistent task failure boundaries."""
import hashlib
import json
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
import array
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient
from miniclaw_web.creator import Creator
from miniclaw_web.creator_routes import routes
from miniclaw_web.canvas import Conflict
from miniclaw_web.overlay import compile_overlay
from miniclaw_web.store import Store
from miniclaw_web.video import binaries, command, execute, font_path, probe, validated_document

SRT = '10\n00:00:00,250 --> 00:00:02,500\n陶瓷杯\n\n20\n00:00:03,000 --> 00:00:05,500\n每天一杯，慢一点。\n'
CARDS = [dict(id='a',kind='punch-pill',cue_start=1,cue_end=1,params={'text':'陶瓷杯','position':'top-left'}),
         dict(id='b',kind='quote-lockup',cue_start=2,cue_end=2,params={'quote':'每天一杯，慢一点。','side':'right'})]


class CapturedExecutor:
    def __init__(self): self.calls=[]
    def submit(self, fn, *args): self.calls.append((fn,args))


class CreatorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='miniclaw-creator-'); self.dir=Path(self.temp.name)
        self.store=Store(self.dir/'home'); self.queue=CapturedExecutor(); self.service=Creator(self.store,ROOT,self.queue)
        self.p=self.service.create('虚构技术验收')
        self.ffmpeg,self.ffprobe=binaries(ROOT)

    def tearDown(self): self.temp.cleanup()

    def import_file(self, slot, name, raw):
        temp=self.dir/'upload.tmp';temp.write_bytes(raw)
        self.p=self.service.import_file(self.p['id'],self.p['revision'],slot,name,temp)

    def test_source_survives_chat_cover_adoption_and_reopen(self):
        import io
        original=io.BytesIO();Image.new('RGB',(32,48),'green').save(original,format='PNG')
        self.import_file('source','product.png',original.getvalue())
        source=dict(self.p['assets']['source'])
        self.p=self.service.patch(self.p['id'],{'revision':self.p['revision'],'script':'同项目口播'})
        edited=self.dir/'edited.png';Image.new('RGB',(32,48),'white').save(edited)
        self.store.put('attachments','edited',dict(id='edited',name='edited.png',kind='image',path=str(edited),canvas_project_id='canvas-demo'),'chat-demo')
        self.p=self.service.adopt_cover(self.p['id'],self.p['revision'],'chat-demo','edited')
        reopened=Creator(self.store,ROOT,self.queue).get(self.p['id'])
        self.assertEqual(reopened['assets']['source'],source)
        self.assertEqual(reopened['script'],'同项目口播')
        self.assertEqual(reopened['assets']['cover']['source']['canvas_project_id'],'canvas-demo')
        self.assertNotEqual(reopened['assets']['cover']['sha256'],source['sha256'])
        self.assertEqual(self.service.file(self.p['id'],source['id'])[0].read_bytes(),original.getvalue())
        with self.assertRaises(ValueError):self.import_file('source','broken.png',b'fake')

    def test_mismatched_image_extension_fails_before_replacing_source(self):
        import io
        raw=io.BytesIO();Image.new('RGB',(32,48),'green').save(raw,format='JPEG')
        self.import_file('source','valid.jpg',raw.getvalue())
        before=self.service.get(self.p['id'])
        with self.assertRaisesRegex(ValueError,'扩展名不一致'):
            self.import_file('source','invalid.png',raw.getvalue())
        self.assertEqual(self.service.get(self.p['id']),before)

    def test_brief_and_adopted_results_track_dependencies_without_regeneration(self):
        import io
        image=io.BytesIO();Image.new('RGB',(32,48),'green').save(image,format='PNG')
        self.import_file('source','source.png',image.getvalue())
        self.p=self.service.patch(self.p['id'],dict(revision=self.p['revision'],facts='陶瓷杯',selling_points='杯身哑光',audience='办公室使用者',style='米白简洁',constraints='不宣称保温时长'))
        self.import_file('cover','cover.png',image.getvalue())
        self.p=self.service.patch(self.p['id'],dict(revision=self.p['revision'],script='哑光陶瓷杯，桌面的一点清爽。'))
        self.assertEqual(self.p['flow'],dict(brief='ready',cover='adopted',script='adopted'))
        old_script=self.p['script'];old_cover=self.p['assets']['cover']['id']
        # Saving a whole form with an unchanged script must not silently reconfirm it.
        self.p=self.service.patch(self.p['id'],dict(revision=self.p['revision'],style='深色沉稳',script=old_script))
        self.assertEqual(self.p['flow']['cover'],'review');self.assertEqual(self.p['flow']['script'],'review')
        self.assertFalse(self.service.list()[0]['progress']['cover']);self.assertFalse(self.service.list()[0]['progress']['script'])
        self.assertEqual(self.p['script'],old_script);self.assertEqual(self.p['assets']['cover']['id'],old_cover)
        self.assertEqual(self.queue.calls,[])
        self.p=self.service.patch(self.p['id'],dict(revision=self.p['revision'],confirm='cover'))
        self.p=self.service.patch(self.p['id'],dict(revision=self.p['revision'],confirm='script'))
        self.assertEqual(self.p['flow']['script'],'adopted')
        self.assertTrue(self.service.list()[0]['progress']['script'])
        self.import_file('cover','second.png',image.getvalue())
        self.assertEqual(self.p['flow']['script'],'review')
        self.p=self.service.patch(self.p['id'],dict(revision=self.p['revision'],script=old_script))
        self.assertEqual(self.p['flow']['script'],'adopted')
        self.p=self.service.patch(self.p['id'],dict(revision=self.p['revision'],caption='新发布标题'))
        self.assertEqual(self.p['flow']['script'],'adopted')
        restored=Creator(self.store,ROOT,self.queue).get(self.p['id'])
        self.assertEqual(restored['style'],'深色沉稳');self.assertEqual(restored['flow'],self.p['flow'])

    def test_old_project_defaults_and_brief_validation_preserve_existing_content(self):
        with self.store.connect() as db:
            raw=json.loads(db.execute('SELECT data FROM creator_projects WHERE id=?',(self.p['id'],)).fetchone()[0])
            for f in ('selling_points','audience','style','constraints'):raw.pop(f,None)
            raw['script']='已有旧稿';self.service._save(db,raw)
        p=Creator(self.store,ROOT,self.queue).get(self.p['id'])
        self.assertEqual(p['style'],'');self.assertEqual(p['script'],'已有旧稿');self.assertEqual(p['flow']['script'],'review')
        for fields in ({'style':[]},{'selling_points':'x'*4001},{'constraints':'x\0'},{'confirm':'cover'}):
            with self.assertRaises(ValueError):self.service.patch(p['id'],dict(revision=p['revision'],**fields))
        self.assertEqual(self.service.get(p['id'])['revision'],p['revision'])

    def test_creator_context_is_scoped_and_stale_adoption_is_rejected(self):
        self.p=self.service.link_chat(self.p['id'],self.p['revision'],'chat-one')
        self.p=self.service.patch(self.p['id'],dict(revision=self.p['revision'],facts='杯子',style='明亮'))
        ctx={'project_id':self.p['id'],'node':'script'}
        snapshot,data=self.service.turn_context(ctx,'chat-one')
        self.assertEqual(data['brief']['style'],'明亮')
        video_snapshot, video_data = self.service.turn_context({**ctx, 'node':'video'}, 'chat-one')
        self.assertEqual(video_snapshot['node'], 'video')
        self.assertEqual(video_data['video']['method'], self.p['method'])
        self.assertFalse(video_data['video']['has_current_output'])
        self.assertEqual(self.queue.calls, [])
        for invalid,owner in ((ctx,'chat-two'),({**ctx,'brief':'spoof'},'chat-one'),({**ctx,'node':'unknown'},'chat-one')):
            with self.assertRaises(ValueError):self.service.turn_context(invalid,owner)
        self.p=self.service.patch(self.p['id'],dict(revision=self.p['revision'],style='深色'))
        self.assertEqual(self.service.turn_context(ctx,'chat-one')[1]['brief']['style'],'深色')
        with self.assertRaises(Conflict):self.service.patch(self.p['id'],dict(revision=snapshot['revision'],script='迟到稿件'))
        self.assertEqual(self.service.get(self.p['id'])['script'],'')
        foreign=self.dir/'foreign.png';Image.new('RGB',(32,48),'blue').save(foreign)
        self.store.put('attachments','foreign',dict(id='foreign',name='foreign.png',kind='image',path=str(foreign)),'chat-two')
        with self.assertRaisesRegex(ValueError,'不属于当前项目聊天'):
            self.service.adopt_cover(self.p['id'],self.p['revision'],'chat-two','foreign')
        self.assertNotIn('cover',self.service.get(self.p['id'])['assets'])

    def test_imported_json_recompiled_from_original_srt(self):
        doc=compile_overlay(SRT,CARDS)
        self.assertEqual(validated_document(json.dumps(doc),SRT),doc)
        for mutate in (lambda d:d['cards'][0].update(start=.3), lambda d:d['cards'][0]['params'].update(text='保温12小时'), lambda d:d.update(css='bad'), lambda d:d['cards'][0]['params'].update(offsetX=3)):
            d=json.loads(json.dumps(doc));mutate(d)
            with self.assertRaises(ValueError):validated_document(json.dumps(d),SRT)
        with self.assertRaises(ValueError):validated_document('[]',SRT)

    def test_project_cas_ownership_utf8_and_route_boundaries(self):
        self.import_file('srt','test.srt',SRT.encode())
        asset=self.p['assets']['srt'];other=self.service.create('另一个任务')
        with self.assertRaises(ValueError):self.service.file(other['id'],asset['id'])
        with self.assertRaises(Conflict):self.service.patch(self.p['id'],{'revision':0,'script':'不能覆盖'})
        for slot,name,raw in [('srt','bad.srt',b'\xff'),('plan','bad.json',b'['),('video','evil.mp4',b'#EXTM3U\nfile:///secret'),('cover','fake.png',b'fake'),('srt','../escape.srt',SRT.encode())]:
            with self.assertRaises(ValueError):self.import_file(slot,name,raw)
        app=FastAPI()
        async def body(req):return await req.json()
        app.include_router(routes(self.service,body),prefix='/api/miniclaw')
        client=TestClient(app);base='/api/miniclaw/creator/projects/'+self.p['id']
        r=client.post(base+'/assets/srt?name=large.srt&revision='+str(self.p['revision']),content=b'x'*65537)
        self.assertEqual(r.status_code,413)
        self.assertFalse(list(self.service.project_folder(self.p['id']).glob('upload-*.tmp')))
        self.assertEqual(client.patch(base,json={'revision':0,'facts':'x'}).status_code,409)
        self.assertEqual(client.get(base+'/files/'+asset['id']).content,SRT.encode())
        self.assertEqual(client.post(base+'/render',json={'revision':self.p['revision'],'shell':'bad'}).status_code,400)
        self.assertEqual(client.get(base,headers={'Origin':'https://untrusted.example'}).status_code,403)
        self.import_file('srt','replacement.srt',SRT.encode())
        used=sum(f.stat().st_size for f in self.service.project_folder(self.p['id']).rglob('*') if f.is_file())
        self.assertEqual(used,len(SRT.encode())*2)  # replacing a reference must not remove the old file from quota
        with self.store.connect() as db:
            self.service._budget(db,self.p['id'],1024*1024*1024-used)
            with self.assertRaises(ValueError):self.service._budget(db,self.p['id'],1024*1024*1024-used+1)

    def source(self):
        if not self.ffmpeg or not self.ffprobe: self.skipTest('FFmpeg/FFprobe未准备：真实媒体检查不能算通过')
        path=self.dir/'source.mp4'
        subprocess.run([self.ffmpeg,'-v','error','-f','lavfi','-i','testsrc2=size=360x640:rate=30:duration=6','-f','lavfi','-i','sine=frequency=440:duration=6',
                        '-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-c:a','aac','-shortest','-metadata','title=PRIVATE_FIXTURE_METADATA','-threads','2',str(path)],check=True,timeout=30)
        return path

    def frame(self,path,second,name):
        target=self.dir/name
        subprocess.run([self.ffmpeg,'-v','error','-ss',str(second),'-i',str(path),'-frames:v','1',str(target)],check=True,timeout=20)
        with Image.open(target) as im:return im.convert('RGB')

    def wait(self, identifier):
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            j=self.service.job(self.p['id'],identifier)
            if j['state'] not in ('queued','running'):return j
            time.sleep(.1)
        self.fail('合成未完成')

    def test_real_portrait_audio_package_stale_and_restart(self):
        source=self.source();original=hashlib.sha256(source.read_bytes()).hexdigest()
        self.import_file('video','source.mp4',source.read_bytes());self.import_file('srt','same.srt',SRT.encode())
        self.import_file('plan','plan.json',json.dumps(compile_overlay(SRT,CARDS),ensure_ascii=False).encode())
        self.p=self.service.patch(self.p['id'],{'revision':self.p['revision'],'caption':'虚构技术演示','facts':'陶瓷杯','script':'每天一杯，慢一点。','provenance':'自制画面＋440Hz测试音，不是真人口播'})
        j=self.service.render(self.p['id'],self.p['revision']);fn,args=self.queue.calls.pop();fn(*args)
        self.assertEqual(self.service.job(self.p['id'],j['id'])['state'],'succeeded')
        self.p=self.service.get(self.p['id']);output=self.p['outputs'][-1];path=self.service.file(self.p['id'],output['id'])[0]
        meta=probe(path,self.ffprobe);self.assertEqual((meta['width'],meta['height']),(720,1280));self.assertTrue(meta['audio']);self.assertAlmostEqual(meta['duration'],6,delta=.08)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),original)
        tags=subprocess.run([self.ffprobe,'-v','error','-show_entries','format_tags=title','-of','json',str(path)],capture_output=True,check=True,timeout=20)
        self.assertNotIn('PRIVATE_FIXTURE_METADATA',tags.stdout.decode())
        frame=self.frame(path,.8,'card.png');r,g,b=frame.getpixel((60,180));self.assertGreater(b,r+60);self.assertGreater(b,g+40)
        self.p=self.service.package(self.p['id'],self.p['revision']);pack=self.p['packages'][-1]
        with zipfile.ZipFile(self.service.file(self.p['id'],pack['id'])[0]) as z:
            self.assertEqual(set(z.namelist()),{'video.mp4','srt.srt','facts.txt','script.txt','caption.txt','manifest.json'})
            self.assertEqual(z.read('video.mp4'),path.read_bytes());self.assertEqual(json.loads(z.read('manifest.json'))['status'],'ready_for_manual_publish')
        restored=Creator(self.store,ROOT,CapturedExecutor()).get(self.p['id']);self.assertTrue(restored['steps']['video']);self.assertTrue(restored['steps']['package'])
        self.p=self.service.patch(self.p['id'],{'revision':self.p['revision'],'caption':'另一个标题'});self.assertTrue(self.p['steps']['video']);self.assertFalse(self.p['steps']['package'])
        self.p=self.service.patch(self.p['id'],{'revision':self.p['revision'],'mode':'landscape'});self.assertFalse(self.p['steps']['video'])
        with self.assertRaises(ValueError):self.service.package(self.p['id'],self.p['revision'])

    def test_real_external_layer_does_not_freeze_or_trim_source(self):
        source=self.source();overlay=self.dir/'alpha.mov';work=self.dir/'compose';work.mkdir();out=work/'video.mp4'
        layer=Image.new('RGBA',(1280,720));layer.paste((255,0,0,255),(20,20,150,150));png=self.dir/'layer.png';layer.save(png)
        subprocess.run([self.ffmpeg,'-v','error','-loop','1','-framerate','30','-i',str(png),'-t','2',
                        '-c:v','prores_ks','-profile:v','4','-pix_fmt','yuva444p10le','-threads','2',str(overlay)],check=True,timeout=40)
        args=command(source,probe(source,self.ffprobe),out,work,self.ffmpeg,'landscape',overlay=overlay,overlay_meta=probe(overlay,self.ffprobe))
        execute(args,work,timeout=60);meta=probe(out,self.ffprobe)
        self.assertAlmostEqual(meta['duration'],6,delta=.08);self.assertTrue(meta['audio'])
        first=self.frame(out,.8,'first.png');last=self.frame(out,4,'last.png')
        self.assertGreater(first.getpixel((70,70))[0],150);self.assertLess(max(last.getpixel((70,70))),20)
        with self.assertRaises(ValueError):command(source,probe(source,self.ffprobe),self.dir/'bad.mp4',work,self.ffmpeg,'portrait',overlay=overlay,overlay_meta=probe(overlay,self.ffprobe))

    def test_cancel_and_restart_never_publish_queued_output(self):
        source=self.source();self.import_file('video','source.mp4',source.read_bytes());self.import_file('srt','same.srt',SRT.encode());self.import_file('plan','plan.json',json.dumps(compile_overlay(SRT,CARDS)).encode())
        j=self.service.render(self.p['id'],self.p['revision']);self.service.cancel(self.p['id'],j['id']);fn,args=self.queue.calls.pop();fn(*args)
        self.assertEqual(self.service.job(self.p['id'],j['id'])['state'],'canceled');self.assertFalse(self.service.get(self.p['id'])['outputs'])
        j=self.service.render(self.p['id'],self.p['revision']);restored=Creator(self.store,ROOT,CapturedExecutor())
        self.assertEqual(restored.job(self.p['id'],j['id'])['state'],'failed');fn,args=self.queue.calls.pop();fn(*args)
        self.assertFalse(restored.get(self.p['id'])['outputs'])

    def test_execute_cancel_kills_owned_encoder(self):
        if not self.ffmpeg:self.skipTest('FFmpeg未准备')
        work=self.dir/'cancel';work.mkdir()
        args=[self.ffmpeg,'-v','error','-re','-f','lavfi','-i','testsrc2=duration=60:size=720x1280','-f','null','-']
        start=time.monotonic()
        with self.assertRaisesRegex(ValueError,'取消'):execute(args,work,canceled=lambda:True,timeout=10)
        self.assertLess(time.monotonic()-start,5)

    def test_delayed_source_audio_keeps_relative_start(self):
        source=self.source();delayed=self.dir/'delayed.mp4';work=self.dir/'delay-work';work.mkdir();out=work/'video.mp4'
        subprocess.run([self.ffmpeg,'-v','error','-i',str(source),'-itsoffset','0.6','-i',str(source),'-map','0:v:0','-map','1:a:0','-c','copy',str(delayed)],check=True,timeout=20)
        meta=probe(delayed,self.ffprobe);self.assertGreater(meta['audio_offset'],.5)
        execute(command(delayed,meta,out,work,self.ffmpeg),work,timeout=60)
        decoded=subprocess.run([self.ffmpeg,'-v','error','-i',str(out),'-vn','-ac','1','-ar','8000','-f','s16le','-'],capture_output=True,check=True,timeout=20)
        samples=array.array('h');samples.frombytes(decoded.stdout)
        self.assertLess(max(abs(v) for v in samples[:1600]),50)
        self.assertGreater(max(abs(v) for v in samples[6400:8000]),1000)


if __name__=='__main__':unittest.main(verbosity=2)
