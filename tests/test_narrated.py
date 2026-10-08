"""Narrated footage boundaries and fixed instruction-TTS protocol."""
import io
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from miniclaw_web import narrated, storyboard
from miniclaw_web.creator import Creator
from miniclaw_web.video import binaries, execute, probe


class NarratedTests(unittest.TestCase):
    def speaker(self, text, target, canceled):
        with wave.open(str(target),'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000);wav.writeframes(b'\0\0'*12000)
        return {'request_id':'offline-fixture'}

    def test_instruction_protocol_and_style_signature(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict('os.environ',{'DASHSCOPE_API_KEY':'test-only'}),patch.object(storyboard.httpx,'Client') as client:
            live=client.return_value.__enter__.return_value
            live.post.return_value.status_code=200
            live.post.return_value.json.return_value={'output':{'audio':{'url':'http://dashscope-a717.oss-cn-beijing.aliyuncs.com/a.wav?fixture=1'}},'request_id':'fixture'}
            stream=live.stream.return_value.__enter__.return_value;stream.status_code=200;stream.iter_bytes.return_value=[b'fixture-wav']
            storyboard.synthesize('先慢下来。',Path(temp)/'one.wav',lambda:False,style='warm')
            payload=live.post.call_args.kwargs['json']
            self.assertEqual(payload['model'],'qwen3-tts-instruct-flash');self.assertEqual(payload['input']['voice'],'Serena')
            self.assertTrue(payload['input']['instructions']);self.assertTrue(payload['input']['optimize_instructions'])
            self.assertEqual(live.stream.call_args.args[1],'https://dashscope-a717.oss-cn-beijing.aliyuncs.com/a.wav?fixture=1')
            for url in ('https://untrusted.oss-cn-beijing.aliyuncs.com/a.wav','https://dashscope-a717.oss-cn-beijing.aliyuncs.com.evil.example/a.wav','https://user@dashscope-a717.oss-cn-beijing.aliyuncs.com/a.wav'):
                with self.assertRaises(ValueError):storyboard.audio_url(url)
            p={'method':'narrated','assets':{'video':{'id':'owned'}},'script':'先慢下来。','mode':'portrait'}
            self.assertNotEqual(Creator.render_key(p),Creator.render_key({**p,'speech_style':'warm'}))
            self.assertNotEqual(Creator.render_key(p),Creator.render_key({**p,'script':'再看一眼。'}))
            self.assertEqual(storyboard.settings()['voice'],'Cherry')
            with self.assertRaises(ValueError):storyboard.settings('arbitrary-model')

    def test_actual_footage_keeps_duration_replaces_audio_and_measures_cues(self):
        with tempfile.TemporaryDirectory() as temp:
            work=Path(temp);ffmpeg,ffprobe=binaries(ROOT);source=work/'source.mp4'
            execute([ffmpeg,'-v','error','-nostdin','-f','lavfi','-i','testsrc2=size=180x320:rate=30','-f','lavfi','-i','sine=frequency=1200:sample_rate=48000','-t','4','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(source)],work)
            p={'script':'先慢下来。\n再看一眼。','mode':'portrait','speech_style':'warm','assets':{'video':probe(source,ffprobe)}}
            result=narrated.render(p,source,ffmpeg,work,lambda:False,speaker=self.speaker)
            meta=probe(work/'video.mp4',ffprobe)
            self.assertEqual((meta['width'],meta['height']),(1080,1920));self.assertTrue(meta['audio']);self.assertAlmostEqual(meta['duration'],4,delta=.1)
            self.assertEqual(result['source_audio'],'replaced-with-narration')
            self.assertIn('00:00:00,350 --> 00:00:00,850',(work/'generated.srt').read_text(encoding='utf-8'))
            self.assertEqual(len(result['segments']),2)
            self.assertAlmostEqual(result['segments'][-1]['end'],2.8,places=2)
            self.assertAlmostEqual(result['sentence_gap_seconds'],1.45,places=2)
            import subprocess
            raw=subprocess.check_output([ffmpeg,'-v','error','-i',str(work/'video.mp4'),'-map','0:a:0','-f','s16le','-ac','1','-ar','8000','-'])
            import array
            samples=array.array('h');samples.frombytes(raw)
            self.assertLess(max(map(abs,samples)),10) # Original 1200Hz audio was not mixed back.

    def test_background_mix_and_missing_track_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            work=Path(temp);ffmpeg,ffprobe=binaries(ROOT);source=work/'source.mp4'
            execute([ffmpeg,'-v','error','-nostdin','-f','lavfi','-i','color=c=green:s=180x320:r=30','-itsoffset','0.6','-f','lavfi','-i','sine=frequency=800:sample_rate=48000','-t','3','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(source)],work)
            p={'script':'先慢下来。','mode':'portrait','keep_source_audio':True,'assets':{'video':probe(source,ffprobe)}}
            result=narrated.render(p,source,ffmpeg,work,lambda:False,speaker=self.speaker)
            self.assertEqual(result['source_audio'],'ducked-under-narration')
            import subprocess,array
            raw=subprocess.check_output([ffmpeg,'-v','error','-i',str(work/'video.mp4'),'-map','0:a:0','-f','s16le','-ac','1','-ar','8000','-'])
            samples=array.array('h');samples.frombytes(raw);self.assertGreater(max(map(abs,samples)),100)
            self.assertLess(max(map(abs,samples[:1600])),10);self.assertGreater(max(map(abs,samples[6400:8000])),100)
            p['assets']['video']['audio']=False
            with self.assertRaisesRegex(ValueError,'没有原音轨'):
                narrated.render(p,source,ffmpeg,work,lambda:False,speaker=MagicMock(side_effect=AssertionError('must not request TTS')))

    def test_short_source_stops_before_requesting_remaining_sentences(self):
        with tempfile.TemporaryDirectory() as temp:
            work=Path(temp);ffmpeg,_=binaries(ROOT);calls=[]
            def speaker(text,target,canceled):calls.append(text);return self.speaker(text,target,canceled)
            p={'script':'先慢下来。\n再看一眼。','mode':'portrait','assets':{'video':{'duration':1}}}
            with self.assertRaisesRegex(ValueError,'后续句子未继续请求'):
                narrated.render(p,work/'unused.mp4',ffmpeg,work,lambda:False,speaker=speaker)
            self.assertEqual(len(calls),1);self.assertFalse((work/'video.mp4').exists())


if __name__=='__main__':unittest.main(verbosity=2)
