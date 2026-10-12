"""Host-owned recovery policy. Hermes remains the only model/tool execution loop."""
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
import random
import threading
import time

import httpx


@dataclass(frozen=True)
class RecoveryPolicy:
    model_attempts: int = 3             # initial request + two retries, per provider/step
    tool_attempts: int = 2              # explicitly read-only tools only
    max_model_requests: int = 24        # cumulative across fallback and clarification resumes
    max_recovery_attempts: int = 6      # model + read-only tool retries together
    max_reserved_tokens: int = 240_000  # conservative text-byte reservation, NOT a bill
    max_output_tokens: int = 4096
    request_timeout_seconds: float = 60
    task_timeout_seconds: float = 180  # cumulative active time; user-answer wait excluded
    backoff_seconds: float = 1
    max_backoff_seconds: float = 15

    @classmethod
    def from_config(cls, config):
        raw = config.get('miniclaw', {}).get('chat_recovery', {})
        if not isinstance(raw, dict):
            raise ValueError('miniclaw.chat_recovery 必须是配置对象')
        unknown = set(raw) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError('未知 Chat 恢复配置项：' + ', '.join(sorted(unknown)))
        value = cls(**raw)
        for f in fields(cls):
            number = getattr(value, f.name)
            default = getattr(cls(), f.name)
            lower = 0 if f.name == 'max_recovery_attempts' else 1e-12
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or number < lower:
                raise ValueError(f'Chat 恢复配置 {f.name} 必须是正数')
            if isinstance(default, int) and not isinstance(number, int):
                raise ValueError(f'Chat 恢复配置 {f.name} 必须是整数')
        return value


