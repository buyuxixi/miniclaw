"""Additional pure local inference after fixture repair; no gate refit or training."""
import argparse
import gc
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.formal_seven_gates import key
from scripts.decision_answer_contract import validate_answers
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',USE_TF='0',HF_HOME='D:/model/laya-runtime/cache/huggingface')

def score(out):
    from laya import load
    import torch
    requests=json.loads((out/'fixture-extra-requests.json').read_text(encoding='utf-8'));counts={}
    for label in ('round04','round05'):
        path=out/label/'scores.jsonl';done={json.loads(s)['key'] for s in path.read_text(encoding='utf-8').splitlines() if s}
        pending={k:r for k,r in requests.items() if k not in done};counts[label]=len(pending)
        agent=load(f'D:/model/laya-business-advisory/round-{label[-2:]}-formal-seven',device='cuda',backend='eager',compile=False,fast=False)
        with path.open('a',encoding='utf-8') as f:
            for ident,req in pending.items():
                raw=agent.system_one(*req,max_len=2048,head_max_len=384)
                row=dict(key=ident,status='suggested',answers=validate_answers(raw,req[1]),phase='finite-fixture-grammar-repair',latency_ms=None)
                f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush()
        del agent;gc.collect();torch.cuda.empty_cache()
    (out/'fixture-extra-scoring.json').write_text(json.dumps(counts,indent=2),encoding='utf-8');print(json.dumps(counts))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);score(p.parse_args().out.resolve())
