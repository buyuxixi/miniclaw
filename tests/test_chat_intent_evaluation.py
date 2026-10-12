"""Evaluation must measure real policy behavior without accidental paid calls."""
import json
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from miniclaw_web.decisions import JevConfig
from miniclaw_web.clarifications import Clarifications
from miniclaw_web.clarification_policy import ClarificationPolicy
from miniclaw_web.store import Store
from scripts.evaluate_chat_intent import (
    EVALUATION_SCOPE, EvaluationDecisions, budget_micro_usd,
    evaluate_cases, load_dataset, main, replay_history, run,
)


def inference_response(request):
    payload = json.loads(request.content)
    answers = {}
    for name, question in payload['questions'].items():
        choices = question['criteria']
        choice = 'discuss' if name == 'intent' else next(iter(choices))
        answers[name] = dict(type='choice', choice=choice, confidence=.99,
                             probabilities={key: float(key == choice) for key in choices})
    return httpx.Response(200, json=dict(model=payload['model'], answers=answers, usage={'input_tokens': 10}))


def test_frozen_set_has_labelled_rule_and_semantic_business_coverage():
    data = load_dataset()
    assert len(data['cases']) == 48
    assert {case['verification'] for case in data['cases']} == {'rule_fallback', 'semantic_required'}
    assert {'discussion', 'execution', 'negation', 'multiple_images', 'conflict', 'compound',
            'cancel', 'revise', 'new_topic'} <= {case['category'] for case in data['cases']}
    assert sum('relation' in case['expected'] for case in data['cases']) == 13
    assert len(data['regression_cases']) == 4


def test_default_cannot_use_ambient_or_supplied_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv('JEV_API', 'must-not-be-used')
    def unexpected_request(*args, **kwargs):
        pytest.fail('offline evaluation attempted an HTTP request')
    monkeypatch.setattr(httpx.Client, 'post', unexpected_request)
    report = run(load_dataset(), config=JevConfig(key='also-not-used'), history_path=tmp_path / 'missing.json')
    assert report['budget']['network_calls'] == 0
    assert report['summary']['decision_statuses'] == {'unavailable': 48}
    assert report['summary']['rule_fallback']['execution_boundary']['total'] == 24
    assert report['summary']['semantic_required']['metrics'] is None
    assert report['summary']['semantic_required']['status'] == 'not_verified_offline'
    assert report['online_accuracy_claim'] is False
    assert report['historical_replay']['status'] == 'source_missing'
    assert report['task_controls']['explicit_action_accuracy']['total'] == 8
    assert report['task_controls']['answer_submission_verified'] is False


def test_live_cases_share_one_call_and_fee_ledger(tmp_path):
    calls = []
    def transport(request):
        calls.append(request)
        return inference_response(request)
    decisions = EvaluationDecisions(Store(tmp_path), JevConfig(key='test', max_calls=2), httpx.MockTransport(transport))
    rows = evaluate_cases(load_dataset()['cases'][:3], decisions, 'live')
    assert len(calls) == 2
    assert rows[-1]['decision_status'] == 'budget_exhausted'
    assert decisions.ledger(EVALUATION_SCOPE)['calls'] == 2


def test_fee_reservation_stops_before_request(tmp_path):
    def unexpected_request(request):
        pytest.fail('request exceeded the reserved evaluation budget')
    decisions = EvaluationDecisions(Store(tmp_path), JevConfig(key='test', budget_micro_usd=1), httpx.MockTransport(unexpected_request))
    row = evaluate_cases(load_dataset()['cases'][:1], decisions, 'live')[0]
    assert row['decision_status'] == 'budget_exhausted'
    assert decisions.ledger(EVALUATION_SCOPE)['calls'] == 0


@pytest.mark.parametrize('value', ['0', '-1', '0.010001', 'NaN', 'Infinity', 'not-a-number'])
def test_invalid_or_unbounded_fee_is_rejected(value):
    with pytest.raises(ValueError):
        budget_micro_usd(value)


def test_live_call_limit_and_missing_key_fail_before_inference(tmp_path):
    data = load_dataset()
    with pytest.raises(ValueError):
        run(data, live=True, max_calls=11, config=JevConfig(key='test'))
    with pytest.raises(ValueError):
        run(data, live=True, config=JevConfig(key=''))
    with pytest.raises(ValueError):
        run(data, case_ids=['unknown'], history_path=tmp_path / 'missing.json')


def test_historical_answers_are_revalidated_instead_of_trusting_saved_intent(tmp_path):
    data = load_dataset()
    source = ROOT / data['historical_replay']['source']
    if not source.is_file():
        pytest.skip('private historical smoke artifact is not included in this checkout')
    history = json.loads(source.read_text(encoding='utf-8'))
    paid = next(record for record in history['cases'] if record['case'] == 'paid')
    paid['intent'] = 'draft'  # Outer historical conclusion is deliberately false.
    altered = tmp_path / 'historical.json'
    altered.write_text(json.dumps(history), encoding='utf-8')
    replay = replay_history(data, Store(tmp_path / 'store'), altered)
    paid_row = next(row for row in replay['cases'] if row['id'] == 'r20')
    assert replay['charged_calls'] == 0 and replay['replayed_responses'] == 3
    assert paid_row['actual_intent'] == 'execute_change'
    assert paid_row['semantic_response_available'] is True
    assert paid_row['intent_match'] is False and paid_row['execution_match'] is True


