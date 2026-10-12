"""Frozen intent checks; offline by default, live inference only with bounded opt-in."""
import argparse
import hashlib
import json
import os
import sys
import tempfile
from collections import Counter
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'hermes-agent')]
from miniclaw_web.clarification_policy import ClarificationPolicy, INTENTS
from miniclaw_web.decisions import JevConfig, JevDecisions
from miniclaw_web.store import Store

DATASET = ROOT / 'docs' / 'chat-intent-evaluation.v1.json'
EVALUATION_SCOPE = 'chat-intent-evaluation-v1'
EXECUTION_INTENTS = {'execute_change', 'generate_media', 'adopt_result'}
GROUPS = {'rule_fallback', 'semantic_required'}
RELATIONS = {'answers_current', 'revises_task', 'new_topic', 'cancel', 'unclear'}


class EvaluationDecisions(JevDecisions):
    """One isolated ledger across every case, so limits cannot reset per task."""
    def evaluate(self, scope, *args, **kwargs):
        return super().evaluate(EVALUATION_SCOPE, *args, **kwargs)


def load_dataset(path=DATASET):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    cases = data.get('cases', []) if isinstance(data, dict) else []
    if not isinstance(cases, list) or not 30 <= len(cases) <= 50:
        raise ValueError('固定评测集必须包含 30–50 条样例')
    if not isinstance(data.get('version'), str) or not isinstance(data.get('frozen_on'), str):
        raise ValueError('评测版本或冻结日期无效')
    regressions = data.get('regression_cases', [])
    if not isinstance(regressions, list) or len(regressions) > 20:
        raise ValueError('定向补充回归必须为最多 20 条样例')
    identifiers = set()
    for case in cases + regressions:
        if not isinstance(case, dict) or not isinstance(case.get('expected'), dict):
            raise ValueError('评测样例与人工标签必须为对象')
        identifier = case.get('id')
        expected = case.get('expected', {})
        if (not isinstance(identifier, str) or not identifier or identifier in identifiers
                or not isinstance(case.get('category'), str) or not case['category']
                or case.get('verification') not in GROUPS
                or not isinstance(case.get('text'), str) or not 1 <= len(case['text'].strip()) <= 1200
                or expected.get('intent') not in INTENTS
                or not isinstance(expected.get('questions'), list)
                or any(not isinstance(q, str) or not q.startswith('Q_') for q in expected['questions'])
                or expected.get('relation', 'unclear') not in RELATIONS
                or case.get('relation_verification', 'semantic_required') not in {'explicit_rule', 'semantic_required'}):
            raise ValueError('评测样例的身份、输入或人工标签无效')
        identifiers.add(identifier)
        context = case.get('context', {})
        if not isinstance(context, dict) or not isinstance(context.get('semantic', {}), dict):
            raise ValueError('评测上下文无效')
        semantic = context.get('semantic', {})
        candidates = semantic.get('candidates', [])
        if (not isinstance(candidates, list) or len(candidates) > 12
                or any(not isinstance(c, dict) or not isinstance(c.get('id'), str)
                       or not isinstance(c.get('label'), str) for c in candidates)
                or (semantic.get('selected') and semantic['selected'] not in {c['id'] for c in candidates})):
            raise ValueError('评测对象或当前目标无效')
    return data


def execution_boundary(intent):
    return 'execute' if intent in EXECUTION_INTENTS else 'read_only'


def metrics(rows):
    count = len(rows)
    def measured(key):
        correct = sum(row[key] for row in rows)
        return dict(correct=correct, total=count, rate=round(correct / count, 4) if count else None)
    return dict(intent=measured('intent_match'), execution_boundary=measured('execution_match'),
                questions=measured('questions_match'),
                false_execution=sum(row['actual_execution'] == 'execute' and row['expected_execution'] == 'read_only' for row in rows),
                missed_execution=sum(row['actual_execution'] == 'read_only' and row['expected_execution'] == 'execute' for row in rows))


