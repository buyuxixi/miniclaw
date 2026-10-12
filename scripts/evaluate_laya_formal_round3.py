"""Local before/after scoring and independently frozen selective calibration."""
import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.decision_answer_contract import validate_answers
from scripts.formal_seven_gates import key,fit,apply_gates
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',USE_TF='0',HF_HOME='D:/model/laya-runtime/cache/huggingface')

def read(path):return json.loads(path.read_text(encoding='utf-8'))
def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def score(out,label,checkpoint):
    import torch
    from laya import load
    folder=out/label
    if folder.exists():raise ValueError('existing_scoring_no_overwrite')
    folder.mkdir();data=read(out/'data/review.json');manifest=read(out/'data/manifest.json')
    for split,info in manifest['outputs'].items():
        if sha(out/'data'/f'{split}.jsonl')!=info['sha256']:raise ValueError('frozen_data_changed')
    model=load(str(checkpoint),device='cuda',backend='eager',compile=False,fast=False)
    if model.cfg.get('temperature')!=[1.,1.,1.]:raise ValueError('unexpected_temperature')
    model.system_one(data[0]['request'][0],data[0]['request'][1],max_len=2048,head_max_len=384)
    cache={};gates=None;summary={}
    with (folder/'scores.jsonl').open('x',encoding='utf-8') as stream:
        def infer(request):
            ident=key(request)
            if ident in cache:return cache[ident]
            torch.cuda.synchronize();start=time.perf_counter()
            raw=model.system_one(request[0],request[1],max_len=2048,head_max_len=384)
            torch.cuda.synchronize();row=dict(key=ident,raw=raw,status='suggested',latency_ms=round((time.perf_counter()-start)*1000,3))
            try:row['answers']=validate_answers(raw,request[1])
            except ValueError as error:row.update(status='unavailable',answers={},error=str(error))
            cache[ident]=row;stream.write(json.dumps(row,ensure_ascii=False)+'\n');stream.flush();return row
        for split in ('dev','calibration','test'):
            items=[]
            for record in data:
                if record['split']!=split:continue
                row=dict(record,prediction=infer(record['request']));items.append(row)
            if split=='calibration':
                gates=fit([r for r in items if r['profile']=='primary'])
                gates.update(checkpoint_sha256=sha(checkpoint/'model.safetensors'),question_sha256=key(['formal-seven',read(out/'data/questions.json')]),
                    calibration_sha256=manifest['outputs']['calibration']['sha256'],frozen_before_test=True)
                write(folder/'gates.json',gates)
            write(folder/f'{split}-detail.json',items)
            summary[split]={}
            for profile in ('primary','enriched'):
                rs=[r for r in items if r['profile']==profile];heads={}
                for head in rs[0]['expected']:
                    accepted=[]
                    for r in rs:
                        if gates and apply_gates(r['prediction'],gates)['selective_acceptance'].get(head):accepted.append(r)
                    heads[head]=dict(total=len(rs),correct=sum(r['prediction'].get('answers',{}).get(head,{}).get('choice')==r['expected'][head] for r in rs),
                        gated=len(accepted),gated_correct=sum(r['prediction']['answers'][head]['choice']==r['expected'][head] for r in accepted))
                summary[split][profile]=heads
            print(json.dumps(dict(model=label,split=split,summary=summary[split]),ensure_ascii=False),flush=True)
        for request in read(out/'requests.json').values():infer(request)
    write(folder/'summary.json',dict(checkpoint=str(checkpoint),checkpoint_sha256=sha(checkpoint/'model.safetensors'),splits=summary,unique_inferences=len(cache)))
    del model;gc.collect();torch.cuda.empty_cache()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);args=p.parse_args()
    score(args.out,'round02',Path('D:/model/laya-business-advisory/round-02'))
    score(args.out,'round03',Path('D:/model/laya-business-advisory/round-03-formal-seven'))
