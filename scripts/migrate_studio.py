"""Explicit, additive migration of the old canvas profile into the formal Store.

Dry run is default. No active/unknown generation is replayed. Backups use SQLite
backup rather than copying a live database file. Imported asset bytes get new paths.
"""
import argparse
import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from miniclaw_web.store import Store
from miniclaw_web.canvas import Canvas
from miniclaw_web.studio import Studio

def migrate(source, destination, root, apply=False):
    source=Path(source);destination=Path(destination)
    source_db=source/'miniclaw.sqlite3'
    if not source_db.is_file(): return {'projects':0,'status':'no_source'}
    with closing(sqlite3.connect(source_db)) as src:
        rows=src.execute('SELECT id,data FROM video_workspaces').fetchall()
        jobs=src.execute('SELECT id,project,data FROM canvas_jobs').fetchall()
        if any(json.loads(row[2])['state'] in ('queued','running','unknown') for row in jobs):
            raise ValueError('原工作区还有活动或未知请求，先核对原任务，不迁移或重新排队')
        if not apply:return {'projects':len(rows),'jobs':len(jobs),'status':'dry_run'}
        destination_db=destination/'miniclaw.sqlite3'
        if destination_db.is_file():
            # Canvas startup recovers interrupted jobs, so inspect before constructing it.
            with closing(sqlite3.connect(f'file:{destination_db.as_posix()}?mode=ro',uri=True)) as existing:
                if existing.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='canvas_jobs'").fetchone():
                    if any(json.loads(row[0])['state'] in ('queued','running','unknown') for row in existing.execute('SELECT data FROM canvas_jobs')):
                        raise ValueError('正式工作区还有活动或未知请求，先核对任务，再迁移')
        store=Store(destination);canvas=Canvas(store);Studio(store,canvas,root)
        backup=destination/'studio-migration-backup';backup.mkdir(exist_ok=True)
        for label,db_path in [('source',source_db),('destination',destination/'miniclaw.sqlite3')]:
            backup_path=backup/(label+'.sqlite3')
            if backup_path.exists():raise ValueError('迁移备份已存在，请先核对上次迁移结果')
            with closing(sqlite3.connect(db_path)) as conn,closing(sqlite3.connect(backup_path)) as out:conn.backup(out)
        tables=['video_workspaces','video_workspace_receipts','video_precision_links','video_precision_requests',
                'canvas_projects','canvas_history','canvas_selections','canvas_jobs','canvas_plans']
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for table in tables:
                if not src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():continue
                data=src.execute(f'SELECT * FROM {table}').fetchall()
                for row in data:
                    marks=','.join('?' for _ in row)
                    # Never overwrite formal objects with the same id.
                    db.execute(f'INSERT INTO {table} VALUES ({marks})',row)
            projects=[row[0] for row in src.execute('SELECT id FROM canvas_projects')]
            for project in projects:
                owner='project-'+project
                for aid,oldowner,raw in src.execute('SELECT id,owner,data FROM attachments WHERE owner=?',(owner,)):
                    record=json.loads(raw)
                    if record.get('path'):
                        old=Path(record['path']);folder=destination/'studio-imported-assets'/project;folder.mkdir(parents=True,exist_ok=True)
                        new=folder/(aid+old.suffix);shutil.copy2(old,new);record['path']=str(new)
                    db.execute('INSERT INTO attachments VALUES (?,?,?)',(aid,oldowner,json.dumps(record)))
        return {'projects':len(rows),'jobs':len(jobs),'status':'imported','source_retained':True}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');parser.add_argument('--source');parser.add_argument('--destination')
    args=parser.parse_args();root=Path(__file__).resolve().parents[1]
    print(json.dumps(migrate(args.source or root/'.hermes/video-workspace',args.destination or root/'.hermes',root,args.apply)))
