"""Three bounded text-only Jev checks in an isolated ledger. No agent/media execution."""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from dataclasses import replace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'hermes-agent')]
from miniclaw_web.store import Store
from miniclaw_web.clarification_policy import ClarificationPolicy, chat_request
from miniclaw_web.decisions import JevDecisions, JevConfig


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.live:
        from dotenv import dotenv_values
        configured = dotenv_values(ROOT / '.hermes' / '.env')
        for key in ('TYPESAFE_API_KEY','JEV_API_KEY','JEV_API'):
            if configured.get(key) and not os.environ.get(key): os.environ[key] = configured[key]
    cases = [('draft','只优化提示词，先不生成图片'),('execute','把当前图片水平翻转，其他内容保留'),('paid','确认生成一张新图片，保留当前图片作为原版')]
    with tempfile.TemporaryDirectory(prefix='miniclaw-jev-chat-') as temporary:
        config = replace(JevConfig.from_env(), max_calls=3, budget_micro_usd=10000)
        if not args.live: config = replace(config, key='')
        decisions = JevDecisions(Store(temporary), config)
        policy = ClarificationPolicy(decisions)
        result = []
        for name, text in cases:
            task = dict(id=name,text=text,confirmed={},context={'semantic':{'selected':'image','candidates':[{'id':'image','label':'当前图片'}]}})
            intent, decision, questions = policy.classify(task)
            result.append(dict(case=name,intent=intent,status=decision['status'],reason=decision.get('reason'),questions=[q['template'] for q in questions],
                               answers=decision.get('answers'),estimated_micro_usd=decision.get('estimated_micro_usd',0),latency_ms=decision.get('latency_ms')))
        report = dict(live=args.live,calls=sum(decisions.ledger('chat:'+name)['calls'] for name,_ in cases),budget_usd=.01,
                      estimated_usd=sum(r['estimated_micro_usd'] for r in result)/1e6,cases=result)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='cases'},ensure_ascii=False))
    for r in result: print(json.dumps({k:v for k,v in r.items() if k!='answers'},ensure_ascii=False))


if __name__ == '__main__': main()
