"""Session-scoped RPC and a recoverable, single-process dispatch coordinator."""
import json
import os
import threading
from pydantic import Field

from .clarifications import Clarifications, ClarificationConflict, encode
from .chat_decisions import chat_policy
from .hermes_clarification_adapter import HermesClarificationAdapter, semantic_context

RULE_NOTE = '\n本轮澄清规则：普通讨论和文字草稿不需要执行参数；上传与画布引用默认是参考。仅在影响目标、范围、费用或不可恢复行为的关键缺口时调用clarify，一次最多3题，给出简短选项或开放问题。不要输出studio-question代替工具。已有用户确认继续有效，新的明确修改覆盖旧要求；不把建议、默认选项或模型置信度当成用户回答。保留已完成步骤与未受影响内容。不要把工具pending当成用户已回答。'


class ClarificationCoordinator:
    def __init__(self, store, server, studio, canvas):
        self.store, self.server, self.studio, self.canvas = store, server, studio, canvas
        self.service = Clarifications(store, timeout=os.environ.get('MINICLAW_CLARIFICATION_TIMEOUT', '3600'))
        from .chat_trace import TraceStore
        self.traces = TraceStore(store)
        self.traces.recover()
        self.policy = chat_policy(studio.decisions)
        self.dispatch_lock = threading.RLock()
        self.wake = threading.Event()
        self.closed = threading.Event()

    def history(self, owner):
        from hermes_state import SessionDB
        with SessionDB(db_path=self.store.home / 'state.db', read_only=True) as db:
            return db.get_messages(owner)

    def owners(self, session):
        from hermes_state import SessionDB
        owner = session['session_key']
        with SessionDB(db_path=self.store.home / 'state.db', read_only=True) as db:
            return list(dict.fromkeys([owner] + db.get_compression_lineage(owner)))

    def versions(self, context):
        value = {}
        if context.get('studio_context'):
            ctx = context['studio_context']
            record = self.studio.workspaces.get(ctx['workspace'])
            targets = list(dict.fromkeys([ctx.get('target')] + (ctx.get('references') or [])))
            with self.store.connect() as db:
                manifest = [dict(target=t, kind=k, version_id=v) for t,k,v in db.execute('SELECT i.target,i.kind,h.revision_id FROM media_items i JOIN media_heads h ON h.item_id=i.id WHERE i.scope=? ORDER BY i.target,i.kind', (ctx['workspace'],))]
            value['studio'] = [m for m in manifest if not any(targets) or m['target'] in targets]
            objects = record['state']['assets'] + record['state']['shots'] + record['state']['notes']
            value['targets'] = [o['id'] for o in objects if o['id'] in targets]
            if ctx.get('target') and ctx['target'] not in value['targets']:
                raise ClarificationConflict('原目标已删除，请修改需求并重新指定目标')
        if context.get('canvas_turn'):
            ctx = context['canvas_turn']
            record = self.canvas.get(ctx['project_id'])
            layer = next((l for l in record['document']['layers'] if l['id'] == ctx['layer_id']), None)
            if not layer:
                raise ClarificationConflict('原图层已删除，请修改需求并重新指定目标')
            value['canvas'] = layer
            value['selection'] = self.canvas.selection(ctx['project_id'])
        return value

    def validate(self, task, session):
        if task['owner'] not in self.owners(session):
            raise ClarificationConflict('原任务不属于当前会话')
        context = task['context']
        if self.versions(context) != context.get('current_versions', context.get('versions', {})):
            raise ClarificationConflict('原目标或素材已改变，回答已保存；请修改需求并重新确认当前目标')
        loaded = {d['function']['name'] for d in getattr(session.get('agent'), 'tools', [])}
        if set(context.get('required_tools', [])) - loaded:
            raise ClarificationConflict('原任务工具已停用，回答已保存；请恢复工具或修改需求')
        if task['used_calls'] >= task['max_calls']:
            raise ClarificationConflict('任务累计调用预算已用完，请取消后重新规划')
        with self.store.connect() as db:
            uncertain = db.execute("SELECT id FROM chat_operations WHERE task_id=? AND status IN ('reserved','running','unknown') LIMIT 1", (task['id'],)).fetchone()
        if uncertain:
            raise ClarificationConflict('有执行结果尚未核对，已保留回答；不会自动重复提交收费任务')

    def reconcile_operations(self):
        """Look up durable local submission IDs; never reissue a supplier request."""
        import hashlib
        with self.store.connect() as db:
            rows = db.execute("SELECT id,task_id,data FROM chat_operations WHERE status='unknown'").fetchall()
        for identifier, task_id, raw in rows:
            operation = json.loads(raw)
            task = self.service.task(task_id)
            owner = operation.get('owner', task['owner'])
            tool = operation['tool']
            request_id = identifier[:64]
            result = None
            if tool == 'miniclaw_edit_image':
                job_id = hashlib.sha256((owner + ':' + request_id).encode()).hexdigest()[:32]
                try:
                    job = self.store.get('image_jobs', job_id, owner)
                    from .images import _service
                    result = _service.public(job) if _service else None
                except ValueError:
                    pass
            elif tool == 'miniclaw_canvas_ai':
                project = (task['context'].get('canvas_turn') or {}).get('project_id')
                if project:
                    job_id = hashlib.sha256((project + ':' + request_id).encode()).hexdigest()[:32]
                    try: result = self.canvas.job(project, job_id)
                    except ValueError: pass
            if result is not None:
                # A found local job proves submission identity, including running,
                # failed and uncertain supplier jobs. Poll that job, never create anew.
                self.service.operation_result(identifier, 'succeeded', encode(dict(success=result.get('state') not in ('failed','canceled'), **result)))

    def refresh_versions(self, task):
        self.service.configure(task['id'], current_versions=self.versions(task['context']))

    def bind(self, session, task_id, resume_job=None):
        from hermes_cli.config import load_config
        from .chat_recovery import ChatRecovery, RecoveryPolicy
        recovery = ChatRecovery(self.store, task_id, session['agent'], RecoveryPolicy.from_config(load_config()))
        from .chat_trace import ChatTrace
        trace = ChatTrace(self.traces, self.service.task(task_id), session['agent'], resume_job)
        adapter = HermesClarificationAdapter(self.service, self.policy, session, task_id,
                                            self.validate, resume_job, self.refresh_versions, recovery=recovery, trace=trace)
        session['agent']._hosted_turn_adapter = adapter
        session['_hosted_prompt_metadata'] = adapter.metadata
        return adapter

    def begin(self, session, text, params, studio_data, attachments):
        context = {key: params[key] for key in ('studio_context','canvas_context','creator_context','director_context','skill') if params.get(key) is not None}
        context.update(attachments=[a['id'] for a in attachments],
                       canvas_turn=session.get('miniclaw_canvas_turn'), overlay_turn=session.get('miniclaw_overlay_turn'),
                       semantic=semantic_context(studio_data, params.get('canvas_context'), attachments),
                       draft_only=bool(params.get('director_context') or (session.get('miniclaw_canvas_turn') or {}).get('mode') in ('plan','context')))
        from .literal_image_target import bind_named_attachment
        named_context = bind_named_attachment(dict(text=text, context=context, confirmed={}))
        if named_context is not None:
            context = named_context
        context['versions'] = self.versions(context)
        context['semantic']['selection'] = bool(context['versions'].get('selection'))
        import hashlib
        context['semantic']['versions'] = hashlib.sha256(encode(context['versions']).encode()).hexdigest()
        context['required_tools'] = []
        # Check all compression ancestors before allowing a second business task.
        active = [r for r in self.service.list(self.owners(session)) if r['status'] == 'pending']
        if active:
            raise ClarificationConflict('还有待回答的问题。请回答，或选择修改需求／取消后发送新话题')
        task = self.service.start(session['session_key'], text, context, owners=self.owners(session))
        self.bind(session, task['id'])
        return task

    def control(self, session, text, attachments=()):
        """Serialize human task controls with resume dispatch, before preparing media."""
        if not callable(getattr(session.get('agent'), 'run_conversation', None)):
            return None
        with self.dispatch_lock:
            if session.get('running'):
                raise ClarificationConflict('本轮仍在执行，请先停止后再修改任务')
            requests = self.service.list(self.owners(session))
            active = next((r for r in requests if r.get('task_status') in ('awaiting_input', 'resume_queued', 'reconciling')), None)
            if active is None:
                return None
            command = self.policy.relation(text)
            if command is None:
                return dict(action='clarify', status='awaiting_input', no_model=True,
                            message='这是回答当前问题，还是修改需求／换话题？请在问题卡中回答，或输入“修改需求：新要求”“换个话题：新问题”“取消当前任务”。')
            if attachments:
                raise ClarificationConflict('请先只发送文字来修改或取消待答任务，附件草稿已保留；修改需求后可以补充附件')
            action = command['action']
            item = self.service.cancel(self.owners(session), active['id'], superseded=action == 'revise')
            self.clarification_event(session, item, 'revise' if action == 'revise' else 'cancel')
            self.notify(session)
            message = ('原任务已取消，已完成的结果仍保留。' if action == 'cancel' else
                       '原任务已结束，可以开始新话题。' if action == 'new_topic' else
                       '已进入修改需求状态，请输入新的要求；已完成结果与累计预算仍保留。')
            return dict(action=action, status='completed', message=message,
                        no_model=action == 'cancel' or not command['text'], task_id=item['task_id'], text=command['text'])

    def revision_params(self, control):
        """Rehydrate owned references when a text control revises the existing task."""
        context = self.service.task(control['task_id'])['context']
        params = {key: context[key] for key in ('studio_context', 'creator_context', 'director_context') if context.get(key) is not None}
        if params.get('studio_context'):
            ctx = dict(params['studio_context'])
            ctx['revision'] = self.studio.workspaces.get(ctx['workspace'])['revision']
            params['studio_context'] = ctx
        canvas = context.get('canvas_turn') or context.get('canvas_context')
        if canvas:
            params['canvas_context'] = {k: canvas[k] for k in ('project_id', 'revision', 'layer_id', 'mode') if k in canvas}
            params['canvas_context']['revision'] = self.canvas.get(canvas['project_id'])['revision']
        params['attachments'] = list(context.get('attachments', []))
        return params

    def pending_revision(self, session):
        if not callable(getattr(session.get('agent'), 'run_conversation', None)):
            return None
        return next((item for item in self.service.list(self.owners(session))
                     if item.get('task_status') == 'revising'), None)

    def record_control(self, session, text, control):
        """Append a real human command and its deterministic receipt to native history."""
        if self.server._ensure_session_db_row(session) is False:
            raise OSError('控制已生效，但会话存储不可用')
        messages = [dict(role='user', content=text, display_metadata=dict(task_id=control['task_id'], task_control=control['action'])),
                    dict(role='assistant', content=control['message'])]
        with session.setdefault('history_lock', threading.RLock()):
            with self.server._session_db(session) as db:
                if db is None:
                    raise OSError('控制已生效，但会话存储不可用')
                db.append_messages_batch(session['session_key'], messages)
                rows = db.get_messages(session['session_key'], limit=2, latest=True)
            for message, row in zip(messages, rows):
                message['_row_id'] = row['id']
            from agent.transcript_repair import sync_flushed_message_markers
            sync_flushed_message_markers(messages, rows)
            history = list(session.get('history') or []) + messages
            session['history'] = history
            session['history_version'] = int(session.get('history_version', 0)) + 1
            session['agent']._session_messages = history
            if hasattr(session['agent'], '_last_flushed_db_idx'):
                session['agent']._last_flushed_db_idx = len(history)
            return messages[0]['_row_id']

    def clarification_event(self, session, item, action):
        from .chat_trace import ChatTrace
        trace = ChatTrace(self.traces, self.service.task(item['task_id']), session.get('agent'), start=False)
        trace.event('input' if action == 'answer' else 'task',
                    '用户补充信息' if action == 'answer' else '用户修改需求' if action == 'revise' else '用户取消任务',
                    status='completed' if action == 'answer' else 'interrupted',
                    input=item.get('answers') if action == 'answer' else None,
                    attributes={'action': action, 'clarification_id': item['id']})

    def notify(self, session):
        sid = next((key for key, value in self.server._sessions.items() if value is session), None)
        if sid:
            self.server._emit('status.update', sid, dict(kind='clarification', text='澄清状态已更新'))

    def dispatch(self):
        if not self.dispatch_lock.acquire(blocking=False):
            return
        try:
            for job in self.service.jobs():
                if job['status'] != 'queued':
                    continue
                task = self.service.task(job['task_id'])
                session = next((s for s in tuple(self.server._sessions.values()) if s.get('session_key') == task['owner']), None)
                if session is None:
                    response = self.server._methods['session.resume'](None, dict(session_id=task['owner'], source='desktop', eager_build=True))
                    if response.get('error'):
                        self.service.defer(job['id'], '原会话暂时无法恢复', uncertain=True); continue
                    sid = response['result']['session_id']
                    session, error = self.server._sess(dict(session_id=sid), None)
                    if error:
                        self.service.defer(job['id'], '原会话暂时无法恢复', uncertain=True); continue
                else:
                    sid = next(key for key, value in self.server._sessions.items() if value is session)
                if session.get('running'):
                    continue
                try:
                    self.validate(task, session)
                except ValueError as error:
                    self.service.defer(job['id'], str(error), uncertain=True); self.notify(session); continue
                if not self.service.claim(job['id']):
                    continue
                request = self.service.request(job['clarification_id'])
                answers = '\n'.join(q['question'] + '：' + (', '.join(request['answers'][q['id']]) if isinstance(request['answers'][q['id']], list) else request['answers'][q['id']]) for q in request['questions'])
                resume_note = '继续原业务任务，复用已完成结果，仅执行尚未完成的步骤。不要重放原指令或重复收费调用。'
                text = '用户对待澄清问题的真实回答：\n' + answers + '\n' + resume_note
                # Rehydrate only trusted turn context. Persisted chat history already
                # contains the original task, tool receipts and image references.
                session['miniclaw_canvas_turn'] = task['context'].get('canvas_turn')
                if session['miniclaw_canvas_turn']:
                    session['miniclaw_canvas_turn'] = {**session['miniclaw_canvas_turn'], 'revision': self.canvas.get(session['miniclaw_canvas_turn']['project_id'])['revision']}
                session['miniclaw_overlay_turn'] = task['context'].get('overlay_turn') or {}
                self.bind(session, task['id'], job['id'])
                session['agent']._hosted_turn_adapter.trace.application_context(
                    resume_note, 'resume')
                try:
                    result = self.server._methods['prompt.submit'](None, dict(session_id=sid, text=text, title_preview=answers[:1000]))
                    if result.get('error'):
                        self.service.defer(job['id'], '恢复提交未接受', uncertain=True)
                    else:
                        row_id = result.get('result', {}).get('user_row_id')
                        if row_id is not None:
                            self.store.put('turns', row_id, dict(text=answers, attachments=[], task_id=task['id'], clarification_id=request['id']), session['session_key'])
                except Exception:
                    self.service.defer(job['id'], '恢复提交状态待核对', uncertain=True)
                self.notify(session)
        finally:
            self.dispatch_lock.release()

    def run(self):
        self.service.recover(self.history)
        self.reconcile_operations()
        while not self.closed.is_set():
            try:
                self.dispatch()
            except Exception:
                self.server.logger.exception('Clarification resume worker could not finish its audit')
                # A claimed dispatch is ambiguous. No automatic second submit.
                for job in self.service.jobs():
                    if job['status'] == 'dispatching':
                        self.service.defer(job['id'], '恢复状态需要核对，回答已保存', uncertain=True)
            self.wake.wait(2); self.wake.clear()


