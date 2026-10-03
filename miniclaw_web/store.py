"""Small display/dependency store. Hermes remains the conversation authority."""
import hashlib
import json
import sqlite3
from pathlib import Path
from contextlib import contextmanager


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


class Store:
    def __init__(self, home):
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS attachments (id TEXT PRIMARY KEY, owner TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS turns (row_id INTEGER PRIMARY KEY, owner TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS bindings (name TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS image_jobs (id TEXT PRIMARY KEY, owner TEXT NOT NULL, data TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.home / 'miniclaw.sqlite3', timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def put(self, table, key, data, owner=None):
        if table not in ('attachments', 'turns', 'bindings', 'image_jobs'):
            raise ValueError('Unknown table')
        column = 'row_id' if table == 'turns' else 'name' if table == 'bindings' else 'id'
        with self.connect() as db:
            if table == 'bindings':
                db.execute(f'INSERT OR REPLACE INTO {table} ({column}, data) VALUES (?, ?)', (key, json.dumps(data, ensure_ascii=False)))
            else:
                db.execute(f'INSERT OR REPLACE INTO {table} ({column}, owner, data) VALUES (?, ?, ?)', (key, owner, json.dumps(data, ensure_ascii=False)))

    def get(self, table, key, owner=None):
        if table not in ('attachments', 'turns', 'bindings', 'image_jobs'):
            raise ValueError('Unknown table')
        column = 'row_id' if table == 'turns' else 'name' if table == 'bindings' else 'id'
        with self.connect() as db:
            row = db.execute(f'SELECT data FROM {table} WHERE {column}=?' + (' AND owner=?' if owner is not None else ''), (key, owner) if owner is not None else (key,)).fetchone()
        if row is None:
            raise ValueError('记录不存在或不属于当前对话')
        return json.loads(row[0])

    def turns(self, owner):
        with self.connect() as db:
            return {str(row): json.loads(data) for row, data in db.execute('SELECT row_id,data FROM turns WHERE owner=?', (owner,))}

    def images(self, owner):
        with self.connect() as db:
            rows = db.execute('SELECT data FROM attachments WHERE owner=? ORDER BY rowid DESC LIMIT 200', (owner,)).fetchall()
        return [json.loads(row[0]) for row in rows if json.loads(row[0]).get('kind') == 'image']

    def image_jobs(self, owner=None):
        with self.connect() as db:
            rows = db.execute('SELECT data FROM image_jobs' + (' WHERE owner=?' if owner is not None else '') + ' ORDER BY rowid DESC', (owner,) if owner is not None else ()).fetchall()
        return [json.loads(row[0]) for row in rows]
