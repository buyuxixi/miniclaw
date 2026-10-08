"""This sample's original edit. Default: local footage only; --render: explicit cloud narration."""
import argparse
import array
import hashlib
import json
import math
import re
import time
import wave
from pathlib import Path
import sys
import httpx

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from miniclaw_web.video import binaries,execute,probe

FOLDER=ROOT/'outputs/tea-film-v3'
SCRIPT='先别急，给自己倒一杯茶。\n看茶汤落下来，光也落进杯里。\n淡一点，浓一点，都有自己的节奏。\n日常的小事，也可以慢慢来。\n把这一刻，留给自己。'
SHOTS=[
    ('action-close',8296117,0,3.0,1,False,'水流入杯，动作开场'),
    ('liquid-detail',8296117,2.65,3.2,.9,True,'茶汤与通透玻璃，细节证据'),
    ('setting-medium',8296134,0,4.5,1,False,'人物与茶具，交代日常场景'),
    ('hands-detail',8296134,4.5,4.2,.95,True,'手部动作，让节奏落到具体事情'),
    ('quiet-return',8296134,8.35,5.1,.85,False,'放下茶壶，动作完成后停留'),
]


def prepare():
    FOLDER.mkdir(parents=True,exist_ok=True);ffmpeg,ffprobe=binaries(ROOT)
    if all((FOLDER/name).is_file() for name in ('footage-edit.mp4','cover.png','sources.json')):
        print('Existing sample edit retained; native render uses saved footage.',flush=True)
        return
    sources=[]
    for identifier in (8296117,8296134):
        source=FOLDER/f'pexels-{identifier}-original.mp4';meta=probe(source,ffprobe)
        sources.append({'id':identifier,'author':'Anna Pou','page':f'https://www.pexels.com/video/{"a-person-pouring-tea" if identifier==8296117 else "a-woman-pouring-tea-on-a-glass"}-{identifier}/',
                        'license':'Pexels License','license_url':'https://www.pexels.com/license/','sha256':hashlib.sha256(source.read_bytes()).hexdigest(),**meta})
    clips=[];timeline=[];cursor=0
    font=Path('C:/Windows/Fonts/msyh.ttc');(FOLDER/'sans.ttc').write_bytes(font.read_bytes())
    serif=Path('C:/Windows/Fonts/simkai.ttf');(FOLDER/'title.ttf').write_bytes(serif.read_bytes())
    (FOLDER/'opening.txt').write_text('先别急。',encoding='utf-8')
    (FOLDER/'end-title.txt').write_text('把日常\n留给一杯茶',encoding='utf-8')
    (FOLDER/'end-title-one.txt').write_text('把日常',encoding='utf-8')
    (FOLDER/'end-title-two.txt').write_text('留给一杯茶',encoding='utf-8')
    (FOLDER/'end-small.txt').write_text('TEA / EVERYDAY RITUALS',encoding='utf-8')
    for index,(name,identifier,start,duration,speed,close,purpose) in enumerate(SHOTS):
        source=next(s for s in sources if s['id']==identifier)
        if start+duration*speed>source['duration']+.05:raise ValueError('选段超过原素材，禁止自动循环')
        clip=FOLDER/f'edit-{index}.mp4'
        framing='crop=1728:3072:216:620,' if close else ''
        vf=framing+f'scale=1080:1920,setsar=1,setpts=(PTS-STARTPTS)/{speed},fps=30,eq=contrast=1.07:saturation=1.08:gamma=0.98,colorbalance=rs=0.015:bs=-0.012'
        # The action and native spoken subtitle carry the opening; avoid a
        # redundant title over the moving teapot with inconsistent contrast.
        if not clip.is_file():
            execute([ffmpeg,'-v','error','-nostdin','-y','-ss',str(start),'-i',f'pexels-{identifier}-original.mp4','-vf',vf,'-t',str(duration),'-an','-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-threads','2',clip.name],FOLDER,cwd=FOLDER)
        if abs(probe(clip,ffprobe)['duration']-duration)>.15:raise ValueError('已有选段不完整；请检查本地中间文件')
        clips.append(clip)
        timeline.append({'shot':index+1,'name':name,'start':round(cursor,3),'end':round(cursor+duration,3),'source':identifier,'source_start':start,'speed':speed,'framing':'detail-crop' if close else 'original-framing','purpose':purpose})
        cursor+=duration
    end=FOLDER/'edit-end.mp4'
    vf="trim=duration=0.033333,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=3,scale=1080:1920,setsar=1,fps=30,eq=contrast=1.07:saturation=1.08:gamma=0.98,drawbox=x=0:y=0:w=iw:h=610:color=0xFAFAF7@0.98:t=fill,drawtext=fontfile=sans.ttc:textfile=end-small.txt:expansion=none:fontsize=22:fontcolor=0x807A70:x=80:y=145,drawtext=fontfile=title.ttf:textfile=end-title-one.txt:expansion=none:fontsize=96:fontcolor=0x302D2E:x=80:y=240,drawtext=fontfile=title.ttf:textfile=end-title-two.txt:expansion=none:fontsize=96:fontcolor=0x302D2E:x=80:y=370,fade=t=in:st=0:d=0.25:color=0xFAFAF7"
    if not end.is_file():
        execute([ffmpeg,'-v','error','-nostdin','-y','-ss','2.4','-i','pexels-8296117-original.mp4','-vf',vf,'-t','3','-an','-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-threads','2',end.name],FOLDER,cwd=FOLDER)
    clips.append(end);timeline.append({'shot':6,'name':'end-card','start':cursor,'end':cursor+3,'source':8296117,'source_start':2.4,'purpose':'真实产品定格与中文片尾'});duration=cursor+3
    (FOLDER/'edit-list.txt').write_text(''.join(f"file '{f.name}'\n" for f in clips),encoding='utf-8')
    # Original sparse pentatonic cue; no downloaded composition or artist imitation.
    rate=48000;values=[0.0]*round(duration*rate)
    for start,midi in [(0,60),(2.9,67),(5.7,72),(8.9,74),(12.1,67),(15.4,69),(18.5,64),(20.5,60)]:
        freq=440*2**((midi-69)/12)
        for i in range(min(round(4.5*rate),len(values)-round(start*rate))):
            t=i/rate;envelope=(1-math.exp(-t*35))*math.exp(-t/1.5)
            tone=sum(amplitude*math.sin(2*math.pi*freq*multiple*t)*math.exp(-t*multiple*.12) for multiple,amplitude in [(1,.7),(2,.16),(3,.08)])
            values[round(start*rate)+i]+=.085*envelope*tone
    pcm=array.array('h',(round(max(-1,min(1,v))*32767) for v in values))
    with wave.open(str(FOLDER/'original-score.wav'),'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(rate);w.writeframes(pcm.tobytes())
    execute([ffmpeg,'-v','error','-nostdin','-y','-f','concat','-safe','1','-i','edit-list.txt','-i','original-score.wav','-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','192k','-ar','48000','-ac','2','-af',f'afade=t=in:d=0.4,afade=t=out:st={duration-1.2}:d=1.2','-t',str(duration),'-map_metadata','-1','-movflags','+faststart','footage-edit.mp4'],FOLDER,cwd=FOLDER)
    execute([ffmpeg,'-v','error','-nostdin','-y','-ss',str(duration-1),'-i','footage-edit.mp4','-frames:v','1','cover.png'],FOLDER,cwd=FOLDER)
    (FOLDER/'sources.json').write_text(json.dumps({'sources':sources,'shots':timeline,'original_score':'Original synthesized pentatonic cue, composed in this sample script; not a recording or stock music.','scope':'Stock lifestyle edit; not a real product endorsement, not an AI-generated video.'},ensure_ascii=False,indent=2),encoding='utf-8')
    (FOLDER/'script.txt').write_text(SCRIPT,encoding='utf-8')
    print(json.dumps({'stage':'footage-prepared','seconds':duration,'shots':6,'sources':2},ensure_ascii=False),flush=True)


def native(render=False):
    report=FOLDER/'report.json';base='http://127.0.0.1:9120'
    html=httpx.get(base,trust_env=False).text;token=re.search(r'__HERMES_SESSION_TOKEN__="([^"]+)"',html).group(1)
    with httpx.Client(base_url=base,headers={'X-Hermes-Session-Token':token},trust_env=False,timeout=60) as c:
        def api(path,method='GET',data=None):
            r=c.request(method,'/api/miniclaw/creator'+path,json=data);r.raise_for_status();return r.json()
        if report.exists():p=api('/projects/'+json.loads(report.read_text(encoding='utf-8'))['project'])
        else:
            p=api('/projects','POST',{'name':'先别急 · 茶与日常 · 实拍剪辑v3'})
            p=api('/projects/'+p['id'],'PATCH',{'revision':p['revision'],'method':'narrated','speech_style':'warm','keep_source_audio':True,'script':SCRIPT,
                'facts':'玻璃茶具的生活方式素材剪辑。两段Anna Pou的Pexels实拍，同场景含淡色/琥珀色茶汤与两只玻璃茶壶。不是某款真实商品广告，不宣称特定参数、价格、功效、真实使用体验或人物代言。',
                'caption':'先别急，给自己倒一杯茶。\n生活方式素材剪辑，配音由AI生成。摄影素材：Anna Pou / Pexels（8296117、8296134）；原创合成配乐。\n#茶与日常 #玻璃茶具 #慢生活',
                'provenance':'Anna Pou/Pexels 8296117与8296134，Pexels License允许修改/发布，不暗示人物代言。Codex依据固定提交director-skills的镜头/摄影/QC资料做6镜头预剪；tvc-director片尾方法作参考。原创合成配乐；百炼Qwen3-TTS-Instruct-Flash/Serena固定自然温柔指令。原始来源与镜头表见本地sources.json。'})
            for slot,name in [('cover','cover.png'),('video','footage-edit.mp4')]:
                r=c.post(f"/api/miniclaw/creator/projects/{p['id']}/assets/{slot}",params={'name':name,'revision':p['revision']},content=(FOLDER/name).read_bytes(),headers={'Content-Type':'application/octet-stream'});r.raise_for_status();p=r.json()
            report.write_text(json.dumps({'project':p['id'],'stage':'native-assets-ready'},ensure_ascii=False,indent=2),encoding='utf-8')
        if render:
            job=api('/projects/'+p['id']+'/render','POST',{'revision':p['revision']});print('native-render='+job['id'],flush=True)
            deadline=time.monotonic()+600
            while time.monotonic()<deadline:
                p=api('/projects/'+p['id']);j=next(j for j in p['jobs'] if j['id']==job['id'])
                if j['state'] in ('succeeded','failed','canceled'):break
                time.sleep(2)
            if j['state']!='succeeded':raise RuntimeError(j.get('error') or j['state'])
        p=api('/projects/'+p['id']);o=next(o for o in reversed(p['outputs']) if o['current'])
        z=next((z for z in reversed(p['packages']) if z['current']),None)
        if z is None:p=api('/projects/'+p['id']+'/package','POST',{'revision':p['revision']});z=next(z for z in reversed(p['packages']) if z['current'])
        for item,name in [(o,'video.mp4'),(z,'publish-package.zip')]:
            r=c.get(f"/api/miniclaw/creator/projects/{p['id']}/files/{item['id']}");r.raise_for_status();(FOLDER/name).write_bytes(r.content)
        report.write_text(json.dumps({'project':p['id'],'revision':p['revision'],'stage':'rendered-and-packaged','output':{k:v for k,v in o.items() if k!='file'},'package':{k:v for k,v in z.items() if k!='file'},'materials':{s:{k:v for k,v in a.items() if k!='file'} for s,a in p['assets'].items()}},ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'stage':'rendered-and-packaged','project':p['id'],'duration':o['duration'],'requests':len(o['production']['requests'])},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--render',action='store_true');parser.add_argument('--collect',action='store_true');opts=parser.parse_args()
    if not opts.collect:prepare()
    if opts.render or opts.collect:native(render=opts.render)