def install_rpc(coordinator):
    from tui_gateway.contracts import registry
    from tui_gateway.contracts.base import Params, Result
    server = coordinator.server

    class SessionParams(Params):
        session_id: str

    class AnswerParams(SessionParams):
        clarification_id: str
        expected_version: int
        answers: dict
        client_submission_id: str = Field(min_length=1, max_length=100)

    class CancelParams(SessionParams):
        clarification_id: str

    class ListResult(Result):
        requests: list[dict]

    class ChangeResult(Result):
        request: dict

    def scoped(rid, params, action):
        session, error = server._sess_nowait(params, rid)
        if error:
            return error
        try:
            return server._ok(rid, action(session))
        except ValueError as error:
            return server._err(rid, 4209, str(error))

    def list_requests(rid, params):
        return scoped(rid, params, lambda s: dict(requests=coordinator.service.list(coordinator.owners(s))))

    def answer(rid, params):
        def action(session):
            if session.get('running'):
                raise ClarificationConflict('本轮尚未完全结束，请稍后提交回答')
            item = coordinator.service.answer(coordinator.owners(session), params['clarification_id'], params['expected_version'], params['answers'], params['client_submission_id'])
            coordinator.clarification_event(session, item, 'answer')
            coordinator.wake.set(); coordinator.notify(session)
            return dict(request=item)
        return scoped(rid, params, action)

    def cancel(rid, params, superseded=False):
        def action(session):
            item = coordinator.service.cancel(coordinator.owners(session), params['clarification_id'], superseded)
            coordinator.clarification_event(session, item, 'revise' if superseded else 'cancel')
            coordinator.notify(session)
            return dict(request=item)
        return scoped(rid, params, action)

    for name, model, result, handler in (
        ('miniclaw.clarification.list', SessionParams, ListResult, list_requests),
        ('miniclaw.clarification.answer', AnswerParams, ChangeResult, answer),
        ('miniclaw.clarification.cancel', CancelParams, ChangeResult, cancel),
        ('miniclaw.task.revise', CancelParams, ChangeResult, lambda rid, p: cancel(rid, p, True)),
    ):
        registry.method(name, params=model, result=result, doc='Durable, session-owned task clarification.')
        server.register_method(name, handler)
