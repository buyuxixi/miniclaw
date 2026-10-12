"""Project entry and proposal handoff for the existing spatial studio."""
import hashlib
import json
import re
import time
from .canvas import Conflict


def project_display_name(name, state):
    candidates=[name,*[n.get('title') for n in state.get('notes',[])],*[s.get('name') for s in state.get('shots',[])],*[a.get('name') for a in state.get('assets',[])]]
    for value in candidates:
        value=re.sub(r'\s*[·-]\s*(创作方案|创意方案|方案)\s*$','',str(value or '')).strip()
        if value and not re.fullmatch(r'[a-f\d]{24,}(?:\.[a-z\d]+)?',value,re.I):
            return value
    return '未命名画布'


def shot_suggestions(text, fence='studio-plan'):
    matches = re.findall(r'```'+re.escape(fence)+r'\s*\n(.*?)```', text, re.S)
    if not matches:
        return []
    try:
        data = json.loads(matches[-1])
        shots = data['shots']
        if set(data) != {'shots'} or not isinstance(shots, list) or not 1 <= len(shots) <= 12:
            raise ValueError()
        for s in shots:
            if not isinstance(s, dict) or set(s) != {'name','duration','prompt'}:
                raise ValueError()
            if not isinstance(s['name'],str) or not 1 <= len(s['name']) <= 80 or type(s['duration']) is not int or s['duration'] != 5:
                raise ValueError()
            if not isinstance(s['prompt'],str) or not 1 <= len(s['prompt']) <= 1500:
                raise ValueError()
        return shots
    except (ValueError,KeyError,TypeError):
        raise ValueError('镜头方案格式不完整，请让助手用短片方案技能重新整理；原讨论仍保留') from None


