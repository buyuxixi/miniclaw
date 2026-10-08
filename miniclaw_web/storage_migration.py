"""Explicit, backup-first migration. Run while the local web service is stopped.

python -m miniclaw_web.storage_migration --home .hermes --apply --vacuum
Without --apply this command only reports storage sizes and table counts.
"""
import argparse
import hashlib
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from .store import Store
from .media_versions import encode


def audit(home):
    home=Path(home).resolve();path=home/'miniclaw.sqlite3'
    with closing(sqlite3.connect(f'{path.as_uri()}?mode=ro',uri=True)) as db:
        names=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        counts={name:db.execute('SELECT count(*) FROM "'+name+'"').fetchone()[0] for name in names}
        inline={name:db.execute('SELECT count(*),coalesce(sum(length(data)),0) FROM "'+name+'" WHERE instr(data,\'data:image/\')>0').fetchone()
                for name in names if 'data' in [r[1] for r in db.execute('PRAGMA table_info("'+name+'")')]}
        integrity=db.execute('PRAGMA quick_check').fetchone()[0]
    return {'home':str(home),'database_bytes':path.stat().st_size,'tables':counts,'inline_images':{k:list(v) for k,v in inline.items() if v[0]},'integrity':integrity}


def backup(home):
    home=Path(home).resolve()
    destination=home/'backups'/('storage-'+time.strftime('%Y%m%d-%H%M%S')+'-'+str(time.time_ns()%1000000))
    destination.mkdir(parents=True)
    for name in ('miniclaw.sqlite3','state.db'):
        path=home/name
        if path.exists():
            with closing(sqlite3.connect(f'{path.as_uri()}?mode=ro',uri=True)) as source,closing(sqlite3.connect(destination/name)) as target:
                source.backup(target)
                if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise OSError('备份数据库校验失败')
    # Original files are retained. This manifest identifies bytes required to restore.
    files=[]
    for folder in ('images/miniclaw','attachments/miniclaw','studio_video','media/objects'):
        for path in (home/folder).rglob('*'):
            if path.is_file():
                with path.open('rb') as stream:checksum=hashlib.file_digest(stream,'sha256').hexdigest()
                files.append({'path':str(path.relative_to(home)),'bytes':path.stat().st_size,'sha256':checksum})
    (destination/'files.json').write_text(encode(files),encoding='utf-8')
    return destination


def basis(state,shot):
    ids=[shot.get('first')] if shot.get('mode')=='first' else shot.get('refs',[])
    sources=[next((a.get('file') for a in state.get('assets',[]) if a['id']==i),None) for i in ids]
    if not sources or not sources[0]:return None
    data={'shot':shot['id'],'name':shot.get('name'),'prompt':shot.get('prompt'),'duration':5,'image':sources[0],'facts':state.get('facts','')}
    if shot.get('mode')!='first':data['references']=sources
    return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()


