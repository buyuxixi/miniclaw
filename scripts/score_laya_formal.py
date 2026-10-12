"""Offline unchanged round-02 answers the exact formal seven-question requests."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',USE_TF='0',HF_HOME='D:/model/laya-runtime/cache/huggingface')
from scripts.decision_answer_contract import CHECKPOINT_SHA,validate_answers


def run(root):
    import torch
    from laya import load
    checkpoint=Path('D:/model/laya-business-advisory/round-02')
    with (checkpoint/'model.safetensors').open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
    if sha!=CHECKPOINT_SHA:raise ValueError('checkpoint_changed')
    requests=json.loads((root/'requests.json').read_text(encoding='utf-8'))
    model=load(str(checkpoint),device='cuda',backend='eager',compile=False,fast=False)
    if model.cfg.get('temperature')!=[1.,1.,1.]:raise ValueError('temperature_changed')
    sample=next(iter(requests.values()))
    model.system_one(sample[0],sample[1],max_len=4096,head_max_len=512)
    with (root/'laya.jsonl').open('x',encoding='utf-8') as stream:
        for key,request in requests.items():
            torch.cuda.synchronize();start=time.monotonic()
            raw=model.system_one(request[0],request[1],max_len=4096,head_max_len=512)
            torch.cuda.synchronize();elapsed=round((time.monotonic()-start)*1000,3)
            result=dict(key=key,raw=raw,latency_ms=elapsed,checkpoint_sha256=sha,status='suggested')
            try:result['answers']=validate_answers(raw,request[1])
            except ValueError as e:result.update(status='unavailable',error=str(e),answers={})
            stream.write(json.dumps(result,ensure_ascii=False)+'\n');stream.flush()
            print(json.dumps(dict(key=key[:12],status=result['status'],ms=elapsed)),flush=True)
    torch.cuda.empty_cache()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);run(p.parse_args().root)
