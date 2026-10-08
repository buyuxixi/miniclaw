"""This concept film's bounded production helper, not an application video agent.

Default is read-only status. --submit N is an explicit paid request.
This version allows the three initial shots plus one reviewed hero repair.
--poll resumes saved jobs without submitting or silently retrying them.
"""
import argparse
import array
import base64
import hashlib
import json
import math
import re
import sys
import time
import wave
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from miniclaw_web.video import binaries, execute, probe

FOLDER = ROOT / 'outputs/serum-film-v4'
MODEL = 'wan2.6-i2v-flash'
BASE = 'https://dashscope.aliyuncs.com/api/v1'
PARAMETERS = {'resolution': '1080P', 'duration': 5, 'audio': False,
              'prompt_extend': False, 'watermark': False, 'seed': 1032026}
SCRIPT = '光，沿着玻璃展开。\n一滴落下，泛起涟漪。\n流动，映出这一抹绿。\n细节，自有光。'
SHOTS = [
    {'name': 'hero-repair', 'image': 'hero', 'purpose': '定向修复：密闭包装与受控灯光', 'prompt': '固定机位，固定构图，5秒的密闭精华液瓶产品静物视频。瓶子是一个完全固定不动的整体，银色盖牢固锁在瓶颈上，银色套筒与瓶肩始终保持首帧相同间距，绝不能出现开盖、拧盖、盖子上浮、零件分离或组装动作。白色胶头、银盖、绿色瓶身、FORM 01标签全程完全保持原位和原形。唯一运动来自瓶子下方水面轻微扩散的自然涟漪，以及左侧白色条形灯亮度缓缓增强，展示玻璃的通透和银盖反射。镜头不移动、不推进、不拉远、不旋转。绿色后方玻璃片保持原位。单个连续镜头，无剪辑，无新增文字或物体。'},
    {'name': 'macro', 'purpose': '滴管液滴脱落与涟漪', 'prompt': '单个连续固定机位的超微距慢动作，5秒。首帧透明滴管保持原位和玻璃材质，一颗透明略黏稠液滴缓慢伸长，在约2秒时脱离滴管，向下落入下方浅绿色液体表面，形成小而柔和的同心圆涟漪。落点清晰可见，液滴不向上飞、不变成固体。之后表面涟漪逐渐扩散，滴管尖端仅形成一颗很小新液滴，不重复滴落，不出现夸张水柱。左侧白色条形高光、深绿色背景、浅景深，真实透明折射。全程无剪辑，无文字、手或人物。'},
    {'name': 'wave', 'purpose': '液体波浪服务包装展示', 'prompt': '单个连续固定机位镜头，5秒精华液产品广告。首帧唯一绿色玻璃瓶、FORM 01标签、银色盖和白色胶头完全保持不变，直立不移动、正面清晰。后方透明绿色液体薄片从左向右缓慢流动、卷曲、逐渐落回水面，少量水滴受重力自然向下落。液体始终在瓶子后方或两侧，不遮挡标签、不穿过瓶子，不让瓶子融化。逆光穿透液体形成通透高光，表面细微涟漪，产品轮廓与接触阴影稳定。克制的慢动作，不循环旋转，不出现新包装或任何字幕。'},
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


def ledger():
    path = FOLDER / 'wan-jobs.json'
    return path, json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'model': MODEL, 'parameters': PARAMETERS, 'jobs': {}}


def key():
    import os
    value = os.environ.get('DASHSCOPE_API_KEY') or dotenv_values(ROOT / '.hermes/.env').get('DASHSCOPE_API_KEY')
    if not value:
        raise ValueError('未配置百炼Key；不会寻找或切换其他Key')
    return value


