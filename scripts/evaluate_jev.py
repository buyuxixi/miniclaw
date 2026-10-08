"""Opt-in bounded live evaluation, synthetic product state only; no media uploads."""
import argparse
import json
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import dotenv_values
from miniclaw_web.creation import Creation
from miniclaw_web.decisions import JevConfig, JevDecisions
from miniclaw_web.store import Store

CASES = [
    ('保留开场和结尾，只把第二段换成瓶口特写，其他不变。', None, 'replace_visual', 'shot_02', 'clear'),
    ('只把这段换成瓶口特写。', 'shot_02', 'replace_visual', 'shot_02', 'clear'),
    ('只把这段改一下。', None, 'clarify', 'unclear', 'clear'),
    ('开场和结尾不动，第二段换成瓶口特写，同时去掉口播，结尾多停一秒。', None, 'compound', 'multiple', 'clear'),
    ('我们先聊聊怎么让画面更高级，暂时不要修改。', None, 'discuss', 'none', 'clear'),
    ('把第一段缩短一秒，其他镜头保留。', None, 'trim', 'shot_01', 'clear'),
    ('把第二张卡片拖到画布左边，素材和成片顺序都不变。', None, 'layout', 'none', 'clear'),
    ('给第二段加上口播：这款精华三天祛皱，销量第一。', None, 'edit_script', 'shot_02', 'review'),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--out', default='outputs/2026-10-07-creation-lab')
    args = parser.parse_args()
    if not args.live:
        parser.error('Use --live explicitly to permit at most eight paid decision requests.')
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    store = Store(ROOT / '.hermes/creation-evaluation')
    snapshot = Creation(store).create_sample('evaluation-sample')
    config = JevConfig.from_env(dotenv_values(ROOT / '.hermes/.env'))
    config.max_calls, config.budget_micro_usd = 8, 10_000
    service = JevDecisions(store, config)
    # Fixed evaluation scope keeps restarts from silently spending a second budget.
    scope = 'creation-evaluation-v1'
    results = []
    for i, (text, selected, action, target, fact) in enumerate(CASES):
        result = service.evaluate(scope, f'eval-case-{i:02}', text, snapshot, selected)
        answers = result.get('answers', {})
        got = {k: answers.get(k, {}).get('choice') for k in ('action', 'target', 'fact_check')}
        expected = dict(action=action, target=target, fact_check=fact)
        results.append(dict(instruction=text, selected=selected, expected=expected, got=got, exact_match=got == expected, result=result))
        print(json.dumps(dict(case=i+1, status=result['status'], got=got, exact_match=got == expected), ensure_ascii=False), flush=True)
        if result.get('reason') in ('http_401', 'http_403') or result['status'] in ('unknown', 'budget_exhausted'):
            break
    report = dict(scope=scope, cases=results, ledger=service.ledger(scope),
                  note='Small Chinese smoke evaluation, not a benchmark or comparison against the main model. Costs are estimates, not invoices.')
    (out / 'jev-evaluation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(matched=sum(r['exact_match'] for r in results), total=len(results), ledger=report['ledger']), ensure_ascii=False))


if __name__ == '__main__': main()