def evaluate_cases(cases, decisions, mode):
    policy = ClarificationPolicy(decisions)
    rows = []
    for case in cases:
        # Pending relationships are evaluated separately: intent classification
        # itself has no pending-question semantic context in its current API.
        task = dict(id=case['id'], text=case['text'], confirmed={}, context=case.get('context', {}))
        intent, decision, questions = policy.classify(task)
        expected = case['expected']
        actual_questions = [q['template'] for q in questions]
        rows.append(dict(id=case['id'], category=case['category'], verification=case['verification'],
                         source=mode, expected_intent=expected['intent'], actual_intent=intent,
                         expected_execution=execution_boundary(expected['intent']), actual_execution=execution_boundary(intent),
                         expected_questions=expected['questions'], actual_questions=actual_questions,
                         intent_match=intent == expected['intent'],
                         execution_match=execution_boundary(intent) == execution_boundary(expected['intent']),
                         questions_match=set(actual_questions) == set(expected['questions']),
                         decision_status=decision['status'], decision_reason=decision.get('reason'),
                         semantic_response_available=bool(decision.get('answers')),
                         decomposition_status='not_evaluated' if 'subgoals' in expected else None))
    return rows


def summarize(rows, mode):
    rule = [row for row in rows if row['verification'] == 'rule_fallback']
    semantic = [row for row in rows if row['verification'] == 'semantic_required']
    return dict(rule_fallback=metrics(rule),
                semantic_required=dict(total=len(semantic),
                                       status='not_verified_offline' if mode == 'offline' else 'sampled_inference',
                                       metrics=None if mode == 'offline' else metrics(semantic)),
                decision_statuses=dict(Counter(row['decision_status'] for row in rows)),
                semantic_responses=sum(row['semantic_response_available'] for row in rows),
                decomposition_cases_not_evaluated=sum(row['decomposition_status'] == 'not_evaluated' for row in rows))


def evaluate_relations(cases):
    """Measure explicit control routing, without claiming answer semantics."""
    policy = ClarificationPolicy(None)
    actions = {'cancel': 'cancel', 'revises_task': 'revise', 'new_topic': 'new_topic'}
    rows = []
    for case in cases:
        relation = case['expected'].get('relation')
        if relation is None:
            continue
        command = policy.relation(case['text'])
        actual = command['action'] if command else None
        expected = actions.get(relation)
        rows.append(dict(id=case['id'], expected_relation=relation, expected_control_action=expected,
                         actual_control_action=actual, action_match=actual == expected,
                         source=command.get('source') if command else None,
                         status='explicit_rule_action_measured' if case.get('relation_verification') == 'explicit_rule'
                                else 'semantic_relationship_not_verified'))
    measured = [row for row in rows if row['status'] == 'explicit_rule_action_measured']
    correct = sum(row['action_match'] for row in measured)
    return dict(scope='explicit_control_actions_only',
                explicit_action_accuracy=dict(correct=correct, total=len(measured),
                                              rate=round(correct / len(measured), 4) if measured else None),
                semantic_relationships_not_verified=sum(row['status'] == 'semantic_relationship_not_verified' for row in rows),
                answer_submission_verified=False, cases=rows)


def replay_history(data, store, source):
    source = Path(source)
    if not source.is_file():
        return dict(status='source_missing', replayed_responses=0, charged_calls=0, cases=[])
    history = json.loads(source.read_text(encoding='utf-8'))
    mapping = data['historical_replay']['record_to_case']
    frozen = {case['id']: case for case in data['cases']}
    selected, responses = [], {}
    for record in history.get('cases', []):
        identifier = mapping.get(record.get('case'))
        if identifier and identifier in frozen and isinstance(record.get('answers'), dict):
            case = frozen[identifier]
            selected.append(case)
            responses[case['text']] = record['answers']
    def transport(request):
        state = json.loads(json.loads(request.content)['state'])
        # Saved answers pass through the production response validator. Zero
        # synthetic usage is only replay scaffolding, never a new billing claim.
        return httpx.Response(200, json=dict(model='jev-1.13.0', answers=responses[state['user_request']], usage={'input_tokens': 0}))
    decisions = EvaluationDecisions(store, JevConfig(key='offline-replay'), httpx.MockTransport(transport))
    rows = evaluate_cases(selected, decisions, 'historical_replay')
    return dict(status='replayed_saved_answers', source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                original_live=history.get('live'), historical_estimated_usd=history.get('estimated_usd'),
                replayed_responses=len(rows), charged_calls=0, metrics=metrics(rows), cases=rows)


def budget_micro_usd(value):
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError('预算必须是有效美元金额') from exc
    if not amount.is_finite() or not Decimal('0.000001') <= amount <= Decimal('0.01'):
        raise ValueError('实时评测预算必须在 0.000001–0.01 美元之间')
    return int(amount * 1_000_000)