def submit(index):
    path, state = ledger()
    shot = SHOTS[index-1]
    if shot['name'] in state['jobs']:
        raise ValueError('该镜头已记录提交，禁止重复计费请求；请 --poll 或检查本地记录')
    if len(state['jobs']) >= 4:
        raise ValueError('本版三段初始镜头加一次已审定开场修复，不继续购买任务')
    image = FOLDER / (shot.get('image', shot['name']) + '.png')
    signature = hashlib.sha256(json.dumps({'model': MODEL, 'parameters': PARAMETERS, 'prompt': shot['prompt'], 'image_sha256': sha(image)}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    secret = key()
    job = {'state': 'SUBMIT_UNKNOWN', 'input_sha256': sha(image), 'signature': signature,
           'purpose': shot['purpose'], 'prompt': shot['prompt'], 'submitted_at': time.time()}
    state['jobs'][shot['name']] = job
    # Persist the uncertainty before the network boundary: a timeout cannot
    # cause the next run to silently buy another render.
    save(path, state)
    payload = {'model': MODEL, 'input': {'img_url': 'data:image/png;base64,' + base64.b64encode(image.read_bytes()).decode(),
               'prompt': shot['prompt'], 'negative_prompt': '瓶身变形，标签改变，重复瓶子，多余瓶盖，穿模，镜头切换，人物，手，广告字幕，水印，夸张粒子，闪烁'}, 'parameters': PARAMETERS}
    try:
        with httpx.Client(timeout=90, trust_env=False, follow_redirects=False) as client:
            response = client.post(BASE + '/services/aigc/video-generation/video-synthesis',
                headers={'Authorization': 'Bearer ' + secret, 'X-DashScope-Async': 'enable'}, json=payload)
            data = response.json()
        if response.status_code != 200 or not data.get('output', {}).get('task_id'):
            job.update(state='SUBMIT_FAILED', http_status=response.status_code, code=data.get('code'))
            save(path, state)
            raise ValueError(f'万相提交失败 HTTP {response.status_code}, code={data.get("code")}；未重试')
        job.update(state=data['output'].get('task_status', 'PENDING'), task_id=data['output']['task_id'], request_id=data.get('request_id'))
        save(path, state)
        print(json.dumps({'shot': shot['name'], 'state': job['state'], 'task_id': job['task_id']}, ensure_ascii=False), flush=True)
    except httpx.HTTPError:
        raise ValueError('万相提交网络异常；结果未知，保留记录，不自动重复提交') from None


def result_url(value):
    p = urlsplit(value)
    allowed = (re.fullmatch(r'dashscope-result-[a-z0-9-]+\.oss-[a-z0-9-]+\.aliyuncs\.com', p.hostname or '')
               or p.hostname == 'dashscope-a717.oss-accelerate.aliyuncs.com')
    if p.scheme not in ('http', 'https') or not allowed or p.username or p.password or p.port not in (None, 80, 443):
        raise ValueError('万相返回下载域未核对；只记录hostname，不扩大下载许可')
    return urlunsplit(('https', p.hostname, p.path, p.query, ''))


def poll():
    path, state = ledger()
    secret = key()
    _, ffprobe = binaries(ROOT)
    with httpx.Client(timeout=90, trust_env=False, follow_redirects=False) as client:
        for name, job in state['jobs'].items():
            target = FOLDER / f'{name}-wan.mp4'
            if target.exists() and job.get('result_sha256') == sha(target):
                print(name + ': collected', flush=True)
                continue
            if not job.get('task_id'):
                print(name + ': ' + job['state'], flush=True)
                continue
            response = client.get(BASE + '/tasks/' + job['task_id'], headers={'Authorization': 'Bearer ' + secret})
            if response.status_code != 200:
                raise ValueError(f'万相查询失败HTTP {response.status_code}；不提交新任务')
            data = response.json()
            out = data.get('output', {})
            job.update(state=out.get('task_status', 'UNKNOWN'), usage=data.get('usage'))
            if out.get('code'):
                job['code'] = out['code']
            save(path, state)
            if job['state'] == 'SUCCEEDED':
                job['download_hostname'] = urlsplit(out['video_url']).hostname
                save(path, state)
                url = result_url(out['video_url'])
                partial = target.with_suffix('.download')
                try:
                    with client.stream('GET', url) as stream:
                        if stream.status_code != 200:
                            raise ValueError('万相结果下载失败')
                        size = 0
                        with partial.open('wb') as file:
                            for chunk in stream.iter_bytes(65536):
                                size += len(chunk)
                                if size > 96 * 1024 * 1024:
                                    raise ValueError('结果超过96MiB上限')
                                file.write(chunk)
                    info = probe(partial, ffprobe)
                    if not 4.9 <= info['duration'] <= 5.2:
                        raise ValueError('万相镜头时长与5秒计划不符')
                    partial.replace(target)
                    job.update(result_sha256=sha(target), media=info)
                    save(path, state)
                finally:
                    if partial.exists():
                        partial.unlink()
            print(name + ': ' + job['state'], flush=True)


def prepare():
    path, state = ledger()
    if any(not (FOLDER / f'{s["name"]}-wan.mp4').exists() for s in SHOTS):
        raise ValueError('三段万相运动镜头尚未全部取得，不用静态推拉冒充生成视频')
    ffmpeg, ffprobe = binaries(ROOT)
    (FOLDER/'sans.ttc').write_bytes(Path('C:/Windows/Fonts/msyh.ttc').read_bytes())
    (FOLDER/'serif.ttf').write_bytes(Path('C:/Windows/Fonts/times.ttf').read_bytes())
    (FOLDER/'disclosure.txt').write_text('概念产品 · AI生成', encoding='utf-8')
    (FOLDER/'end-main.txt').write_text('FORM 01', encoding='utf-8')
    (FOLDER/'end-sub.txt').write_text('精华液 · 视觉概念', encoding='utf-8')
    clips=[]
    timeline=[]
    for shot in SHOTS:
        source=FOLDER/f'{shot["name"]}-wan.mp4'
        if state['jobs'][shot['name']].get('result_sha256') != sha(source):
            raise ValueError('生成镜头hash不符，禁止替换源后仍复用旧记录')
    edit=[('hero-repair',0,2.4,'','产品建立'),
          ('hero-repair',2.4,1.8,'crop=648:1152:216:620,','玻璃/金属包装细节'),
          ('macro',0,4.5,'','透明液体下落与扩散'),
          ('wave',0,4.5,'','液体波浪与完整包装'),
          ('wave',2.8,1.8,'crop=648:1152:216:620,','同瓶标签与材质确认')]
    cursor=0
    for index,(name,start,duration,framing,purpose) in enumerate(edit):
        source=FOLDER/f'{name}-wan.mp4'
        if start+duration>probe(source,ffprobe)['duration']+.02:
            raise ValueError('剪辑选段超出来源，禁止自动循环')
        # Exact portrait crop differs slightly from the provider's native grid.
        vf=framing+'scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30'
        vf+=',drawtext=fontfile=sans.ttc:textfile=disclosure.txt:expansion=none:fontsize=24:fontcolor=white@0.68:shadowcolor=black@0.6:shadowx=1:shadowy=1:x=64:y=64'
        out=FOLDER/f'edit-{index}.mp4'
        execute([ffmpeg,'-v','error','-nostdin','-y','-ss',str(start),'-i',source.name,'-vf',vf,'-t',str(duration),'-an','-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-threads','2',out.name], FOLDER, cwd=FOLDER)
        clips.append(out)
        timeline.append({'shot':index+1,'start':round(cursor,3),'end':round(cursor+duration,3),'name':name,'source_start':start,'framing':framing or 'full','purpose':purpose,'source_sha256':sha(source)})
        cursor+=duration
    vf='scale=1080:1920,setsar=1,fps=30'
    vf+=',drawtext=fontfile=serif.ttf:textfile=end-main.txt:expansion=none:fontsize=94:fontcolor=0xEFEDE3:x=(w-text_w)/2:y=210'
    vf+=',drawtext=fontfile=sans.ttc:textfile=end-sub.txt:expansion=none:fontsize=30:fontcolor=0xCFD9D0:x=(w-text_w)/2:y=336'
    vf+=',drawtext=fontfile=sans.ttc:textfile=disclosure.txt:expansion=none:fontsize=24:fontcolor=white@0.68:x=64:y=64'
    end=FOLDER/'edit-end.mp4'
    execute([ffmpeg,'-v','error','-nostdin','-y','-loop','1','-i','hero.png','-vf',vf,'-t','3','-an','-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-threads','2',end.name],FOLDER,cwd=FOLDER)
    clips.append(end);timeline.append({'shot':6,'start':15,'end':18,'name':'end-card','purpose':'干净产品定格与概念标识','source_sha256':sha(FOLDER/'hero.png')})
    (FOLDER/'edit-list.txt').write_text(''.join(f"file '{f.name}'\n" for f in clips),encoding='utf-8')
    # An original sparse electronic bed; no borrowed recording.
    rate=48000;duration=18;values=[0.0]*(rate*duration)
    for start,midi in [(0,48),(0,55),(3,60),(5,55),(8,67),(10,48),(10,55),(13,62),(15,60)]:
        freq=440*2**((midi-69)/12)
        for i in range(min(rate*4,len(values)-round(start*rate))):
            t=i/rate;env=(1-math.exp(-t*12))*math.exp(-t/1.3)
            values[round(start*rate)+i]+=.032*env*(math.sin(2*math.pi*freq*t)+.15*math.sin(2*math.pi*freq*2*t))
    pcm=array.array('h',(round(max(-1,min(1,v))*32767) for v in values))
    with wave.open(str(FOLDER/'original-score.wav'),'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(rate);wav.writeframes(pcm.tobytes())
    execute([ffmpeg,'-v','error','-nostdin','-y','-f','concat','-safe','1','-i','edit-list.txt','-i','original-score.wav','-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','192k','-ar','48000','-ac','2','-af','afade=t=in:d=0.3,afade=t=out:st=16.8:d=1.2','-t','18','-map_metadata','-1','-movflags','+faststart','footage-edit.mp4'],FOLDER,cwd=FOLDER)
    execute([ffmpeg,'-v','error','-nostdin','-y','-ss','16','-i','footage-edit.mp4','-frames:v','1','cover.png'],FOLDER,cwd=FOLDER)
    save(FOLDER/'sources.json',{'scope':'Fictional serum concept, all imagery AI-generated; no actual efficacy claims or real brand endorsement.', 'image_generation':'Codex built-in imagegen (no model ID exposed by tool)', 'image_assets':json.loads((FOLDER/'image-assets.json').read_text(encoding='utf-8')), 'video_model':MODEL,'video_parameters':PARAMETERS,'key_source':'existing local Beijing DASHSCOPE_API_KEY; never included in artifact','jobs':state['jobs'],'shots':timeline,'music':'Original synthesized electronic bed; not downloaded or imitating a recording.','reference':'User-supplied BUV video, expression reference only; no reference pixels/person/brand reused.'})
    (FOLDER/'script.txt').write_text(SCRIPT,encoding='utf-8')
    print(json.dumps({'stage':'prepared','media':probe(FOLDER/'footage-edit.mp4',ffprobe)},ensure_ascii=False),flush=True)


def native(render=False):
    report=FOLDER/'report.json';base='http://127.0.0.1:9120'
    html=httpx.get(base,trust_env=False).text
    token=re.search(r'__HERMES_SESSION_TOKEN__="([^"]+)"',html).group(1)
    with httpx.Client(base_url=base,headers={'X-Hermes-Session-Token':token},trust_env=False,timeout=60) as c:
        def api(path,method='GET',data=None):
            r=c.request(method,'/api/miniclaw/creator'+path,json=data);r.raise_for_status();return r.json()
        if report.exists():
            p=api('/projects/'+json.loads(report.read_text(encoding='utf-8'))['project'])
        else:
            p=api('/projects','POST',{'name':'FORM 01 · 精华液概念广告 v4'})
            # Persist the owned project before subsequent network mutations.
            save(report,{'project':p['id'],'stage':'native-project-created'})
        if not p.get('script') and not any(p.get('assets',{}).values()):
            p=api('/projects/'+p['id'],'PATCH',{'revision':p['revision'],'method':'narrated','speech_style':'warm','keep_source_audio':True,'script':SCRIPT,
                'facts':'虚构FORM 01精华液概念产品：绿色玻璃滴管瓶、银色瓶盖、白色胶头和FORM/01标签。全部产品/液滴/液体画面由AI生成。无真实品牌、商品配方、含量、效果、价格、销量或临床证据。本片只展示视觉设计和材质表达。',
                'caption':'FORM 01 · 精华液视觉概念。\n虚构产品，画面与配音由AI生成，无真实商品或护肤功效宣称。参考BUV产品广告的材质/光影表达，未复用其画面、人物、品牌或声音。\n#产品视觉 #精华液 #AI概念广告',
                'provenance':'内置imagegen制作基准及引用编辑首帧；百炼wan2.6-i2v-flash三段5秒1080P无声运动视频；TVC Director固定MIT提交的产品/光影/收束方法。原创合成配乐；工作台原生百炼Serena旁白/实测SRT/FFmpeg。详情见sources.json及验收15–17。'})
        for slot,name in [('cover','cover.png'),('video','footage-edit.mp4')]:
            current=p.get('assets',{}).get(slot)
            if current and current['sha256']==sha(FOLDER/name):
                continue
            if current and not render:
                raise ValueError('本地素材与项目版本不同；仅收集不会覆盖，请检查后显式 --render')
            r=c.post(f"/api/miniclaw/creator/projects/{p['id']}/assets/{slot}",params={'name':name,'revision':p['revision']},content=(FOLDER/name).read_bytes(),headers={'Content-Type':'application/octet-stream'});r.raise_for_status();p=r.json()
            save(report,{'project':p['id'],'stage':'native-assets-ready'})
        if render:
            existing=next((o for o in reversed(p['outputs']) if o['current']),None)
            if not existing:
                running=next((j for j in p['jobs'] if j['state'] in ('queued','running')),None)
                job=running or api('/projects/'+p['id']+'/render','POST',{'revision':p['revision']})
                print('native-render='+job['id'],flush=True)
                deadline=time.monotonic()+600
                while time.monotonic()<deadline:
                    p=api('/projects/'+p['id']);j=next(j for j in p['jobs'] if j['id']==job['id'])
                    if j['state'] in ('succeeded','failed','canceled'):
                        break
                    time.sleep(2)
                if j['state']!='succeeded':
                    raise ValueError(j.get('error') or j['state'])
        p=api('/projects/'+p['id'])
        output=next(o for o in reversed(p['outputs']) if o['current'])
        package=next((z for z in reversed(p['packages']) if z['current']),None)
        if package is None:
            p=api('/projects/'+p['id']+'/package','POST',{'revision':p['revision']});package=next(z for z in reversed(p['packages']) if z['current'])
        for item,name in [(output,'video.mp4'),(package,'publish-package.zip')]:
            r=c.get(f"/api/miniclaw/creator/projects/{p['id']}/files/{item['id']}");r.raise_for_status();(FOLDER/name).write_bytes(r.content)
        save(report,{'project':p['id'],'revision':p['revision'],'stage':'rendered-and-packaged','output':{k:v for k,v in output.items() if k!='file'},'package':{k:v for k,v in package.items() if k!='file'},'materials':{s:{k:v for k,v in a.items() if k!='file'} for s,a in p['assets'].items()}})
        print(json.dumps({'stage':'rendered-and-packaged','project':p['id'],'duration':output['duration']},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    actions=parser.add_mutually_exclusive_group()
    actions.add_argument('--submit',type=int,choices=(1,2,3))
    actions.add_argument('--poll',action='store_true')
    actions.add_argument('--prepare',action='store_true')
    actions.add_argument('--render',action='store_true')
    actions.add_argument('--collect',action='store_true')
    opts=parser.parse_args()
    FOLDER.mkdir(parents=True,exist_ok=True)
    if opts.submit: submit(opts.submit)
    elif opts.poll: poll()
    elif opts.prepare: prepare()
    elif opts.render or opts.collect: native(render=opts.render)
    else:
        _, state=ledger();print(json.dumps({'model':MODEL,'jobs':{n:j['state'] for n,j in state['jobs'].items()}},ensure_ascii=False))
