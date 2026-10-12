"""Durable business state. Hermes history remains the authority for executed turns.

Every transition uses an SQLite write transaction; no socket/thread is a checkpoint.
The prepared -> pending boundary is committed only after canonical history flush.
"""
import hashlib
import json
import time
import uuid


class ClarificationConflict(ValueError):
    pass


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def questions(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 3:
        raise ValueError('一次需要1至3个澄清问题')
    clean = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError('澄清问题格式无效')
        title = item.get('question', item.get('title'))
        choices = item.get('choices') or []
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 1000:
            raise ValueError('问题需要1至1000字')
        if not isinstance(choices, list) or len(choices) > 5 or any(not isinstance(c, str) or not c.strip() or len(c) > 200 for c in choices):
            raise ValueError('选项无效')
        if len(set(choices)) != len(choices):
            raise ValueError('选项不能重复')
        clean.append(dict(id=str(item.get('id') or f'q{index + 1}')[:80], question=title.strip(), choices=choices,
                          multi_select=bool(item.get('multi_select')), template=item.get('template', 'model')))
    if len({q['id'] for q in clean}) != len(clean):
        raise ValueError('问题标识不能重复')
    return clean


class Clarifications:
    def __init__(self, store, timeout=3600, clock=time.time):
        self.store, self.timeout, self.clock = store, max(1, min(86400, int(timeout))), clock

    @staticmethod
    def _row(row):
        if row is None:
            raise ClarificationConflict('任务或问题不存在')
        return {**json.loads(row[4]), 'id': row[0], 'owner': row[1], 'status': row[2], 'version': row[3]}

    def _task(self, db, identifier):
        return self._row(db.execute('SELECT id,owner,status,version,data FROM chat_tasks WHERE id=?', (identifier,)).fetchone())

    def task(self, identifier):
        with self.store.connect() as db:
            return self._task(db, identifier)

    def configure(self, identifier, **context):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            task = self._task(db, identifier)
            task['context'].update(context)
            self._write_task(db, task)

    def request(self, identifier):
        with self.store.connect() as db:
            return self._row(db.execute('SELECT id,owner,status,version,data FROM chat_clarifications WHERE id=?', (identifier,)).fetchone())

    def _write_task(self, db, task, status=None):
        db.execute('UPDATE chat_tasks SET status=?,version=version+1,data=?,updated=? WHERE id=?',
                   (status or task['status'], encode(task), self.clock(), task['id']))

    def _move_owner(self, db, task, owner):
        if task['owner'] == owner:
            return
        # Local operation identity must keep the owner used at submission,
        # even when native compression advances the conversation session.
        for identifier, raw in db.execute('SELECT id,data FROM chat_operations WHERE task_id=?', (task['id'],)).fetchall():
            operation = json.loads(raw)
            operation.setdefault('owner', task['owner'])
            db.execute('UPDATE chat_operations SET data=? WHERE id=?', (encode(operation), identifier))
        db.execute('UPDATE chat_tasks SET owner=? WHERE id=?', (owner, task['id']))
        db.execute('UPDATE chat_clarifications SET owner=? WHERE task_id=?', (owner, task['id']))
        task['owner'] = owner

    def start(self, owner, text, context=None, *, owners=None):
        from .clarification_policy import DRAFT_ONLY, PAID_CONSENT
        import re
        paid_allowance = 0
        text_output = re.search(r'(?:生成|修改|优化|整理|写)[^。！？!?\n]*(?:提示词|方案)', text)
        discussion = re.search(r'为什么|怎么做|可行吗|能不能|可不可以|能否', text)
        if PAID_CONSENT.search(text) and not DRAFT_ONLY.search(text) and not text_output and not discussion and not (context or {}).get('draft_only'):
            count = re.search(r'([1-3一二两三])\s*张', text)
            paid_allowance = {'一':1,'二':2,'两':2,'三':3}.get(count[1], int(count[1]) if count and count[1].isdigit() else 1) if count else 1
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            lineage = list(dict.fromkeys([owner] + list(owners or [])))
            for ancestor in lineage:
                self._expire(db, ancestor)
            placeholders = ','.join('?' for _ in lineage)
            live = db.execute(f"SELECT id FROM chat_tasks WHERE owner IN ({placeholders}) AND status IN ('running','awaiting_input','resume_queued','reconciling')", tuple(lineage)).fetchone()
            if live:
                raise ClarificationConflict('此对话有未完成任务，请回答、修改需求或取消后再发送新话题')
            revising = db.execute(f"SELECT id FROM chat_tasks WHERE owner IN ({placeholders}) AND status='revising' ORDER BY updated DESC LIMIT 1", tuple(lineage)).fetchone()
            if revising:
                task = self._task(db, revising[0])
                self._move_owner(db, task, owner)
                # These answers belong to the previous requirements. A revision
                # keeps receipts and budgets, but trusts only the new UI context
                # until the user confirms the revised task's execution/target.
                for slot in list(task['confirmed']):
                    if slot.startswith('Q_') or slot == 'target_id':
                        task['confirmed'].pop(slot)
                used_paid = sum(bool(json.loads(row[0]).get('paid')) for row in db.execute(
                    'SELECT data FROM chat_operations WHERE task_id=?', (task['id'],)))
                task['context'] = context or {}
                task['text'] = text
                # A revised request replaces unused consent; merely resubmitting
                # the same revision must not accumulate additional paid calls.
                task['paid_allowance'] = used_paid + paid_allowance
                self._write_task(db, task, 'running')
                return {**task, 'status': 'running'}
            identifier = uuid.uuid4().hex
            data = dict(text=text, context=context or {}, used_calls=0, max_calls=100, rounds=0, confirmed={}, paid_allowance=paid_allowance, created=self.clock())
            db.execute('INSERT INTO chat_tasks VALUES (?,?,?,1,?,?)', (identifier, owner, 'running', encode(data), self.clock()))
        return self.task(identifier)

    def prepare(self, task_id, value, channel, call_id=None):
        value = questions(value)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            task = self._task(db, task_id)
            row = db.execute("SELECT id FROM chat_clarifications WHERE task_id=? AND status IN ('prepared','pending')", (task_id,)).fetchone()
            if row:
                return row[0]
            if task['status'] != 'running':
                raise ClarificationConflict('任务已停止，不能继续提问')
            # Repeated identical answered questions make no progress. No new automatic loop.
            previous = db.execute("SELECT data FROM chat_clarifications WHERE task_id=? AND status='answered'", (task_id,)).fetchall()
            if sum(encode(json.loads(r[0])['questions']) == encode(value) for r in previous) >= 2:
                raise ClarificationConflict('已连续两次询问相同问题，请修改需求或手动指定目标')
            identifier = uuid.uuid4().hex
            data = dict(task_id=task_id, questions=value, channel=channel, tool_call_id=call_id,
                        created=self.clock(), deadline=self.clock() + self.timeout)
            db.execute('INSERT INTO chat_clarifications VALUES (?,?,?, ?,1,?,?,?)',
                       (identifier, task_id, task['owner'], 'prepared', data['deadline'], encode(data), self.clock()))
            task['active_clarification'] = identifier
            task['rounds'] += 1
            self._write_task(db, task)
        return identifier

    def seal(self, task_id, owner, watermark, calls=0):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            task = self._task(db, task_id)
            if task['status'] != 'running':
                raise ClarificationConflict('任务已终结，不能重新进入等待')
            self._move_owner(db, task, owner)
            task.update(watermark=watermark)
            task['used_calls'] += max(0,int(calls or 0))
            db.execute("UPDATE chat_clarifications SET status='pending',version=version+1,owner=?,updated=? WHERE task_id=? AND status='prepared'", (owner, self.clock(), task_id))
            self._write_task(db, task, 'awaiting_input')
            db.execute("UPDATE chat_resume_jobs SET status='done',updated=? WHERE task_id=? AND status='dispatching'", (self.clock(),task_id))

    def _expire(self, db, owner=None):
        expired = db.execute("SELECT id,task_id FROM chat_clarifications WHERE status='pending' AND deadline<=?" + (' AND owner=?' if owner else ''),
                             (self.clock(), owner) if owner else (self.clock(),)).fetchall()
        for identifier, task_id in expired:
            db.execute("UPDATE chat_clarifications SET status='timed_out',version=version+1,updated=? WHERE id=?", (self.clock(), identifier))
            task = self._task(db, task_id)
            self._write_task(db, task, 'aborted')

    def list(self, owners):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for owner in owners:
                self._expire(db, owner)
            placeholders = ','.join('?' for _ in owners)
            if not placeholders:
                return []
            rows = db.execute(f"SELECT c.id,c.owner,c.status,c.version,c.data,t.status FROM chat_clarifications c JOIN chat_tasks t ON t.id=c.task_id WHERE c.owner IN ({placeholders}) AND (c.status!='prepared' OR t.status='reconciling') ORDER BY c.updated DESC LIMIT 30", tuple(owners)).fetchall()
            result = []
            represented = set()
            for r in rows:
                item = {**self._row(r[:5]), 'task_status':r[5]}
                represented.add(item['task_id'])
                if item['status'] == 'prepared': item['status'] = 'blocked'
                job = db.execute('SELECT data FROM chat_resume_jobs WHERE clarification_id=?', (item['id'],)).fetchone()
                if job: item['reason'] = json.loads(job[0]).get('reason')
                result.append(item)
            for r in db.execute(f"SELECT id,owner,status,version,data FROM chat_tasks WHERE owner IN ({placeholders}) AND status='reconciling' ORDER BY updated DESC", tuple(owners)):
                task = self._row(r)
                if task['id'] not in represented:
                    result.insert(0,dict(id='task:'+task['id'],task_id=task['id'],owner=task['owner'],version=task['version'],status='blocked',task_status='reconciling',questions=[],deadline=0))
            return result

    def answer(self, owners, identifier, version, answers, submission):
        if not isinstance(submission, str) or not 1 <= len(submission) <= 100:
            raise ValueError('回答提交标识无效')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._expire(db)
            item = self._row(db.execute('SELECT id,owner,status,version,data FROM chat_clarifications WHERE id=?', (identifier,)).fetchone())
            if item['owner'] not in owners:
                raise ClarificationConflict('问题不属于当前对话')
            if item['status'] == 'answered':
                if item.get('answers') != answers:
                    raise ClarificationConflict('问题已有其他回答，请刷新查看')
                return item
            if item['status'] != 'pending' or item['version'] != version:
                raise ClarificationConflict('问题状态已变化，请刷新查看')
            prior_job = db.execute('SELECT clarification_id FROM chat_resume_jobs WHERE id=?', (submission,)).fetchone()
            if prior_job and prior_job[0] != identifier:
                raise ClarificationConflict('提交标识已被其他问题使用，请重新打开当前问题')
            if not isinstance(answers, dict) or set(answers) != {q['id'] for q in item['questions']}:
                raise ValueError('请填写全部问题')
            for q in item['questions']:
                answer = answers[q['id']]
                if q['multi_select'] and isinstance(answer, list):
                    if not answer or any(a not in q['choices'] for a in answer) or len(set(answer)) != len(answer):
                        raise ValueError('多选回答无效')
                elif not isinstance(answer, str) or not answer.strip() or len(answer) > 2000:
                    raise ValueError('回答需要1至2000字')
            item.update(answers=answers, submission_id=submission, answered_at=self.clock())
            db.execute("UPDATE chat_clarifications SET status='answered',version=version+1,data=?,updated=? WHERE id=?", (encode(item), self.clock(), identifier))
            task = self._task(db, item['task_id'])
            task['confirmed'].update({q['template']: answers[q['id']] for q in item['questions']})
            target_answer = task['confirmed'].get('Q_TARGET')
            candidates = task['context'].get('semantic',{}).get('candidates',[])
            matches = [c for c in candidates if target_answer in (c['id'],c['label'])]
            if len(matches)==1:
                task['context']['semantic']['selected'] = matches[0]['id']
                task['confirmed']['target_id'] = matches[0]['id']
            if any(q['template']=='Q_EXECUTION' and answers[q['id']] in ('确认执行','确认生成') for q in item['questions']):
                task['paid_allowance'] = task.get('paid_allowance',0)+1
            if task['confirmed'].get('Q_INTENT') == '直接执行修改':
                task['context']['intent'] = 'execute_change'
            elif task['confirmed'].get('Q_INTENT') == '先整理方案':
                task['context']['intent'] = 'draft'
            self._write_task(db, task, 'resume_queued')
            db.execute('INSERT INTO chat_resume_jobs VALUES (?,?,?, ?,?,?)', (submission, task['id'], identifier, 'queued', encode(dict(owner=item['owner'], submission_id=submission)), self.clock()))
        return {**item, 'status': 'answered', 'version': version + 1}

    def cancel(self, owners, identifier, superseded=False):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if identifier.startswith('task:'):
                task = self._task(db, identifier[5:])
                if task['owner'] not in owners or task['status'] != 'reconciling':
                    raise ClarificationConflict('任务状态已变化，请刷新查看')
                self._write_task(db, task, 'revising' if superseded else 'aborted')
                return dict(id=identifier,task_id=task['id'],status='superseded' if superseded else 'canceled',version=task['version']+1,questions=[],deadline=0)
            item = self._row(db.execute('SELECT id,owner,status,version,data FROM chat_clarifications WHERE id=?', (identifier,)).fetchone())
            if item['owner'] not in owners:
                raise ClarificationConflict('问题不属于当前对话')
            task = self._task(db, item['task_id'])
            if task['status'] == 'running':
                raise ClarificationConflict('任务已恢复，请使用停止按钮')
            if item['status'] not in ('prepared','pending','answered','timed_out'):
                return item
            status = 'superseded' if superseded else 'canceled'
            db.execute('UPDATE chat_clarifications SET status=?,version=version+1,updated=? WHERE id=?', (status, self.clock(), identifier))
            db.execute("UPDATE chat_resume_jobs SET status='canceled',updated=? WHERE task_id=? AND status IN ('queued','dispatching')", (self.clock(), task['id']))
            self._write_task(db, task, 'revising' if superseded else 'aborted')
        return {**item, 'status': status, 'version': item['version'] + 1}

    def finish(self, task_id, status, calls=0, owner=None):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            task = self._task(db, task_id)
            task['used_calls'] += max(0, int(calls or 0))
            if owner:
                self._move_owner(db, task, owner)
            self._write_task(db, task, status)
            db.execute("UPDATE chat_resume_jobs SET status='done',updated=? WHERE task_id=? AND status='dispatching'", (self.clock(), task_id))

    def jobs(self):
        with self.store.connect() as db:
            return [dict(id=r[0], task_id=r[1], clarification_id=r[2], status=r[3], **json.loads(r[4])) for r in db.execute("SELECT id,task_id,clarification_id,status,data FROM chat_resume_jobs WHERE status IN ('queued','dispatching') ORDER BY updated")]

    def claim(self, job_id):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT task_id FROM chat_resume_jobs WHERE id=? AND status='queued'", (job_id,)).fetchone()
            if not row:
                return False
            task = self._task(db, row[0])
            if task['status'] != 'resume_queued':
                return False
            self._write_task(db, task, 'running')
            db.execute("UPDATE chat_resume_jobs SET status='dispatching',updated=? WHERE id=?", (self.clock(), job_id))
            return True

    def defer(self, job_id, reason, uncertain=False):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT task_id,data FROM chat_resume_jobs WHERE id=?', (job_id,)).fetchone()
            if not row:
                return
            data = json.loads(row[1]); data['reason'] = reason
            db.execute('UPDATE chat_resume_jobs SET status=?,data=?,updated=? WHERE id=?', ('reconciling' if uncertain else 'queued', encode(data), self.clock(), job_id))
            self._write_task(db, self._task(db, row[0]), 'reconciling' if uncertain else 'resume_queued')

    def operation(self, task_id, name, args, versions, paid=False):
        signature = encode(dict(task_id=task_id, tool=name, args=args, versions=versions))
        identifier = hashlib.sha256(signature.encode()).hexdigest()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT status,data FROM chat_operations WHERE id=?', (identifier,)).fetchone()
            if row:
                return identifier, row[0], json.loads(row[1])
            task = self._task(db, task_id)
            if paid:
                used = sum(bool(json.loads(r[0]).get('paid')) for r in db.execute('SELECT data FROM chat_operations WHERE task_id=?',(task_id,)))
                if used >= task.get('paid_allowance',0):
                    return identifier, 'needs_consent', {}
            db.execute('INSERT INTO chat_operations VALUES (?,?,?, ?,?)', (identifier, task_id, 'reserved', encode(dict(tool=name, args=args, versions=versions, paid=paid, owner=task['owner'])), self.clock()))
            return identifier, 'new', {}

    def guard_manual(self, *, owner=None, project=None, workspace=None):
        with self.store.connect() as db:
            rows = db.execute("SELECT id,owner,status,version,data FROM chat_tasks WHERE status IN ('awaiting_input','resume_queued','reconciling')").fetchall()
        for row in rows:
            task = self._row(row)
            context = task['context']
            if (owner and task['owner'] == owner or project and (context.get('canvas_turn') or {}).get('project_id') == project
                    or workspace and (context.get('studio_context') or {}).get('workspace') == workspace):
                raise ClarificationConflict('此任务正在等待补充或核对，请先回答、修改需求或取消；未提交新的修改或收费请求')

    def operation_result(self, identifier, status, result=None):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT data FROM chat_operations WHERE id=?', (identifier,)).fetchone()
            data = json.loads(row[0]); data['result'] = result
            db.execute('UPDATE chat_operations SET status=?,data=?,updated=? WHERE id=?', (status, encode(data), self.clock(), identifier))

    def recover(self, read_history):
        """Startup audit: never infer a side effect succeeded from a lost worker."""
        with self.store.connect() as db:
            db.execute("UPDATE chat_operations SET status='unknown' WHERE status IN ('reserved','running')")
            active = db.execute("SELECT id FROM chat_tasks WHERE status IN ('running','awaiting_input','resume_queued')").fetchall()
        for (identifier,) in active:
            task = self.task(identifier)
            try:
                history = read_history(task['owner'])
            except Exception:
                self.finish(identifier, 'reconciling'); continue
            request_id = task.get('active_clarification')
            with self.store.connect() as db:
                row = db.execute('SELECT status,data FROM chat_clarifications WHERE id=?', (request_id,)).fetchone()
            if row and row[0] == 'prepared':
                data = json.loads(row[1])
                paired = not data.get('tool_call_id') or any(m.get('role') == 'tool' and m.get('tool_call_id') == data['tool_call_id'] for m in history)
                closed = any((m.get('display_metadata') or {}).get('clarification_id') == request_id and m.get('role') == 'assistant' for m in history)
                if paired and closed:
                    self.seal(identifier, task['owner'], len(history))
                else:
                    self.finish(identifier, 'reconciling')
            elif task['status'] == 'running':
                jobs = [j for j in self.jobs() if j['task_id'] == identifier]
                if jobs:
                    j = jobs[0]
                    accepted = any((m.get('display_metadata') or {}).get('resume_job_id') == j['id'] for m in history)
                    self.defer(j['id'], '服务重启，请核对已接受的运行片段' if accepted else '尚未追加回答', uncertain=accepted)
                else:
                    self.finish(identifier, 'reconciling')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE'); self._expire(db)
