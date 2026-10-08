"""Append-only content versions and lightweight, exact operation replay."""
import base64
import copy
import hashlib
import json
import re
import time
import uuid


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


class MediaVersions:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def item_id(scope, target, kind):
        return hashlib.sha256(encode([scope, target, kind]).encode()).hexdigest()

    def append(self, db, scope, target, kind, data, label, objects=(), at=None, force=False):
        item = self.item_id(scope, target, kind)
        content = encode(data)
        checksum = hashlib.sha256(content.encode()).hexdigest()
        db.execute('INSERT OR IGNORE INTO media_items VALUES (?,?,?,?)', (item, scope, target, kind))
        head = db.execute('SELECT r.id,r.content_hash FROM media_heads h JOIN media_revisions r ON r.id=h.revision_id WHERE h.item_id=?', (item,)).fetchone()
        if head and head[1] == checksum and not force:
            return head[0]
        identifier = uuid.uuid4().hex
        db.execute('INSERT INTO media_revisions VALUES (?,?,?,?,?,?,?)',
                   (identifier, item, head[0] if head else None, checksum, content, label, at or time.time()))
        for obj in set(objects):
            db.execute('INSERT INTO media_revision_objects VALUES (?,?)', (identifier, obj))
            db.execute('INSERT OR IGNORE INTO media_grants VALUES (?,?)', (scope, obj))
        db.execute('INSERT INTO media_heads VALUES (?,?) ON CONFLICT(item_id) DO UPDATE SET revision_id=excluded.revision_id', (item, identifier))
        return identifier

    def list(self, scope, target=None, kind=None):
        with self.store.connect() as db:
            rows = db.execute('''SELECT r.id,i.target,i.kind,r.parent_id,r.label,r.created_at,
                r.id=h.revision_id,r.data FROM media_revisions r JOIN media_items i ON i.id=r.item_id
                LEFT JOIN media_heads h ON h.item_id=i.id WHERE i.scope=?
                AND (? IS NULL OR i.target=?) AND (? IS NULL OR i.kind=?) ORDER BY r.created_at DESC,r.rowid DESC''',
                (scope,target,target,kind,kind)).fetchall()
        return [dict(id=r[0],target=r[1],kind=r[2],parent_id=r[3],label=r[4],time=r[5],current=bool(r[6]),data=json.loads(r[7])) for r in rows]

    def read(self, db, scope, identifier):
        found = db.execute('''SELECT r.item_id,r.data,i.target,i.kind FROM media_revisions r
            JOIN media_items i ON i.id=r.item_id WHERE r.id=? AND i.scope=?''', (identifier, scope)).fetchone()
        if not found:
            raise ValueError('版本不存在或不属于该项目')
        return dict(item=found[0],data=json.loads(found[1]),target=found[2],kind=found[3])

    def page(self, scope, target=None, kind=None, page=1, page_size=20, category='all'):
        from .pagination import bounds
        clauses=['i.scope=?'];args=[scope]
        if target:clauses.append('i.target=?');args.append(target)
        if kind:clauses.append('i.kind=?');args.append(kind)
        categories={
            'all':'1=1', 'image':"i.kind='image'", 'copy':"i.kind IN ('note','text') AND i.target!='narration'",
            'narration':"i.target='narration'", 'video':"i.kind IN ('prompt','video')", 'render':"i.kind='render'",
        }
        if category not in categories:raise ValueError('版本分类无效')
        clauses.append('('+categories[category]+')')
        query=' FROM media_revisions r JOIN media_items i ON i.id=r.item_id LEFT JOIN media_heads h ON h.item_id=i.id WHERE '+' AND '.join(clauses)
        with self.store.connect() as db:
            db.execute('BEGIN')
            total=db.execute('SELECT count(*)'+query,args).fetchone()[0]
            current,offset=bounds(page,page_size,total)
            # Only small previews leave the database. Layer graphs and render manifests are read on demand.
            rows=db.execute('''SELECT r.id,i.target,i.kind,r.parent_id,r.label,r.created_at,r.id=h.revision_id,
                json_extract(r.data,'$.file'),substr(json_extract(r.data,'$.text'),1,220),
                json_extract(r.data,'$.title'),json_extract(r.data,'$.id')'''+query+' ORDER BY r.created_at DESC,r.id DESC LIMIT ? OFFSET ?',args+[page_size,offset]).fetchall()
            targets=[{'id':r[0],'kind':r[1]} for r in db.execute('SELECT DISTINCT target,kind FROM media_items WHERE scope=? ORDER BY target,kind',(scope,))]
        items=[dict(id=r[0],target=r[1],kind=r[2],parent_id=r[3],label=r[4],time=r[5],current=bool(r[6]),data={k:v for k,v in zip(('file','text','title','id'),r[7:]) if v is not None}) for r in rows]
        return dict(items=items,total=total,page=current,page_size=page_size,targets=targets)

    def detail(self, scope, identifier):
        with self.store.connect() as db:return self.read(db,scope,identifier)

    def capacity(self, scope):
        with self.store.connect() as db:
            db.execute('BEGIN')
            count,metadata=db.execute('SELECT count(*),coalesce(sum(length(cast(r.data AS BLOB))),0) FROM media_revisions r JOIN media_items i ON i.id=r.item_id WHERE i.scope=?',(scope,)).fetchone()
            files,size=db.execute('SELECT count(*),coalesce(sum(bytes),0) FROM file_objects WHERE id IN (SELECT object_id FROM media_grants WHERE scope=?)',(scope,)).fetchone()
            snapshots,snapshot_bytes=db.execute('SELECT count(*),coalesce(sum(length(cast(data AS BLOB))),0) FROM workspace_snapshots WHERE workspace=?',(scope,)).fetchone()
        return dict(versions=count,version_metadata_bytes=metadata,objects=files,object_bytes=size,snapshots=snapshots,snapshot_bytes=snapshot_bytes,automatic_cleanup=False)

    def select(self, db, scope, identifier):
        version = self.read(db, scope, identifier)
        db.execute('INSERT INTO media_heads VALUES (?,?) ON CONFLICT(item_id) DO UPDATE SET revision_id=excluded.revision_id', (version['item'], identifier))
        return version

    def normalize(self, value, scope, aliases=None):
        """Legacy canvas data URLs are accepted at the boundary, never persisted anew."""
        if isinstance(value, str) and value.startswith('data:image/'):
            match = re.fullmatch(r'data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=]+)', value)
            if not match:
                raise ValueError('画布图片编码无效')
            from .attachments import decode_upload
            suffix = {'image/png':'png','image/jpeg':'jpg','image/webp':'webp'}[match[1]]
            raw, _, mime, _ = decode_upload('image.'+suffix, match[2])
            obj = self.store.media.put_bytes(raw, mime)
            with self.store.connect() as db:
                db.execute('INSERT OR IGNORE INTO media_grants VALUES (?,?)', (scope, obj['id']))
            url = self.store.media.url(obj['id'])
            if aliases is not None:
                aliases[hashlib.sha256(value.encode()).hexdigest()] = hashlib.sha256(url.encode()).hexdigest()
            return url
        if isinstance(value, list):
            return [self.normalize(v, scope, aliases) for v in value]
        if isinstance(value, dict):
            return {k:self.normalize(v, scope, aliases) for k,v in value.items()}
        return value

    def objects(self, db, value):
        found = set()
        def visit(v):
            if isinstance(v,str):
                match = re.fullmatch(r'/studio/media/objects/([a-f0-9]{64})',v)
                if match: found.add(match[1])
                match = re.fullmatch(r'/api/precision/projects/[a-f0-9]{32}/assets/([a-f0-9]{32})',v)
                if match:
                    row=db.execute('SELECT data FROM attachments WHERE id=?',(match[1],)).fetchone()
                    if row and json.loads(row[0]).get('object_id'): found.add(json.loads(row[0])['object_id'])
            elif isinstance(v,dict):
                for child in v.values(): visit(child)
            elif isinstance(v,list):
                for child in v: visit(child)
        visit(value)
        return found

    def track_workspace(self, db, record):
        scope, state = record['id'], record['state']
        for asset in state.get('assets',[]):
            # Import the pre-existing file-only history too. It does not imply
            # that a missing layered document can be reconstructed.
            past=([{'file':asset['originalFile']}] if asset.get('originalFile') else [])+asset.get('versions',[])
            item=self.item_id(scope,asset['id'],'image')
            for entry in past:
                if not isinstance(entry,dict) or not entry.get('file'):continue
                if not db.execute("SELECT 1 FROM media_revisions WHERE item_id=? AND json_extract(data,'$.file')=? LIMIT 1",(item,entry['file'])).fetchone():
                    payload={'file':entry['file']}
                    self.append(db,scope,asset['id'],'image',payload,'迁入旧素材版本',self.objects(db,payload),at=entry.get('at'))
            if asset.get('file'):
                # File identity changes create a version; moving/renaming a node does not.
                payload = {k:asset[k] for k in ('file','editProject','documentVersion') if k in asset}
                self.append(db,scope,asset['id'],'image',payload,'图片版本',self.objects(db,payload))
        for shot in state.get('shots',[]):
            self.append(db,scope,shot['id'],'prompt',{'text':shot.get('prompt','')},'镜头文案')
        for note in state.get('notes',[]):
            self.append(db,scope,note['id'],'note',{'text':note.get('text',''),'title':note.get('title','')},'创作说明')
        for field in ('facts','narration'):
            if isinstance(state.get(field),str):
                self.append(db,scope,field,'text',{'text':state[field]},'共同要求' if field=='facts' else '口播文案')

    @staticmethod
    def receipt(db, encoded):
        value = json.loads(encoded)
        if isinstance(value,dict) and set(value)=={'snapshot_id'}:
            row=db.execute('SELECT data FROM workspace_snapshots WHERE id=?',(value['snapshot_id'],)).fetchone()
            if not row: raise ValueError('操作快照缺失，请恢复数据库备份')
            return json.loads(row[0])
        return value

    def put_receipt(self, db, workspace, request_id, signature, record):
        content=encode(record)
        identifier=hashlib.sha256(content.encode()).hexdigest()
        db.execute('INSERT OR IGNORE INTO workspace_snapshots VALUES (?,?,?,?,?)',
                   (identifier,workspace,record['revision'],content,record.get('updated_at',time.time())))
        db.execute('INSERT INTO video_workspace_receipts VALUES (?,?,?,?)',
                   (workspace,request_id,signature,encode({'snapshot_id':identifier})))
        self.track_workspace(db,record)
