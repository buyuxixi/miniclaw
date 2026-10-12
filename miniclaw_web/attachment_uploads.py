"""Resumable local uploads. Original bytes and parser jobs have separate lifetimes."""
import codecs
import hashlib
import json
import math
import os
import re
import threading
import time
import uuid
import zipfile
from pathlib import Path

from PIL import Image

from .attachments import MAX_IMAGE, MAX_TEXT, public

PART_SIZE = 4 * 1024 * 1024
MAX_DOCUMENT = 50 * 1024 * 1024
EXTENSIONS = {
    '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp',
    '.txt': 'text/plain', '.md': 'text/markdown', '.markdown': 'text/markdown',
    '.srt': 'application/x-subrip', '.csv': 'text/csv', '.pdf': 'application/pdf',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
}
TEXT_EXTENSIONS = {'.txt', '.md', '.markdown', '.srt', '.csv'}
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp'}
_COLUMNS = ('id', 'owner', 'request_id', 'signature', 'name', 'size', 'part_size', 'state',
            'attachment_id', 'error', 'created_at', 'updated_at')


class UploadError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class _PartStream:
    """Expose ordered files as a bounded stream to MediaStorage.put_stream."""
    def __init__(self, paths):
        self.paths = iter(paths)
        self.current = None

    def read(self, size):
        while True:
            if self.current is None:
                path = next(self.paths, None)
                if path is None:
                    return b''
                self.current = path.open('rb')
            chunk = self.current.read(size)
            if chunk:
                return chunk
            self.current.close()
            self.current = None

    def close(self):
        if self.current:
            self.current.close()
            self.current = None


