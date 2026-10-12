"""GPU scoring: calibration gates saved before any new test inference."""
import argparse
import gc
import json
import os
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.formal_seven_gates import key
from scripts.formal_seven_label_gates import fit_labels
from scripts.formal_seven_consumption_gates import fit_consumption
from scripts.decision_answer_contract import validate_answers
from scripts.evaluate_laya_formal_round3 import read,write,sha
from miniclaw_web.clarification_policy import chat_request
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',USE_TF='0',HF_HOME='D:/model/laya-runtime/cache/huggingface')

def score(out,label):
    import torch
    from laya import load
    folder=out/label
    if folder.exists():raise ValueError('no_overwrite_scores')
    folder.mkdir();manifest=read(out/'data/manifest.json');data=read(out/'data/fresh.json')
    for split,info in manifest['outputs'].items():
        if sha(out/'data'/f'{split}.jsonl')!=info['sha256']:raise ValueError('frozen_data_changed')
    checkpoint=Path(f'D:/model/laya-business-advisory/round-{label[-2:]}-formal-seven')
    agent=load(str(checkpoint),device='cuda',backend='eager',compile=False,fast=False)
    if agent.cfg.get('temperature')!=[1.,1.,1.]:raise ValueError('unexpected_temperature')
    warm=chat_request('请解释产品构图。',dict(selected=None,candidates=[dict(id='img1',label='第一张'),dict(id='img2',label='第二张')]),{})
    agent.system_one(*warm,max_len=2048,head_max_len=384);cached={};timings=[]
    with (folder/'scores.jsonl').open('x',encoding='utf-8') as stream:
        def infer(request):
            ident=key(request)
            if ident in cached:return cached[ident]
            torch.cuda.synchronize();start=time.perf_counter();raw=agent.system_one(*request,max_len=2048,head_max_len=384);torch.cuda.synchronize()
            r=dict(key=ident,status='suggested',latency_ms=round((time.perf_counter()-start)*1000,3))
            try:r['answers']=validate_answers(raw,request[1])
            except ValueError as e:r.update(status='unavailable',answers={},reason=str(e))
            cached[ident]=r;timings.append(r['latency_ms']);stream.write(json.dumps(r,ensure_ascii=False)+'\n');stream.flush();return r
        for split in ('dev','calibration','test'):
            items=[dict(r,prediction=infer(r['request'])) for r in data if r['split']==split]
            if any(not r['prediction']['answers'] for r in items):raise ValueError('invalid_score_response')
            if split=='calibration':
                for name,fit in [('label-gates',fit_labels),('consumption-gates',fit_consumption)]:
                    gates=fit(items);gates.update(checkpoint_sha256=sha(checkpoint/'model.safetensors'),profile='primary',candidate_counts=[0,1,2,3,4],
                        calibration_sha256=manifest['outputs']['calibration']['sha256'],question_sha256=key(['formal-seven',warm[1]]),
                        contract='chat-clarification-v1',frozen_before_test=True,fit_split='calibration-primary-only',name_domain='authored business names; arbitrary production names not proven')
                    write(folder/(name+'.json'),gates)
            write(folder/(split+'-detail.json'),items)
            print(json.dumps(dict(model=label,split=split,n=len(items),intent_correct=sum(r['prediction']['answers']['intent']['choice']==r['expected']['intent'] for r in items))),flush=True)
        for request in read(out/'requests.json').values():infer(request)
        # Known regression input, excluded from fresh conclusions and gate fitting.
        old=read(ROOT/'.codex/verification/laya-formal-round4-2026-10-11/data/review.json')
        for r in old:
            if r['split']=='test' and r['profile']=='primary':infer(r['request'])
    write(folder/'summary.json',dict(checkpoint_sha256=sha(checkpoint/'model.safetensors'),unique_inferences=len(cached),temperatures=agent.cfg.get('temperature'),source_sha256=sha(Path(__file__))))
    del agent;gc.collect();torch.cuda.empty_cache()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);a=p.parse_args();score(a.out,'round04');score(a.out,'round05')
