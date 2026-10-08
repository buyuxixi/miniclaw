"""Durable state for the original free canvas, separate from transient UI state."""
import hashlib
import json
import re
import time
from .canvas import Conflict


FIELDS = {'assets','shots','edits','narration','voice','review','sequence','saved','messages','candidate','notes','narrationNode','facts','canvasLayout'}


class VideoWorkspace:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS video_workspaces (id TEXT PRIMARY KEY, data TEXT);
              CREATE TABLE IF NOT EXISTS video_workspace_receipts (workspace TEXT, id TEXT, signature TEXT, data TEXT, PRIMARY KEY(workspace,id));
            ''')

    @staticmethod
    def identifier(value):
        if not isinstance(value,str) or not re.fullmatch(r'[\w-]{8,80}',value): raise ValueError('项目标识无效')
        return value

    def get(self, workspace):
        self.identifier(workspace)
        with self.store.connect() as db:
            row=db.execute('SELECT data FROM video_workspaces WHERE id=?',(workspace,)).fetchone()
        if not row: return None
        return json.loads(row[0])

    def save(self, workspace, request):
        self.identifier(workspace); request_id=self.identifier(request.get('request_id'))
        state=request.get('state'); revision=request.get('revision')
        if not isinstance(state,dict) or set(state)-FIELDS or not isinstance(revision,int): raise ValueError('项目内容无效')
        if not isinstance(state.get('facts',''),str) or len(state.get('facts',''))>1000: raise ValueError('共同要求最多1000字')
        import math
        layout=state.get('canvasLayout',{})
        if not isinstance(layout,dict) or len(layout)>1000: raise ValueError('画布位置无效')
        for key,node in layout.items():
            if not isinstance(key,str) or len(key)>100 or not isinstance(node,dict) or set(node)-{'x','y','hidden'}: raise ValueError('画布位置无效')
            if any(type(node.get(axis)) not in (int,float) or not math.isfinite(node[axis]) or abs(node[axis])>100000 for axis in ('x','y')): raise ValueError('画布位置无效')
            if 'hidden' in node and type(node['hidden']) is not bool: raise ValueError('画布位置无效')
        for field in ('assets','shots','notes','messages','saved','sequence'):
            if not isinstance(state.get(field),list): raise ValueError('项目内容不完整')
        for field in ('assets','shots','notes'):
            if len(state[field])>500: raise ValueError('项目对象过多')
            ids=[item.get('id') for item in state[field] if isinstance(item,dict)]
            if len(ids)!=len(state[field]) or any(not isinstance(v,str) for v in ids) or len(ids)!=len(set(ids)): raise ValueError('对象标识无效')
        signature=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()
        # Publish bytes before acquiring the SQLite write lock.
        aliases={}
        state=self.store.versions.normalize(state,workspace,aliases)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT signature,data FROM video_workspace_receipts WHERE workspace=? AND id=?',(workspace,request_id)).fetchone()
            if old:
                if old[0]!=signature: raise ValueError('保存请求内容不一致')
                return self.store.versions.receipt(db,old[1])
            row=db.execute('SELECT data FROM video_workspaces WHERE id=?',(workspace,)).fetchone()
            previous=json.loads(row[0]) if row else {'revision':0,'events':[]}
            if revision!=previous['revision']: raise Conflict('另一个窗口已更新项目。当前编辑仍保留，请先读取最新进度。')
            if 'canvasLayout' not in state and 'canvasLayout' in previous.get('state',{}):
                state={**state,'canvasLayout':previous['state']['canvasLayout']}
            events=previous['events']
            if state!=previous.get('state'):
                label='保存画布'
                if not row: label='建立项目'
                elif state.get('facts')!=previous['state'].get('facts'): label='更新共同要求'
                elif state.get('edits')!=previous['state'].get('edits'): label='更新图片修改'
                elif state.get('shots')!=previous['state'].get('shots'): label='更新视频片段'
                elif state.get('messages')!=previous['state'].get('messages'): label='记录导演讨论'
                elif state.get('assets')!=previous['state'].get('assets'): label='更新素材'
                events=(events+[{'id':request_id,'label':label,'at':time.time()}])[-80:]
            result={'id':workspace,'revision':revision+1,'state':state,'events':events,'updated_at':time.time()}
            encoded=json.dumps(result,ensure_ascii=False)
            db.execute('INSERT OR REPLACE INTO video_workspaces VALUES (?,?)',(workspace,encoded))
            if aliases and db.execute("SELECT 1 FROM sqlite_master WHERE name='video_precision_links'").fetchone():
                for target,data in db.execute('SELECT object_id,data FROM video_precision_links WHERE workspace=?',(workspace,)).fetchall():
                    link=json.loads(data)
                    if link.get('signature') in aliases:
                        link['signature']=aliases[link['signature']]
                        db.execute('UPDATE video_precision_links SET data=? WHERE workspace=? AND object_id=?',(json.dumps(link),workspace,target))
            self.store.versions.put_receipt(db,workspace,request_id,signature,result)
            return result

    def versions(self, workspace, target=None):
        if not self.get(workspace): raise ValueError('项目不存在')
        return self.store.versions.list(workspace,target)

    def restore_version(self, workspace, request):
        if set(request)!={'request_id','revision','version_id'}: raise ValueError('版本恢复参数无效')
        rid=self.identifier(request['request_id'])
        signature=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT signature,data FROM video_workspace_receipts WHERE workspace=? AND id=?',(workspace,rid)).fetchone()
            if old:
                if old[0]!=signature: raise ValueError('恢复请求内容不能改变')
                return self.store.versions.receipt(db,old[1])
            row=db.execute('SELECT data FROM video_workspaces WHERE id=?',(workspace,)).fetchone()
            if not row: raise ValueError('项目不存在')
            record=json.loads(row[0])
            if record['revision']!=request['revision']: raise Conflict('项目已更新，请重新读取版本')
            version=self.store.versions.read(db,workspace,request['version_id'])
            state=record['state'];target=version['target'];kind=version['kind'];data=version['data']
            if kind=='image':
                asset=next((a for a in state['assets'] if a['id']==target),None)
                if not asset: raise ValueError('素材节点已移除，请先恢复节点')
                asset.update(data)
                if 'editProject' not in data: asset.pop('editProject',None)
                # A file-only old version gets its own working draft on next open.
                # Do not flatten or overwrite the previous layered document.
                asset['versionBase']=request['version_id']
                if 'documentVersion' not in data:asset.pop('documentVersion',None)
                for shot in state['shots']:
                    if target in ([shot.get('first')] if shot.get('mode')=='first' else shot.get('refs',[])):
                        shot.update(dirty=True,inputReview=True)
            elif kind in ('prompt','note'):
                key='shots' if kind=='prompt' else 'notes'
                node=next((s for s in state[key] if s['id']==target),None)
                if not node: raise ValueError('版本对应的节点已移除')
                if kind=='prompt':node.update(prompt=data['text'],dirty=True,inputReview=True)
                else:node.update(data)
            elif kind=='text' and target in ('facts','narration'):state[target]=data['text']
            else:raise ValueError('此版本请通过对应的精修或视频接口采用')
            self.store.versions.select(db,workspace,request['version_id'])
            record.update(revision=record['revision']+1,updated_at=time.time())
            record['events']=(record['events']+[{'id':rid,'label':'恢复历史版本','object':target,'at':time.time()}])[-80:]
            db.execute('UPDATE video_workspaces SET data=? WHERE id=?',(json.dumps(record,ensure_ascii=False),workspace))
            self.store.versions.put_receipt(db,workspace,rid,signature,record)
            return record