class AttachmentUploads:
    def __init__(self, store, documents, *, clock=time.time, part_size=PART_SIZE,
                 max_active=10, max_active_bytes=10 * MAX_DOCUMENT, ttl=24 * 60 * 60):
        self.store, self.documents, self.clock = store, documents, clock
        self.part_size, self.max_active = part_size, max_active
        self.max_active_bytes, self.ttl = max_active_bytes, ttl
        self.root = (store.home / 'media' / 'uploads').resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    @staticmethod
    def _owner(owner):
        if not isinstance(owner, str) or not re.fullmatch(r'[\w-]{1,128}', owner):
            raise UploadError(400, '会话标识无效')

    @staticmethod
    def _name(name):
        if (not isinstance(name, str) or not name or len(name) > 200 or name in ('.', '..')
                or any(c in name for c in '/\\:') or any(ord(c) < 32 for c in name)):
            raise UploadError(400, '文件名称无效')
        ext = Path(name).suffix.lower()
        if ext not in EXTENSIONS:
            raise UploadError(400, '支持图片、TXT、Markdown、SRT、PDF、DOCX、CSV和XLSX；旧版DOC/XLS请先转换')
        return ext

    def _get(self, db, identifier, owner):
        self._owner(owner)
        if not isinstance(identifier, str) or not re.fullmatch('[a-f0-9]{32}', identifier):
            raise UploadError(404, '上传任务不可用')
        row = db.execute('SELECT ' + ','.join(_COLUMNS) + ' FROM attachment_uploads WHERE id=? AND owner=?',
                         (identifier, owner)).fetchone()
        if not row:
            raise UploadError(404, '上传任务不可用')
        return dict(zip(_COLUMNS, row))

    def _path(self, identifier, name):
        # Paths only come from a generated ID and numeric part/hash names.
        path = (self.root / identifier / name).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise UploadError(400, '上传暂存路径无效')
        return path

    def _attachment(self, identifier, owner, enqueue=False):
        record = self.store.get('attachments', identifier, owner)
        result = {**public(record), 'parse_status': record.get('parse_status', 'ready' if record['kind'] == 'image' else 'queued')}
        if record['kind'] != 'image':
            if enqueue:
                status = self.documents.enqueue(identifier, owner)
            else:
                try:
                    status = self.documents.status(identifier, owner)
                except ValueError:
                    # Repair the original-file/job receipt gap after an interrupted completion.
                    status = self.documents.enqueue(identifier, owner)
            result.update({key: status[key] for key in ('parse_status', 'parse_error', 'chunks', 'rows', 'coverage',
                           'parser_version', 'object_id', 'attempt', 'updated_at') if key in status})
            result['warnings'] = [{'code': item.get('code'), 'message': item.get('message', '')[:300]}
                                  for item in status.get('warnings', [])[:5]]
        return result

    def _status(self, row, db):
        parts = [dict(zip(('part_no', 'size', 'sha256'), item)) for item in db.execute(
            'SELECT part_no,size,sha256 FROM attachment_upload_parts WHERE upload_id=? ORDER BY part_no', (row['id'],))]
        result = {key: row[key] for key in ('id', 'name', 'size', 'part_size', 'state', 'error')}
        result['parts'] = parts
        return result

    def init(self, owner, name, size, request_id):
        self._owner(owner)
        ext = self._name(name)
        cap = MAX_IMAGE if ext in IMAGE_EXTENSIONS else MAX_DOCUMENT
        if type(size) is not int or not 0 < size <= cap:
            raise UploadError(400, '图片最大5 MiB，文档最大50 MiB，文件不能为空')
        if not isinstance(request_id, str) or not re.fullmatch(r'[\w-]{1,128}', request_id):
            raise UploadError(400, '上传请求标识无效')
        signature = hashlib.sha256(json.dumps([name, size], ensure_ascii=False).encode()).hexdigest()
        with self.lock:
            self.cleanup()
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                existing = db.execute('SELECT id,signature FROM attachment_uploads WHERE owner=? AND request_id=?', (owner, request_id)).fetchone()
                if existing:
                    if existing[1] != signature:
                        raise UploadError(409, '同一上传请求不能更换文件')
                    identifier = existing[0]
                else:
                    count, reserved = db.execute("SELECT count(*),coalesce(sum(size),0) FROM attachment_uploads WHERE state IN ('uploading','completing')").fetchone()
                    if count >= self.max_active or reserved + size > self.max_active_bytes:
                        raise UploadError(429, '未完成上传过多，请完成或取消已有上传后重试')
                    identifier, now = uuid.uuid4().hex, self.clock()
                    db.execute('INSERT INTO attachment_uploads VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                               (identifier, owner, request_id, signature, name, size, self.part_size, 'uploading', None, '', now, now))
            return self.status(identifier, owner)

    def status(self, identifier, owner):
        with self.lock:
            self.cleanup()
            with self.store.connect() as db:
                row = self._get(db, identifier, owner)
                result = self._status(row, db)
            if row['state'] == 'completed':
                result['attachment'] = self._attachment(row['attachment_id'], owner)
            return result

    def put_part(self, identifier, owner, part_no, raw, sha256):
        if type(part_no) is not int or part_no < 0:
            raise UploadError(400, '分片序号无效')
        if not isinstance(raw, (bytes, bytearray)) or not raw or len(raw) > self.part_size:
            raise UploadError(400, '分片大小无效')
        if not isinstance(sha256, str) or not re.fullmatch('[a-f0-9]{64}', sha256):
            raise UploadError(400, '需要有效的X-Part-SHA256校验值')
        if hashlib.sha256(raw).hexdigest() != sha256:
            raise UploadError(400, '分片校验失败，请重传该分片')
        with self.lock:
            self.cleanup()
            with self.store.connect() as db:
                row = self._get(db, identifier, owner)
                if row['state'] != 'uploading':
                    raise UploadError(409, '此上传已结束，不能继续添加分片')
                count = math.ceil(row['size'] / row['part_size'])
                expected = min(row['part_size'], row['size'] - part_no * row['part_size'])
                if part_no >= count or len(raw) != expected:
                    raise UploadError(400, '分片大小或序号与声明文件不一致')
                previous = db.execute('SELECT size,sha256 FROM attachment_upload_parts WHERE upload_id=? AND part_no=?', (identifier, part_no)).fetchone()
                if previous and previous != (len(raw), sha256):
                    raise UploadError(409, '已保存的分片不能被不同内容替换，请重新上传文件')
                if not previous:
                    destination = self._path(identifier, f'{part_no}-{sha256}.part')
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    temporary = self._path(identifier, uuid.uuid4().hex + '.tmp')
                    try:
                        with temporary.open('xb') as output:
                            output.write(raw)
                            output.flush()
                            os.fsync(output.fileno())
                        os.replace(temporary, destination)
                        db.execute('INSERT INTO attachment_upload_parts VALUES (?,?,?,?,?)',
                                   (identifier, part_no, len(raw), sha256, str(destination)))
                    finally:
                        temporary.unlink(missing_ok=True)
                db.execute('UPDATE attachment_uploads SET updated_at=? WHERE id=?', (self.clock(), identifier))
            return self.status(identifier, owner)

    def _validate(self, row, path):
        ext, mime = self._name(row['name']), EXTENSIONS[Path(row['name']).suffix.lower()]
        text = None
        if ext in IMAGE_EXTENSIONS:
            expected = {'.png': 'PNG', '.jpg': 'JPEG', '.jpeg': 'JPEG', '.webp': 'WEBP'}[ext]
            try:
                with Image.open(path) as image:
                    if image.format != expected or image.width * image.height > 20_000_000:
                        raise UploadError(400, '图片格式或尺寸不支持（最大2000万像素）')
                    image.verify()
            except (OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
                raise UploadError(400, '图片损坏或尺寸过大') from None
            return 'image', mime, None
        if ext in TEXT_EXTENSIONS:
            decoder = codecs.getincrementaldecoder('utf-8-sig')()
            small = [] if row['size'] <= MAX_TEXT and ext != '.csv' else None
            try:
                with path.open('rb') as stream:
                    while chunk := stream.read(1024 * 1024):
                        decoded = decoder.decode(chunk)
                        if '\x00' in decoded:
                            raise UploadError(400, '该文件不是文本')
                        if small is not None:
                            small.append(decoded)
                    tail = decoder.decode(b'', final=True)
                    if small is not None:
                        small.append(tail)
            except UnicodeError:
                raise UploadError(400, '文本附件需要使用UTF-8编码') from None
            if small is not None:
                text = ''.join(small)
                return 'text', mime, text
        elif ext == '.pdf':
            with path.open('rb') as stream:
                if stream.read(5) != b'%PDF-':
                    raise UploadError(400, 'PDF内容与扩展名不一致')
        else:
            required = 'word/document.xml' if ext == '.docx' else 'xl/workbook.xml'
            try:
                with zipfile.ZipFile(path) as package:
                    names = set(package.namelist())
                    if '[Content_Types].xml' not in names or required not in names:
                        raise UploadError(400, 'Office文件内容与扩展名不一致')
                    if len(package.infolist()) > 10000 or sum(item.file_size for item in package.infolist()) > 200 * 1024 * 1024:
                        raise UploadError(400, 'Office文件解压体积或条目数超过限制')
            except zipfile.BadZipFile:
                raise UploadError(400, 'Office文件损坏或格式不支持') from None
        return 'document', mime, text

    def complete(self, identifier, owner):
        with self.lock:
            self.cleanup()
            with self.store.connect() as db:
                row = self._get(db, identifier, owner)
                if row['state'] == 'completed':
                    attachment_id = row['attachment_id']
                elif row['state'] not in ('uploading', 'completing'):
                    raise UploadError(409, '此上传已取消或过期，请重新选择文件')
                else:
                    attachment_id = None
                parts = db.execute('SELECT part_no,size,sha256,path FROM attachment_upload_parts WHERE upload_id=? ORDER BY part_no', (identifier,)).fetchall()
            if attachment_id:
                return self._attachment(attachment_id, owner)
            count = math.ceil(row['size'] / row['part_size'])
            if len(parts) != count or [p[0] for p in parts] != list(range(count)) or sum(p[1] for p in parts) != row['size']:
                raise UploadError(409, '分片尚未全部上传，请继续上传缺失分片')
            paths = []
            for part_no, size, checksum, saved_path in parts:
                path = self._path(identifier, f'{part_no}-{checksum}.part')
                if str(path) != saved_path or not path.is_file() or path.stat().st_size != size:
                    raise UploadError(409, '已上传分片不可用，请重新上传文件')
                with path.open('rb') as stream:
                    if hashlib.file_digest(stream, 'sha256').hexdigest() != checksum:
                        raise UploadError(409, '已上传分片校验失败，请重新上传文件')
                paths.append(path)
            with self.store.connect() as db:
                db.execute("UPDATE attachment_uploads SET state='completing',updated_at=? WHERE id=?", (self.clock(), identifier))
            stream = _PartStream(paths)
            combined = self._path(identifier, uuid.uuid4().hex + '.tmp')
            try:
                with combined.open('xb') as output:
                    while chunk := stream.read(1024 * 1024):
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                kind, mime, text = self._validate(row, combined)
                obj = self.store.media.put_file(combined, mime)
                path = self.store.media.materialize(obj['id'])
                try:
                    self.store.get('attachments', identifier, owner)
                except ValueError:
                    record = dict(id=identifier, name=row['name'], kind=kind, mime=mime,
                                  bytes=row['size'], object_id=obj['id'], path=str(path), text=text,
                                  parse_status='ready' if kind == 'image' else 'queued')
                    self.store.put('attachments', identifier, record, owner)
                with self.store.connect() as db:
                    db.execute("UPDATE attachment_uploads SET state='completed',attachment_id=?,error='',updated_at=? WHERE id=?", (identifier, self.clock(), identifier))
                result = self._attachment(identifier, owner, enqueue=True)
                self._remove_parts(identifier, keep_metadata=True)
                return result
            except (ValueError, OSError) as error:
                # A successful original file receipt survives a later parser enqueue failure.
                with self.store.connect() as db:
                    db.execute("UPDATE attachment_uploads SET state=CASE WHEN state='completed' THEN state ELSE 'uploading' END,error=?,updated_at=? WHERE id=?",
                               ('附件完成未成功，请重试完成或取消此上传', self.clock(), identifier))
                raise error
            finally:
                stream.close()
                combined.unlink(missing_ok=True)

    def _remove_parts(self, identifier, keep_metadata=False):
        with self.store.connect() as db:
            rows = db.execute('SELECT part_no,sha256 FROM attachment_upload_parts WHERE upload_id=?', (identifier,)).fetchall()
            for part_no, checksum in rows:
                self._path(identifier, f'{part_no}-{checksum}.part').unlink(missing_ok=True)
            if not keep_metadata:
                db.execute('DELETE FROM attachment_upload_parts WHERE upload_id=?', (identifier,))
        folder = self._path(identifier, 'placeholder').parent
        if folder.exists():
            # Only generated temporary files inside this upload directory are eligible.
            for path in folder.iterdir():
                if (re.fullmatch(r'(?:[a-f0-9]{32}\.tmp|\d+-[a-f0-9]{64}\.part)', path.name)
                        and path.resolve().is_relative_to(self.root)):
                    path.unlink(missing_ok=True)
            try:
                folder.rmdir()
            except OSError:
                pass

    def cancel(self, identifier, owner):
        with self.lock:
            with self.store.connect() as db:
                row = self._get(db, identifier, owner)
                if row['state'] == 'completed':
                    raise UploadError(409, '文件已保存，不能取消已完成上传')
                db.execute("UPDATE attachment_uploads SET state='canceled',updated_at=? WHERE id=?", (self.clock(), identifier))
            self._remove_parts(identifier)
            return self.status(identifier, owner)

    def cleanup(self):
        with self.lock:
            with self.store.connect() as db:
                expired = [r[0] for r in db.execute("SELECT id FROM attachment_uploads WHERE state IN ('uploading','completing') AND updated_at<?", (self.clock() - self.ttl,))]
                for identifier in expired:
                    db.execute("UPDATE attachment_uploads SET state='expired',error='上传已过期，请重新选择文件',updated_at=? WHERE id=?", (self.clock(), identifier))
            # Completed metadata is retained for browser content verification; only
            # directories still on disk need cleanup, avoiding a scan of every past upload.
            for folder in list(self.root.iterdir()):
                if not folder.is_dir() or not re.fullmatch('[a-f0-9]{32}', folder.name):
                    continue
                with self.store.connect() as db:
                    state = db.execute('SELECT state FROM attachment_uploads WHERE id=?', (folder.name,)).fetchone()
                if state and state[0] in ('expired', 'canceled', 'completed'):
                    self._remove_parts(folder.name, keep_metadata=state[0] == 'completed')
            return len(expired)
