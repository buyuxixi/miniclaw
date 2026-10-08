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
    def project_list(self, owner=None, page=None, page_size=6, q='', workspace=None):
        from .pagination import bounds
        if not isinstance(q,str) or len(q)>100:raise ValueError('搜索词最多100字')
        clauses=[];args=[]
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
        return rows[0] if rows else None

    def create_project(self, request, owner):
        if set(request)-{'request_id','name','message','facts','session_id'} or not {'request_id','name','session_id'}<=set(request):
            raise ValueError('请填写项目名并选择当前对话')
        identifier=self.workspaces.identifier(request['request_id']);workspace=self.workspaces.identifier('project-'+identifier)
        name=request['name'];facts=request.get('facts','')
        if not isinstance(name,str) or not 1<=len(name.strip())<=80 or not isinstance(facts,str) or len(facts)>1000:
            raise ValueError('项目名最多80字，共同要求最多1000字')
        text=self.message_reader(owner,request['message']) if request.get('message') is not None else ''
        suggestions=shot_suggestions(text)
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
