"""GPU scoring; freeze global and per-label gates before opening new test."""
import argparse
import gc
import json
import os
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.decision_answer_contract import validate_answers
from scripts.formal_seven_gates import key,fit,apply_gates
from scripts.formal_seven_label_gates import fit_labels,apply_labels
from scripts.evaluate_laya_formal_round3 import read,write,sha
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',USE_TF='0',HF_HOME='D:/model/laya-runtime/cache/huggingface')

def score(out,label,checkpoint):
    import torch
    from laya import load
    folder=out/label
    if folder.exists():raise ValueError('scoring_exists_no_overwrite')
    folder.mkdir();data=read(out/'data/review.json');manifest=read(out/'data/manifest.json')
    for split,info in manifest['outputs'].items():
        if sha(out/'data'/f'{split}.jsonl')!=info['sha256']:raise ValueError('frozen_data_changed')
    model=load(str(checkpoint),device='cuda',backend='eager',compile=False,fast=False)
    if model.cfg.get('temperature')!=[1.,1.,1.]:raise ValueError('unexpected_temperature')
    model.system_one(data[0]['request'][0],data[0]['request'][1],max_len=2048,head_max_len=384)
    cached={};summary={};all_gates={}
    with (folder/'scores.jsonl').open('x',encoding='utf-8') as stream:
        def infer(request):
            ident=key(request)
            if ident in cached:return cached[ident]
            torch.cuda.synchronize();start=time.perf_counter()
            raw=model.system_one(request[0],request[1],max_len=2048,head_max_len=384)
            torch.cuda.synchronize();row=dict(key=ident,raw=raw,status='suggested',latency_ms=round((time.perf_counter()-start)*1000,3))
            try:row['answers']=validate_answers(raw,request[1])
            except ValueError as error:row.update(status='unavailable',answers={},error=str(error))
            cached[ident]=row;stream.write(json.dumps(row,ensure_ascii=False)+'\n');stream.flush();return row
        for split in ('dev','calibration','test'):
            items=[dict(r,prediction=infer(r['request'])) for r in data if r['split']==split]
            if split=='calibration':
                for profile in ('primary','enriched'):
                    group=[r for r in items if r['profile']==profile]
                    global_gates=fit(group);label_gates=fit_labels(group)
                    for gate in (global_gates,label_gates):
                        gate.update(checkpoint_sha256=sha(checkpoint/'model.safetensors'),profile=profile,
                            calibration_sha256=manifest['outputs']['calibration']['sha256'],
                            question_sha256=key(['formal-seven',read(out/'data/questions.json')]),frozen_before_test=True)
                        gate['fit_split']='calibration-'+profile+'-only'
                    all_gates[profile]=dict(global_gates=global_gates,label_gates=label_gates)
                write(folder/'gates.json',all_gates['primary']['global_gates'])
                write(folder/'label-gates.json',all_gates['primary']['label_gates'])
                write(folder/'profile-gates.json',all_gates)
            write(folder/f'{split}-detail.json',items)
            summary[split]={}
            for profile in ('primary','enriched'):
                group=[r for r in items if r['profile']==profile];heads={}
                for head in group[0]['expected']:
                    stats=dict(total=len(group),raw_correct=0,global_accepted=0,global_correct=0,label_accepted=0,label_correct=0)
                    for r in group:
                        pred=r['prediction'];correct=pred.get('answers',{}).get(head,{}).get('choice')==r['expected'][head]
                        stats['raw_correct']+=correct
                        if profile in all_gates:
                            for prefix,fn,field in (('global',apply_gates,'global_gates'),('label',apply_labels,'label_gates')):
                                if fn(pred,all_gates[profile][field])['selective_acceptance'].get(head):
                                    stats[prefix+'_accepted']+=1;stats[prefix+'_correct']+=correct
                    heads[head]=stats
                summary[split][profile]=heads
            print(json.dumps(dict(model=label,split=split,summary=summary[split]),ensure_ascii=False),flush=True)
        for request in read(out/'requests.json').values():infer(request)
    write(folder/'summary.json',dict(checkpoint=str(checkpoint),checkpoint_sha256=sha(checkpoint/'model.safetensors'),splits=summary,
        unique_inferences=len(cached),source_sha256=sha(Path(__file__)),temperatures=model.cfg.get('temperature')))
    del model;gc.collect();torch.cuda.empty_cache()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);a=p.parse_args()
    score(a.out,'round03',Path('D:/model/laya-business-advisory/round-03-formal-seven'))
    score(a.out,'round04',Path('D:/model/laya-business-advisory/round-04-formal-seven'))