class StudioProjects:
    def chat_materials(self, workspace):
        self.workspaces.get(workspace)
        owner = self.chat(workspace)
        if not owner:
            return []
        return [{'id': image['id'], 'name': image['name'], 'file': self.store.media.url(image['object_id'])}
                for image in reversed(self.store.images(owner)) if image.get('object_id')]

    def import_chat_material(self, workspace, request):
        if not isinstance(request, dict) or set(request) != {'request_id', 'attachment'}:
            raise ValueError('请选择本项目对话中的图片')
        owner = self.chat(workspace)
        if not owner:
            raise ValueError('本项目尚未关联对话')
        return self.add_chat_image(workspace, {**request, 'session_id': 'canvas'}, owner)

    def _chat_asset(self, workspace, owner, image, occupied):
        from PIL import Image
        obj = image['object_id']
        with Image.open(self.store.media.materialize(obj)) as pixels:
            width, height = pixels.size
        w = 220; h = min(420, w * height / width); x = 60; y = 40
        for _ in range(len(occupied) + 1):
            hits = [n for n in occupied if x < n.get('x', 0) + n.get('w', 620) + 36 and x + w + 36 > n.get('x', 0)
                    and y < n.get('y', 0) + n.get('h', 400) + 36 and y + h + 101 > n.get('y', 0)]
            if not hits:
                break
            y = max(n.get('y', 0) + n.get('h', 400) + 70 for n in hits)
        source = {'type': 'chat', 'sessionId': owner, 'attachmentId': image['id'], 'objectId': obj, 'label': '项目对话中的图片'}
        for key in ('image_job_id', 'parent_id', 'root_id'):
            if image.get(key):
                source[key] = image[key]
        return {'id': 'chat-image-' + hashlib.sha256((workspace + obj).encode()).hexdigest()[:32],
                'name': image['name'], 'file': self.store.media.url(obj), 'x': x, 'y': y, 'w': w, 'h': h, 'source': source}

    def add_chat_image(self, workspace, request, owner):
        """Append an owned Chat image without copying bytes or replacing a canvas draft."""
        self.workspaces.identifier(workspace)
        if not isinstance(request,dict) or set(request)!={'request_id','session_id','attachment'}:
            raise ValueError('请选择当前对话中的图片')
        rid=self.workspaces.identifier(request['request_id'])
        attachment=request['attachment']
        if not isinstance(attachment,str) or not re.fullmatch(r'[\w-]{1,128}',attachment):
            raise ValueError('图片标识无效')
        signature=hashlib.sha256(json.dumps([owner,attachment],sort_keys=True).encode()).hexdigest()
        with self.canvas.lock,self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            link=db.execute('SELECT chat_id FROM studio_links WHERE workspace=?',(workspace,)).fetchone()
            if not link or link[0]!=owner:raise ValueError('本对话未关联该创作项目')
            found=db.execute('SELECT data FROM attachments WHERE id=? AND owner=?',(attachment,owner)).fetchone()
            if not found:raise ValueError('图片不存在或不属于当前对话')
            image=json.loads(found[0]);obj=image.get('object_id')
            media=db.execute('SELECT mime FROM file_objects WHERE id=?',(obj,)).fetchone()
            if image.get('kind')!='image' or not media or media[0] not in ('image/png','image/jpeg','image/webp'):
                raise ValueError('只能将图片加入画布')
            nid='chat-image-'+hashlib.sha256((workspace+obj).encode()).hexdigest()[:32]
            def matches(asset):
                source=asset.get('source')
                return (asset['id']==nid or isinstance(source,dict) and source.get('objectId')==obj
                        or obj in self.store.versions.objects(db,{k:asset[k] for k in ('file','originalFile','versions') if k in asset}))
            old=db.execute('SELECT signature,data FROM video_workspace_receipts WHERE workspace=? AND id=?',(workspace,rid)).fetchone()
            if old:
                if old[0]!=signature:raise ValueError('同一加入请求不能更换图片')
                record=self.store.versions.receipt(db,old[1])
            else:
                found=db.execute('SELECT data FROM video_workspaces WHERE id=?',(workspace,)).fetchone()
                if not found:raise ValueError('项目不存在')
                record=json.loads(found[0]);state=record['state']
                asset=next((a for a in state['assets'] if matches(a)),None)
                if not asset:
                    if len(state['assets'])>=500:raise ValueError('画布素材已满')
                    asset=self._chat_asset(workspace,owner,image,state['assets']+state['shots']+state['notes'])
                    state['assets'].append(asset)
                    record.update(revision=record['revision']+1,updated_at=time.time())
                    record['events']=(record['events']+[{'id':rid,'label':'将对话图片加入画布','object':nid,'at':time.time()}])[-80:]
                    db.execute('UPDATE video_workspaces SET data=? WHERE id=?',(json.dumps(record,ensure_ascii=False),workspace))
                self.store.versions.put_receipt(db,workspace,rid,signature,record)
            asset=next(a for a in record['state']['assets'] if matches(a))
            return {'workspace':workspace,'revision':record['revision'],'object':asset['id'],
                    'added':any(e['id']==rid and e.get('object')==asset['id'] for e in record['events'])}

    def project_list(self, owner=None, page=None, page_size=6, q='', workspace=None, archived=False):
        from .pagination import bounds
        if not isinstance(q,str) or len(q)>100:raise ValueError('搜索词最多100字')
        clauses=[];args=[]
        # Archived projects stay intact; they are only hidden from the default list.
        if not workspace:clauses.append(('' if archived else 'NOT ')+'EXISTS (SELECT 1 FROM project_archive a WHERE a.workspace=c.workspace)')
        if owner:clauses.append('l.chat_id=?');args.append(owner)
        if workspace:clauses.append('c.workspace=?');args.append(workspace)
        if q.strip():
            clauses.append("c.name LIKE ? ESCAPE '\\'")
            args.append('%'+q.strip().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%')
        query=' FROM workspace_catalog c LEFT JOIN studio_links l ON l.workspace=c.workspace'+(' WHERE '+' AND '.join(clauses) if clauses else '')
        with self.store.connect() as db:
            db.execute('BEGIN')
            total=db.execute('SELECT count(*)'+query,args).fetchone()[0]
            current,offset=bounds(page if page is not None else 1,page_size,total)
            rows=db.execute('SELECT c.workspace,c.name,l.chat_id,c.updated_at,c.revision,c.cover,c.notes,c.plan,c.pictures,c.shots,c.adopted'+query+' ORDER BY c.updated_at DESC,c.workspace'+(' LIMIT ? OFFSET ?' if page is not None else ''),args+([page_size,offset] if page is not None else [])).fetchall()
        result=[dict(zip(('id','name','chat_id','updated_at','revision','cover','notes','plan','pictures','shots','adopted'),r)) for r in rows]
        for record in result:record['name']=project_display_name(record['name'],{})
        return {'items':result,'total':total,'page':current,'page_size':page_size} if page is not None else result

    def project_info(self,workspace):
        rows=self.project_list(workspace=workspace)
        if not rows:return None
        with self.store.connect() as db:
            rows[0]['archived']=bool(db.execute('SELECT 1 FROM project_archive WHERE workspace=?',(workspace,)).fetchone())
        return rows[0]

    def set_archived(self, workspace, archived):
        if not isinstance(archived,bool):raise ValueError('归档状态无效')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM video_workspaces WHERE id=?',(workspace,)).fetchone():raise ValueError('项目不存在')
            if archived:db.execute('INSERT OR IGNORE INTO project_archive VALUES (?,?)',(workspace,time.time()))
            else:db.execute('DELETE FROM project_archive WHERE workspace=?',(workspace,))
        return self.project_info(workspace)

    def library_collect(self, workspace):
        """Add every saved picture of a project to the library; used before archiving test projects."""
        record=self.workspaces.get(workspace);added=[]
        for asset in record['state'].get('assets',[]):
            if not asset.get('file'):continue
            try:added.append(self.library_add(workspace,asset['file'],(asset.get('name') or '未命名素材')[:120]))
            except ValueError:continue
        return added

    def library_list(self, q=''):
        if not isinstance(q,str) or len(q)>100:raise ValueError('搜索词最多100字')
        like='%'+q.strip().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        with self.store.connect() as db:
            rows=db.execute("SELECT object_id,name,kind,source_workspace,created_at FROM library_items WHERE name LIKE ? ESCAPE '\\' ORDER BY created_at DESC,object_id LIMIT 500",(like,)).fetchall()
        return [{'id':r[0],'name':r[1],'kind':r[2],'source':r[3],'created_at':r[4],'url':self.store.media.url(r[0])} for r in rows]

    def library_add(self, workspace, file, name):
        """Collect a project file into the global library without copying bytes."""
        if not isinstance(name,str) or not 1<=len(name.strip())<=120:raise ValueError('素材名最多120字')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            found=self.store.versions.objects(db,file)
            if len(found)!=1:raise ValueError('只能收藏已保存的项目图片或视频')
            obj=found.pop()
            if not db.execute('SELECT 1 FROM media_grants WHERE scope=? AND object_id=?',(workspace,obj)).fetchone() and not db.execute(
                'SELECT 1 FROM attachments WHERE json_extract(data,\'$.object_id\')=?',(obj,)).fetchone():raise ValueError('文件不属于当前项目')
            mime=db.execute('SELECT mime FROM file_objects WHERE id=?',(obj,)).fetchone()[0]
            kind='video' if mime.startswith('video/') else 'image'
            db.execute('INSERT OR IGNORE INTO media_grants VALUES (?,?)',('library',obj))
            db.execute('INSERT OR REPLACE INTO library_items VALUES (?,?,?,?,coalesce((SELECT created_at FROM library_items WHERE object_id=?),?))',(obj,name.strip(),kind,workspace,obj,time.time()))
        return next(i for i in self.library_list() if i['id']==obj)

    def library_remove(self, obj):
        with self.store.connect() as db:
            db.execute('DELETE FROM library_items WHERE object_id=?',(obj,))
            db.execute("DELETE FROM media_grants WHERE scope='library' AND object_id=?",(obj,))
        return {'ok':True}

    def library_use(self, workspace, obj):
        """Grant a library object to a project so its canvas can reference it."""
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM library_items WHERE object_id=?',(obj,)).fetchone():raise ValueError('素材不在素材库中')
            if not db.execute('SELECT 1 FROM video_workspaces WHERE id=?',(workspace,)).fetchone():raise ValueError('项目不存在')
            db.execute('INSERT OR IGNORE INTO media_grants VALUES (?,?)',(workspace,obj))
        return {'url':self.store.media.url(obj)}

    def create_project(self, request, owner):
        if set(request)-{'request_id','name','message','facts','session_id','include_images'} or not {'request_id','name','session_id'}<=set(request):
            raise ValueError('请填写项目名并选择当前对话')
        identifier=self.workspaces.identifier(request['request_id']);workspace=self.workspaces.identifier('project-'+identifier)
        name=request['name'];facts=request.get('facts','')
        if not isinstance(name,str) or not 1<=len(name.strip())<=80 or not isinstance(facts,str) or len(facts)>1000:
            raise ValueError('项目名最多80字，共同要求最多1000字')
        text=self.message_reader(owner,request['message']) if request.get('message') is not None else ''
        suggestions=shot_suggestions(text)
        include_images=request.get('include_images',False)
        if not isinstance(include_images,bool):raise ValueError('带入素材选项无效')
        with self.canvas.lock,self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous=db.execute('SELECT data FROM video_workspaces WHERE id=?',(workspace,)).fetchone()
            if previous:
                if db.execute('SELECT chat_id FROM studio_links WHERE workspace=?',(workspace,)).fetchone()[0]!=owner:
                    raise ValueError('创建请求不属于当前对话')
                existing=json.loads(previous[0])
                signature=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()
                row=db.execute('SELECT signature FROM video_workspace_receipts WHERE workspace=? AND id=?',(workspace,identifier)).fetchone()
                if not row or row[0]!=signature:raise ValueError('同一创建请求不能更改内容')
                return existing
            notes=[]
            if text:
                notes=[{'id':'plan-'+identifier,'title':name.strip()+' · 创作方案','text':text,'x':60,'y':40,'w':360,'h':260,
                    'source':{'id':'plan-'+identifier,'type':'chat','sessionId':owner,'messageId':request['message'],'label':'自由Chat原始方案'}}]
            shots=[{'id':'shot-'+identifier+'-'+str(i),'name':s['name'],'duration':s['duration'],'prompt':s['prompt'],
                'creativeBrief':s['prompt'],'briefSource':notes[0]['id'],'mode':'first','first':'','refs':[],
                'x':500+i*460,'y':40,'dirty':True} for i,s in enumerate(suggestions)]
            state={'assets':[],'shots':shots,'edits':{},'notes':notes,'messages':[],'saved':[],'sequence':[],
                'facts':facts,'narration':'','voice':False,'review':'待核对','candidate':{'removed':True,'x':1100,'y':50},
                'narrationNode':{'removed':True,'x':500,'y':700}}
            if include_images:
                # Only actual user-turn attachments belonging to this owner and
                # preceding the adopted proposal. Never infer shot/image pairs.
                image_ids=[]
                for _,data in db.execute('SELECT row_id,data FROM turns WHERE owner=? AND row_id<=? ORDER BY row_id',
                                         (owner,request['message'] if request.get('message') is not None else 2**63-1)):
                    image_ids.extend(a['id'] for a in json.loads(data).get('attachments',[]) if a.get('kind')=='image')
                objects=set()
                for image_id in dict.fromkeys(image_ids):
                    row=db.execute('SELECT data FROM attachments WHERE id=? AND owner=?',(image_id,owner)).fetchone()
                    if not row:continue
                    image=json.loads(row[0]);obj=image.get('object_id')
                    if image.get('kind')!='image' or not obj or obj in objects:continue
                    if len(state['assets'])>=500:raise ValueError('对话素材超过画布容量，请取消自动带入并按需选择')
                    objects.add(obj)
                    state['assets'].append(self._chat_asset(workspace,owner,image,state['assets']))
                if state['assets']:
                    for note in notes:note['x']=380
                    for i,shot in enumerate(shots):shot.update(x=850,y=40+i*490)
            record={'id':workspace,'revision':1,'state':state,'events':[{'id':identifier,'label':'从自由Chat建立项目','at':time.time()}],'updated_at':time.time()}
            encoded=json.dumps(record,ensure_ascii=False)
            db.execute('INSERT INTO video_workspaces VALUES (?,?)',(workspace,encoded))
            db.execute('INSERT INTO studio_projects VALUES (?,?,?)',(workspace,name.strip(),json.dumps({'type':'chat','message':request.get('message')})))
            db.execute('INSERT INTO studio_links VALUES (?,?)',(workspace,owner))
            self.store.versions.put_receipt(db,workspace,identifier,hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest(),record)
            return record

    def adopt_shot_plan(self, workspace, request):
        args=request['args']
        if set(args) not in ({'owner','message','shot'},{'owner','message','shot','expected_prompt'}) or self.chat(workspace)!=args['owner']:raise ValueError('镜头建议不属于当前项目')
        shots=shot_suggestions(self.message_reader(args['owner'],args['message']))
        if len(shots)!=1:raise ValueError('请选择一个镜头的修改建议')
        with self.canvas.lock,self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT signature,data FROM video_workspace_receipts WHERE workspace=? AND id=?',(workspace,request['request_id'])).fetchone()
            signature=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()
            if old:
                if old[0]!=signature:raise ValueError('请求内容不能改变')
                return self.store.versions.receipt(db,old[1])
            record=self.workspaces.get(workspace)
            if record['revision']!=request['revision']:raise Conflict('项目已更新，镜头建议保留，请重新读取后采用')
            shot=next((s for s in record['state']['shots'] if s['id']==args['shot']),None)
            if not shot:raise ValueError('镜头已不存在')
            if 'expected_prompt' in args and shot.get('prompt','')!=args['expected_prompt']:raise Conflict('镜头提示词已修改，优化建议仍保留，请重新比较')
            shot.update(prompt=shots[0]['prompt'],duration=5,dirty=True,inputReview=False)
            record.update(revision=record['revision']+1,updated_at=time.time())
            record['events']=(record['events']+[{'id':request['request_id'],'label':'采用导演镜头要求','object':shot['id'],'at':time.time()}])[-80:]
            encoded=json.dumps(record,ensure_ascii=False)
            db.execute('UPDATE video_workspaces SET data=? WHERE id=?',(encoded,workspace))
            self.store.versions.put_receipt(db,workspace,request['request_id'],signature,record)
            return record
