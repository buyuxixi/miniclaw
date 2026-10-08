"""Small versioned creation aggregate shared by chat, director and canvas clients.

The initial slice uses existing media candidates. It never submits video generation.
"""
import hashlib
import json
import time
import uuid

from .canvas import Conflict

ENTRANCES = {'chat', 'director', 'canvas'}


class Creation:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS creation_projects (id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS creation_operations (project TEXT, id TEXT, signature TEXT, data TEXT,
                    PRIMARY KEY(project,id));
            ''')

    def create_sample(self, identifier=None):
        identifier = identifier or uuid.uuid4().hex
        p = dict(id=identifier, name='FORM 01 · 清透之间', revision=0,
                 facts=[{'text': '产品外观以提供的原图为依据', 'source': 'source.png', 'status': 'confirmed'},
                        {'text': '不宣称未提供依据的成分与功效', 'source': 'project_requirement', 'status': 'confirmed'}],
                 shots=[dict(id=f'shot_{i:02}', revision=0, purpose=purpose, duration=duration,
                             adopted=f'asset_{i:02}_v1', history=[f'asset_{i:02}_v1'],
                             versions=[dict(id=f'asset_{i:02}_v1', image=image, note='现用版本', source='existing_media')])
                        for i, purpose, duration, image in [(1, '产品登场', 4, 'hero.png'), (2, '瓶身光影', 4, 'source.png'), (3, '品牌停留', 3, 'frame-end.png')]],
                 proposals=[], events=[], conversations={'chat': [], 'director': []},
                 budget=dict(video_limit=0, video_submitted=0), created=time.time())
        with self.store.connect() as db:
            db.execute('INSERT OR IGNORE INTO creation_projects VALUES (?,?)', (identifier, json.dumps(p, ensure_ascii=False)))
        return self.get(identifier)

    def _read(self, db, project):
        row = db.execute('SELECT data FROM creation_projects WHERE id=?', (project,)).fetchone()
        if not row:
            raise ValueError('项目不存在')
        return json.loads(row[0])

    def get(self, project):
        with self.store.connect() as db:
            return self._read(db, project)

    @staticmethod
    def shot(project, identifier):
        found = next((s for s in project['shots'] if s['id'] == identifier), None)
        if found is None:
            raise ValueError('镜头不属于当前项目')
        return found

    def command(self, project, data):
        if not isinstance(data, dict) or set(data) != {'request_id', 'revision', 'entrance', 'action', 'args'}:
            raise ValueError('需要操作标识、当前版本、入口、动作和参数')
        rid, revision, entrance, action, args = (data[k] for k in ('request_id', 'revision', 'entrance', 'action', 'args'))
        if not isinstance(rid, str) or not 8 <= len(rid) <= 80 or type(revision) is not int or not isinstance(entrance, str) or entrance not in ENTRANCES or not isinstance(action, str) or not isinstance(args, dict):
            raise ValueError('操作字段无效')
        signature = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT signature,data FROM creation_operations WHERE project=? AND id=?', (project, rid)).fetchone()
            if previous:
                if previous[0] != signature:
                    raise ValueError('操作标识已用于不同请求')
                return dict(project=self._read(db, project), receipt=json.loads(previous[1]), replayed=True)
            p = self._read(db, project)
            if p['revision'] != revision:
                raise Conflict('项目已变化，已保留你的输入；请读取最新状态后重试')
            detail = self._apply(p, action, args)
            p['revision'] += 1
            receipt = dict(id=rid, revision=p['revision'], entrance=entrance, action=action, detail=detail, time=time.time())
            p['events'].append(receipt)
            db.execute('UPDATE creation_projects SET data=? WHERE id=?', (json.dumps(p, ensure_ascii=False), project))
            db.execute('INSERT INTO creation_operations VALUES (?,?,?,?)', (project, rid, signature, json.dumps(receipt, ensure_ascii=False)))
            return dict(project=p, receipt=receipt, replayed=False)

    def _apply(self, p, action, args):
        if action == 'propose':
            if set(args) != {'shot_id', 'instruction', 'decision_id'}:
                raise ValueError('修改提案参数无效')
            shot = self.shot(p, args['shot_id'])
            text = args['instruction']
            if not isinstance(text, str) or not 1 <= len(text.strip()) <= 1200:
                raise ValueError('需要明确修改要求')
            decision_id = args['decision_id']
            if decision_id is not None and (not isinstance(decision_id, str) or not 8 <= len(decision_id) <= 80):
                raise ValueError('决策标识无效')
            prop = dict(id=uuid.uuid4().hex, shot_id=shot['id'], basis=shot['revision'],
                        instruction=text, decision_id=decision_id, status='draft', candidate=None)
            p['proposals'].append(prop)
            return dict(proposal_id=prop['id'], affected=[shot['id']], preserved=[s['id'] for s in p['shots'] if s['id'] != shot['id']])
        if action == 'candidate':
            if set(args) != {'proposal_id', 'media'} or args['media'] not in ('detail.png', 'macro.png', 'hero.png', 'source.png'):
                raise ValueError('请选择已有素材候选')
            prop = self._proposal(p, args['proposal_id'])
            if prop['status'] != 'draft':
                raise ValueError('该提案已经准备过候选')
            shot = self.shot(p, prop['shot_id'])
            candidate = dict(id=uuid.uuid4().hex, image=args['media'], note=prop['instruction'], source='existing_media', proposal_id=prop['id'])
            shot['versions'].append(candidate)
            prop.update(candidate=candidate['id'], status='ready')
            return dict(candidate=candidate['id'], shot_id=shot['id'], source='existing_media', generation_submitted=False)
        if action == 'adopt':
            if set(args) != {'proposal_id'}:
                raise ValueError('采用参数无效')
            prop = self._proposal(p, args['proposal_id'])
            shot = self.shot(p, prop['shot_id'])
            if prop['status'] != 'ready':
                raise ValueError('没有可采用候选')
            if shot['revision'] != prop['basis']:
                raise Conflict('该镜头在提案后已修改；候选保留，请重新核对')
            shot.update(adopted=prop['candidate'], revision=shot['revision'] + 1)
            shot['history'].append(prop['candidate'])
            prop['status'] = 'adopted'
            return dict(shot_id=shot['id'], adopted=shot['adopted'])
        if action == 'restore':
            if set(args) != {'shot_id', 'version_id'}:
                raise ValueError('恢复参数无效')
            shot = self.shot(p, args['shot_id'])
            if args['version_id'] not in shot['history']:
                raise ValueError('只能恢复该镜头曾采用的版本')
            if shot['adopted'] == args['version_id']:
                raise ValueError('该版本已在使用')
            shot.update(adopted=args['version_id'], revision=shot['revision'] + 1)
            return dict(shot_id=shot['id'], restored=shot['adopted'])
        if action == 'message':
            if set(args) != {'surface', 'text'} or args['surface'] not in ('chat', 'director') or not isinstance(args['text'], str) or not 1 <= len(args['text'].strip()) <= 1200:
                raise ValueError('讨论内容无效')
            p['conversations'][args['surface']].append(dict(id=uuid.uuid4().hex, text=args['text'], time=time.time()))
            return dict(surface=args['surface'], saved=True)
        raise ValueError('未知项目操作')

    @staticmethod
    def _proposal(p, identifier):
        found = next((v for v in p['proposals'] if v['id'] == identifier), None)
        if found is None:
            raise ValueError('提案不属于当前项目')
        return found
