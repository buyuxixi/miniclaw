"""Actual HTTP parsing, durable fallback, and both production factories."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json

import httpx
import pytest

from miniclaw_web.chat_decisions import chat_policy
from miniclaw_web.clarification_policy import RULE_VERSION, chat_request, ClarificationPolicy
from miniclaw_web.candidate_clarification_policy import CandidateClarificationPolicy
from miniclaw_web.decision_routing import (
    DEFAULT_CHECKPOINT, DEFAULT_GATE, DEFAULT_URL, RoutedDecisions, decision_service,
)
from miniclaw_web.decisions import JevConfig, JevDecisions
from miniclaw_web.laya_formal import LayaFormalDecisions
from miniclaw_web.store import Store


def request():
    return chat_request('请把选中图片旋转90度。', dict(
        selected='real-image', candidates=[dict(id='real-image', label='杯子')]), {})


def answers(questions, *, local=False):
    result = {}
    for name, q in questions.items():
        if q['type'] == 'noul':
            result[name] = dict(type='noul', noul=.9)
            continue
        labels = list(q['criteria'])
        choice = {'intent': 'execute_change', 'target': 'real-image',
                  'conflict': 'none', 'scope': 'whole_object'}.get(name, labels[0])
        if choice not in labels:
            choice = labels[0]
        result[name] = dict(type='choice', choice=choice, confidence=1. if local else .99,
                           probabilities={x: .99 if x == choice else .01/(len(labels)-1) for x in labels})
        if local:
            result[name]['raw_confidence'] = .99
    return result


def local_result(req):
    return dict(answers=answers(req[1], local=True), checkpoint_sha256=DEFAULT_CHECKPOINT,
                gate_sha256=DEFAULT_GATE, acceptance_marker_not_probability=True,
                selective_acceptance={q: True for q in req[1]})


def make(tmp_path, local_handler=None, cloud_handler=None, key='test-key', max_calls=20, clock=None):
    store = Store(tmp_path)
    local_calls, cloud_calls = [], []
    def local_http(r):
        local_calls.append(r)
        return local_handler(r) if local_handler else httpx.Response(200, json=local_result(request()))
    def cloud_http(r):
        cloud_calls.append(r)
        if cloud_handler:
            return cloud_handler(r)
        payload = json.loads(r.content)
        return httpx.Response(200, json=dict(answers=answers(payload['questions']),
                                           usage=dict(input_tokens=100), model='jev-fixture'))
    primary = LayaFormalDecisions(DEFAULT_URL, DEFAULT_CHECKPOINT,
                                 gate_sha256=DEFAULT_GATE, timeout=.2,
                                 transport=httpx.MockTransport(local_http))
    cloud = JevDecisions(store, JevConfig(key=key, max_calls=max_calls),
                         transport=httpx.MockTransport(cloud_http))
    router = RoutedDecisions(store, primary, cloud, **({'clock': clock} if clock else {}))
    return router, local_calls, cloud_calls


def evaluate(router, identifier='request-0001', req=None, revision=1):
    return router.evaluate('scope', identifier, '请求', dict(revision=revision),
                           request=req or request(), question_version=RULE_VERSION)


def test_success_is_local_only_and_persistent_across_restart(tmp_path):
    router, local, cloud = make(tmp_path)
    first = evaluate(router)
    assert first['provider'] == 'laya-local' and first['jev_fallback'] is False
    assert len(local) == 1 and not cloud
    restarted = RoutedDecisions(router.store, router.primary, router.fallback)
    assert evaluate(restarted) == first and len(local) == 1 and not cloud
    assert router.ledger('scope')['local_calls'] == 1
    with pytest.raises(ValueError, match='同一请求'):
        evaluate(restarted, revision=2)


@pytest.mark.parametrize('failure', ['connection', 'timeout', '503', '422', 'invalid_json', 'pin', 'gate', 'markers'])
def test_failures_use_cloud_once_and_preserve_identical_request(tmp_path, failure):
    def broken(r):
        if failure == 'connection': raise httpx.ConnectError('private diagnostic', request=r)
        if failure == 'timeout': raise httpx.ReadTimeout('private diagnostic', request=r)
        if failure in ('503', '422'): return httpx.Response(int(failure), json={})
        if failure == 'invalid_json': return httpx.Response(200, content=b'bad json')
        value = local_result(request())
        if failure == 'pin': value['checkpoint_sha256'] = 'a'*64
        if failure == 'gate': value['gate_sha256'] = 'a'*64
        if failure == 'markers': value['selective_acceptance']['intent'] = False
        return httpx.Response(200, json=value)
    router, local, cloud = make(tmp_path, broken)
    first = evaluate(router)
    assert first['provider'] == 'jev' and first['jev_fallback'] is True
    assert first['status'] == 'suggested' and first['grants_permission'] is False
    assert json.loads(cloud[0].content)['state'] == request()[0]
    assert 'private diagnostic' not in json.dumps(first)
    assert evaluate(router) == first and len(local) == len(cloud) == 1
    assert router.ledger('scope')['calls'] == router.ledger('scope')['fallback_calls'] == 1


def test_unusable_intent_uses_cloud_without_loosening_local_gates(tmp_path):
    value = local_result(request())
    for q in value['answers']:
        value['answers'][q]['confidence'] = 0.
        value['selective_acceptance'][q] = False
    router, local, cloud = make(tmp_path, lambda r: httpx.Response(200, json=value))
    result = evaluate(router)
    assert result['provider'] == 'jev' and len(cloud) == 1
    assert result['fallback_reason'] == 'local_intent_abstention'
    assert router.retry_after == 0
    task = dict(id='task-id', text='旋转图片', confirmed={}, context=dict(semantic={}))
    policy = CandidateClarificationPolicy(router)
    # An unusable/abstained suggestion never turns confidence into permission.
    task['context']['intent'] = 'unclear'
    assert policy.guard(task, 'miniclaw_edit_image', {})['template'] == 'Q_EXECUTION'


@pytest.mark.parametrize('kind', ['unclear', 'conflict'])
def test_genuine_unclear_or_conflict_never_gets_overridden_by_cloud(tmp_path, kind):
    value = local_result(request())
    if kind == 'unclear':
        value['answers']['intent']['choice'] = 'unclear'
        probs = value['answers']['intent']['probabilities']
        probs['unclear'], probs['execute_change'] = probs['execute_change'], probs['unclear']
    else:
        value['answers']['intent']['confidence'] = 0.
        value['selective_acceptance']['intent'] = False
        value['answers']['conflict']['choice'] = 'present'
        probs = value['answers']['conflict']['probabilities']
        probs['present'], probs['none'] = probs['none'], probs['present']
    router, local, cloud = make(tmp_path, lambda r: httpx.Response(200, json=value))
    assert evaluate(router)['provider'] == 'laya-local' and not cloud


def test_cooldown_skips_repeated_connection_then_returns_to_local(tmp_path):
    now = [100.]
    up = [False]
    def handler(r):
        if not up[0]: raise httpx.ConnectError('down', request=r)
        return httpx.Response(200, json=local_result(request()))
    router, local, cloud = make(tmp_path, handler, clock=lambda: now[0])
    assert evaluate(router)['provider'] == 'jev'
    up[0] = True
    assert evaluate(router, 'request-0002')['fallback_reason'] == 'local_cooldown'
    now[0] += 6
    assert evaluate(router, 'request-0003')['provider'] == 'laya-local'
    assert len(local) == len(cloud) == 2


@pytest.mark.parametrize('mode', ['missing_key', 'budget', 'unknown'])
def test_failed_cloud_is_not_retried_or_promoted_to_success(tmp_path, mode):
    def timeout(r): raise httpx.ReadTimeout('secret', request=r)
    router, local, cloud = make(tmp_path, lambda r: httpx.Response(503),
                               timeout if mode == 'unknown' else None,
                               key='' if mode == 'missing_key' else 'key',
                               max_calls=0 if mode == 'budget' else 20)
    first = evaluate(router)
    assert first['status'] == {'missing_key': 'unavailable', 'budget': 'budget_exhausted', 'unknown': 'unknown'}[mode]
    assert not first.get('answers') and first['grants_permission'] is False
    assert evaluate(router) == first
    assert len(cloud) == (1 if mode == 'unknown' else 0)


def test_concurrent_same_id_cloud_charge_once(tmp_path):
    router, local, cloud = make(tmp_path, lambda r: httpx.Response(503))
    other = RoutedDecisions(router.store, router.primary, router.fallback)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda n: evaluate(router if n % 2 else other), range(8)))
    assert len(cloud) == 1
    assert all(r['status'] in ('suggested', 'pending') for r in results)
    assert router.fallback.ledger('scope')['calls'] == 1


def test_pre_switch_cloud_unknown_is_reused_without_local_or_cloud_retry(tmp_path):
    def timeout(r): raise httpx.ReadTimeout('timeout', request=r)
    router, local, cloud = make(tmp_path, cloud_handler=timeout)
    router.fallback.evaluate('scope', 'request-0001', '请求', dict(revision=1),
                             request=request(), question_version=RULE_VERSION)
    with pytest.raises(ValueError, match='同一请求'):
        evaluate(router, revision=2)
    result = evaluate(router)
    assert result['status'] == 'unknown' and result['fallback_reason'] == 'existing_cloud_request'
    assert not local and len(cloud) == 1


def test_studio_contract_uses_same_router_and_explicit_unsupported_fallback(tmp_path):
    router, local, cloud = make(tmp_path)
    snapshot = dict(revision=1, shots=[dict(id='shot-one', purpose='开场')])
    result = router.evaluate('studio', 'studio-0001', '改开场为近景', snapshot, 'shot-one')
    assert result['provider'] == 'jev' and result['fallback_reason'] == 'unsupported_local_contract'
    assert result['answers']['preserve_others']['type'] == 'noul'
    assert not local and len(cloud) == 1


def test_factory_defaults_and_explicit_second_option(tmp_path):
    store = Store(tmp_path)
    service = decision_service(store, {})
    assert isinstance(service, RoutedDecisions)
    assert service.primary.url == DEFAULT_URL and service.primary.checkpoint == DEFAULT_CHECKPOINT
    assert service.primary.gate_pin == DEFAULT_GATE and service.primary.timeout == 3
    policy = chat_policy(service, {})
    assert isinstance(policy, CandidateClarificationPolicy) and policy.decisions is service
    cloud = decision_service(store, {'MINICLAW_DECISION_PROVIDER': 'jev'})
    assert isinstance(cloud, JevDecisions)
    assert type(chat_policy(service, {'MINICLAW_CHAT_DECISION_PROVIDER': 'jev'})) is ClarificationPolicy
    assert chat_policy(service, {'MINICLAW_CHAT_DECISION_PROVIDER': 'jev'}).decisions is service.fallback
    assert service.capabilities()['fallback_provider'] == 'jev'
    with pytest.raises(ValueError): decision_service(store, {'MINICLAW_DECISION_PROVIDER': 'typo'})


def test_invalid_local_configuration_falls_back_instead_of_preventing_startup(tmp_path):
    router, local, cloud = make(tmp_path)
    service = decision_service(router.store, {'MINICLAW_LAYA_URL': 'https://external.invalid'}, fallback=router.fallback)
    result = evaluate(service)
    assert result['provider'] == 'jev' and result['fallback_reason'] == 'local_configuration'
    assert not local and len(cloud) == 1


def test_bad_port_and_timeout_configuration_can_use_cloud(tmp_path):
    router, local, cloud = make(tmp_path)
    for n, env in enumerate(({'MINICLAW_LAYA_URL': 'http://127.0.0.1:bad'},
                             {'MINICLAW_LAYA_TIMEOUT': 'NaN'})):
        service = decision_service(router.store, env, fallback=router.fallback)
        assert evaluate(service, f'bad-config-{n}')['fallback_reason'] == 'local_configuration'
    assert not local and len(cloud) == 2


def test_state_rejection_does_not_disable_next_supported_request(tmp_path):
    count = [0]
    def handler(r):
        count[0] += 1
        return httpx.Response(422) if count[0] == 1 else httpx.Response(200, json=local_result(request()))
    router, local, cloud = make(tmp_path, handler)
    assert evaluate(router)['provider'] == 'jev'
    assert evaluate(router, 'request-0002')['provider'] == 'laya-local'
    assert len(local) == 2 and len(cloud) == 1


def test_interrupted_route_is_unknown_and_never_replayed(tmp_path):
    import time
    router, local, cloud = make(tmp_path)
    saved = evaluate(router)
    saved.update(status='pending', created=time.time()-1000)
    with router.store.connect() as db:
        db.execute('UPDATE decision_routes SET data=?', (json.dumps(saved),))
    result = evaluate(RoutedDecisions(router.store, router.primary, router.fallback))
    assert result['status'] == 'unknown' and result['retryable'] is False
    assert len(local) == 1 and not cloud


def test_actual_studio_constructor_uses_default_router(tmp_path, monkeypatch):
    from pathlib import Path
    from miniclaw_web.canvas import Canvas
    from miniclaw_web.studio import Studio
    monkeypatch.delenv('MINICLAW_DECISION_PROVIDER', raising=False)
    store = Store(tmp_path)
    studio = Studio(store, Canvas(store), Path(__file__).resolve().parents[1])
    assert isinstance(studio.decisions, RoutedDecisions)
    assert chat_policy(studio.decisions, {}).decisions is studio.decisions
