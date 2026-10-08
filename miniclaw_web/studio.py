"""The original free canvas, backed by the same Store and Canvas as Hermes.

Canvas documents own editing history. Workspaces own adoption and shot references.
The director and full Chat resume the same durable project conversation.
"""
import copy
import hashlib
import json
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from .canvas import Conflict
from .video_workspace import VideoWorkspace
from .video_precision import VideoPrecision
from .studio_projects import StudioProjects


class Studio(StudioProjects):
    def __init__(self, store, canvas, root):
        self.store, self.canvas = store, canvas
        self.folder = Path(root) / 'frontend' / 'public' / 'studio'
        self.workspaces = VideoWorkspace(store)
        self.precision = VideoPrecision(self.folder, store.home, store=store, canvas=canvas)
        with store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS studio_links (workspace TEXT PRIMARY KEY, chat_id TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS studio_limits (workspace TEXT PRIMARY KEY, calls INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS studio_reservations (workspace TEXT, job TEXT PRIMARY KEY)')
            db.execute('CREATE TABLE IF NOT EXISTS studio_projects (workspace TEXT PRIMARY KEY, name TEXT NOT NULL, origin TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS studio_image_requests (workspace TEXT, id TEXT, signature TEXT, data TEXT, PRIMARY KEY(workspace,id))')
        canvas.submission_policy = self.reserve
        from .decisions import JevDecisions, JevConfig
        self.decisions = JevDecisions(store, JevConfig.from_env())
        self._video=None;self.root=Path(root)

    @property
    def video(self):
        with self.canvas.lock:
            if self._video is None:
                from .studio_video import StudioVideo
                self._video=StudioVideo(self,self.root)
        return self._video

    def list(self, owner=None):
        return self.project_list(owner)

    def import_creator(self, creator, identifier, revision):
        # Explicit, one-time mapping. Never merge projects based on their names.
        workspace='creator-'+identifier
        with creator.lock, self.canvas.lock:
            old=self.workspaces.get(workspace)
            if old:return old
            source=creator.get(identifier);creator._cas(source,revision)
            if any(j['state'] in ('queued','running','unknown') for j in source['jobs']):raise Conflict('旧项目还有处理中任务，请先完成或核对任务再迁入')
            assets=[]
            for slot in ('source','cover','detail','scene'):
                if slot not in source['assets']:continue
                item=source['assets'][slot]
                project=self.canvas.create(source['name']+' · '+slot)
                asset=self.canvas.add_asset(project['id'],creator._asset_path(source,slot).read_bytes(),item['name'])
                from .canvas_document import blank, layer_base
                document=blank(asset['width'],asset['height']);document['layers']=[layer_base('image',item['name'],asset['width'],asset['height'],asset_id=asset['id'])]
                self.canvas.save(project['id'],project['revision'],document,'迁入旧项目图片')
                assets.append({'id':slot+'-'+item['id'],'name':item['name'],'file':self.precision.file_url(project['id'],asset['id']), 'role':slot,'x':len(assets)*300,'y':0,'w':250,'h':360})
            notes=[]
            for field,title in [('facts','商品事实'),('selling_points','购买理由建议'),('audience','受众'),('style','风格'),('constraints','限制'),('script','口播稿'),('caption','发布文案')]:
                if source.get(field):notes.append({'id':'n-'+field,'title':title,'text':source[field],'x':len(notes)*360,'y':-300,'w':340,'h':240,'source':{'type':'creator','label':source['name'],'project':identifier,'revision':revision}})
            state={'assets':assets,'shots':[],'edits':{},'notes':notes,'messages':[],'saved':[],'sequence':[],'facts':source['constraints'] if len(source['constraints'])<=1000 else ''}
            record=self.workspaces.save(workspace,{'request_id':'creator-import-'+identifier,'revision':0,'state':state})
            with self.store.connect() as db:db.execute('INSERT INTO studio_projects VALUES (?,?,?)',(workspace,source['name'],json.dumps({'profile':'formal','creator':identifier,'revision':revision})))
            if source.get('chat_id'):self.link(workspace,source['chat_id'])
            return record

    def decide(self, workspace, request):
        if set(request)!={'request_id','revision','instruction','target'}:raise ValueError('决策请求字段无效')
        record=self.workspaces.get(workspace)
        if not record or record['revision']!=request['revision']:raise Conflict('决策依据已更新')
        state=record['state'];shots=state['shots'][:12]
        if not shots:return {'status':'unavailable','reason':'no_shots','mode':'shadow'}
        selected=request['target'] if request['target'] in [s['id'] for s in shots] else None
        snapshot={'revision':record['revision'],'facts':[{'text':state.get('facts',''),'source':'project_requirement'}],
                  'shots':[{'id':s['id'],'purpose':s.get('name','视频片段')} for s in shots],
                  'studio':{'objects':[{'id':o['id'],'label':o.get('name',o.get('title','对象'))} for o in (state['assets']+shots+state['notes'])[:20]]}}
        result=self.decisions.evaluate('studio-'+workspace,request['request_id'],request['instruction'],snapshot,selected)
        return {**result,'mode':'shadow','question_version':'studio-v2'}

    def reserve(self, db, project, job_id):
        # This callback runs in the same transaction as inserting the job.
        row=db.execute('SELECT workspace FROM video_precision_links WHERE json_extract(data,\'$.project\')=?',(project,)).fetchone()
        if not row: return
        workspace=row[0]
        limit=db.execute('SELECT calls FROM studio_limits WHERE workspace=?',(workspace,)).fetchone()
        used=db.execute('SELECT COUNT(*) FROM studio_reservations WHERE workspace=?',(workspace,)).fetchone()[0]
        if not limit or used>=limit[0]: raise ValueError('本项目图片生成次数已达上限。请在项目资料→项目概览→图片生成次数上限中调高并保存；当前方案和原图已保留。')
        db.execute('INSERT INTO studio_reservations VALUES (?,?)',(workspace,job_id))

    def budget(self, workspace, calls=None):
        if not self.workspaces.get(workspace): raise ValueError('项目不存在')
        with self.store.connect() as db:
            if calls is not None:
                if type(calls) is not int or not 0<=calls<=1000: raise ValueError('请输入0至1000的整数作为项目图片生成次数上限')
                db.execute('INSERT OR REPLACE INTO studio_limits VALUES (?,?)',(workspace,calls))
            limit=db.execute('SELECT calls FROM studio_limits WHERE workspace=?',(workspace,)).fetchone()
            used=db.execute('SELECT COUNT(*) FROM studio_reservations WHERE workspace=?',(workspace,)).fetchone()[0]
        return {'limit':limit[0] if limit else 0,'reserved':used,'remaining':max(0,(limit[0] if limit else 0)-used),'max_calls':1000,'cost':'供应商未返回实际费用；生成次数是上限，金额待账单核对'}

    def chat(self, workspace):
        self.workspaces.identifier(workspace)
        with self.store.connect() as db:
            row = db.execute('SELECT chat_id FROM studio_links WHERE workspace=?', (workspace,)).fetchone()
        return row[0] if row else None

    def link(self, workspace, owner):
        if not self.workspaces.get(workspace):
            raise ValueError('请先保存创作项目')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT chat_id FROM studio_links WHERE workspace=?', (workspace,)).fetchone()
            if row and row[0] != owner:
                raise Conflict('项目已有关联对话，请恢复该对话继续。当前草稿已保留。')
            db.execute('INSERT OR IGNORE INTO studio_links VALUES (?,?)', (workspace, owner))
        return {'chat_id': owner}

    def context(self, request, owner):
        if not isinstance(request, dict) or set(request) - {'workspace', 'target', 'revision'}:
            raise ValueError('项目引用无效')
        workspace = request.get('workspace')
        self.workspaces.identifier(workspace)
        with self.store.connect() as db:
            db.execute('BEGIN')
            link=db.execute('SELECT chat_id FROM studio_links WHERE workspace=?',(workspace,)).fetchone()
            if not link or link[0]!=owner:raise ValueError('本对话未关联该创作项目')
            row=db.execute('SELECT data FROM video_workspaces WHERE id=?',(workspace,)).fetchone()
            record=json.loads(row[0]) if row else None
            manifest=[dict(target=t,kind=k,version_id=v) for t,k,v in db.execute('SELECT i.target,i.kind,h.revision_id FROM media_items i JOIN media_heads h ON h.item_id=i.id WHERE i.scope=? ORDER BY i.target,i.kind',(workspace,))]
        if not record or request.get('revision') != record['revision']:
            raise Conflict('项目已更新，请读取最新进度后再发送。草稿仍保留。')
        state, target = record['state'], request.get('target')
        objects = state['assets'] + state['shots'] + state['notes']
        selected = next((o for o in objects if o['id'] == target), None)
        if target and not selected:
            raise ValueError('引用对象已删除，请重新选择')
        def summary(obj):return {k:v for k,v in obj.items() if k not in ('file','originalFile','versions','region','x','y','w','h')}
        data = {'workspace': workspace, 'revision': record['revision'], 'name':(self.project_info(workspace) or {}).get('name','创作项目'), 'requirements': state.get('facts', ''),
                'target': summary(selected) if selected else None, 'assets': [summary(o) for o in state['assets']],
                'shots': [summary(o) for o in state['shots']], 'recent_changes': record['events'][-6:]}
        data['video_tasks']=[{k:j.get(k) for k in ('id','shot','name','state','duration','stale','error')} for j in self.video.list(workspace)]
        data['adopted_sequence']=state['sequence'];data['outputs']=self.video.renders(workspace)
        data['content_versions']=manifest
        return data

    @staticmethod
    def shot_inputs(shot):
        return [item for item in ([shot.get('first')] if shot and shot.get('mode') == 'first' else shot.get('refs', []) if shot else []) if item]

    @classmethod
    def edit_key(cls, shot, asset):
        if asset.get('versionBase'):return 'version-'+hashlib.sha256((asset['id']+asset['versionBase']).encode()).hexdigest()[:40]
        if not shot or asset.get('editProject'): return asset['id']
        suffix = '-'+hashlib.sha256(asset['id'].encode()).hexdigest()[:16] if len(cls.shot_inputs(shot)) > 1 else ''
        return 'shot-'+shot['id']+suffix

    def editing_target(self, workspace, target, asset_id=None):
        record = self.workspaces.get(workspace)
        if not record: raise ValueError('项目不存在')
        state = record['state']
        asset = next((a for a in state['assets'] if a['id'] == target), None)
        if not asset:
            shot = next((s for s in state['shots'] if s['id'] == target), None)
            inputs = self.shot_inputs(shot)
            if asset_id and asset_id not in inputs: raise ValueError('这张图片不属于当前片段，请重新选择')
            if len(inputs) > 1 and not asset_id: raise ValueError('请选择要修改的参考图')
            asset = next((a for a in state['assets'] if a['id'] == asset_id), None) if asset_id else next((a for a in state['assets'] if a['id'] in inputs), None)
        elif asset_id and asset_id != asset['id']: raise ValueError('图片与当前对象不一致')
        if not asset or asset.get('pending'): raise ValueError('请先选择一张已有图片')
        return asset

    def open(self, workspace, target, asset_id=None):
        record = self.workspaces.get(workspace)
        if not record: raise ValueError('项目不存在')
        shot = next((s for s in record['state']['shots'] if s['id']==target),None)
        inputs = self.shot_inputs(shot)
        choices = [{'id':a['id'],'name':a['name'],'file':a['file']} for a in record['state']['assets'] if a['id'] in inputs and not a.get('pending')]
        if len(inputs)>1 and not asset_id: return {'selection_required':True,'assets':choices}
        if not asset_id and (shot and not inputs or any(n['id']==target for n in record['state']['notes'])):
            return {'discussion_only':True,'assets':[]}
        asset = self.editing_target(workspace, target, asset_id)
        # An adopted layered asset remains the shared working document across
        # asset selection, its shot, director and Chat. Legacy shot drafts stay
        # separate until an explicit adoption establishes this association.
        edit_key = self.edit_key(shot, asset)
        if asset.get('versionBase') and asset.get('documentVersion') and asset.get('editProject'):
            # New versions retain editable layers. Explicit history restore moves
            # the working-document head; old file-only history opens a new draft.
            project=asset['editProject']
            with self.store.connect() as db:
                initialized=db.execute('SELECT 1 FROM video_precision_links WHERE workspace=? AND object_id=?',(workspace,edit_key)).fetchone()
                head=db.execute('SELECT revision_id FROM media_heads WHERE item_id=?',(self.store.versions.item_id('canvas:'+project,'document','document'),)).fetchone()
            if not initialized and (not head or head[0]!=asset['documentVersion']):
                row=self.canvas.get(project)
                self.canvas.restore_version(project,row['revision'],asset['documentVersion'])
            with self.store.connect() as db:
                original=db.execute('SELECT data FROM video_precision_links WHERE workspace=? AND object_id=?',(workspace,asset['id'])).fetchone()
                if original and json.loads(original[0])['project']==project:
                    db.execute('INSERT OR IGNORE INTO video_precision_links VALUES (?,?,?)',(workspace,edit_key,original[0]))
        meta = self.precision.full_open({'workspace': workspace, 'object_id': edit_key, 'file': asset['file'], 'name': asset['name']})
        row = self.canvas.get(meta['project'])
        owner = self.chat(workspace)
        if owner and row['chat_id'] != owner:
            row = self.canvas.metadata(row['id'], row['revision'], chat_id=owner, link=True)
        return {**meta, 'revision':row['revision'], 'layer':row['document']['layers'][0]['id'], 'object':asset['id'], 'source':asset['file'], 'assets':choices if len(inputs)>1 else [], **({'shot':shot['id']} if shot else {})}

    def image_request(self, workspace, request_id):
        self.workspaces.identifier(request_id)
        with self.store.connect() as db:
            row = db.execute('SELECT data FROM studio_image_requests WHERE workspace=? AND id=?', (workspace, request_id)).fetchone()
        if not row: raise ValueError('图片任务不存在')
        meta = json.loads(row[0])
        job = self.canvas.job(meta['project'], meta['job'])
        output = job.get('output')
        return {**meta, 'state':job['state'], 'error':job.get('error',''),
                'output':self.precision.file_url(meta['project'], output['id']) if output else None,
                'output_id':output['id'] if output else None,
                'width':output['width'] if output else None, 'height':output['height'] if output else None}

    def submit_image(self, workspace, request):
        if set(request) != {'request_id','revision','object','task','provider','model','prompt'}:
            raise ValueError('图片任务参数无效')
        rid = self.workspaces.identifier(request['request_id'])
        signature = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        from .media_models import resolve
        from .canvas_document import blank, layer_base, png
        from PIL import Image
        with self.canvas.lock:
            with self.store.connect() as db:
                old = db.execute('SELECT signature,data FROM studio_image_requests WHERE workspace=? AND id=?', (workspace,rid)).fetchone()
            if old:
                if old[0] != signature: raise ValueError('同一图片请求不能更换模型或参数')
                return self.image_request(workspace, rid)
            record = self.workspaces.get(workspace)
            if not record or record['revision'] != request['revision']: raise Conflict('项目已变化，请保存后重新生成')
            task = request['task']
            if task not in ('generate','edit'): raise ValueError('图片任务无效')
            resolve(task, request['provider'], request['model'])
            if not isinstance(request['prompt'],str) or not 1 <= len(request['prompt'].strip()) <= 2000: raise ValueError('图片要求需要1至2000字')
            target = next((a for a in record['state']['assets'] if a['id']==request['object']),None)
            if not target: raise ValueError('图片节点已移除')
            if task == 'edit':
                if target.get('versionBase'):
                    meta=self.open(workspace,target['id'])
                else:
                    meta = self.precision.open({'workspace':workspace,'object_id':target['id'],'file':target.get('file'),'name':target['name']})
                row = self.canvas.get(meta['project'])
            else:
                with self.store.connect() as db:
                    oldlink = db.execute('SELECT data FROM video_precision_links WHERE workspace=? AND object_id=?', (workspace,target['id'])).fetchone()
                if oldlink:
                    row = self.canvas.get(json.loads(oldlink[0])['project'])
                else:
                    row = self.canvas.create(target['name'])
                    asset = self.canvas.add_asset(row['id'], png(Image.new('RGB',(928,1664),'#181818')), 'generation-base.png')
                    doc = blank(928,1664); doc['layers']=[layer_base('image',target['name'],928,1664,asset_id=asset['id'])]
                    row = self.canvas.save(row['id'],row['revision'],doc,'准备图片生成')
                    with self.store.connect() as db:
                        db.execute('INSERT INTO video_precision_links VALUES (?,?,?)',(workspace,target['id'],json.dumps({'project':row['id'],'original':asset['id'],'signature':hashlib.sha256(b'').hexdigest()})))
            job = self.canvas.submit(row['id'],row['revision'],row['document']['layers'][0]['id'],
                                     request['prompt'],rid,False, model=request['model'],provider=request['provider'],task=task)
            meta = {'project':row['id'],'job':job['id'],'revision':row['revision'], 'object':target['id'],
                    'request_id':rid,'task':task,'model':request['model'],'provider':request['provider'], 'source':target.get('file')}
            with self.store.connect() as db:
                db.execute('INSERT INTO studio_image_requests VALUES (?,?,?,?)',(workspace,rid,signature,json.dumps(meta)))
            return self.image_request(workspace, rid)

    def tasks(self, workspace):
        self.workspaces.identifier(workspace)
        with self.store.connect() as db:
            links = db.execute('SELECT object_id,data FROM video_precision_links WHERE workspace=?', (workspace,)).fetchall()
        result=[]
        for object_id, raw in links:
            row=self.canvas.get(json.loads(raw)['project'])
            result.append({'object':object_id,'project':row['id'],'name':row['name'],'revision':row['revision'],
                           'jobs':self.canvas.jobs(row['id']), 'plans':self.canvas.plans.list(row['id'])})
        return result

    def compare_job(self, project, request):
        """Compare a retained result against today's document, without changing it."""
        if not isinstance(request,dict) or set(request)!={'revision','job'}:raise ValueError('请选择要比较的修图结果')
        with self.canvas.lock:
            row=self.canvas.get(project)
            self.canvas._cas(row,request['revision'])
            job=self.canvas.job(project,request['job'])
            if job['state']!='succeeded' or not job.get('output'):raise ValueError('没有可比较的结果')
            if job.get('review',{}).get('decision')=='reject':raise ValueError('候选已标记为未采用，请先重新核对')
            _,layer=self.canvas._target(project,row['revision'],job['layer_id'])
            document=copy.deepcopy(row['document'])
            next(l for l in document['layers'] if l['id']==layer['id'])['asset_id']=job['output']['id']
            before=self.canvas.add_asset(project,self.canvas.export(project),'当前工作图.png')
            after=self.canvas.add_asset(project,self.canvas.preview(project,row['revision'],document),'待采用修图.png')
            # Bind the exact reviewed document to its immutable image. Adoption still
            # requires the same revision; refreshing a comparison never applies it.
            owner=self.canvas.owner(project)
            asset=self.store.get('attachments',after['id'],owner)
            asset['studio_comparison']={'revision':row['revision'],'job':job['id'],'document':document}
            self.store.put('attachments',after['id'],asset,owner)
            return {'project':project,'revision':row['revision'],'output':self.precision.file_url(project,after['id']),
                    'output_id':after['id'],'before_output':self.precision.file_url(project,before['id']),
                    'width':after['width'],'height':after['height'],'comparison':{'id':after['id'],'job':job['id']}}

    def apply_preview(self, project, request):
        """Recover a confirmed working-document step without executing it twice."""
        if not isinstance(request,dict) or set(request)!={'revision','kind','id'}:raise ValueError('比较确认参数无效')
        with self.canvas.lock:
            row=self.canvas.get(project)
            revision=request['revision']
            if request['kind']=='comparison':
                asset=self.store.get('attachments',request['id'],self.canvas.owner(project))
                comparison=asset.get('studio_comparison')
                if not comparison or comparison['revision']!=revision:raise ValueError('比较依据无效')
                job=self.canvas.job(project,comparison['job'])
                if job.get('review',{}).get('decision')=='reject':raise ValueError('候选已标记为未采用，请先重新核对')
                if row['revision']==revision:
                    self.canvas.save(project,revision,comparison['document'],'采用已比较的修图结果')
                elif not (row['revision']==revision+1 and row['document']==comparison['document']):
                    raise Conflict('工作图已变化，候选已保留，请重新比较')
            elif request['kind']=='plan':
                plan=next((p for p in self.canvas.plans.list(project) if p['id']==request['id']),None)
                if not plan or any(s['action']=='ai_edit' for s in plan['steps']):raise ValueError('请先核对完整方案')
                if row['revision']==revision:
                    self.canvas.plans.apply(project,plan['id'],revision)
                elif not (row['revision']==revision+1 and plan['state']=='applied' and plan['revision']==row['revision']):
                    raise Conflict('工作图已变化，预览仍保留，请重新比较')
            elif request['kind']=='job':
                job=self.canvas.job(project,request['id'])
                if not job or job['revision']!=revision:raise ValueError('候选依据无效')
                if row['revision']==revision:self.canvas.adopt(project,revision,job['id'])
                elif not (row['revision']==revision+1 and job.get('output') and any(l['id']==job['layer_id'] and l.get('asset_id')==job['output']['id'] for l in row['document']['layers'])):
                    raise Conflict('工作图已变化，候选已保留，请重新比较')
            else:raise ValueError('比较类型无效')
            return self.canvas.get(project)

    def command(self, workspace, request):
        """Adoption is a server-side object operation, never a model-owned snapshot."""
        self.workspaces.identifier(workspace)
        if set(request) != {'request_id','revision','action','args'}: raise ValueError('操作字段无效')
        rid=self.workspaces.identifier(request['request_id'])
        if request['action']=='shot-plan':return self.adopt_shot_plan(workspace,request)
        signature=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()
        args=request['args']
        with self.canvas.lock, self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT signature,data FROM video_workspace_receipts WHERE workspace=? AND id=?',(workspace,rid)).fetchone()
            if old:
                if old[0]!=signature: raise ValueError('同一操作的内容不能改变')
                return self.store.versions.receipt(db,old[1])
            found=db.execute('SELECT data FROM video_workspaces WHERE id=?',(workspace,)).fetchone()
            if not found: raise ValueError('项目不存在')
            record=json.loads(found[0])
            if request['revision'] != record['revision']: raise Conflict('项目已更新，请重新比较后采用')
            state=record['state']
            if request['action']=='idea':
                if not isinstance(args,dict) or set(args)!={'owner','message'} or self.chat(workspace)!=args['owner']:raise ValueError('讨论不属于该项目')
                text=self.message_reader(args['owner'],args['message'])
                nid='n'+hashlib.sha256((workspace+args['owner']+str(args['message'])).encode()).hexdigest()[:32]
                if not any(n['id']==nid for n in state['notes']):
                    if len(state['notes'])>=500:raise ValueError('画布方案已满')
                    state['notes'].append({'id':nid,'title':'讨论中的方案','text':text,'x':360,'y':-200-len(state['notes'])*270,'w':340,'h':240,
                        'source':{'id':nid,'type':'chat','sessionId':args['owner'],'messageId':args['message'],'label':'用户从项目对话保存的想法'}})
                record.update(revision=record['revision']+1,updated_at=time.time())
                record['events']=(record['events']+[{'id':rid,'label':'将讨论放到画布','object':nid,'at':time.time()}])[-80:]
                encoded=json.dumps(record,ensure_ascii=False)
                db.execute('UPDATE video_workspaces SET data=? WHERE id=?',(encoded,workspace))
                self.store.versions.put_receipt(db,workspace,rid,signature,record)
                return record
            if request['action'] not in ('adopt','restore'): raise ValueError('操作不支持')
            required={'object','source','project','revision','asset'} if request['action']=='adopt' else {'object','source'}
            if not isinstance(args,dict) or set(args)-required-({'shot'} if request['action']=='adopt' else set()) or not required<=set(args): raise ValueError('采用参数无效')
            asset=next((a for a in state['assets'] if a['id']==args['object']),None)
            if not asset or asset['file']!=args['source']: raise Conflict('原素材已改变，结果保留，请重新核对')
            if request['action']=='adopt':
                shot = next((s for s in state['shots'] if s['id']==args.get('shot')),None) if args.get('shot') else None
                if args.get('shot') and (not shot or asset['id'] not in ([shot.get('first')] if shot.get('mode')=='first' else shot.get('refs',[]))):raise Conflict('镜头的输入已变化，请重新比较')
                previous_key=self.edit_key(shot,asset)
                link=db.execute('SELECT data FROM video_precision_links WHERE workspace=? AND object_id=?',(workspace,previous_key)).fetchone()
                if not link or json.loads(link[0])['project']!=args['project']: raise ValueError('候选不属于这张图片')
                row=self.canvas._get(db,args['project'])
                self.canvas._cas(row,args['revision'])
                output=self.canvas.asset(row['id'],args['asset'])
                # Only exports recorded by full_preview are eligible for project adoption.
                preview=self.store.get('attachments',output['id'],self.canvas.owner(row['id']))
                if preview.get('studio_export_revision') != args['revision']: raise Conflict('候选不是当前工作图的比较结果，请重新比较')
                destination=self.precision.file_url(row['id'],output['id'])
                if shot:
                    import uuid
                    original_id=asset['id'];asset=copy.deepcopy(asset);asset['id']=uuid.uuid4().hex
                    asset['name']+=' · '+shot.get('name','局部修改')
                    # A derived input remains visible without covering existing nodes.
                    occupied=state['assets']+state['shots']+state['notes']
                    width,height=asset.get('w',280),asset.get('h',380)
                    start_x,start_y=asset.get('x',0),asset.get('y',0)+height+60
                    for offset in range(len(occupied)+1):
                        x=start_x+(offset%4)*(width+50);y=start_y+(offset//4)*(height+60)
                        if not any(x<o.get('x',0)+o.get('w',620)+20 and x+width+20>o.get('x',0) and y<o.get('y',0)+o.get('h',400)+20 and y+height+20>o.get('y',0) for o in occupied):
                            asset.update(x=x,y=y);break
                    state['assets'].append(asset)
                    if shot.get('mode')=='first':shot['first']=asset['id']
                    else:shot['refs']=[asset['id'] if ref==original_id else ref for ref in shot.get('refs',[])]
                    # The adopted reference is a new visible node, but keeps
                    # the same layered working document and its history.
                    next_key=self.edit_key(shot,asset)
                    if next_key!=previous_key:
                        db.execute('INSERT INTO video_precision_links VALUES (?,?,?)',(workspace,next_key,link[0]))
                asset.setdefault('originalFile',asset['file'])
                asset.setdefault('versions',[]).append({'file':asset['file'],'at':time.time()})
                asset.update(file=destination,editProject=row['id'])
                version_head=db.execute('SELECT revision_id FROM media_heads WHERE item_id=?',
                    (self.store.versions.item_id('canvas:'+row['id'],'document','document'),)).fetchone()
                if version_head:asset['documentVersion']=version_head[0]
                shared=db.execute('SELECT data FROM video_precision_links WHERE workspace=? AND object_id=?',(workspace,asset['id'])).fetchone()
                if shared and json.loads(shared[0])['project']!=row['id'] and not asset.get('versionBase'):
                    raise Conflict('素材已有其他工作图，请重新核对采用关系')
                db.execute('INSERT INTO video_precision_links VALUES (?,?,?) ON CONFLICT(workspace,object_id) DO UPDATE SET data=excluded.data',(workspace,asset['id'],link[0]))
                asset.pop('versionBase',None)
                state['edits'][asset['id']]={'applied':True,'project':row['id'],'revision':row['revision']}
                label='采用精修结果'
            else:
                if not asset.get('originalFile'): raise ValueError('没有可恢复的原图')
                asset.setdefault('versions',[]).append({'file':asset['file'],'at':time.time()})
                asset['file']=asset['originalFile']; label='恢复原素材'
            for shot in state['shots']:
                if asset['id'] in ([shot.get('first')] if shot.get('mode')=='first' else shot.get('refs',[])):
                    shot.update(dirty=True,inputReview=True)
            state['saved']=[s for s in state['saved'] if not next((x.get('inputReview') for x in state['shots'] if x['id']==s['id']),False)]
            record.update(revision=record['revision']+1,updated_at=time.time())
            record['events']=(record['events']+[{'id':rid,'label':label,'object':asset['id'],'at':time.time()}])[-80:]
            encoded=json.dumps(record,ensure_ascii=False)
            db.execute('UPDATE video_workspaces SET data=? WHERE id=?',(encoded,workspace))
            self.store.versions.put_receipt(db,workspace,rid,signature,record)
            return record


def routes(studio, body, session, persist, creator=None):
    import asyncio
    router=APIRouter()
    async def call(fn,*args):
        try: return await asyncio.to_thread(fn,*args)
        except Conflict as e: raise HTTPException(409,str(e)) from None
        except (ValueError,KeyError,TypeError) as e: raise HTTPException(400,str(e)) from None
    async def checked(request):
        origin=request.headers.get('origin')
        if origin and origin.rstrip('/')!=str(request.base_url).rstrip('/'): raise HTTPException(403,'仅允许本工作区操作')
        return await body(request,8*1024*1024)
    @router.get('/api/workspaces')
    async def list_projects(owner:str|None=None,page:int|None=None,page_size:int=6,q:str=''):
        from fastapi.responses import JSONResponse
        from hermes_cli.web_server import _SESSION_TOKEN
        response=JSONResponse(await call(studio.project_list,owner,page,page_size,q))
        response.set_cookie('studio_media',_SESSION_TOKEN,httponly=True,samesite='strict',path='/studio/media')
        return response
    @router.post('/api/workspaces')
    async def create_project(request:Request):
        p=await checked(request);live=session(p.get('session_id'));persist(live)
        return await call(studio.create_project,p,live['session_key'])
    @router.get('/api/workspaces/{workspace}/info')
    async def info(workspace:str):return await call(studio.project_info,workspace)
    @router.post('/api/workspaces/import-creator/{identifier}')
    async def import_creator(identifier:str,request:Request):
        p=await checked(request)
        if not creator or set(p)!={'revision'}:raise HTTPException(400,'请选择旧项目及版本')
        return await call(studio.import_creator,creator,identifier,p['revision'])
    @router.get('/api/workspaces/{workspace}')
    async def get(workspace:str): return await call(studio.workspaces.get,workspace)
    @router.post('/api/workspaces/{workspace}')
    async def save(workspace:str,request:Request): return await call(studio.workspaces.save,workspace,await checked(request))
    @router.get('/api/workspaces/{workspace}/versions')
    async def versions(workspace:str,target:str|None=None,page:int=1,page_size:int=20,category:str='all'):
        if not await call(studio.workspaces.get,workspace):raise HTTPException(404,'项目不存在')
        return await call(studio.store.versions.page,workspace,target,None,page,page_size,category)
    @router.get('/api/workspaces/{workspace}/versions/{version_id}')
    async def version_detail(workspace:str,version_id:str):return await call(studio.store.versions.detail,workspace,version_id)
    @router.get('/api/workspaces/{workspace}/storage')
    async def storage_capacity(workspace:str):
        if not await call(studio.workspaces.get,workspace):raise HTTPException(404,'项目不存在')
        return await call(studio.store.versions.capacity,workspace)
    @router.post('/api/workspaces/{workspace}/versions/restore')
    async def restore_version(workspace:str,request:Request):return await call(studio.workspaces.restore_version,workspace,await checked(request))
    @router.post('/api/workspaces/{workspace}/assets/upload')
    async def upload_asset(workspace:str,request:Request):
        import base64,secrets
        from hermes_cli.web_server import _SESSION_TOKEN
        from .attachments import decode_upload,MAX_IMAGE
        if not secrets.compare_digest(request.headers.get('x-hermes-session-token',''),_SESSION_TOKEN):raise HTTPException(401)
        origin=request.headers.get('origin')
        if origin and origin.rstrip('/')!=str(request.base_url).rstrip('/'):raise HTTPException(403)
        if not await call(studio.workspaces.get,workspace):raise HTTPException(404,'项目不存在')
        content=bytearray()
        async for chunk in request.stream():
            if len(content)+len(chunk)>MAX_IMAGE:raise HTTPException(413,'图片最大5 MiB')
            content.extend(chunk)
        def publish():
            import io
            from PIL import Image
            name=request.query_params.get('name','image.png')
            raw,kind,mime,_=decode_upload(name,base64.b64encode(content).decode())
            if kind!='image':raise ValueError('请选择图片')
            obj=studio.store.media.put_bytes(raw,mime)
            with studio.store.connect() as db:db.execute('INSERT OR IGNORE INTO media_grants VALUES (?,?)',(workspace,obj['id']))
            with Image.open(io.BytesIO(raw)) as image:width,height=image.size
            return dict(file=studio.store.media.url(obj['id']),object_id=obj['id'],width=width,height=height,name=name)
        return await call(publish)
    @router.get('/api/workspaces/{workspace}/chat')
    async def chat(workspace:str): return {'chat_id':await call(studio.chat,workspace)}
    @router.post('/api/workspaces/{workspace}/chat')
    async def link(workspace:str,request:Request):
        p=await checked(request)
        if set(p)!={'session_id'}: raise HTTPException(400,'需要运行对话')
        live=session(p['session_id']);persist(live)
        return await call(studio.link,workspace,live['session_key'])
    @router.get('/api/workspaces/{workspace}/tasks')
    async def tasks(workspace:str): return await call(studio.tasks,workspace)
    @router.get('/api/workspaces/{workspace}/audit')
    async def audit(workspace:str):
        from .generation_audit import project_ledger
        return await call(project_ledger,studio,workspace)
    @router.get('/api/workspaces/{workspace}/video')
    async def video_status(workspace:str):return {'provider':studio.video.status(),'jobs':await call(studio.video.list,workspace),'renders':await call(studio.video.renders,workspace)}
    @router.get('/api/workspaces/{workspace}/models')
    async def model_catalog(workspace:str):
        if not studio.workspaces.get(workspace): raise HTTPException(404,'项目不存在')
        from .media_models import catalog
        return {'models':catalog()}
    @router.post('/api/workspaces/{workspace}/images')
    async def image_submit(workspace:str,request:Request):return await call(studio.submit_image,workspace,await checked(request))
    @router.get('/api/workspaces/{workspace}/images/{request_id}')
    async def image_status(workspace:str,request_id:str):return await call(studio.image_request,workspace,request_id)
    @router.post('/api/workspaces/{workspace}/video')
    async def video_submit(workspace:str,request:Request):return await call(studio.video.submit,workspace,await checked(request))
    @router.post('/api/workspaces/{workspace}/video/adopt')
    async def video_adopt(workspace:str,request:Request):return await call(studio.video.adopt,workspace,await checked(request))
    @router.post('/api/workspaces/{workspace}/video/render')
    async def video_render(workspace:str,request:Request):return await call(studio.video.render,workspace,await checked(request))
    @router.get('/api/workspaces/{workspace}/budget')
    async def budget(workspace:str): return await call(studio.budget,workspace)
    @router.post('/api/workspaces/{workspace}/budget')
    async def set_budget(workspace:str,request:Request):
        p=await checked(request)
        if set(p)!={'calls'}: raise HTTPException(400,'请指定生成次数上限')
        if p['calls'] is None: raise HTTPException(400,'请输入0至1000的整数作为项目图片生成次数上限')
        return await call(studio.budget,workspace,p['calls'])
    @router.post('/api/workspaces/{workspace}/decisions')
    async def decision(workspace:str,request:Request): return await call(studio.decide,workspace,await checked(request))
    @router.post('/api/workspaces/{workspace}/commands')
    async def command(workspace:str,request:Request): return await call(studio.command,workspace,await checked(request))
    @router.post('/api/workspaces/{workspace}/editing-target')
    async def target(workspace:str,request:Request):
        p=await checked(request)
        if set(p)-{'target','session_id','asset'} or not {'target','session_id'}<=set(p): raise HTTPException(400,'请选择操作对象与当前对话')
        live=session(p['session_id']);persist(live)
        await call(studio.link,workspace,live['session_key'])
        return await call(studio.open,workspace,p['target'],p.get('asset'))
    @router.post('/api/precision/full/open')
    async def open_image(request:Request):
        p=await checked(request)
        return await call(studio.open,p.get('workspace'),p.get('object_id'))
    @router.post('/api/precision/full/{project}/preview')
    async def preview(project:str,request:Request):
        p=await checked(request)
        result=await call(studio.precision.full_preview,project,p)
        owner=studio.canvas.owner(project)
        record=studio.store.get('attachments',result['output_id'],owner)
        record['studio_export_revision']=result['revision']
        studio.store.put('attachments',result['output_id'],record,owner)
        return result
    @router.post('/api/precision/full/{project}/apply-preview')
    async def apply_preview(project:str,request:Request):
        return await call(studio.apply_preview,project,await checked(request))
    @router.post('/api/precision/full/{project}/compare-job')
    async def compare_job(project:str,request:Request):
        return await call(studio.compare_job,project,await checked(request))
    @router.get('/api/precision/projects/{project}/assets/{asset}')
    async def image(project:str,asset:str):
        record=await call(studio.canvas.asset,project,asset)
        return FileResponse(record['path'],media_type=record['mime'],headers={'Cache-Control':'no-store'})
    @router.get('/editor/precision-workspace.html')
    async def editor():
        from hermes_cli.web_server import _SESSION_TOKEN
        file=studio.folder.parents[1]/'dist'/'precision-workspace.html'
        if not file.is_file(): raise HTTPException(503,'精修页面尚未构建')
        content=file.read_text(encoding='utf-8').replace('<head>','<head><script>window.__HERMES_SESSION_TOKEN__='+json.dumps(_SESSION_TOKEN)+';</script>')
        return HTMLResponse(content,headers={'Cache-Control':'no-store'})
    @router.get('/studio/media/{project}/assets/{asset}')
    async def media(project:str,asset:str,request:Request):
        import secrets
        from hermes_cli.web_server import _SESSION_TOKEN
        if not secrets.compare_digest(request.cookies.get('studio_media',''),_SESSION_TOKEN):raise HTTPException(401)
        origin=request.headers.get('origin')
        if origin and origin.rstrip('/')!=str(request.base_url).rstrip('/'):raise HTTPException(403)
        record=await call(studio.canvas.asset,project,asset)
        return FileResponse(record['path'],media_type=record['mime'],headers={'Cache-Control':'no-store'})
    @router.get('/studio/media/objects/{identifier}')
    async def object_media(identifier:str,request:Request):
        import secrets
        from hermes_cli.web_server import _SESSION_TOKEN
        if not secrets.compare_digest(request.cookies.get('studio_media',''),_SESSION_TOKEN):raise HTTPException(401)
        origin=request.headers.get('origin')
        if origin and origin.rstrip('/')!=str(request.base_url).rstrip('/'):raise HTTPException(403)
        def resolve():
            obj=studio.store.media.get(identifier)
            with studio.store.connect() as db:
                if not db.execute('SELECT 1 FROM media_grants WHERE object_id=? LIMIT 1',(identifier,)).fetchone():raise ValueError('文件未关联到当前工作区')
            return studio.store.media.materialize(identifier),obj['mime']
        path,mime=await call(resolve)
        return FileResponse(path,media_type=mime,headers={'Cache-Control':'private, max-age=31536000, immutable','ETag':'"'+identifier+'"'})
    @router.get('/studio/media/{kind}/{identifier}')
    async def video_media(kind:str,identifier:str,request:Request):
        import secrets
        from hermes_cli.web_server import _SESSION_TOKEN
        if kind not in ('video','render') or not secrets.compare_digest(request.cookies.get('studio_media',''),_SESSION_TOKEN):raise HTTPException(401)
        path=await call(studio.video.media,identifier,kind)
        return FileResponse(path,media_type='video/mp4',headers={'Cache-Control':'no-store'},filename='product-film.mp4' if request.query_params.get('download') else None)
    @router.get('/studio/{path:path}')
    async def static(path:str,request:Request):
        path=path or 'index.html'
        allowed={'index.html','app.js','usability.js','workflow.js','integration.js','production.js','node-composer.js','interaction.js','node-composer.css','workbench.css','project-name.js','style.css','source.png','macro.png','hero.png','frame-end.png','candidate.mp4','vendor/alpine.min.js'}
        if path not in allowed: raise HTTPException(404)
        if path=='index.html':
            from hermes_cli.web_server import _SESSION_TOKEN
            content=(studio.folder/path).read_text(encoding='utf-8').replace('__WORKSPACE_TOKEN__',_SESSION_TOKEN)
            for asset_name in ('app.js','usability.js','workflow.js','integration.js','production.js','node-composer.js','interaction.js','node-composer.css','workbench.css','project-name.js','style.css'):
                content=content.replace('"'+asset_name+'"','"'+asset_name+'?v='+str((studio.folder/asset_name).stat().st_mtime_ns)+'"')
            response=HTMLResponse(content,headers={'Cache-Control':'no-store'})
            response.set_cookie('studio_media',_SESSION_TOKEN,httponly=True,samesite='strict',path='/studio/media')
            return response
        return FileResponse(studio.folder/path,headers={'Cache-Control':'no-store'} if path.endswith(('.js','.css')) else None)
    return router
