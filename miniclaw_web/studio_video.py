"""Durable image-to-video jobs. POST is never retried; polling is safe to resume."""
import base64
import hashlib
import io
import json
import os
import re
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from PIL import Image
from .canvas import Conflict
from .image_provider import checked_endpoint, checked_result_url, settings
from .video import binaries, probe, MAX_MEDIA


class StudioVideo:
    MODEL='wan2.2-i2v-flash'
    def __init__(self,studio,root,executor=None,client_factory=httpx.Client):
        self.studio=studio;self.store=studio.store;self.root=Path(root)
        self.folder=Path(self.store.home)/'studio_video';self.folder.mkdir(exist_ok=True)
        self.executor=executor or ThreadPoolExecutor(max_workers=2,thread_name_prefix='studio-video')
        self.client_factory=client_factory;self.active=set();self.lock=threading.RLock()
        with self.store.connect() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS studio_video_jobs (id TEXT PRIMARY KEY,workspace TEXT,data TEXT); CREATE TABLE IF NOT EXISTS studio_video_renders (id TEXT PRIMARY KEY,workspace TEXT,data TEXT);')
            # A crash during submission may have charged the request. Never resubmit it.
            for row in db.execute('SELECT id,data FROM studio_video_jobs').fetchall():
                job=json.loads(row[1])
                if job['state']=='submitting':
                    job.update(state='unknown',error='提交时服务中断，结果待核对；不会自动重新生成')
                    db.execute('UPDATE studio_video_jobs SET data=? WHERE id=?',(json.dumps(job,ensure_ascii=False),row[0]))
            for row in db.execute('SELECT id,data FROM studio_video_renders').fetchall():
                render=json.loads(row[1])
                if render['state']=='running':
                    render.update(state='failed',error='合成被服务重启中断，可以重新合成，视频片段仍保留')
                    db.execute('UPDATE studio_video_renders SET data=? WHERE id=?',(json.dumps(render,ensure_ascii=False),row[0]))

    def status(self):
        ffmpeg,ffprobe=binaries(self.root)
        from .minimax_video import public_status
        mini=public_status();wan={'provider':'dashscope','configured':bool(settings()['key']),'model':self.MODEL,'duration':5,'output_duration':5,'resolution':'720P','reference_cny':1.0,'price_source':'https://help.aliyun.com/zh/model-studio/model-pricing'}
        default=mini if mini['configured'] else wan
        return {**default,'options':[mini,wan],'render_ready':bool(ffmpeg and ffprobe)}

    def _get(self,identifier,table='studio_video_jobs'):
        self.studio.workspaces.identifier(identifier)
        with self.store.connect() as db:row=db.execute(f'SELECT data FROM {table} WHERE id=?',(identifier,)).fetchone()
        if not row:raise ValueError('视频任务不存在')
        return json.loads(row[0])

    def _put(self,job,table='studio_video_jobs'):
        job['updated_at']=time.time()
        if job.get('state')=='succeeded' and job.get('path') and not job.get('object_id'):
            obj=self.store.media.put_file(job['path'],'video/mp4')
            job['object_id']=obj['id']
        if job.get('object_id') and 'input_objects' not in job:
            job['input_objects']=[self.store.media.put_file(path,'image/jpeg')['id'] for path in job.get('input_paths',[])]
        with self.store.connect() as db:
            db.execute(f'UPDATE {table} SET data=? WHERE id=?',(json.dumps(job,ensure_ascii=False),job['id']))
            if job.get('object_id'):
                self.store.versions.append(db,job['workspace'],job.get('shot','render'),
                    'video' if table=='studio_video_jobs' else 'render',
                    {k:v for k,v in job.items() if k not in ('path','input_path','input_paths','result_url','updated_at','error')},
                    '视频生成结果' if table=='studio_video_jobs' else '合成结果',[job['object_id'],*job.get('input_objects',[])])

    def basis(self,workspace,shot_id):
        record=self.studio.workspaces.get(workspace)
        if not record:raise ValueError('项目不存在')
        state=record['state'];shot=next((s for s in state['shots'] if s['id']==shot_id),None)
        if not shot:raise ValueError('视频片段已删除')
        ids = [shot.get('first')] if shot.get('mode') == 'first' else shot.get('refs', [])
        if not ids:raise ValueError('请连接首帧或参考图片')
        if shot.get('mode') != 'first':
            from .media_models import resolve
            option = resolve('video',shot.get('videoProvider',self.status()['provider']),shot.get('videoModel'),require_key=False)
            if not option.get('references') or len(ids)>9:raise ValueError('所选模型不支持这些参考图，请选 MiniMax H3 或使用首帧')
        asset=next((a for a in state['assets'] if a['id']==ids[0] and a.get('file') and not a.get('pending')),None)
        if not asset:raise ValueError('请先补充首帧图片')
        if shot.get('duration')!=5:raise ValueError('当前视频模型生成5秒片段')
        prompt=shot.get('prompt','')
        if not isinstance(prompt,str) or not 1<=len(prompt.strip())<=1500:raise ValueError('请填写1至1500字的镜头要求')
        value={'shot':shot_id,'name':shot['name'],'prompt':prompt,'duration':5,'image':asset['file'],'facts':state.get('facts','')}
        if shot.get('mode') != 'first':
            value['references'] = [next((a['file'] for a in state['assets'] if a['id']==i and a.get('file') and not a.get('pending')),None) for i in ids]
            if None in value['references']: raise ValueError('参考图片尚未补充')
        return record,shot,asset,hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()

    def _safe(self,job):
        result={k:v for k,v in job.items() if k not in ('path','input_path','input_paths','result_url')}
        result['reference_count']=len(job.get('input_paths') or []) if job.get('mode')=='reference' else 1
        try:result['stale']=self.basis(job['workspace'],job['shot'])[3]!=job['basis']
        except ValueError:result['stale']=True
        if job['state']=='succeeded':result['media']=f"/studio/media/video/{job['id']}"
        from .generation_audit import entry
        result['audit']=entry(job,'video')
        return result

    def list(self,workspace):
        if not self.studio.workspaces.get(workspace):raise ValueError('项目不存在')
        with self.store.connect() as db:rows=db.execute('SELECT data FROM studio_video_jobs WHERE workspace=?',(workspace,)).fetchall()
        jobs=[json.loads(r[0]) for r in rows]
        for job in jobs:
            if job['state'] in ('queued','running'):self._schedule(job['id'])
        return [self._safe(j) for j in sorted(jobs,key=lambda x:x['created_at'])]

    def submit(self,workspace,request):
        if set(request)!={'request_id','revision','shot'}:raise ValueError('视频生成参数无效')
        identifier=self.studio.workspaces.identifier(request['request_id'])
        signature=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()
        with self.studio.canvas.lock,self.lock:
            with self.store.connect() as db:old=db.execute('SELECT data FROM studio_video_jobs WHERE id=?',(identifier,)).fetchone()
            if old:
                job=json.loads(old[0])
                if job['workspace']!=workspace or job['signature']!=signature:raise ValueError('不能更改同一生成请求')
                return self._safe(job)
            record,shot,asset,basis=self.basis(workspace,request['shot'])
            if record['revision']!=request['revision']:raise Conflict('镜头已更新，请重新读取后生成')
            provider=shot.get('videoProvider',self.status()['provider'])
            if provider not in ('minimax','dashscope'):raise ValueError('视频供应商无效')
            option=next(o for o in self.status()['options'] if o['provider']==provider)
            if shot.get('videoModel'):
                from .media_models import resolve
                option = resolve('video', provider, shot['videoModel'])
            if not option['configured']:raise ValueError('所选视频模型尚未配置 API Key')
            if provider=='dashscope':checked_endpoint(settings()['base'])
            else:
                from .minimax_video import configuration
                configuration()
            if any(j['shot']==shot['id'] and j['state'] in ('queued','submitting','running','unknown') for j in self.list(workspace)):
                raise Conflict('这个镜头已有未完成或待核对任务，请先查看原任务')
            meta=self.studio.precision.full_open({'workspace':workspace,'object_id':asset['id'],'file':asset['file'],'name':asset['name']})
            row=self.studio.canvas.get(meta['project']);source=self.studio.canvas.asset(row['id'],row['document']['layers'][0]['asset_id'])
            # Use the explicitly adopted asset pixels, not subsequent working-document changes.
            import re
            match=re.fullmatch(r'/api/precision/projects/([a-f0-9]{32})/assets/([a-f0-9]{32})',asset['file'])
            if match:source=self.studio.canvas.asset(match[1],match[2])
            folder=self.folder/identifier;folder.mkdir(exist_ok=True)
            with Image.open(source['path']) as image:
                image.convert('RGB').save(folder/'input.jpg',quality=95)
            input_paths = [str(folder/'input.jpg')]
            if shot.get('mode') != 'first':
                input_paths = []
                for index, asset_id in enumerate(shot['refs']):
                    reference = next(a for a in record['state']['assets'] if a['id']==asset_id)
                    reference_meta = self.studio.precision.full_open({'workspace':workspace,'object_id':reference['id'],'file':reference['file'],'name':reference['name']})
                    refrow = self.studio.canvas.get(reference_meta['project'])
                    refsource = self.studio.canvas.asset(refrow['id'],refrow['document']['layers'][0]['asset_id'])
                    refmatch = re.fullmatch(r'/api/precision/projects/([a-f0-9]{32})/assets/([a-f0-9]{32})',reference['file'])
                    if refmatch: refsource = self.studio.canvas.asset(refmatch[1],refmatch[2])
                    path = folder / ('reference-'+str(index)+'.jpg')
                    with Image.open(refsource['path']) as image: image.convert('RGB').save(path,quality=95)
                    input_paths.append(str(path))
            job={'id':identifier,'workspace':workspace,'signature':signature,'basis':basis,'shot':shot['id'],'name':shot['name'],
                'prompt':shot['prompt'],'facts':record['state'].get('facts',''),'state':'queued','model':option['model'],'provider':provider,'duration':5,
                'generation_duration':option['duration'],'resolution':option['resolution'],
                'provider_base':configuration()['base'] if provider=='minimax' else settings()['base'],
                'input_path':str(folder/'input.jpg'),'input_paths':input_paths,'mode':shot['mode'],'image':asset['file'],'created_at':time.time(),'error':''}
            with self.store.connect() as db:db.execute('INSERT INTO studio_video_jobs VALUES (?,?,?)',(identifier,workspace,json.dumps(job,ensure_ascii=False)))
            self._schedule(identifier)
            return self._safe(job)

    def _schedule(self,identifier):
        with self.lock:
            if identifier in self.active:return
            self.active.add(identifier)
            self.executor.submit(self._run,identifier)

    def _run(self,identifier):
        try:
            job=self._get(identifier)
            if job.get('provider')=='minimax':
                self._run_minimax(job)
                return
            cfg=settings();endpoint=checked_endpoint(job.get('provider_base',cfg['base']))
            with self.client_factory(timeout=httpx.Timeout(60,connect=10),trust_env=False,follow_redirects=False) as client:
                headers={'Authorization':'Bearer '+cfg['key']}
                if job['state']=='queued':
                    job.update(provider='dashscope',provider_region='中国内地' if cfg['base'].rstrip('/')=='https://dashscope.aliyuncs.com' else '其他地域')
                    job.update(state='submitting');self._put(job)
                    payload={'model':job['model'],'input':{'img_url':'data:image/jpeg;base64,'+base64.b64encode(Path(job['input_path']).read_bytes()).decode(),
                        'prompt':job['prompt']+'\n共同要求：'+job['facts'],'negative_prompt':'人物，人脸，手，包装文字变形，产品变形，水印'},
                        'parameters':{'duration':5,'resolution':'720P','prompt_extend':False,'watermark':False}}
                    try:
                        response=client.post(endpoint+'/api/v1/services/aigc/video-generation/video-synthesis',headers={**headers,'X-DashScope-Async':'enable'},json=payload)
                        if response.status_code>=500:raise httpx.ReadError('uncertain submission')
                        if response.status_code!=200:
                            job.update(state='failed',error=f"视频服务拒绝请求（HTTP {response.status_code}），请核对模型权限与额度");self._put(job);return
                        output=response.json().get('output',{});task_id=output.get('task_id')
                        if not isinstance(task_id,str) or not re.fullmatch(r'[A-Za-z0-9-]{1,128}',task_id):raise ValueError('missing task')
                        job.update(state='running',task_id=task_id);self._put(job)
                    except (httpx.HTTPError,ValueError,KeyError,TypeError):
                        job.update(state='unknown',error='视频提交结果未知，云端可能已计费；不会自动重试');self._put(job);return
                if job['state']!='running':return
                for _ in range(90):
                    try:
                        response=client.get(endpoint+'/api/v1/tasks/'+job['task_id'],headers=headers)
                        if response.status_code!=200:raise ValueError()
                        body=response.json();output=body['output'];status=output.get('task_status')
                        from .generation_audit import usage_fields
                        job['usage']=usage_fields(body.get('usage'))
                        if status in ('FAILED','CANCELED'):
                            job.update(state='failed',error='视频模型未完成任务，原图、提示词和历史候选已保留');self._put(job);return
                        if status=='SUCCEEDED':
                            url=checked_result_url(output['video_url']);job.update(result_url=url);self._put(job)
                            path=self.folder/identifier/'result.mp4'
                            with client.stream('GET',url,timeout=60) as download:
                                if download.status_code!=200:raise ValueError()
                                count=0
                                with path.open('wb') as target:
                                    for chunk in download.iter_bytes():
                                        count+=len(chunk)
                                        if count>MAX_MEDIA:raise ValueError()
                                        target.write(chunk)
                            ffmpeg,ffprobe=binaries(self.root)
                            if not ffprobe:raise ValueError()
                            info=probe(path,ffprobe)
                            if not 4.8<=info['duration']<=5.5:raise ValueError()
                            job.update(state='succeeded',path=str(path),info=info,error='');self._put(job);return
                    except (httpx.HTTPError,ValueError,KeyError,TypeError,OSError):
                        job.update(error='暂时无法读取或下载结果；保留原任务编号，下次读取只查询原任务');self._put(job);return
                    time.sleep(10)
                job.update(error='生成仍未结束，刷新后继续查询原任务');self._put(job)
        except Exception:
            job=self._get(identifier)
            job.update(state='unknown' if job['state']=='submitting' else 'failed',error='视频任务处理未完成，原素材与任务记录已保留；不会重新提交')
            self._put(job)
        finally:
            with self.lock:self.active.discard(identifier)

    def _run_minimax(self,job):
        from .minimax_video import configuration,checked_body,checked_download
        cfg=configuration();endpoint=job.get('provider_base',cfg['base'])
        h3 = job['model'] in ('MiniMax-H3','MiniMax-H3-Max')
        if endpoint not in ('https://api.minimax.cn/v1','https://api.minimaxi.com/v1','https://api.minimax.io/v1'):raise ValueError('MiniMax API 地址无效')
        with self.client_factory(timeout=httpx.Timeout(60,connect=10),trust_env=False,follow_redirects=False) as client:
            headers={'Authorization':'Bearer '+cfg['key']}
            if job['state']=='queued':
                prompt=job['prompt']+('\n共同要求：'+job['facts'] if job['facts'] else '')
                if len(prompt)>2000:
                    job.update(state='failed',error='MiniMax 镜头要求与共同要求合计最多2000字');self._put(job);return
                job.update(state='submitting',provider_region='国际' if 'api.minimax.io' in endpoint else '中国内地');self._put(job)
                payload={'model':job['model'],'first_frame_image':'data:image/jpeg;base64,'+base64.b64encode(Path(job['input_path']).read_bytes()).decode(),
                         'prompt':prompt,'duration':job['generation_duration'],'resolution':job['resolution'],'prompt_optimizer':False,'aigc_watermark':False}
                if h3:
                    payload = {'model':job['model'],'content':[{'type':'text','text':prompt}] + [
                        {'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(Path(path).read_bytes()).decode()},
                         'role':'reference_image' if job.get('mode')=='reference' else 'first_frame'}
                        for path in job.get('input_paths',[job['input_path']])],
                        'duration':5,'resolution':job['resolution'],'ratio':'9:16' if job.get('mode')=='reference' else 'adaptive'}
                try:
                    response=client.post((endpoint[:-3]+'/v2' if h3 else endpoint)+'/video_generation',headers=headers,json=payload)
                    if response.status_code>=500:raise httpx.ReadError('uncertain submission')
                    if response.status_code!=200:
                        job.update(state='failed',error=f'MiniMax 拒绝请求（HTTP {response.status_code}），请核对权限与余额');self._put(job);return
                    body=response.json()
                    if body.get('base_resp',{}).get('status_code') not in (None,0):
                        job.update(state='failed',error='MiniMax 拒绝请求，请核对视频权限与余额');self._put(job);return
                    task=body.get('task_id')
                    if not isinstance(task,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',task):raise ValueError('missing task')
                    job.update(state='running',task_id=task);self._put(job)
                except (httpx.HTTPError,ValueError,TypeError):
                    job.update(state='unknown',error='MiniMax 提交结果未知，保留请求；不会自动重新生成');self._put(job);return
            if job['state']!='running':return
            for _ in range(90):
                try:
                    if h3:
                        response = client.get(endpoint[:-3]+'/v2/query/video_generation/'+job['task_id'],headers=headers)
                        if response.status_code!=200: raise ValueError('H3 query unavailable')
                        task = response.json()['task']
                        body = {'status':{'succeeded':'Success','failed':'Fail','cancelled':'Fail'}.get(task['status'],'Processing'), 'download_url':task.get('content',{}).get('url')}
                    else:
                        body=checked_body(client.get(endpoint+'/query/video_generation',headers=headers,params={'task_id':job['task_id']}))
                    if body.get('status')=='Fail':
                        job.update(state='failed',error='MiniMax 生成失败，素材与历史任务保留');self._put(job);return
                    if body.get('status')=='Success':
                        file_id=body.get('file_id')
                        if h3:
                            url=checked_download(body.get('download_url'))
                        else:
                            if not isinstance(file_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',file_id):raise ValueError('missing file')
                            result=checked_body(client.get(endpoint+'/files/retrieve',headers=headers,params={'file_id':file_id}))
                            url=checked_download(result['file']['download_url'])
                        job.update(file_id=file_id,result_url=url);self._put(job)
                        raw=self.folder/job['id']/'generated-6s.mp4';count=0
                        with client.stream('GET',url,timeout=60) as download:
                            if download.status_code!=200:raise ValueError('download')
                            with raw.open('wb') as target:
                                for chunk in download.iter_bytes():
                                    count+=len(chunk)
                                    if count>MAX_MEDIA:raise ValueError('too large')
                                    target.write(chunk)
                        ffmpeg,ffprobe=binaries(self.root)
                        if not ffmpeg or not ffprobe:raise ValueError('missing media runtime')
                        info=probe(raw,ffprobe)
                        if abs(info['duration']-job['generation_duration'])>.6:raise ValueError('duration mismatch')
                        output=raw.with_name('result.mp4')
                        result=subprocess.run([ffmpeg,'-y','-v','error','-i',str(raw),'-t','5','-an','-c:v','libx264','-preset','fast','-crf','19','-pix_fmt','yuv420p','-movflags','+faststart',str(output)],capture_output=True,timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                        if result.returncode:raise ValueError('trim failed')
                        final=probe(output,ffprobe)
                        if abs(final['duration']-5)>.1:raise ValueError('trim duration')
                        job.update(state='succeeded',path=str(output),info=final,generated_info=info,usage={'video_duration':job['generation_duration']},error='');self._put(job);return
                except (httpx.HTTPError,ValueError,KeyError,TypeError,OSError,subprocess.TimeoutExpired):
                    job.update(error='MiniMax 查询或下载暂未完成；保留原任务，下次只查询不重新提交');self._put(job);return
                time.sleep(10)
            job.update(error='MiniMax 仍在生成，稍后继续查询原任务');self._put(job)

    def adopt(self,workspace,request):
        if not {'request_id','revision','job'}<=set(request) or set(request)-{'request_id','revision','job','use_history'} or ('use_history' in request and type(request['use_history']) is not bool):raise ValueError('采用参数无效')
        rid=self.studio.workspaces.identifier(request['request_id']);signature=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()
        with self.studio.canvas.lock,self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT signature,data FROM video_workspace_receipts WHERE workspace=? AND id=?',(workspace,rid)).fetchone()
            if old:
                if old[0]!=signature:raise ValueError('采用请求不能更改')
                return self.store.versions.receipt(db,old[1])
            job=self._get(request['job'])
            historical=self._safe(job)['stale']
            if job['workspace']!=workspace or job['state']!='succeeded' or (historical and not request.get('use_history')):raise Conflict('这个候选与当前镜头要求不一致，视频仍保留供比较')
            record=self.studio.workspaces.get(workspace)
            if not any(s['id']==job['shot'] for s in record['state']['shots']):raise ValueError('对应镜头已移除')
            if record['revision']!=request['revision']:raise Conflict('项目已更新，请重新核对采用')
            sequence=record['state']['sequence'];sequence[:]=[s for s in sequence if isinstance(s,dict) and s.get('shot')!=job['shot']]
            sequence.append({'shot':job['shot'],'job':job['id'],'duration':5,**({'use_history':True} if historical else {})})
            order={s['id']:i for i,s in enumerate(record['state']['shots'])};sequence.sort(key=lambda s:order.get(s['shot'],999))
            record.update(revision=record['revision']+1,updated_at=time.time())
            record['events']=(record['events']+[{'id':rid,'label':'采用视频：'+job['name'],'object':job['shot'],'at':time.time()}])[-80:]
            encoded=json.dumps(record,ensure_ascii=False);db.execute('UPDATE video_workspaces SET data=? WHERE id=?',(encoded,workspace));self.store.versions.put_receipt(db,workspace,rid,signature,record)
            return record

    def render_basis(self,workspace):
        record=self.studio.workspaces.get(workspace);sequence=record['state']['sequence']
        if not 1<=len(sequence)<=12:raise ValueError('请先采用视频片段')
        jobs=[]
        for s in sequence:
            if not isinstance(s,dict) or not s.get('job'):raise ValueError('历史示例不是模型结果，请重新生成并采用真实视频')
            job=self._get(s['job'])
            if job['workspace']!=workspace or job['state']!='succeeded' or (self._safe(job)['stale'] and s.get('use_history') is not True):raise Conflict('有采用片段的要求已变化，请先核对并重新采用当前结果')
            if job.get('object_id'):job['path']=str(self.store.media.materialize(job['object_id']))
            jobs.append(job)
        return record,jobs,hashlib.sha256(json.dumps(sequence,sort_keys=True).encode()).hexdigest()

    def renders(self,workspace):
        with self.store.connect() as db:rows=db.execute('SELECT data FROM studio_video_renders WHERE workspace=?',(workspace,)).fetchall()
        result=[]
        try:basis=self.render_basis(workspace)[2]
        except (ValueError,Conflict):basis=None
        for row in rows:
            render=json.loads(row[0]);render.pop('path',None);render['stale']=render['basis']!=basis
            if render['state']=='succeeded':render['media']=f"/studio/media/render/{render['id']}"
            result.append(render)
        return sorted(result,key=lambda r:r['created_at'],reverse=True)

    def render(self,workspace,request):
        if set(request)!={'request_id','revision'}:raise ValueError('合成请求无效')
        rid=self.studio.workspaces.identifier(request['request_id'])
        with self.studio.canvas.lock,self.lock:
            with self.store.connect() as db:old=db.execute('SELECT data FROM studio_video_renders WHERE id=?',(rid,)).fetchone()
            if old:
                render=json.loads(old[0])
                if render['workspace']!=workspace or render['revision']!=request['revision']:raise ValueError('合成请求不能更改')
                return next(r for r in self.renders(workspace) if r['id']==rid)
            record,jobs,basis=self.render_basis(workspace)
            if record['revision']!=request['revision']:raise Conflict('时间线已变化，请重新读取后合成')
            ffmpeg,ffprobe=binaries(self.root)
            if not ffmpeg or not ffprobe:raise ValueError('本机缺少视频合成组件')
            render={'id':rid,'workspace':workspace,'basis':basis,'revision':record['revision'],'state':'running','duration':len(jobs)*5,'created_at':time.time(),'error':''}
            render['input_versions']=[{'job':j['id'],'object_id':j.get('object_id'),'use_history':next((s.get('use_history',False) for s in record['state']['sequence'] if s.get('job')==j['id']),False)} for j in jobs]
            with self.store.connect() as db:db.execute('INSERT INTO studio_video_renders VALUES (?,?,?)',(rid,workspace,json.dumps(render)))
            self.executor.submit(self._compose,render,jobs,ffmpeg,ffprobe)
            return render

    def _compose(self,render,jobs,ffmpeg,ffprobe):
        try:
            folder=self.folder/render['id'];folder.mkdir(exist_ok=True);output=folder/'product-film.mp4'
            args=[ffmpeg,'-y','-hide_banner','-loglevel','error']
            for job in jobs:args+=['-i',job['path']]
            filters=';'.join(f'[{i}:v]scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,trim=duration=5,setpts=PTS-STARTPTS[v{i}]' for i in range(len(jobs)))
            filters+=';'+''.join(f'[v{i}]' for i in range(len(jobs)))+f'concat=n={len(jobs)}:v=1:a=0[out]'
            result=subprocess.run(args+['-filter_complex',filters,'-map','[out]','-c:v','libx264','-preset','fast','-crf','19','-pix_fmt','yuv420p','-movflags','+faststart',str(output)],capture_output=True,timeout=180,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if result.returncode:raise ValueError()
            info=probe(output,ffprobe)
            if abs(info['duration']-render['duration'])>.1:raise ValueError()
            render.update(state='succeeded',path=str(output),info=info)
        except (ValueError,OSError,subprocess.TimeoutExpired):render.update(state='failed',error='本地合成未完成，已采用片段保留，可以重新合成')
        self._put(render,'studio_video_renders')

    def media(self,identifier,kind):
        item=self._get(identifier,'studio_video_renders' if kind=='render' else 'studio_video_jobs')
        if item['state']!='succeeded':raise ValueError('视频尚未完成')
        return str(self.store.media.materialize(item['object_id'])) if item.get('object_id') else item['path']