class RecoveryStopped(RuntimeError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


COPY = {
    'billing': '模型账户额度或余额不足，备用服务也未能继续。请检查额度后再继续。',
    'auth': '模型服务鉴权失败。请检查对应服务的 Key、地域和权限。',
    'auth_permanent': '模型服务鉴权失败。请检查对应服务的 Key、地域和权限。',
    'format_error': '模型请求参数不被服务接受。请调整模型配置或输入后再继续。',
    'content_policy_blocked': '模型服务拒绝了这次请求。请调整输入后再继续。',
    'context_overflow': '对话超出模型上下文容量。请压缩对话或减少附件后再继续。',
    'model_not_found': '配置的模型不可用。请检查模型名称和服务权限。',
    'request_budget': '本任务已达到模型请求次数上限，已停止继续调用。',
    'retry_budget': '本任务已达到自动恢复次数上限，已停止重试。',
    'token_budget': '本任务已达到 Token 预留预算，已停止新增调用。',
    'task_timeout': '本任务已达到执行时间上限，已停止等待和新增调用。',
    'iteration_budget': '本任务已达到工具处理轮数上限，已停止新增调用。请缩小任务范围后继续。',
    'stream_interrupted': '回复传输中断，已保留收到的部分文字并停止自动重发。请核对后再继续。',
    'rate_limit': '模型服务持续限流，有限重试和可用备用服务已耗尽。请稍后继续。',
    'timeout': '模型服务响应超时，有限重试和可用备用服务已耗尽。请稍后继续。',
}
PRESERVED = '已收到的回复和已完成的操作会保留；收费或写入操作如结果未知，请先核对任务记录。'
TRANSIENT = {'rate_limit', 'upstream_rate_limit', 'overloaded', 'server_error', 'timeout'}
FALLBACK = TRANSIENT | {'billing', 'auth', 'auth_permanent', 'model_not_found', 'model_entitlement', 'upstream_blocked'}


def tool_reason(error):
    """Only affirmative transient signals permit replay of an explicitly read-only tool."""
    if isinstance(error, (TimeoutError, httpx.TimeoutException)):
        return 'timeout'
    if isinstance(error, (ConnectionError, httpx.NetworkError)):
        return 'server_error'
    status = getattr(error, 'status_code', None)
    if status is None and isinstance(error, dict):
        status = error.get('status_code')
        if error.get('retryable') is True and error.get('error_code') in TRANSIENT:
            return error['error_code']
    if status == 429:
        return 'rate_limit'
    if isinstance(status, int) and 500 <= status <= 599:
        return 'server_error'
    return 'unknown'


def unknown_effect(result):
    if not isinstance(result, dict) or not result:
        return True  # malformed write receipt is not proof of success
    error = str(result.get('error', '')).lower()
    return bool(result.get('outcome_uncertain') or result.get('effect_disposition') == 'unknown'
                or result.get('state') in ('unknown', 'timeout')
                or any(word in error for word in ('timeout', 'timed out', '超时', '结果未知')))


class ChatRecovery:
    def __init__(self, store, task_id, agent, policy=None, *, clock=time.monotonic, jitter=random.uniform):
        self.store, self.task_id, self.agent = store, task_id, agent
        self.policy = policy or RecoveryPolicy()
        self.clock, self.jitter = clock, jitter
        self.started = None
        self.deadline = None
        self.reason = None
        self.trace = None
        self.steps = {}
        self.timer = None
        self.lock = threading.RLock()
        self.closed = False
        with store.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS chat_recovery_budget (
                task_id TEXT PRIMARY KEY, requests INTEGER NOT NULL DEFAULT 0,
                retries INTEGER NOT NULL DEFAULT 0, tokens INTEGER NOT NULL DEFAULT 0,
                active_seconds REAL NOT NULL DEFAULT 0)''')
            db.execute('INSERT OR IGNORE INTO chat_recovery_budget(task_id) VALUES (?)', (task_id,))

    def snapshot(self):
        with self.store.connect() as db:
            row = db.execute('SELECT requests,retries,tokens,active_seconds FROM chat_recovery_budget WHERE task_id=?', (self.task_id,)).fetchone()
        return dict(zip(('requests', 'retries', 'tokens', 'active_seconds'), row))

    def start(self):
        if self.started is not None:
            return
        self.started = self.clock()
        remaining = self.policy.task_timeout_seconds - self.snapshot()['active_seconds']
        self.deadline = self.started + max(0, remaining)
        if remaining <= 0:
            raise RecoveryStopped('task_timeout')
        self.timer = threading.Timer(remaining, self._expire)
        self.timer.daemon = True
        self.timer.start()

    def _expire(self):
        with self.lock:
            if self.closed:
                return
            self.reason = 'task_timeout'
            if self.trace:
                self.trace.decision('stop', self.reason, budget=self.snapshot())
            self.notify(COPY[self.reason])
            self.agent.interrupt(hard_cancel=True, tool_reason='chat_task_timeout')

    def check(self):
        if self.closed or getattr(self.agent, '_interrupt_requested', False):
            raise InterruptedError('Chat execution stopped')
        if self.deadline is not None and self.clock() >= self.deadline:
            self.reason = 'task_timeout'
            raise RecoveryStopped(self.reason)

    def notify(self, text):
        emit = getattr(self.agent, '_emit_status', None)
        if emit:
            emit(text)

    def reserve(self, *, tokens=0, retry=False, model=False):
        self.check()
        p = self.policy
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            requests, retries, reserved = db.execute('SELECT requests,retries,tokens FROM chat_recovery_budget WHERE task_id=?', (self.task_id,)).fetchone()
            reason = ('request_budget' if model and requests >= p.max_model_requests
                      else 'retry_budget' if retry and retries >= p.max_recovery_attempts
                      else 'token_budget' if reserved + tokens > p.max_reserved_tokens else None)
            if reason:
                self.reason = reason
                raise RecoveryStopped(reason)
            db.execute('UPDATE chat_recovery_budget SET requests=requests+?, retries=retries+?, tokens=tokens+? WHERE task_id=?',
                       (int(model), int(retry), tokens, self.task_id))

    def before_request(self, kwargs, request_id):
        # Count every physical host request, including destination repairs and fallback.
        # Transport-owned SDK retries are disabled; the Agent owns retries.
        self.check()
        client = getattr(self.agent, 'client', None)
        if isinstance(getattr(client, 'max_retries', None), int):
            client.max_retries = 0
        if isinstance(getattr(self.agent, '_client_kwargs', None), dict):
            self.agent._client_kwargs['max_retries'] = 0
        cap_key = 'max_completion_tokens' if 'max_completion_tokens' in kwargs else 'max_tokens'
        kwargs[cap_key] = min(kwargs.get(cap_key) or self.policy.max_output_tokens, self.policy.max_output_tokens)
        if isinstance(kwargs.get('extra_body'), dict):
            kwargs['extra_body'] = dict(kwargs['extra_body'])
            for key in ('max_tokens', 'max_completion_tokens'):
                if key in kwargs['extra_body']:
                    kwargs['extra_body'][key] = min(kwargs['extra_body'][key], self.policy.max_output_tokens)
        remaining = max(.01, self.deadline - self.clock())
        kwargs['timeout'] = httpx.Timeout(min(self.policy.request_timeout_seconds, remaining), connect=min(10, remaining))
        prompt = {key: kwargs[key] for key in ('messages', 'tools') if key in kwargs}
        # UTF-8 bytes intentionally over-reserve text tokens; failed/unknown calls never refund.
        tokens = len(json.dumps(prompt, ensure_ascii=False).encode('utf-8')) + kwargs[cap_key]
        key = (request_id, str(self.agent.provider), str(self.agent.model))
        count = self.steps.get(key, 0)
        self.reserve(tokens=tokens, retry=count > 0, model=True)
        self.steps[key] = count + 1
        if self.trace:
            self.trace.model_start(kwargs, request_id, self.snapshot())

    def delay(self, error, attempt):
        header = getattr(getattr(error, 'response', None), 'headers', {}).get('retry-after')
        retry_after = 0
        if header:
            try:
                retry_after = float(header)
            except ValueError:
                try:
                    retry_after = (parsedate_to_datetime(header) - datetime.now(timezone.utc)).total_seconds()
                except (TypeError, ValueError, OverflowError):
                    pass
        backoff = min(self.policy.max_backoff_seconds, self.policy.backoff_seconds * 2 ** min(attempt - 1, 10))
        # Do not violate a provider's Retry-After by truncating it; fallback/stop instead.
        return max(retry_after, self.jitter(backoff / 2, backoff))

    def wait(self, delay):
        self.check()
        if delay >= self.deadline - self.clock():
            self.reason = 'task_timeout'
            raise RecoveryStopped(self.reason)
        until = self.clock() + delay
        while self.clock() < until:
            self.check()
            time.sleep(min(.1, max(0, until - self.clock())))

    def on_model_error(self, error, reason, request_id):
        if isinstance(error, RecoveryStopped):
            self.reason = error.reason
            return 'stop'
        if isinstance(error, InterruptedError) or getattr(self.agent, '_interrupt_requested', False):
            return 'stop'
        try:
            self.check()
            self.reason = reason
            if str(getattr(self.agent, '_current_streamed_assistant_text', '') or '').strip():
                self.reason = 'stream_interrupted'
                return 'stop'
            if reason in {'format_error', 'content_policy_blocked', 'provider_policy_blocked', 'ssl_cert_verification'}:
                return 'stop'
            # Context/format repairs stay in Hermes, still metered before their next request.
            if reason not in FALLBACK:
                return None
            count = self.steps.get((request_id, str(self.agent.provider), str(self.agent.model)), 1)
            if reason in TRANSIENT and count < self.policy.model_attempts:
                if self.snapshot()['retries'] >= self.policy.max_recovery_attempts:
                    raise RecoveryStopped('retry_budget')
                delay = self.delay(error, count)
                if delay <= self.policy.max_backoff_seconds and delay < self.deadline - self.clock():
                    if self.trace:
                        self.trace.decision('retry', reason, delay_seconds=delay, next_attempt=count + 1, budget=self.snapshot())
                    self.notify(f'模型服务暂时不可用，{delay:.1f} 秒后重试（{count}/{self.policy.model_attempts - 1}）。')
                    self.wait(delay)
                    return 'retry'
            if self.snapshot()['requests'] >= self.policy.max_model_requests:
                raise RecoveryStopped('request_budget')
            if self.fallback_available():
                self.reserve(retry=True)
                return 'fallback'
            return 'stop'
        except RecoveryStopped as stopped:
            self.reason = stopped.reason
            return 'stop'
        except InterruptedError:
            return 'stop'

    def failure(self, messages, api_calls):
        reason = self.reason or 'unknown'
        text = COPY.get(reason, '模型服务暂时无法继续，自动恢复已停止。请稍后继续。') + PRESERVED
        partial = str(getattr(self.agent, '_current_streamed_assistant_text', '') or '').strip()
        if partial and not (messages and messages[-1].get('role') == 'assistant' and messages[-1].get('content') == partial):
            from agent.message_metadata import append_message
            append_message(messages, dict(role='assistant', content=partial))
        return dict(final_response=partial or text, partial=bool(partial), messages=messages, api_calls=api_calls, completed=False,
                    failed=True, error=text, failure_reason=reason, failure_retryable=False)

    def fallback_available(self):
        # A declared key_env must never fall through to OPENAI_API_KEY or the primary key.
        from hermes_cli.fallback_config import resolve_entry_api_key
        while self.agent._has_pending_fallback():
            entry = self.agent._fallback_chain[self.agent._fallback_index]
            if (entry.get('key_env') or entry.get('api_key_env')) and not resolve_entry_api_key(entry):
                self.agent._fallback_index += 1
                if self.trace:
                    self.trace.decision('skip_fallback', 'missing_credentials', provider=entry.get('provider'), model=entry.get('model'))
                self.notify('备用服务缺少对应凭据，已跳过。请检查配置后继续。')
                continue
            return True
        return False

    def iteration_limit(self):
        self.reason = 'iteration_budget'
        return COPY[self.reason] + PRESERVED

    def read_tool(self, name, execute):
        self.check()
        for attempt in range(self.policy.tool_attempts):
            try:
                result = execute()
                try:
                    parsed = json.loads(result) if isinstance(result, str) else result
                except (ValueError, TypeError):
                    parsed = None
                failed = isinstance(parsed, dict) and (parsed.get('error') or parsed.get('success') is False)
                if not failed or tool_reason(parsed) not in TRANSIENT or attempt + 1 == self.policy.tool_attempts:
                    return result
                error = parsed
            except (RecoveryStopped, InterruptedError):
                raise
            except Exception as exc:
                if tool_reason(exc) not in TRANSIENT or attempt + 1 == self.policy.tool_attempts:
                    raise
                error = exc
            self.reserve(retry=True)
            delay = self.delay(error, attempt + 1)
            if self.trace:
                self.trace.decision('retry', tool_reason(error), tool_name=name, next_attempt=attempt + 2, delay_seconds=delay, budget=self.snapshot())
            self.notify(f'只读工具 {name} 暂时不可用，正在重试（{attempt + 1}/{self.policy.tool_attempts - 1}）。')
            self.wait(delay)

    def finish(self, result):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            if self.timer:
                self.timer.cancel()
            if self.started is not None:
                elapsed = max(0, self.clock() - self.started)
                with self.store.connect() as db:
                    db.execute('UPDATE chat_recovery_budget SET active_seconds=active_seconds+? WHERE task_id=?', (elapsed, self.task_id))
            if not isinstance(result, dict):
                return
            if self.reason in ('task_timeout', 'iteration_budget'):
                result.update(failed=True, completed=False, interrupted=False, failure_reason=self.reason)
            if result.get('failed') or result.get('error'):
                reason = result.get('failure_reason') or self.reason or 'unknown'
                text = COPY.get(reason, '本轮未能完成，自动恢复已停止。请检查服务状态后继续。') + PRESERVED
                result['error'] = text
                if not result.get('partial'):
                    result['final_response'] = text
