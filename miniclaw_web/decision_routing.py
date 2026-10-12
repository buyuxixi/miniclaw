"""App-wide Laya preference with bounded, durable cloud fallback."""
from copy import deepcopy
import hashlib
import json
import os
import threading
import time

from .clarification_policy import RULE_VERSION, high
from .decisions import JevConfig, JevDecisions, QUESTION_VERSION, decision_request
from .laya_formal import LayaFormalDecisions

DEFAULT_CHECKPOINT = '6c1d336ea08c1bd87292c573a393a7ed0b58bb8ce5b7a60a79cb72456083d041'
DEFAULT_GATE = '69639c48ac04dbe6de7fb99a098a7d184acf1e16a32b823efe52b4112694f315'
DEFAULT_URL = 'http://127.0.0.1:8771'


def local_decisions(env):
    return LayaFormalDecisions(
        env.get('MINICLAW_LAYA_URL', DEFAULT_URL),
        env.get('MINICLAW_LAYA_CHECKPOINT_SHA256', DEFAULT_CHECKPOINT),
        gate_sha256=env.get('MINICLAW_LAYA_GATE_SHA256', DEFAULT_GATE),
        timeout=float(env.get('MINICLAW_LAYA_TIMEOUT', '3')),
    )


class RoutedDecisions:
    """Inference only; routed suggestions never grant operation permission.

    One durable outcome per scope/id, including failed/unknown cloud outcomes.
    Unsupported contracts use the secondary instead of borrowing seven-question
    calibration. Accepted conflict/unclear remain local; unusable intent can use
    the secondary without loosening any local acceptance gate.
    """
    def __init__(self, store, primary, fallback, *, configuration_error=False,
                 cooldown=5, clock=time.monotonic):
        self.store, self.primary, self.fallback = store, primary, fallback
        self.configuration_error = configuration_error
        self.cooldown, self.clock = cooldown, clock
        self.retry_after = 0
        self.lock = threading.RLock()
        self.deadline = getattr(primary, 'timeout', 3) + fallback.config.timeout + 5
        with store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS decision_routes '
                       '(scope TEXT, id TEXT, signature TEXT, data TEXT, PRIMARY KEY(scope,id))')

    def capabilities(self):
        cloud = self.fallback.capabilities()
        return {**cloud, 'configured': self.primary is not None or cloud['configured'],
                'model': 'laya-local', 'primary_provider': 'laya', 'fallback_provider': 'jev',
                'fallback_configured': cloud['configured'], 'fallback_model': cloud['model'],
                'local_configured': self.primary is not None, 'supported_contracts': [RULE_VERSION],
                'local_timeout_seconds': getattr(self.primary, 'timeout', None),
                'checkpoint_sha256': getattr(self.primary, 'checkpoint', None),
                'gate_sha256': getattr(self.primary, 'gate_pin', None)}

    def ledger(self, scope):
        cloud = self.fallback.ledger(scope)
        with self.store.connect() as db:
            rows = [json.loads(r[0]) for r in db.execute(
                'SELECT data FROM decision_routes WHERE scope=?', (scope,))]
        return {**cloud, 'local_calls': sum(r.get('provider') == 'laya-local' for r in rows),
                'fallback_calls': sum(r.get('jev_fallback') is True for r in rows),
                'routed_requests': len(rows)}

    def evaluate(self, scope, request_id, instruction, snapshot, selected=None, *,
                 request=None, question_version=QUESTION_VERSION):
        if not isinstance(request_id, str) or not 8 <= len(request_id) <= 80:
            raise ValueError('需要稳定的决策请求标识')
        request = request if request is not None else decision_request(instruction, snapshot, selected)
        encoded = json.dumps([request, snapshot['revision'], question_version],
                             ensure_ascii=False, sort_keys=True).encode()
        if len(encoded) > 12_000:
            raise ValueError('决策上下文过大，请缩小目标范围')
        signature = hashlib.sha256(encoded).hexdigest()
        pending = dict(id=request_id, project_revision=snapshot['revision'],
                       question_version=question_version, status='pending', created=time.time(),
                       primary_provider='laya', mode='advisory', grants_permission=False)
        with self.lock:
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT signature,data FROM decision_routes WHERE scope=? AND id=?',
                                 (scope, request_id)).fetchone()
                if row:
                    if row[0] != signature:
                        raise ValueError('同一请求标识不能使用不同的内容或版本')
                    saved = json.loads(row[1])
                    if saved['status'] == 'pending' and time.time() - saved['created'] > self.deadline:
                        return {**saved, 'status': 'unknown', 'reason': 'interrupted', 'retryable': False}
                    return saved
                # Preserve pre-switch cloud outcomes, including unknown/pending.
                old_cloud = db.execute('SELECT signature FROM creation_decisions WHERE scope=? AND id=?',
                                       (scope, request_id)).fetchone()
                if old_cloud:
                    payload = dict(model=self.fallback.config.model, state=request[0], questions=request[1])
                    cloud_encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
                    old_signature = hashlib.sha256(cloud_encoded + str(snapshot['revision']).encode()).hexdigest()
                    if old_cloud[0] != old_signature:
                        raise ValueError('同一请求标识不能使用不同的内容或版本')
                db.execute('INSERT INTO decision_routes VALUES (?,?,?,?)',
                           (scope, request_id, signature, json.dumps(pending)))
            started = self.clock()
            if old_cloud:
                local = dict(status='unavailable', reason='existing_cloud_request')
            elif self.primary is None:
                local = dict(status='unavailable', reason='local_configuration')
            elif question_version != RULE_VERSION:
                local = dict(status='unavailable', reason='unsupported_local_contract')
            elif self.clock() < self.retry_after:
                local = dict(status='unavailable', reason='local_cooldown')
            else:
                local = self.primary.evaluate(scope, request_id, instruction, snapshot, selected,
                                              request=request, question_version=question_version)
                if local['status'] == 'unavailable' and local.get('reason') not in (
                        'unsupported_host_request', 'local_http_400', 'local_http_413', 'local_http_422'):
                    self.retry_after = self.clock() + self.cooldown
                if (local.get('status') == 'suggested' and high(local, 'intent') is None
                        and high(local, 'conflict') != 'present'):
                    local = dict(status='needs_review', reason='local_intent_abstention')
            if local.get('status') == 'suggested':
                result = {**pending, **local, 'primary_provider': 'laya', 'jev_fallback': False}
            else:
                cloud = self.fallback.evaluate(scope, request_id, instruction, snapshot, selected,
                                               request=request, question_version=question_version)
                result = {**pending, **cloud, 'provider': 'jev', 'primary_provider': 'laya',
                          'jev_fallback': True, 'fallback_reason': local.get('reason', 'local_unavailable'),
                          'primary_status': local.get('status'), 'grants_permission': False}
            result['route_latency_ms'] = round((self.clock() - started) * 1000, 3)
            with self.store.connect() as db:
                db.execute('UPDATE decision_routes SET data=? WHERE scope=? AND id=?',
                           (json.dumps(result, ensure_ascii=False), scope, request_id))
            return deepcopy(result)


def decision_service(store, environ=None, *, fallback=None):
    env = os.environ if environ is None else environ
    fallback = fallback if fallback is not None else JevDecisions(store, JevConfig.from_env(env))
    provider = env.get('MINICLAW_DECISION_PROVIDER', 'laya')
    if provider == 'jev':
        return fallback
    if provider != 'laya':
        raise ValueError('unsupported_decision_provider')
    try:
        primary = local_decisions(env)
    except (ValueError, TypeError):
        primary = None
    return RoutedDecisions(store, primary, fallback, configuration_error=primary is None)
