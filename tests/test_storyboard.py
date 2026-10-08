"""Exercise the real film recipe without cloud calls; test adoption ownership and CAS."""
import io
import json
import sys
import tempfile
import unittest
import wave
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PIL import Image
from miniclaw_web import storyboard
from miniclaw_web.creator import Creator
from miniclaw_web.canvas import Conflict
from miniclaw_web.store import Store
from miniclaw_web.video import binaries, probe
from miniclaw_web.attachments import upload


class StoryboardTests(unittest.TestCase):
    def test_reediting_same_project_reuses_audio_without_cloud_call(self):
        class Queue:
            def submit(self, fn, *args): self.fn,self.args=fn,args
        with tempfile.TemporaryDirectory() as temp:
            queue=Queue();service=Creator(Store(Path(temp)/'home'),ROOT,queue);p=service.create()
            p=service.patch(p['id'],{'revision':0,'script':'一杯茶。','method':'storyboard'})
            for slot in ('cover',):
                image=Path(temp)/'input.png';Image.new('RGB',(32,48),'green').save(image)
                p=service.import_file(p['id'],p['revision'],slot,slot+'.png',image)
            old_id='b'*32;old=service.project_folder(p['id'])/('job-'+old_id);old.mkdir();raw=b'cached-original-wav'
            (old/'speech-0.wav').write_bytes(raw)
            with service.store.connect() as db:
                stored=service._get(db,p['id']);stored['outputs'].append({'id':old_id,'render_key':'old','production':{'speech':storyboard.settings(),'segments':[{'text':'一杯茶。'}],'requests':[{'request_id':'original-receipt'}]}});service._save(db,stored)
            def renderer(p,assets,ffmpeg,work,canceled,speaker):
                target=work/'speech-0.wav';receipt=speaker('一杯茶。',target,canceled)
                self.assertEqual(target.read_bytes(),raw);self.assertTrue(receipt['reused']);(work/'video.mp4').write_bytes(b'fixture-video')
                return {'requests':[receipt]}
            with patch.dict('os.environ',{'DASHSCOPE_API_KEY':'test-only'}),patch.object(storyboard,'synthesize',side_effect=AssertionError('must not bill again')),patch.object(storyboard,'render',side_effect=renderer),patch('miniclaw_web.creator.probe',return_value={'width':1080,'height':1920,'audio':True,'duration':2}):
                job=service.render(p['id'],p['revision']);queue.fn(*queue.args)
                self.assertEqual(service.job(p['id'],job['id'])['state'],'succeeded')

    def test_url_and_script_bounds(self):
        good='http://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/one.wav?Signature=test'
        self.assertTrue(storyboard.audio_url(good).startswith('https://'))
        for value in ('https://localhost/a', 'https://aliyuncs.com/a', 'https://evil.aliyuncs.com/a', 'https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com@evil.com/a', good.replace('/one.wav', ':444/one.wav')):
            with self.assertRaises(ValueError): storyboard.audio_url(value)
        self.assertEqual(storyboard.lines('一杯茶。\n慢一点。'),['一杯茶。','慢一点。'])
        for text in ('', 'x'*37, '\n'.join(['茶。']*13), 'x'*321):
            with self.assertRaises(ValueError): storyboard.lines(text)

    def test_cover_adoption_immutable_owned_cas(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/'home'); service=Creator(store,ROOT); p=service.create()
            raw=io.BytesIO(); Image.new('RGB',(32,48),'green').save(raw,format='PNG')
            import base64
            a=upload(store,'owner-one','cover.png',base64.b64encode(raw.getvalue()).decode())
            with self.assertRaises(ValueError):service.adopt_cover(p['id'],0,'owner-two',a['id'])
            p=service.adopt_cover(p['id'],0,'owner-one',a['id'])
            path,_=service.file(p['id'],p['assets']['cover']['id']);self.assertEqual(path.read_bytes(),raw.getvalue())
            self.assertEqual(p['assets']['cover']['source']['attachment'],a['id'])
            with self.assertRaises(Conflict):service.adopt_cover(p['id'],0,'owner-one',a['id'])
            self.assertEqual(service.get(p['id'])['revision'],1)
            self.assertFalse(list(service.project_folder(p['id']).glob('adopt-*.tmp')))
            self.assertNotEqual(Creator.render_key({**p,'method':'storyboard','script':'一杯。'}),Creator.render_key({**p,'method':'storyboard','script':'慢一点。'}))
            service.executor.shutdown()

    def test_actual_recipe_audio_subtitles_and_three_shots(self):
        with tempfile.TemporaryDirectory() as temp:
            work=Path(temp);assets={}
            for slot,color in [('cover','#dbe5b0'),('detail','#59764b'),('scene','#a7bac5')]:
                assets[slot]=work/(slot+'.png');Image.new('RGB',(540,960),color).save(assets[slot])
            calls=[]
            def speaker(text,target,canceled):
                calls.append(text)
                with wave.open(str(target),'wb') as wav:
                    wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000);wav.writeframes(b'\0\0'*12000)
                raw=bytearray(target.read_bytes());raw[40:44]=(2**31-100).to_bytes(4,'little');target.write_bytes(raw)
                return {'request_id':'offline-fixture'}
            ffmpeg,ffprobe=binaries(ROOT)
            p={'script':'一杯茶。\n看杯沿。\n看晨光。\n慢一点。','mode':'portrait'}
            result=storyboard.render(p,assets,ffmpeg,work,lambda:False,speaker=speaker)
            meta=probe(work/'video.mp4',ffprobe)
            self.assertEqual((meta['width'],meta['height']),(1080,1920));self.assertTrue(meta['audio'])
            self.assertEqual([v['slot'] for v in result['segments']],['cover','detail','scene','cover'])
            self.assertEqual(len(calls),4);self.assertIn('00:00:00,800 --> 00:00:01,300',(work/'generated.srt').read_text(encoding='utf-8'))
            self.assertTrue(all(abs(s['end']-s['start']-.5)<.001 for s in result['segments']))

    def test_actual_single_photo_recipe_falls_back_for_every_sentence(self):
        with tempfile.TemporaryDirectory() as temp:
            work=Path(temp);cover=work/'cover.png';Image.new('RGB',(540,960),'green').save(cover)
            def speaker(text,target,canceled):
                with wave.open(str(target),'wb') as wav:
                    wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000);wav.writeframes(b'\0\0'*12000)
                return {'request_id':'offline-fixture'}
            ffmpeg,ffprobe=binaries(ROOT)
            result=storyboard.render({'script':'一把茶壶。\n看壶身。\n看把手。\n慢一点。','mode':'portrait'}, {'cover':cover},ffmpeg,work,lambda:False,speaker=speaker)
            meta=probe(work/'video.mp4',ffprobe)
            self.assertTrue(meta['audio']);self.assertEqual((meta['width'],meta['height']),(1080,1920))
            self.assertEqual([s['slot'] for s in result['segments']],['cover']*4)
            self.assertEqual(result['recipe'],'original-photo-motion-editorial-v3')
            self.assertIn('看把手。',(work/'generated.srt').read_text(encoding='utf-8'))


if __name__=='__main__':unittest.main(verbosity=2)
