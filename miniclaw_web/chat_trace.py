"""Local, bounded execution records. Observation never schedules an Agent action."""
from functools import wraps
import json
import logging
import math
import re
import sqlite3
import threading
import time
import uuid

logger = logging.getLogger(__name__)
REDACTED = '[已脱敏]'
_SECRET_KEY = re.compile(r'(?:^(?:token|key|signature|sig)$|api[_-]?key|authorization|cookie|password|passwd|secret|credential|access[_-]?token|refresh[_-]?token|security[_-]?token)', re.I)
_SECRET_TEXT = re.compile(r'(?i)(bearer\s+)[^\s"\']+|\bsk-[A-Za-z0-9_-]{12,}|((?:\b[A-Z0-9_]{0,64}(?:API_KEY|PASSWORD|SECRET|ACCESS_TOKEN|REFRESH_TOKEN|TOKEN|KEY|SIGNATURE|COOKIE|AUTHORIZATION))\s*[=:]\s*["\']?)[^\s,;，；&#"\']+')
_JSON_SECRET = re.compile(r'(?i)(["\'](?:[^"\']{0,120}(?:api[_-]?key|authorization|cookie|password|passwd|secret|credential|access[_-]?token|refresh[_-]?token|security[_-]?token)|token|key|signature|sig)["\']\s*:\s*["\'])[^"\']*(["\'])')
_QUERY_SECRET = re.compile(r'(?i)([?&](?:api[_-]?key|key|token|access_token|password|secret|signature|sig|x-amz-signature|x-amz-credential|x-amz-security-token|x-goog-signature|x-goog-credential)=)[^&#\s"\']*')


def scrub(value, secrets=(), depth=0, budget=None):
    """Redact before writing; bound work across the whole tree, not only each branch."""
    budget = budget if budget is not None else {'chars': 60000, 'nodes': 1200, 'truncated': False}
    budget['nodes'] -= 1
    if depth > 9 or budget['nodes'] < 0 or budget['chars'] <= 0:
        budget['truncated'] = True
        return '[内容已截断]'
    if isinstance(value, str):
        if len(value) <= 120000 and value.lstrip().startswith(('{', '[')):
            try:
                parsed = json.loads(value)
            except (ValueError, RecursionError):
                parsed = None
            if isinstance(parsed, (dict, list)):
                return json.dumps(scrub(parsed, secrets, depth + 1, budget), ensure_ascii=False)
        original_length = len(value)
        cap = min(16000, budget['chars'])
        value = value[:cap]
        for secret in secrets:
            if secret and len(secret) >= 3:
                value = value.replace(secret, REDACTED)
        value = _SECRET_TEXT.sub(lambda m: (m.group(1) or m.group(2) or '') + REDACTED, value)
        value = _JSON_SECRET.sub(lambda m: m.group(1) + REDACTED + m.group(2), value)
        value = _QUERY_SECRET.sub(lambda m: m.group(1) + REDACTED, value)
        value = re.sub(r'data:[^;\s]+;base64,[A-Za-z0-9+/=]+', '[二进制内容省略]', value)
        budget['chars'] -= len(value)
        if original_length > cap:
            budget['truncated'] = True
            value += '\n[内容已截断]'
        return value
    if isinstance(value, dict):
        out = {}
        for index, (k, v) in enumerate(value.items()):
            if index >= 80 or budget['nodes'] <= 0 or budget['chars'] <= 0:
                budget['truncated'] = True
                out['_truncated_items'] = len(value) - index
                break
            key = str(k)[:120]
            budget['chars'] -= len(key)
            out[key] = REDACTED if _SECRET_KEY.search(key) else scrub(v, secrets, depth + 1, budget)
        return out
    if isinstance(value, (list, tuple)):
        out = []
        for index, v in enumerate(value):
            if index >= 80 or budget['nodes'] <= 0 or budget['chars'] <= 0:
                budget['truncated'] = True
                out.append({'truncated_items': len(value) - index})
                break
            out.append(scrub(v, secrets, depth + 1, budget))
        return out
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, 'model_dump'):
        return scrub(value.model_dump(mode='json'), secrets, depth + 1, budget)
    return scrub(str(value), secrets, depth + 1, budget)