def migrate(home, vacuum=False):
    home=Path(home).resolve();before=audit(home);saved=backup(home)
    store=Store(home);aliases={};warnings=[]
    with store.connect() as db:
        if db.execute('SELECT 1 FROM schema_migrations WHERE version=1001').fetchone():
            return {'before':before,'after':before,'backup':str(saved),'warnings':[],'already_migrated':True}
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        attachments=db.execute('SELECT id,owner,data FROM attachments').fetchall()
    for identifier,owner,raw in attachments:
        record=json.loads(raw)
        if record.get('object_id'):continue
        if not Path(record.get('path','')).is_file():
            warnings.append('缺失附件:'+identifier);continue
        store.put('attachments',identifier,record,owner)
    for table in ('studio_video_jobs','studio_video_renders'):
        if table not in tables:continue
        with store.connect() as db:jobs=db.execute('SELECT id,data FROM '+table).fetchall()
        for identifier,raw in jobs:
            job=json.loads(raw)
            if not job.get('path'):continue
            if not Path(job['path']).is_file():warnings.append('缺失视频:'+identifier);continue
            obj=store.media.put_file(job['path'],'video/mp4');job['object_id']=obj['id']
            # Input proxies are immutable generation evidence as well.
            inputs=[]
            for path in job.get('input_paths',[]):
                if Path(path).is_file():inputs.append(store.media.put_file(path,'image/jpeg')['id'])
                else:warnings.append('缺失视频输入:'+identifier)
            job['input_objects']=inputs
            with store.connect() as db:
                db.execute('UPDATE '+table+' SET data=? WHERE id=?',(encode(job),identifier))
                store.versions.append(db,job['workspace'],job.get('shot','render'),
                    'video' if table=='studio_video_jobs' else 'render',
                    {k:v for k,v in job.items() if k not in ('path','input_path','input_paths','result_url','updated_at','error')},
                    '迁入视频结果',[obj['id'],*inputs],at=job.get('created_at'))
    old_current={}
    if 'video_workspaces' in tables:
        with store.connect() as db:workspaces=db.execute('SELECT id,data FROM video_workspaces').fetchall()
        old_current={identifier:json.loads(raw) for identifier,raw in workspaces}
        # Receipt replay keeps its original response revision and request signature.
        # Read one response at a time; the old receipt column can be hundreds of MiB.
        with store.connect() as db:
            receipts=db.execute('''SELECT r.workspace,r.id,r.signature FROM video_workspace_receipts r
                LEFT JOIN workspace_snapshots s ON s.id=json_extract(r.data,'$.snapshot_id')
                ORDER BY r.workspace,coalesce(json_extract(r.data,'$.revision'),s.revision)''').fetchall()
        for workspace,rid,signature in receipts:
            with store.connect() as db:
                raw=db.execute('SELECT data FROM video_workspace_receipts WHERE workspace=? AND id=?',(workspace,rid)).fetchone()[0]
                record=store.versions.receipt(db,raw)
            normalized=store.versions.normalize(record,workspace,aliases)
            with store.connect() as db:
                db.execute('DELETE FROM video_workspace_receipts WHERE workspace=? AND id=?',(workspace,rid))
                store.versions.put_receipt(db,workspace,rid,signature,normalized)
        for workspace,original in old_current.items():
            record=store.versions.normalize(original,workspace,aliases)
            with store.connect() as db:
                db.execute('UPDATE video_workspaces SET data=? WHERE id=?',(encode(record),workspace))
                store.versions.track_workspace(db,record)
                # Changing the physical URL must not make a previously valid video stale.
                if 'studio_video_jobs' in tables:
                    for identifier,raw in db.execute('SELECT id,data FROM studio_video_jobs WHERE workspace=?',(workspace,)).fetchall():
                        job=json.loads(raw);shot=next((s for s in original['state']['shots'] if s['id']==job['shot']),None)
                        if shot and job.get('basis')==basis(original['state'],shot):
                            nextshot=next(s for s in record['state']['shots'] if s['id']==job['shot'])
                            job['basis']=basis(record['state'],nextshot)
                            ids=[nextshot.get('first')] if nextshot.get('mode')=='first' else nextshot.get('refs',[])
                            job['image']=next(a['file'] for a in record['state']['assets'] if a['id']==ids[0])
                            db.execute('UPDATE studio_video_jobs SET data=? WHERE id=?',(encode(job),identifier))
    if 'video_precision_links' in tables:
        with store.connect() as db:
            for workspace,target,raw in db.execute('SELECT workspace,object_id,data FROM video_precision_links').fetchall():
                link=json.loads(raw)
                if link.get('signature') in aliases:
                    link['signature']=aliases[link['signature']]
                    db.execute('UPDATE video_precision_links SET data=? WHERE workspace=? AND object_id=?',(encode(link),workspace,target))
    if 'canvas_history' in tables:
        with store.connect() as db:
            for project,seq,raw in db.execute('SELECT project,seq,data FROM canvas_history ORDER BY project,seq').fetchall():
                snapshot=json.loads(raw)
                if not snapshot.get('version_id'):
                    objects=[]
                    for layer in snapshot['document']['layers']:
                        if layer.get('asset_id'):
                            found=db.execute('SELECT data FROM attachments WHERE id=?',(layer['asset_id'],)).fetchone()
                            if found and json.loads(found[0]).get('object_id'):objects.append(json.loads(found[0])['object_id'])
                    snapshot['version_id']=store.versions.append(db,'canvas:'+project,'document','document',snapshot['document'],snapshot['label'],objects,at=snapshot['time'])
                    db.execute('UPDATE canvas_history SET data=? WHERE project=? AND seq=?',(encode(snapshot),project,seq))
            for project,raw in db.execute('SELECT id,data FROM canvas_projects').fetchall():
                current=json.loads(raw)
                found=db.execute('SELECT data FROM canvas_history WHERE project=? AND seq=?',(project,current['cursor'])).fetchone()
                if found:store.versions.select(db,'canvas:'+project,json.loads(found[0])['version_id'])
    with store.connect() as db:
        if db.execute('PRAGMA foreign_key_check').fetchall():raise OSError('迁移外键校验失败')
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise OSError('迁移完整性校验失败')
        db.execute('INSERT INTO schema_migrations VALUES (1001,?,?)',(hashlib.sha256(b'local-media-data-v1').hexdigest(),time.time()))
    if vacuum:
        with closing(sqlite3.connect(home/'miniclaw.sqlite3')) as db:db.execute('VACUUM')
    after=audit(home)
    report={'before':before,'after':after,'backup':str(saved),'warnings':warnings,
            'historical_limit':'只能迁入仍然存在的历史；旧撤销分支被删除的版本无法恢复。'}
    (saved/'migration-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home',default='.hermes');parser.add_argument('--apply',action='store_true');parser.add_argument('--vacuum',action='store_true')
    args=parser.parse_args()
    print(json.dumps(migrate(args.home,args.vacuum) if args.apply else audit(args.home),ensure_ascii=False,indent=2))
