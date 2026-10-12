"""Immutable, streamed objects. Business records store keys, never signed URLs.

An OSS adapter implements ObjectBackend and is injected into MediaStorage.backends.
No cloud SDK or credentials are required for the default local backend.
"""
import hashlib
import io
import json
import os
import re
import tempfile
import time
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import BinaryIO, Protocol


class ObjectBackend(Protocol):
    def publish(self, key: str, source: Path, sha256: str, size: int) -> None: ...
    def open(self, key: str) -> BinaryIO: ...
    def size(self, key: str) -> int: ...


class LocalObjects:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key):
        if not re.fullmatch(r'sha256/[a-f0-9]{2}/[a-f0-9]{64}', key):
            raise ValueError('无效的文件对象路径')
        return self.root / key

    def publish(self, key, source, sha256, size):
        destination = self.path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            # Do not silently accept a corrupted existing object.
            with destination.open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            if destination.stat().st_size != size or actual != sha256:
                raise OSError('已有文件对象校验失败')
            return
        # The configured object directory can be on another volume.
        fd,name=tempfile.mkstemp(dir=destination.parent)
        temporary=Path(name)
        try:
            with os.fdopen(fd,'wb') as output,source.open('rb') as stream:
                shutil.copyfileobj(stream,output,1024*1024)
                output.flush();os.fsync(output.fileno())
            os.replace(temporary,destination)
        finally:
            temporary.unlink(missing_ok=True)

    def open(self, key):
        return self.path(key).open('rb')

    def size(self, key):
        return self.path(key).stat().st_size


class MediaStorage:
    def __init__(self, store, backends=None, write_backend='local'):
        self.store = store
        root = os.environ.get('MINICLAW_MEDIA_ROOT') or store.home / 'media' / 'objects'
        self.backends = {'local': LocalObjects(root), **(backends or {})}
        if write_backend not in self.backends:
            raise ValueError('文件存储后端未配置')
        self.write_backend = write_backend

    def put_stream(self, stream, mime='application/octet-stream'):
        # Spool in chunks: videos must not be read into one large Python bytes value.
        staging = self.store.home / 'media' / 'staging'
        staging.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=staging)
        source = Path(name)
        checksum, size = hashlib.sha256(), 0
        try:
            with os.fdopen(fd, 'wb') as output:
                while chunk := stream.read(1024 * 1024):
                    checksum.update(chunk)
                    size += len(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if not size:
                raise ValueError('文件为空')
            identifier = checksum.hexdigest()
            key = 'sha256/' + identifier[:2] + '/' + identifier
            # Existing location is authoritative even if the default backend changes.
            with self.store.connect() as db:
                found = db.execute('SELECT backend,storage_key FROM file_objects WHERE id=?', (identifier,)).fetchone()
            backend, key = found if found else (self.write_backend, key)
            self.backends[backend].publish(key, source, identifier, size)
            with self.store.connect() as db:
                db.execute('INSERT OR IGNORE INTO file_objects VALUES (?,?,?,?,?,?,?)',
                           (identifier, backend, key, identifier, size, mime, time.time()))
            return self.get(identifier)
        finally:
            source.unlink(missing_ok=True)

    def put_bytes(self, raw, mime):
        return self.put_stream(io.BytesIO(raw), mime)

    def put_file(self, path, mime='application/octet-stream'):
        with Path(path).open('rb') as stream:
            return self.put_stream(stream, mime)

    def get(self, identifier, db=None):
        if not isinstance(identifier, str) or not re.fullmatch('[a-f0-9]{64}', identifier):
            raise ValueError('文件对象标识无效')
        if db is None:
            with self.store.connect() as connection:
                return self.get(identifier, connection)
        row = db.execute('SELECT id,backend,storage_key,sha256,bytes,mime,created_at FROM file_objects WHERE id=?', (identifier,)).fetchone()
        if not row:
            raise ValueError('文件对象不存在')
        return dict(zip(('id','backend','storage_key','sha256','bytes','mime','created_at'), row))

    def materialize(self, identifier):
        """Local path for existing PIL/FFmpeg/FileResponse; OSS uses a verified cache."""
        record = self.get(identifier)
        backend = self.backends[record['backend']]
        if isinstance(backend, LocalObjects):
            return backend.path(record['storage_key'])
        cache = LocalObjects(self.store.home / 'media' / 'cache')
        destination = cache.path(record['storage_key'])
        if destination.exists():
            with destination.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() == identifier:
                    return destination
            destination.unlink()
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=destination.parent)
        temporary = Path(name)
        try:
            checksum, size = hashlib.sha256(), 0
            with os.fdopen(fd, 'wb') as output, backend.open(record['storage_key']) as stream:
                while chunk := stream.read(1024 * 1024):
                    checksum.update(chunk); size += len(chunk); output.write(chunk)
                output.flush(); os.fsync(output.fileno())
            if size != record['bytes'] or checksum.hexdigest() != identifier:
                raise OSError('远端文件校验失败')
            cache.publish(record['storage_key'], temporary, identifier, size)
            return destination
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def url(identifier):
        return '/studio/media/objects/' + identifier


def migrate_schema(db):
    baseline=Path(__file__).with_name('schema')/'000_business_legacy.sql'
    db.executescript(baseline.read_text(encoding='utf-8'))
    db.execute('CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, checksum TEXT NOT NULL, applied_at REAL NOT NULL)')
    for version, name in ((1,'001_media_storage.sql'),(2,'002_integrity_catalog.sql'),(3,'003_archive_library.sql'),(4,'004_chat_clarifications.sql'),(5,'005_attachment_documents.sql')):
        source=(baseline.parent/name).read_text(encoding='utf-8')
        checksum=hashlib.sha256(source.encode()).hexdigest()
        existing=db.execute('SELECT checksum FROM schema_migrations WHERE version=?',(version,)).fetchone()
        if existing:
            if existing[0]!=checksum:raise ValueError('已执行的数据库迁移文件发生变化')
            continue
        db.commit()
        if version>=2:
            # SQLite backups include committed WAL pages. Never copy a live .db file.
            location=db.execute('PRAGMA database_list').fetchone()[2]
            if location and any(db.execute('SELECT 1 FROM '+table+' LIMIT 1').fetchone() for table in ('video_workspaces','canvas_projects','attachments','media_revisions')):
                destination=Path(location).parent/'backups'/('schema-v'+str(version)+'-'+str(time.time_ns())+'.sqlite3')
                destination.parent.mkdir(parents=True,exist_ok=True)
                with closing(sqlite3.connect(destination)) as backup:db.backup(backup)
        db.execute('PRAGMA foreign_keys=OFF')
        try:
            db.execute('BEGIN IMMEDIATE')
            statement=''
            for line in source.splitlines(keepends=True):
                statement+=line
                if sqlite3.complete_statement(statement):
                    db.execute(statement);statement=''
            if statement.strip():raise ValueError('数据库迁移 SQL 不完整')
            violations=db.execute('PRAGMA foreign_key_check').fetchall()
            if violations:raise ValueError('旧数据存在失效关联，迁移已回滚，请检查备份: '+repr(violations[:12]))
            db.execute('INSERT INTO schema_migrations VALUES (?,?,?)',(version,checksum,time.time()))
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.execute('PRAGMA foreign_keys=ON')