def observation(method):
    """A full or unavailable trace store must not turn a successful write into a retry."""
    @wraps(method)
    def observed(self, *args, **kwargs):
        if self.disabled:
            return None
        try:
            return method(self, *args, **kwargs)
        except Exception as error:
            self.disabled = True
            logger.warning('Local Chat trace unavailable (%s); Agent execution continues.', type(error).__name__)
            return None
    return observed


class TraceStore:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS chat_trace_steps (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
                    owner TEXT NOT NULL, task_id TEXT NOT NULL, kind TEXT NOT NULL,
                    status TEXT NOT NULL, started_at REAL NOT NULL, ended_at REAL,
                    updated REAL NOT NULL, data TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS trace_owner_sequence ON chat_trace_steps(owner, sequence);
                CREATE INDEX IF NOT EXISTS trace_task_sequence ON chat_trace_steps(task_id, sequence);
            """)

    def recover(self):
        # Startup is the only place that reconciles a process which died before settlement.
        with self.store.connect() as db:
            rows = db.execute("SELECT id,data FROM chat_trace_steps WHERE status='running'").fetchall()
            for identifier, raw in rows:
                data = json.loads(raw)
                data.update(status='unknown', ended_at=None, duration_ms=None,
                            error='服务重启前未收到最终回执，请核对任务结果。')
                data['attributes']['reason'] = 'process_restart'
                db.execute("UPDATE chat_trace_steps SET status='unknown',updated=?,data=? WHERE id=?",
                           (time.time(), json.dumps(data, ensure_ascii=False), identifier))

    def page(self, owners, limit=500, before=None):
        placeholders = ','.join('?' for _ in owners)
        where = f'owner IN ({placeholders})'
        args = list(owners)
        if before is not None:
            where += ' AND sequence < ?'
            args.append(before)
        with self.store.connect() as db:
            rows = db.execute(f'SELECT sequence,data,updated FROM chat_trace_steps WHERE {where} ORDER BY sequence DESC LIMIT ?',
                              (*args, limit + 1)).fetchall()
            revision = db.execute(f'SELECT MAX(updated) FROM chat_trace_steps WHERE owner IN ({placeholders})', owners).fetchone()[0]
        has_more = len(rows) > limit
        rows = rows[:limit]
        steps = [dict(json.loads(raw), sequence=sequence, updated_at=updated) for sequence, raw, updated in reversed(rows)]
        return dict(steps=steps, has_more=has_more,
                    next_before=rows[-1][0] if has_more and rows else None, revision=revision)


class ChatTrace:
    def __init__(self, trace_store, task, agent, resume_job=None, start=True):
        self.store, self.agent = trace_store.store, agent
        self.task_id, self.owner = task['id'], task['owner']
        self.disabled = False
        self.lock = threading.RLock()
        self.active_model = None
        self.last_model = None
        self.attempts = {}
        self.model_index = 0
        self.current_turn_id = None
        self.tool_index = 0
        self.started = {}
        self.assistants = []
        self.context_spans = []
        self.history_floor = 0
        self.public_users = {}
        self.public_input = task['text']
        if resume_job:
            self.public_input = self._public_task_input(task['id'], resume_job) or self.public_input
        self.closed = False
        from agent.secret_scope import current_secret_scope
        scope = current_secret_scope() or {}
        self.secrets = tuple(str(v) for k, v in scope.items() if _SECRET_KEY.search(k) and v)
        self.attributes = {'resume_job_id': resume_job} if resume_job else {}
        self.capture_history_floor()
        self.task_span = self.begin('task', '任务继续' if resume_job else '任务执行',
                                    attributes=self.attributes) if start else None
        self.input_span = self.event('input', '继续任务' if resume_job else '用户输入',
                                    content=self.public_input, input=self.public_input, attributes=self.attributes) if start else None

    def _public_task_input(self, task_id, resume_job=None):
        with self.store.connect() as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('chat_tasks','chat_resume_jobs','chat_clarifications')")}
            if 'chat_tasks' not in tables:
                return None
            if resume_job and {'chat_resume_jobs', 'chat_clarifications'} <= tables:
                row = db.execute('SELECT c.data FROM chat_resume_jobs j JOIN chat_clarifications c ON c.id=j.clarification_id WHERE j.id=? AND j.task_id=?',
                                 (resume_job, task_id)).fetchone()
                if row:
                    item = json.loads(row[0])
                    return '\n'.join(q['question'] + '：' + (', '.join(item['answers'][q['id']]) if isinstance(item['answers'][q['id']], list) else item['answers'][q['id']])
                                     for q in item['questions'])
            row = db.execute('SELECT data FROM chat_tasks WHERE id=?', (task_id,)).fetchone()
            return json.loads(row[0])['text'] if row else None

    @staticmethod
    def _public_text_key(content):
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            return '\n'.join(part.get('text', '') for part in content if isinstance(part, dict) and part.get('type') == 'text').strip()
        return None

    @observation
    def capture_public_messages(self, messages):
        users = [m for m in messages if isinstance(m, dict) and m.get('role') == 'user']
        for index, message in enumerate(users):
            public = self.public_input if index == len(users) - 1 else None
            if public is None:
                row_id = message.get('_row_id') or message.get('id')
                with self.store.connect() as db:
                    sidecar = db.execute('SELECT data FROM turns WHERE row_id=?', (row_id,)).fetchone() if isinstance(row_id, int) else None
                if sidecar:
                    public = json.loads(sidecar[0]).get('text')
                elif (message.get('display_metadata') or {}).get('task_id'):
                    metadata = message['display_metadata']
                    public = self._public_task_input(metadata['task_id'], metadata.get('resume_job_id'))
            if public is None:
                continue
            for content in (message.get('content'), message.get('api_content')):
                key = self._public_text_key(content)
                if key is not None:
                    self.public_users[key] = public

    @staticmethod
    def public_tool_result(value):
        is_text = isinstance(value, str)
        try:
            parsed = json.loads(value) if is_text else value
        except (ValueError, TypeError):
            return value
        if isinstance(parsed, dict) and parsed.get('status') == 'awaiting_input' and parsed.get('task_id') and parsed.get('clarification_id'):
            if parsed.get('instructions') == 'No answer has been supplied. Resume only after a real user answer.':
                parsed = {key: item for key, item in parsed.items() if key != 'instructions'}
                return json.dumps(parsed, ensure_ascii=False) if is_text else parsed
        return value

    @observation
    def application_context(self, text, source='application'):
        """Only explicitly supplied app-authored additions, never whole SDK prompts."""
        if isinstance(text, str) and text.strip():
            identifier = self.event('context', '任务恢复上下文' if source == 'resume' else '本轮应用上下文',
                                    content=text.strip(), attributes={'context_source': source})
            self.context_spans.append(identifier)
            return identifier

    def _safe(self, value):
        secrets = self.secrets + (str(getattr(self.agent, 'api_key', '') or ''),)
        bodies = ('input', 'output', 'content')
        data = {}
        truncated = False
        # Evidence fields get independent budgets, so a large body cannot consume its
        # operation id, error, usage or final state during a later update.
        for key, item in value.items():
            if key in bodies or key == 'attributes':
                continue
            budget = {'chars': 4000 if key == 'error' else 2000 if key == 'summary' else 512,
                      'nodes': 100, 'truncated': False}
            data[key] = scrub(item, secrets, budget=budget)
            truncated |= budget['truncated']
        attributes = value.get('attributes', {})
        priority = ('budget', 'usage', 'call_id', 'message_id', 'model_step_id', 'error_type',
                    'status_code', 'reason', 'action', 'executed', 'effect_state', 'blocked',
                    'call_role', 'first_chunk_at', 'response_model', 'resume_job_id',
                    'next_attempt', 'delay_seconds', 'completed', 'partial', 'truncated')
        ordered = {key: attributes[key] for key in priority if key in attributes}
        ordered.update({key: item for key, item in attributes.items() if key not in ordered})
        budget = {'chars': 12000, 'nodes': 400, 'truncated': False}
        data['attributes'] = scrub(ordered, secrets, budget=budget)
        truncated |= budget['truncated']
        for key in bodies:
            if key in value:
                budget = {'chars': 14000, 'nodes': 400, 'truncated': False}
                data[key] = scrub(value[key], secrets, budget=budget)
                truncated |= budget['truncated']
        if truncated:
            data['attributes']['truncated'] = True
        if len(json.dumps(data, ensure_ascii=False).encode('utf-8')) > 120000:
            for key in bodies:
                if key in data:
                    data[key] = {'truncated': True, 'preview': str(data[key])[:1200]} if key in ('input', 'output') else str(data[key])[:1200]
            data['attributes']['truncated'] = True
        return data

    @observation
    def begin(self, kind, name, **fields):
        identifier = uuid.uuid4().hex
        now = time.time()
        fields.setdefault('turn_id', self.current_turn_id)
        data = self._safe(dict(id=identifier, task_id=self.task_id, session_id=self.owner,
                              kind=kind, name=name, status='running', started_at=now,
                              ended_at=None, duration_ms=None, source='trace',
                              attributes={**self.attributes, **fields.pop('attributes', {})}, **fields))
        with self.lock, self.store.connect() as db:
            db.execute('INSERT INTO chat_trace_steps(id,owner,task_id,kind,status,started_at,updated,data) VALUES (?,?,?,?,?,?,?,?)',
                       (identifier, self.owner, self.task_id, kind, 'running', now, now, json.dumps(data, ensure_ascii=False)))
            self.started[identifier] = time.monotonic()
        return identifier

    @observation
    def update(self, identifier, **fields):
        if not identifier:
            return
        with self.lock, self.store.connect() as db:
            raw = db.execute('SELECT data FROM chat_trace_steps WHERE id=?', (identifier,)).fetchone()
            if raw is None:
                return
            data = json.loads(raw[0])
            attributes = fields.pop('attributes', {})
            data.update(fields)
            data['attributes'].update(attributes)
            data = self._safe(data)
            db.execute('UPDATE chat_trace_steps SET status=?,ended_at=?,updated=?,data=? WHERE id=?',
                       (data['status'], data.get('ended_at'), time.time(), json.dumps(data, ensure_ascii=False), identifier))

    def end(self, identifier, status='completed', **fields):
        with self.lock:
            started = self.started.pop(identifier, None)
        duration = max(0, (time.monotonic() - started) * 1000) if started is not None else None
        self.update(identifier, status=status, ended_at=time.time(), duration_ms=duration, **fields)

    def event(self, kind, name, status='completed', **fields):
        identifier = self.begin(kind, name, **fields)
        # An instantaneous observation has no measured execution duration.
        self.started.pop(identifier, None)
        self.update(identifier, status=status, ended_at=time.time(), duration_ms=None)
        return identifier

    @observation
    def capture_history_floor(self):
        db = getattr(self.agent, '_session_db', None)
        if db:
            rows = db.get_messages(str(getattr(self.agent, 'session_id', None) or self.owner), limit=1, latest=True)
            self.history_floor = rows[-1]['id'] if rows else 0

    def bind_input(self, row_id):
        self.history_floor = max(self.history_floor, row_id)
        self.update(self.input_span, attributes={'message_id': row_id})

    @observation
    def model_start(self, kwargs, request_id, budget):
        with self.lock:
            self.current_turn_id = request_id.rsplit(':api:', 1)[0] if ':api:' in str(request_id) else None
            for identifier in (self.input_span, self.task_span, *self.context_spans):
                self.update(identifier, turn_id=self.current_turn_id)
            attempt_key = (request_id, str(self.agent.provider), str(self.agent.model))
            self.attempts[attempt_key] = self.attempts.get(attempt_key, 0) + 1
            self.model_index += 1
            # Include public conversation data, never system/developer prompts or reasoning.
            messages = []
            for message in kwargs.get('messages', []):
                if message.get('role') not in ('user', 'assistant', 'tool'):
                    continue
                public = {k: v for k, v in message.items() if k in ('role', 'content', 'tool_calls', 'tool_call_id', 'name')}
                if public['role'] == 'user':
                    content_key = self._public_text_key(public.get('content'))
                    public['content'] = self.public_users.get(content_key, '[公开输入未记录；应用上下文已省略]')
                elif public['role'] == 'assistant' and isinstance(public.get('content'), str):
                    public['content'] = self.agent._strip_think_blocks(public['content'])
                elif public['role'] == 'tool':
                    public['content'] = self.public_tool_result(public.get('content'))
                messages.append(public)
            request = {'messages': messages[-24:], 'tools': [t.get('function', {}).get('name') for t in kwargs.get('tools', [])],
                       'parameters': {k: kwargs[k] for k in ('stream', 'max_tokens', 'max_completion_tokens', 'temperature') if k in kwargs}}
            self.active_model = self.begin('model', '模型请求', request_id=request_id,
                provider=str(self.agent.provider), model=str(self.agent.model), attempt=self.attempts[attempt_key],
                turn_id=self.current_turn_id,
                call_index=self.model_index, input=request, attributes={'budget': budget,
                'call_role': 'fallback' if int(getattr(self.agent, '_fallback_index', 0) or 0) else 'primary',
                'input_projection': 'public_conversation', 'internal_context_omitted': True})
            self.last_model = self.active_model

    @observation
    def model_done(self, response):
        with self.lock:
            identifier = self.active_model
            self.active_model = None
        if not identifier:
            return
        usage = self.agent._usage_summary_for_api_request_hook(response)
        choices = getattr(response, 'choices', None) or []
        message = getattr(choices[0], 'message', None) if choices else None
        content = getattr(message, 'content', None)
        if isinstance(content, str):
            content = self.agent._strip_think_blocks(content)
        calls = getattr(message, 'tool_calls', None) or []
        if message is None:
            # Other provider response formats remain inspectable without inventing text.
            output = {'response_id': getattr(response, 'id', None), 'model': getattr(response, 'model', None),
                      'stop_reason': getattr(response, 'stop_reason', None), 'usage': usage}
        else:
            output = {'content': content, 'tool_calls': self.agent._hook_jsonable(calls), 'usage': usage}
        first_chunk = getattr(self.agent, '_last_api_first_chunk_at', None)
        self.end(identifier, output=output, input_tokens=usage.get('prompt_tokens') if usage else None,
                 output_tokens=usage.get('output_tokens', usage.get('completion_tokens')) if usage else None,
                 attributes={'usage': usage, 'response_model': getattr(response, 'model', None), 'first_chunk_at': first_chunk})
        text = content if isinstance(content, str) else ''
        if text or calls:
            assistant = self.event('assistant', '助手回复' if text else '助手调用工具',
                content=text, summary=text[:160] if text else '、'.join(str(getattr(getattr(c, 'function', None), 'name', '工具')) for c in calls),
                output={'content': text, 'tool_calls': self.agent._hook_jsonable(calls)},
                request_id=getattr(self.agent, '_current_api_request_id', None), attributes={'model_step_id': identifier})
            self.assistants.append((assistant, text))

    def model_error(self, error):
        with self.lock:
            identifier = self.active_model
            self.active_model = None
        if not identifier:
            return
        interrupted = isinstance(error, InterruptedError) or getattr(self.agent, '_interrupt_requested', False)
        self.end(identifier, 'interrupted' if interrupted else 'failed', error=str(error),
                 attributes={'error_type': type(error).__name__, 'status_code': getattr(error, 'status_code', None)})

    def decision(self, action, reason=None, **details):
        names = {'retry': '准备重试', 'fallback': '切换备用模型', 'stop': '停止自动恢复',
                 'skip_fallback': '跳过备用服务', 'waiting': '等待用户补充信息', 'reuse': '复用操作回执', 'reconcile': '等待核对操作结果'}
        if self.last_model and reason and action in ('retry', 'fallback', 'stop') and not details.get('tool_name'):
            self.update(self.last_model, attributes={'reason': reason})
        return self.event('recovery', names.get(action, action), status='waiting' if action in ('waiting', 'reconcile') else 'completed',
                          summary=details.pop('summary', reason or ''),
                          attributes={'action': action, 'reason': reason, **details})

    def tool_start(self, name, args, call_id, attempt, operation_id=None):
        with self.lock:
            self.tool_index += 1
        return self.begin('tool', name, tool_name=name, input=args, attempt=attempt,
            operation_id=operation_id, call_index=self.tool_index,
            attributes={'call_id': call_id, 'executed': True})

    @observation
    def tool_end(self, identifier, result=None, error=None, operation_id=None):
        from .chat_recovery import unknown_effect
        if error is not None:
            self.end(identifier, 'unknown' if operation_id else 'failed', error=str(error),
                     attributes={'error_type': type(error).__name__, 'effect_state': 'unknown' if operation_id else None})
            return
        try:
            parsed = json.loads(result) if isinstance(result, str) else result
        except (ValueError, TypeError):
            parsed = result
        failed = isinstance(parsed, dict) and (parsed.get('error') or parsed.get('success') is False or parsed.get('state') in ('failed', 'canceled'))
        unknown = bool(operation_id and unknown_effect(parsed))
        self.end(identifier, 'unknown' if unknown else 'failed' if failed else 'completed',
                 output=self.public_tool_result(parsed), summary=str(self.public_tool_result(parsed))[:160], error=str(parsed.get('error')) if failed and parsed.get('error') else None,
                 attributes={'effect_state': 'unknown' if unknown else 'failed' if failed else 'succeeded' if operation_id else None})

    @observation
    def skipped_tool(self, name, args, call_id, result):
        try:
            parsed = json.loads(result) if isinstance(result, str) else result
        except (ValueError, TypeError):
            parsed = result
        waiting = isinstance(parsed, dict) and parsed.get('status') in ('awaiting_input', 'not_executed_awaiting_input')
        failed = isinstance(parsed, dict) and (parsed.get('error') or parsed.get('success') is False or parsed.get('state') == 'failed')
        blocked = isinstance(parsed, dict) and (parsed.get('status') == 'not_executed' or parsed.get('state') == 'canceled')
        unknown = isinstance(parsed, dict) and (parsed.get('outcome_uncertain') or parsed.get('effect_disposition') == 'unknown' or parsed.get('state') in ('unknown', 'timeout'))
        status = 'waiting' if waiting else 'unknown' if unknown else 'failed' if failed else 'interrupted' if blocked else 'completed'
        self.event('tool', name, status=status, tool_name=name,
                   input=args, output=self.public_tool_result(parsed), error=str(parsed.get('error')) if failed and parsed.get('error') else None,
                   attributes={'call_id': call_id, 'executed': False, 'blocked': blocked})

    @observation
    def finish(self, result, warning=None, budget=None):
        if self.closed:
            return
        self.closed = True
        result = result if isinstance(result, dict) else {}
        status = ('unknown' if warning else 'interrupted' if result.get('interrupted') else
                  'failed' if result.get('failed') or result.get('error') else 'waiting' if result.get('awaiting_input') else 'completed')
        if self.active_model:
            self.model_error(InterruptedError('任务已停止，模型请求未取得最终结果。'))
        partial = result.get('final_response') if result.get('partial') else None
        if partial and not any(text == partial for _, text in self.assistants):
            self.assistants.append((self.event('assistant', '部分回复', status=status, content=partial,
                                               attributes={'partial': True}), partial))
        self.end(self.task_span, status, summary=warning or result.get('error') or result.get('final_response', '')[:160],
                 error=warning or result.get('error'), attributes={'budget': budget, 'reason': result.get('failure_reason'),
                 'completed': bool(result.get('completed')), 'partial': bool(result.get('partial'))})
        db = getattr(self.agent, '_session_db', None)
        if db:
            messages = db.get_messages(str(getattr(self.agent, 'session_id', None) or self.owner), limit=250, latest=True)
            used = set()
            for identifier, text in reversed(self.assistants):
                matching = next((m for m in reversed(messages) if m.get('role') == 'assistant' and str(m.get('content') or '') == text and m['id'] > self.history_floor and m['id'] not in used), None)
                if matching:
                    used.add(matching['id'])
                    self.update(identifier, attributes={'message_id': matching['id']})
