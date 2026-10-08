"""Stage generated originals in the real app; rendering only when --render is explicit."""
import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--render',action='store_true');parser.add_argument('--collect',action='store_true');opts=parser.parse_args()
    folder=ROOT/'outputs/tea-film-v2';report=folder/'report.json'
    base='http://127.0.0.1:9120';html=httpx.get(base,trust_env=False).text
    token=re.search(r'__HERMES_SESSION_TOKEN__="([^"]+)"',html).group(1)
    with httpx.Client(base_url=base,headers={'X-Hermes-Session-Token':token},trust_env=False,timeout=60) as client:
        def api(path,method='GET',data=None):
            response=client.request(method,'/api/miniclaw/creator'+path,json=data)
            response.raise_for_status();return response.json()
        if report.exists(): p=api('/projects/'+json.loads(report.read_text(encoding='utf-8'))['project'])
        else:
            p=api('/projects','POST',{'name':'留一刻，给茶 · 国风口播短片'})
            p=api('/projects/'+p['id'],'PATCH',{'revision':p['revision'],'facts':'原创AI视觉概念样片；青瓷色茶杯、杯沿特写、窗边晨光。没有真实商品品牌、参数、价格、功效或真实消费体验。文案以观察和邀请为主。','script':'忙了一天，也留一刻，给一杯茶。\n看光落在杯沿，茶色慢慢透出来。\n不赶时间，也不急着把话说完。\n让日常慢一点，从这一杯开始。','caption':'留一刻，给茶。\n原创AI视觉概念短片，非实拍商品广告。\n#器物之美 #茶与日常 #AI创作','provenance':'三张原创图由Codex内置imagegen生成，按用户提供的chinese-style-poster-skill提炼D05/D03/D08方向；没有搬运短视频平台内容。语音使用现有百炼Key的Qwen3-TTS，字幕按实际逐句WAV长度生成；剪辑为本系统固定镜头配方。','method':'storyboard'})
            for slot in ('cover','detail','scene'):
                response=client.post(f"/api/miniclaw/creator/projects/{p['id']}/assets/{slot}",params={'name':slot+'.png','revision':p['revision']},content=(folder/(slot+'.png')).read_bytes(),headers={'Content-Type':'application/octet-stream'})
                response.raise_for_status();p=response.json()
            report.write_text(json.dumps({'project':p['id'],'stage':'assets-staged'},ensure_ascii=False,indent=2),encoding='utf-8')
        if opts.render:
            job=api('/projects/'+p['id']+'/render','POST',{'revision':p['revision']})
            print('render-job='+job['id'],flush=True)
            deadline=time.monotonic()+600
            while time.monotonic()<deadline:
                p=api('/projects/'+p['id']);j=next(j for j in p['jobs'] if j['id']==job['id'])
                if j['state'] in ('succeeded','failed','canceled'):break
                time.sleep(2)
            if j['state']!='succeeded':raise RuntimeError(j.get('error') or j['state'])
        if opts.collect or opts.render:
            p=api('/projects/'+p['id']);output=next(o for o in reversed(p['outputs']) if o['current'])
            pack=next((z for z in reversed(p['packages']) if z['current']),None)
            if pack is None:
                p=api('/projects/'+p['id']+'/package','POST',{'revision':p['revision']});pack=next(z for z in reversed(p['packages']) if z['current'])
            for item,name in ((output,'video.mp4'),(pack,'publish-package.zip')):
                response=client.get(f"/api/miniclaw/creator/projects/{p['id']}/files/{item['id']}");response.raise_for_status();(folder/name).write_bytes(response.content)
            report.write_text(json.dumps({'project':p['id'],'chat_id':p.get('chat_id'),'stage':'rendered-and-packaged','output':{k:v for k,v in output.items() if k!='file'},'package':{k:v for k,v in pack.items() if k!='file'},'materials':{s:{k:v for k,v in a.items() if k!='file'} for s,a in p['assets'].items()},'original_generation_hashes':{s:hashlib.sha256((folder/(s+'.png')).read_bytes()).hexdigest() for s in ('cover','detail','scene')}},ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'project':p['id'],'revision':p['revision'],'method':p['method'],'stage':json.loads(report.read_text(encoding='utf-8'))['stage']},ensure_ascii=False))


if __name__=='__main__':main()