def run(data, *, live=False, max_calls=3, budget_usd='0.01', case_ids=None, limit=None, history_path=None, config=None, transport=None):
    if type(max_calls) is not int or not 1 <= max_calls <= 10:
        raise ValueError('实时评测最多允许 1–10 次请求')
    budget = budget_micro_usd(budget_usd)
    cases = data['cases'] + data.get('regression_cases', [])
    if case_ids:
        unknown = set(case_ids) - {case['id'] for case in cases}
        if unknown:
            raise ValueError('存在未知的评测样例 ID')
        cases = [case for case in cases if case['id'] in case_ids]
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError('样例数必须是正整数')
    if live:
        cases = cases[:min(limit or max_calls, max_calls)]
        if config is None:
            from dotenv import dotenv_values
            configured = {**dotenv_values(ROOT / '.hermes' / '.env'), **os.environ}
            config = JevConfig.from_env(configured)
        if not config.key:
            raise ValueError('Jev 凭据未配置，未发出网络请求')
        config = replace(config, max_calls=max_calls, budget_micro_usd=budget)
    else:
        cases = cases[:limit] if limit else cases
        # Never read credentials or honor a caller-provided key in offline mode.
        config, transport = JevConfig(key=''), None
    with tempfile.TemporaryDirectory(prefix='miniclaw-intent-evaluation-') as temporary:
        store = Store(Path(temporary) / 'inference')
        decisions = EvaluationDecisions(store, config, transport)
        mode = 'live' if live else 'offline'
        rows = evaluate_cases(cases, decisions, mode)
        regression_ids = {case['id'] for case in data.get('regression_cases', [])}
        baseline = [row for row in rows if row['id'] not in regression_ids]
        regressions = [row for row in rows if row['id'] in regression_ids]
        ledger = decisions.ledger(EVALUATION_SCOPE)
        report = dict(dataset_version=data['version'], frozen_on=data['frozen_on'],
                      dataset_sha256=hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
                      mode=mode, dataset_cases=len(data['cases']),
                      regression_dataset_cases=len(regression_ids), evaluated_cases=len(rows),
                      model=config.model, confidence_threshold=.85, probability_margin_threshold=.20,
                      online_accuracy_claim=False, summary=summarize(baseline, mode), cases=rows,
                      regression_summary=metrics(regressions),
                      expanded_rule_fallback=metrics([row for row in rows if row['verification'] == 'rule_fallback']),
                      task_controls=evaluate_relations(cases),
                      budget=dict(network_calls=ledger['calls'] if live else 0, max_calls=max_calls,
                                  budget_usd=budget / 1e6, reserved_usd=ledger['reserved_usd'],
                                  estimated_usd=ledger['estimated_usd'], estimate_is_invoice_cap=False))
        if not live:
            source = history_path or ROOT / data['historical_replay']['source']
            report['historical_replay'] = replay_history(data, Store(Path(temporary) / 'replay'), source)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=DATASET)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--history', type=Path)
    parser.add_argument('--live', action='store_true', help='显式启用少量 Jev 请求；默认完全离线')
    parser.add_argument('--max-calls', type=int, default=3)
    parser.add_argument('--budget-usd', default='0.01')
    parser.add_argument('--case-id', action='append')
    parser.add_argument('--limit', type=int)
    args = parser.parse_args(argv)
    try:
        report = run(load_dataset(args.dataset), live=args.live, max_calls=args.max_calls,
                     budget_usd=args.budget_usd, case_ids=args.case_id, limit=args.limit, history_path=args.history)
    except (ValueError, OSError, KeyError) as exc:
        # Provider exceptions are already reduced to safe reasons by JevDecisions.
        parser.exit(2, '评测未完成：' + str(exc) + '\n')
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    visible = {key: value for key, value in report.items() if key not in ('cases', 'historical_replay', 'task_controls')}
    visible['task_controls'] = {key: value for key, value in report['task_controls'].items() if key != 'cases'}
    if 'historical_replay' in report:
        visible['historical_replay'] = {key: value for key, value in report['historical_replay'].items() if key != 'cases'}
    print(json.dumps(visible, ensure_ascii=False, indent=2))
    return report


if __name__ == '__main__':
    main()
