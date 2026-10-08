"""Local service acceptance with original synthetic media; no cloud/model/publish call."""
import hashlib
import argparse
import json
import re
import subprocess
import sys
import time
import wave
import zipfile
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from miniclaw_web.overlay import compile_overlay
from miniclaw_web.video import binaries, font_path, probe


def fixture(folder):
    folder.mkdir(parents=True,exist_ok=True)
    ffmpeg,_=binaries(ROOT)
    if not ffmpeg or not font_path():raise RuntimeError('需要本机FFmpeg和中文字体')
    # Windows-only test voice; never treated as an installed app TTS feature.
    if sys.platform!='win32':raise RuntimeError('本机语音样片脚本使用Windows SAPI；其他系统请运行test_creator技术样片')
    ps=folder/'make-test-speech.ps1'
    quoted=lambda p:"'"+str(p).replace("'","''")+"'"
    lines=["$ErrorActionPreference = 'Stop'", "$sampleVoice = New-Object -ComObject SAPI.SpVoice", "$sampleVoice.Voice = $sampleVoice.GetVoices('Language=804').Item(0)"]
    for i,text in enumerate(('这是一个虚构的陶瓷杯。','每天一杯，慢一点。'),1):
        lines += ["$sampleStream = New-Object -ComObject SAPI.SpFileStream", f'$sampleStream.Open({quoted(folder/f"speech-{i}.wav")}, 3, $false)',
                  '$sampleVoice.AudioOutputStream = $sampleStream', f"$null = $sampleVoice.Speak('{text}')", '$sampleStream.Close()']
    ps.write_text('\n'.join(lines),encoding='utf-8-sig')
    subprocess.run(['pwsh','-NoProfile','-File',str(ps)],check=True,timeout=30)
    clips=[]
    for i in (1,2):
        with wave.open(str(folder/f'speech-{i}.wav'),'rb') as reader:
            clips.append((reader.getparams(),reader.readframes(reader.getnframes())))
    params=clips[0][0]
    if params[:3]!=clips[1][0][:3]:raise RuntimeError('测试音频格式不一致')
    def silence(seconds):return b'\0'*round(seconds*params.framerate)*params.nchannels*params.sampwidth
    lead=.25;gap=.5;end1=lead+clips[0][0].nframes/params.framerate;start2=end1+gap;end2=start2+clips[1][0].nframes/params.framerate
    audio=folder/'speech.wav'
    with wave.open(str(audio),'wb') as writer:
        writer.setparams(params);writer.writeframes(silence(lead)+clips[0][1]+silence(gap)+clips[1][1]+silence(.75))
    def clock(t):
        ms=round(t*1000);return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'
    srt=f'1\n{clock(lead)} --> {clock(end1)}\n这是一个虚构的陶瓷杯。\n\n2\n{clock(start2)} --> {clock(end2)}\n每天一杯，慢一点。\n'
    (folder/'demo.srt').write_text(srt,encoding='utf-8')
    cards=[dict(id='intro',kind='punch-pill',cue_start=1,cue_end=1,params={'text':'陶瓷杯','position':'top-left'}),
           dict(id='quote',kind='quote-lockup',cue_start=2,cue_end=2,params={'quote':'每天一杯，慢一点。','side':'right'})]
    (folder/'demo.json').write_text(json.dumps(compile_overlay(srt,cards),ensure_ascii=False,indent=2),encoding='utf-8')
    cover=Image.new('RGB',(720,1280),'#EEF0DE');draw=ImageDraw.Draw(cover);title=ImageFont.truetype(font_path(),44);small=ImageFont.truetype(font_path(),23)
    draw.text((70,70),'每天一杯，慢一点',fill='#213A2A',font=title)
    draw.ellipse((165,850,570,930),fill='#CBD2BB');draw.rounded_rectangle((190,390,480,890),radius=55,fill='#E1AB76',outline='#8C653E',width=7)
    draw.ellipse((170,350,500,450),fill='#DFC8A8',outline='#8C653E',width=7);draw.ellipse((210,368,460,414),fill='#F1E2C5')
    draw.arc((430,470,625,740),270,90,fill='#8C653E',width=20)
    draw.text((70,1090),'虚构技术样片 · 非商品实拍',fill='#566048',font=small)
    cover.save(folder/'cover.png')
    source=folder/'source.mp4'
    if source.exists():source.unlink()  # exact private fixture path, never user material
    subprocess.run([ffmpeg,'-v','error','-loop','1','-framerate','30','-i',str(folder/'cover.png'),'-i',str(audio),'-t',str(end2+.75),
                    '-c:v','libx264','-preset','veryfast','-crf','22','-pix_fmt','yuv420p','-c:a','aac','-movflags','+faststart','-threads','2',str(source)],check=True,timeout=60)
    return {'source':'original illustration + local Microsoft Huihui synthetic speech; not real recording', 'subtitle_times_from_actual_wav_segments':True}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--resume',action='store_true',help='仅复核已有验收任务，不新建或重做媒体');opts=parser.parse_args()
    folder=ROOT/'.codex/verification/creator-flow'
    previous=json.loads((folder/'report.json').read_text(encoding='utf-8')) if opts.resume else None
    fixture_info=previous['fixture'] if previous else fixture(folder)
    base='http://127.0.0.1:9120'
    html=httpx.get(base,trust_env=False).text;token=re.search(r'__HERMES_SESSION_TOKEN__="([^"]+)"',html).group(1)
    client=httpx.Client(base_url=base,headers={'X-Hermes-Session-Token':token},trust_env=False,timeout=60)
    api='/api/miniclaw/creator';report={'fixture':fixture_info,'model_called':False,'platform_published':False}
    assert client.get(api+'/projects').status_code==200
    assert httpx.get(base+api+'/projects',trust_env=False).status_code in (401,403)
    rejected=client.get(api+'/projects',headers={'Origin':'https://untrusted.example'})
    assert rejected.status_code==403, (rejected.status_code,rejected.text[:160])
    if previous:
        pid=previous['project_id'];path=api+'/projects/'+pid;p=client.get(path).json()
    else:
        p=client.post(api+'/projects',json={'name':'验收样片 · 虚构陶瓷杯'}).json();pid=p['id'];path=api+'/projects/'+pid
        p=client.patch(path,json={'revision':p['revision'],'facts':'虚构练习商品：陶瓷杯。没有品牌、容量或功能证据。', 'script':'这是一个虚构的陶瓷杯。每天一杯，慢一点。',
                                 'caption':'技术验收样片：每天一杯，慢一点。#创作练习', 'provenance':fixture_info['source']}).json()
        for slot,name in [('video','source.mp4'),('srt','demo.srt'),('plan','demo.json'),('cover','cover.png')]:
            r=client.post(path+'/assets/'+slot,params={'revision':p['revision'],'name':name},content=(folder/name).read_bytes(),headers={'Content-Type':'application/octet-stream'})
            r.raise_for_status();p=r.json()
    hashes={slot:a['sha256'] for slot,a in p['assets'].items()}
    start=time.monotonic()
    if not previous:
        j=client.post(path+'/render',json={'revision':p['revision']}).json()
        while time.monotonic()-start<120:
            r=client.get(path);r.raise_for_status();p=r.json();state=next(x for x in p['jobs'] if x['id']==j['id'])
            if state['state'] not in ('running','queued'):break
            time.sleep(.3)
        assert state['state']=='succeeded',state
    out=next(o for o in reversed(p['outputs']) if o['current']);r=client.get(path+'/files/'+out['id']);r.raise_for_status();(folder/'video.mp4').write_bytes(r.content)
    assert hashlib.sha256(r.content).hexdigest()==out['sha256']
    meta=probe(folder/'video.mp4',binaries(ROOT)[1]);assert (meta['width'],meta['height'])==(720,1280) and meta['audio']
    if not previous:p=client.post(path+'/package',json={'revision':p['revision']}).json()
    pack=next(z for z in reversed(p['packages']) if z['current'])
    r=client.get(path+'/files/'+pack['id']);r.raise_for_status();(folder/'publish-package.zip').write_bytes(r.content)
    with zipfile.ZipFile(folder/'publish-package.zip') as z:
        assert z.read('video.mp4')==(folder/'video.mp4').read_bytes()
        assert z.read('cover.png')==(folder/'cover.png').read_bytes()
        manifest=json.loads(z.read('manifest.json'));assert manifest['status']=='ready_for_manual_publish'
    for slot,a in p['assets'].items():
        r=client.get(path+'/files/'+a['id']);r.raise_for_status();assert hashlib.sha256(r.content).hexdigest()==hashes[slot]
    if not previous:
        other=client.post(api+'/projects',json={'name':'归属拒绝技术检查'}).json()
        assert client.get(api+'/projects/'+other['id']+'/files/'+out['id']).status_code==400
    report.update(status='passed',project_id=pid,metadata=meta,output_id=out['id'],package_id=pack['id'],all_inputs_unchanged=True,authenticated_download=True,
                  origin_and_missing_auth_rejected=True,zip_contents_match=True,resumed_existing_task=opts.resume,elapsed_seconds=round(time.monotonic()-start,2),steps=p['steps'])
    (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