def test_malformed_saved_semantic_answers_do_not_become_accepted_prediction(tmp_path):
    data = load_dataset()
    source = tmp_path / 'history.json'
    source.write_text(json.dumps({'cases': [{'case': 'paid', 'answers': {'intent': {'choice': 'generate_media'}}}]}), encoding='utf-8')
    replay = replay_history(data, Store(tmp_path / 'store'), source)
    row = replay['cases'][0]
    assert row['decision_status'] == 'unavailable'
    assert row['decision_reason'] == 'invalid_response'
    assert row['semantic_response_available'] is False


def test_duplicate_ids_and_bad_gold_labels_are_rejected(tmp_path):
    data = load_dataset()
    data['cases'][1]['id'] = data['cases'][0]['id']
    source = tmp_path / 'bad-dataset.json'
    source.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError):
        load_dataset(source)
    data = load_dataset()
    data['cases'][0]['expected']['intent'] = 'invented'
    source.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError):
        load_dataset(source)


@pytest.mark.parametrize('kind', ['case_list', 'case_object', 'gold_object', 'category'])
def test_malformed_dataset_is_rejected_before_any_live_call(tmp_path, kind):
    data = load_dataset()
    if kind == 'case_list':
        data['cases'] = {str(i): {} for i in range(40)}
    elif kind == 'case_object':
        data['cases'][0] = 'invalid'
    elif kind == 'gold_object':
        data['cases'][0]['expected'] = 'invalid'
    else:
        data['cases'][0].pop('category')
    source = tmp_path / 'malformed.json'
    source.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError):
        load_dataset(source)


def test_cli_writes_reviewable_report_and_identifies_unverified_semantics(tmp_path, capsys):
    output = tmp_path / 'report.json'
    report = main(['--output', str(output), '--history', str(tmp_path / 'absent.json')])
    saved = json.loads(output.read_text(encoding='utf-8'))
    assert saved == report
    assert saved['evaluated_cases'] == 52
    assert saved['dataset_cases'] == 48 and saved['regression_dataset_cases'] == 4
    assert saved['summary']['rule_fallback']['execution_boundary']['total'] == 24
    assert saved['expanded_rule_fallback']['execution_boundary']['total'] == 28
    assert saved['task_controls']['semantic_relationships_not_verified'] == 5
    assert saved['task_controls']['explicit_action_accuracy']['total'] == 8
    assert saved['summary']['decomposition_cases_not_evaluated'] == 1
    assert 'not_verified_offline' in capsys.readouterr().out


def test_explicit_controls_are_measured_without_confusing_negation_or_short_answer(tmp_path):
    report = run(load_dataset(), history_path=tmp_path / 'missing.json')
    controls = {row['id']: row for row in report['task_controls']['cases']}
    assert [controls[key]['actual_control_action'] for key in ('c41', 'c42', 'c43')] == ['cancel', 'revise', 'new_topic']
    assert all(controls[key]['actual_control_action'] is None for key in ('c44', 'c45', 'c46', 'c47', 'c48'))
    assert controls['c48']['expected_relation'] == 'answers_current'
    assert report['task_controls']['explicit_action_accuracy']['correct'] == 8
    assert controls['s36']['status'] == 'semantic_relationship_not_verified'


def test_live_entry_bounds_sample_and_keeps_history_separate():
    calls = []
    def transport(request):
        calls.append(request)
        return inference_response(request)
    report = run(load_dataset(), live=True, max_calls=2, limit=40, config=JevConfig(key='test'), transport=httpx.MockTransport(transport))
    assert len(calls) == report['budget']['network_calls'] == 2
    assert report['evaluated_cases'] == 2
    assert 'historical_replay' not in report
    assert report['online_accuracy_claim'] is False


@pytest.mark.parametrize('identifier', ['g49', 'g50', 'g51', 'g52'])
def test_generation_mentions_in_discussion_or_text_output_cannot_authorize_paid_tool(tmp_path, identifier):
    case = next(case for case in load_dataset()['regression_cases'] if case['id'] == identifier)
    store = Store(tmp_path)
    service = Clarifications(store)
    policy = ClarificationPolicy(EvaluationDecisions(store, JevConfig(key='')))
    task = service.start('isolated-evaluation', case['text'])
    intent, _, _ = policy.classify(task)
    assert intent in ('draft', 'discuss')
    assert task['paid_allowance'] == 0
    task['context']['intent'] = intent
    assert policy.guard(task, 'miniclaw_canvas_ai', {'prompt': 'synthetic'})['template'] == 'Q_EXECUTION'


@pytest.mark.parametrize('text', ['不要再生成图片。', '不需要生成图片，先帮我写文案。'])
def test_explicit_negative_generation_never_grants_allowance_or_passes_paid_guard(tmp_path, text):
    store = Store(tmp_path)
    policy = ClarificationPolicy(EvaluationDecisions(store, JevConfig(key='')))
    task = Clarifications(store).start('negative-evaluation', text)
    intent, _, _ = policy.classify(task)
    assert intent == 'draft'
    assert task['paid_allowance'] == 0
    task['context']['intent'] = intent
    for name, args in [('miniclaw_canvas_ai', {}), ('miniclaw_edit_image', {'operation': 'ai_edit'})]:
        assert policy.guard(task, name, args)['template'] == 'Q_EXECUTION'
