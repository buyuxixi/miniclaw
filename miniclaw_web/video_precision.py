"""Connect the original video canvas to existing, immutable precision editing.

The separate profile does not restart Hermes jobs. Removing a UI node never
deletes its source files or request receipts.
"""
import base64
import copy
import hashlib
import json
import re
from pathlib import Path
from PIL import Image
from .attachments import decode_upload
from .canvas import Canvas, Conflict
from .canvas_document import blank, layer_base, number
from .image_provider import provider_status
from .store import Store


class VideoPrecision:
    def __init__(self, folder, home, *, store=None, canvas=None):
        self.folder = Path(folder)
        self.store = store or Store(home)
        self.canvas = canvas or Canvas(self.store)
        self.lock = self.canvas.lock
        with self.store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS video_precision_links
                  (workspace TEXT, object_id TEXT, data TEXT, PRIMARY KEY(workspace,object_id));
                CREATE TABLE IF NOT EXISTS video_precision_requests
                  (project TEXT, request_id TEXT, signature TEXT, data TEXT,
                   PRIMARY KEY(project,request_id));
            ''')

    @staticmethod
    def file_url(project, asset):
        return f'/api/precision/projects/{project}/assets/{asset}'

    def asset(self, project, identifier):
        asset = self.canvas.asset(project, identifier)
        with Image.open(asset['path']) as image:
            return {**asset, 'width':image.width, 'height':image.height}

    def _document(self, row, asset):
        doc = copy.deepcopy(row['document'])
        doc.update(width=asset['width'],height=asset['height'])
        doc['layers'][0].update(asset_id=asset['id'],width=asset['width'],height=asset['height'])
        return doc

    def metadata(self, project):
        row = self.canvas.get(project)
        layer = row['document']['layers'][0]
        return dict(project=project,revision=row['revision'],layer=layer['id'],source=layer['asset_id'],
                    width=layer['width'],height=layer['height'],
                    before=self.file_url(project,layer['asset_id']),cloud=provider_status())

    def open(self, data):
        workspace,object_id,file = data.get('workspace'),data.get('object_id'),data.get('file')
        if not isinstance(workspace,str) or not re.fullmatch(r'[\w-]{8,80}',workspace):
            raise ValueError('画布标识无效，请刷新后重试')
        if not isinstance(object_id,str) or not re.fullmatch(r'[\w-]{1,100}',object_id):
            raise ValueError('请选择画布中的图片')
        if not isinstance(file,str): raise ValueError('图片来源无效')
        with self.lock:
            with self.store.connect() as db:
                found=db.execute('SELECT data FROM video_precision_links WHERE workspace=? AND object_id=?',
                                 (workspace,object_id)).fetchone()
            if found:
                link=json.loads(found[0]); row=self.canvas.get(link['project'])
                match=re.fullmatch(r'/api/precision/projects/([a-f0-9]{32})/assets/([a-f0-9]{32})',file)
                if match and match[1]==row['id']: asset=self.asset(row['id'],match[2])
                elif hashlib.sha256(file.encode()).hexdigest()==link['signature']:
                    asset=self.asset(row['id'],link['original'])
                else: raise ValueError('图片来源已改变，请作为新素材加入画布')
                if row['document']['layers'][0]['asset_id']!=asset['id']:
                    if any(j['state'] in ('queued','running') for j in self.canvas.jobs(row['id'])):
                        raise Conflict('这张图仍在修图，请先核对原请求')
                    self.canvas.save(row['id'],row['revision'],self._document(row,asset),'恢复当前素材')
                return self.metadata(row['id'])
            if file in {'source.png','macro.png','hero.png','frame-end.png'}:
                raw,kind,_,_=decode_upload(file,base64.b64encode((self.folder/file).read_bytes()).decode())
            elif re.fullmatch(r'data:image/(?:png|jpeg|webp);base64,[a-zA-Z0-9+/=]+',file):
                ext={'image/png':'png','image/jpeg':'jpg','image/webp':'webp'}[file[5:].split(';')[0]]
                raw,kind,_,_=decode_upload('image.'+ext,file.split(',',1)[1])
            elif re.fullmatch(r'/studio/media/objects/[a-f0-9]{64}',file):
                identifier=file.rsplit('/',1)[1]
                with self.store.connect() as db:
                    if not db.execute('SELECT 1 FROM media_grants WHERE scope=? AND object_id=?',(workspace,identifier)).fetchone():raise ValueError('图片不属于该工作区')
                obj=self.store.media.get(identifier)
                ext={'image/png':'png','image/jpeg':'jpg','image/webp':'webp'}.get(obj['mime'])
                if not ext:raise ValueError('请选择图片')
                raw,kind,_,_=decode_upload('image.'+ext,base64.b64encode(self.store.media.materialize(identifier).read_bytes()).decode())
            elif re.fullmatch(r'/api/precision/projects/[a-f0-9]{32}/assets/[a-f0-9]{32}',file):
                parts=file.split('/')
                source=self.canvas.asset(parts[4],parts[6])
                raw,kind,_,_=decode_upload('image.png',base64.b64encode(Path(source['path']).read_bytes()).decode())
            else: raise ValueError('图片来源不支持，请重新上传图片')
            if kind!='image': raise ValueError('请选择图片')
            name=data.get('name')
            name=name.strip()[:100] if isinstance(name,str) and name.strip() else '图片'
            row=self.canvas.create(('视频素材：'+name)[:100])
            asset=self.canvas.add_asset(row['id'],raw,'original.png')
            doc=blank(asset['width'],asset['height'])
            doc['layers']=[layer_base('image',name,asset['width'],asset['height'],asset_id=asset['id'])]
            self.canvas.save(row['id'],row['revision'],doc,'导入原图')
            link=dict(project=row['id'],original=asset['id'],signature=hashlib.sha256(file.encode()).hexdigest())
            with self.store.connect() as db:
                db.execute('INSERT INTO video_precision_links VALUES (?,?,?)',(workspace,object_id,json.dumps(link)))
            return self.metadata(row['id'])

    def _request(self, project, request_id):
        with self.store.connect() as db:
            found=db.execute('SELECT signature,data FROM video_precision_requests WHERE project=? AND request_id=?',
                             (project,request_id)).fetchone()
        if not found: raise ValueError('原请求尚未受理，可重新提交同一请求')
        return found[0],json.loads(found[1])

    def full_open(self, data):
        # Opening a layered draft must not flatten it or replace its first layer.
        workspace, object_id = data.get('workspace'), data.get('object_id')
        if not isinstance(workspace, str) or not re.fullmatch(r'[\w-]{8,80}', workspace):
            raise ValueError('画布标识无效')
        if not isinstance(object_id, str) or not re.fullmatch(r'[\w-]{1,100}', object_id):
            raise ValueError('图片标识无效')
        with self.lock:
            with self.store.connect() as db:
                found = db.execute('SELECT data FROM video_precision_links WHERE workspace=? AND object_id=?', (workspace, object_id)).fetchone()
            if not found:
                return self.open(data)
            link = json.loads(found[0])
            source = data.get('file', '')
            if not isinstance(source, str): raise ValueError('图片来源无效')
            original = hashlib.sha256(source.encode()).hexdigest() == link['signature']
            owned = re.fullmatch(r'/api/precision/projects/([a-f0-9]{32})/assets/([a-f0-9]{32})', source)
            if not original and not (owned and owned[1] == link['project']):
                raise Conflict('素材来源已改变，请重新打开精修')
            if owned and owned[1] == link['project']:
                self.canvas.asset(link['project'], owned[2])
            row = self.canvas.get(link['project'])
            return dict(project=row['id'], revision=row['revision'], width=row['document']['width'], height=row['document']['height'])

    def full_preview(self, project, data):
        with self.lock:
            row = self.canvas.get(project)
            self.canvas._cas(row, data.get('revision'))
            if any(j['state'] in ('queued', 'running') for j in self.canvas.jobs(project)):
                raise Conflict('还有修图正在执行，请等待结果后比较')
            # Export an immutable candidate. Keep the editable layers and history.
            asset = self.canvas.add_asset(project, self.canvas.export(project), '精修工作图.png')
            return dict(project=project, revision=row['revision'], output=self.file_url(project, asset['id']), output_id=asset['id'], width=asset['width'], height=asset['height'])

    def status(self, project, request_id):
        _,receipt=self._request(project,request_id)
        if receipt['state']=='unknown' and not receipt.get('job'):
            # The executor may have accepted work before the receipt was saved.
            job_id=hashlib.sha256((project+':'+request_id).encode()).hexdigest()[:32]
            try: job=self.canvas.job(project,job_id)
            except ValueError: job=None
            if job: receipt['job']=job_id
        if receipt.get('job'):
            job=self.canvas.job(project,receipt['job'])
            receipt.update(state=job['state'],error=job.get('error'))
            if job.get('output'):
                receipt.update(output=self.file_url(project,job['output']['id']),output_id=job['output']['id'])
        receipt['revision']=self.canvas.get(project)['revision']
        return receipt

    def edit(self, project, data):
        if set(data)-{'request_id','revision','source','kind','params','region','prompt'}:
            raise ValueError('修图字段无效')
        request_id=data.get('request_id')
        if not isinstance(request_id,str) or not re.fullmatch(r'[\w-]{8,80}',request_id):
            raise ValueError('修图请求标识无效')
        signature=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
        with self.lock:
            try: previous,_=self._request(project,request_id)
            except ValueError: previous=None
            if previous:
                if previous!=signature: raise ValueError('原请求不能更换参数，请建立新的修改')
                return self.status(project,request_id)
            row=self.canvas.get(project); self.canvas._cas(row,data.get('revision'))
            layer=row['document']['layers'][0]
            if layer['asset_id']!=data.get('source'): raise Conflict('原图版本已变化，请重新打开这张图')
            if any(j['state'] in ('queued','running') for j in self.canvas.jobs(project)):
                raise ValueError('这张图已有修图任务，请等待结果')
            kind=data.get('kind'); params=data.get('params',{}); region=data.get('region'); selection=None
            if kind not in ('local','ai'): raise ValueError('修图方式无效')
            if region is not None:
                if not isinstance(region,dict) or set(region)!={'x','y','w','h'}: raise ValueError('选区无效，请重新框选')
                x,y=number(region['x'],0,1),number(region['y'],0,1)
                w,h=number(region['w'],.002,1),number(region['h'],.002,1)
                if x+w>1.00001 or y+h>1.00001: raise ValueError('选区超出图片')
                selection=self.canvas.select(project,row['revision'],layer['id'],'rectangle',
                    [[x*layer['width'],y*layer['height']],
                     [min(layer['width']-1,(x+w)*layer['width']-1),min(layer['height']-1,(y+h)*layer['height']-1)]])
            receipt=dict(project=project,request_id=request_id,source=layer['asset_id'],
                         before=self.file_url(project,layer['asset_id']),state='unknown')
            with self.store.connect() as db:
                db.execute('INSERT INTO video_precision_requests VALUES (?,?,?,?)',(project,request_id,signature,json.dumps(receipt)))
            try:
                if kind=='ai':
                    job=self.canvas.submit(project,row['revision'],layer['id'],data.get('prompt'),request_id,
                                           bool(region),0,selection['id'] if selection else None)
                    receipt.update(job=job['id'],state=job['state'])
                else:
                    edited=(self.canvas.masked(project,row['revision'],layer['id'],'adjust',params,selection['id'])
                            if selection else self.canvas.local(project,row['revision'],layer['id'],'adjust',params))
                    output=edited['document']['layers'][0]['asset_id']
                    self.canvas.save(project,edited['revision'],row['document'],'保留原图，等待确认')
                    receipt.update(state='succeeded',output_id=output,output=self.file_url(project,output))
            except (ValueError,Conflict) as error: receipt.update(state='failed',error=str(error))
            except Exception: receipt.update(state='unknown',error='结果暂未确认，请核对原请求；不会自动重复执行')
            with self.store.connect() as db:
                db.execute('UPDATE video_precision_requests SET data=? WHERE project=? AND request_id=?',
                           (json.dumps(receipt),project,request_id))
            return self.status(project,request_id)

    def apply(self, project, data):
        with self.lock:
            receipt=self.status(project,data.get('request_id'))
            if receipt['state']!='succeeded' or not receipt.get('output_id'): raise ValueError('还没有可采用的修图结果')
            row=self.canvas.get(project)
            if row['document']['layers'][0]['asset_id']==receipt['output_id']:
                return self.metadata(project)
            self.canvas._cas(row,data.get('revision'))
            if row['document']['layers'][0]['asset_id']!=receipt['source']:
                raise Conflict('当前图片已变化，结果仍保留，请重新核对')
            self.canvas.save(project,row['revision'],self._document(row,self.asset(project,receipt['output_id'])),'采用精修结果')
            return self.metadata(project)
