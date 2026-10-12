"""Compare original/trained checkpoints; fit gates on calibration, then freeze test."""
from __future__ import annotations
import argparse
from collections import Counter
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from miniclaw_web.laya_advisory import VERSION, CATEGORIES, INTENTS, questions, question_sha256, parse_prediction, advisory
os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', USE_TF='0',
                  HF_HOME='D:/model/laya-runtime/cache/huggingface')

def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')

def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def records(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line]

def wilson_lower(correct, count):
    # 95% Wilson interval; descriptive evidence, not a deployment accuracy guarantee.
    if not count: return 0.
    z=1.96; p=correct/count
    return (p+z*z/(2*count)-z*math.sqrt((p*(1-p)+z*z/(4*count))/count))/(1+z*z/count)

def fit_gates(samples):
    result = dict(version=VERSION, kind='exploratory_calibration', source='calibration.jsonl only',
                  rule='Grid 0.50..0.99; margin>=0.1; >=12 accepted and zero observed errors per question. A suggested label needs >=3 accepted observations. Direct clarification needs >=12 correct observations of that reason. Small author-labelled samples are not production guarantees.',
                  questions={})
    for name in questions():
        chosen = None
        for threshold in [i/100 for i in range(50, 100)]:
            accepted = [s for s in samples if s.get('parsed') and s['parsed'][name]['probability'] >= threshold and s['parsed'][name]['margin'] >= .1]
            correct = sum(s['parsed'][name]['choice'] == s['gold'][name] for s in accepted)
            if len(accepted) >= 12 and correct == len(accepted):
                support = Counter(s['parsed'][name]['choice'] for s in accepted)
                chosen = dict(enabled=True, threshold=threshold, accepted=len(accepted), errors=0,
                              labels=[label for label,n in support.items() if n>=3],
                              label_support=dict(support), wilson_lower_95=round(wilson_lower(correct,len(accepted)),4),
                              direct_labels=[label for label,n in support.items() if n>=12 and label in ('target','region')])
                break
        result['questions'][name] = chosen or dict(enabled=False, threshold=1., labels=[], direct_labels=[], reason='Insufficient error-free calibration coverage')
    return result

def macro_f1(pairs, labels):
    values=[]
    for label in labels:
        tp=sum(g==label and p==label for g,p in pairs)
        fp=sum(g!=label and p==label for g,p in pairs)
        fn=sum(g==label and p!=label for g,p in pairs)
        if tp+fp+fn: values.append(2*tp/(2*tp+fp+fn))
    return round(sum(values)/len(values),4) if values else None

def summarize(samples, gates):
    n=len(samples); valid=[s for s in samples if s.get('parsed')]
    accuracy={name:sum(s['parsed'][name]['choice']==s['gold'][name] for s in valid)/n for name in questions()}
    execution={'execute_change','generate_media','adopt_result'}
    joint=0; cats_exact=0; false_exec=0; unnecessary=0; missing=0; skipped=0; accepted_intent=0; correct_intent=0
    category_tp=category_fp=category_fn=0; positive_suggestions=positive_correct=0
    per_category={}
    for c in CATEGORIES:
        tp=sum(s['gold']['category_'+c]=='yes' and s['parsed']['category_'+c]['choice']=='yes' for s in valid)
        fp=sum(s['gold']['category_'+c]=='no' and s['parsed']['category_'+c]['choice']=='yes' for s in valid)
        fn=sum(s['gold']['category_'+c]=='yes' and s['parsed']['category_'+c]['choice']=='no' for s in valid)
        per_category[c]=dict(positive_support=sum(s['gold']['category_'+c]=='yes' for s in samples),
                             true_positive=tp,false_positive=fp,false_negative=fn,
                             positive_f1=round(2*tp/(2*tp+fp+fn),4) if 2*tp+fp+fn else None)
    for s in samples:
        if not s.get('parsed'): continue
        parsed=s['parsed']; gold=s['gold']
        predicted={c for c in CATEGORIES if parsed['category_'+c]['choice']=='yes'}
        expected={c for c in CATEGORIES if gold['category_'+c]=='yes'}
        cats_exact+=predicted==expected
        category_tp+=len(predicted&expected);category_fp+=len(predicted-expected);category_fn+=len(expected-predicted)
        joint+=all(parsed[q]['choice']==gold[q] for q in questions())
        false_exec+=parsed['intent']['choice'] in execution and gold['intent'] not in execution
        unnecessary+=parsed['clarification']['choice']!='none' and gold['clarification']=='none'
        missing+=parsed['clarification']['choice']=='none' and gold['clarification']!='none'
        advice=advisory(s['raw'],s['context'],gates)
        s['advice']=advice
        if advice['intent'] is not None:
            accepted_intent+=1;correct_intent+=advice['intent']==gold['intent']
        positive_suggestions+=len(advice['categories'])
        positive_correct+=len(set(advice['categories'])&expected)
        skipped+=advice['main_model_required'] is False
    denom=2*category_tp+category_fp+category_fn
    return dict(cases=n, valid=len(valid), intent_correct=round(accuracy['intent']*n),
                intent_accuracy=round(accuracy['intent'],4),
                intent_macro_f1=macro_f1([(s['gold']['intent'],s['parsed']['intent']['choice']) for s in valid],INTENTS),
                clarification_correct=round(accuracy['clarification']*n),
                clarification_accuracy=round(accuracy['clarification'],4),
                categories_exact_correct=cats_exact, categories_exact_accuracy=round(cats_exact/n,4),
                category_micro_f1=round(2*category_tp/denom,4) if denom else None,
                per_category=per_category,
                per_question_accuracy={k:round(v,4) for k,v in accuracy.items()}, joint_correct=joint,
                false_execution_suggestions=false_exec, unnecessary_clarification_suggestions=unnecessary,
                missed_clarification_suggestions=missing,
                gated_intent_suggestions=accepted_intent,gated_intent_correct=correct_intent,
                gated_positive_categories=positive_suggestions,gated_positive_categories_correct=positive_correct,
                direct_question_candidates=skipped,
                warm_inference_ms_median=round(statistics.median(s['latency_ms'] for s in samples),2),
                limitation='Raw suggestions, not executed actions; no native main-model/tool-flow benchmark in this run.')

def evaluate_checkpoint(checkpoint, data, out):
    import torch
    from laya import load
    out.mkdir()
    agent=load(str(checkpoint),device='cuda',backend='eager',compile=False,fast=False)
    # Fix raw fp32 weights and temperature=1 for both arms. Entropy confidence is not
    # used as an accuracy estimate; gates use option probabilities on held-out data.
    if agent.cfg.get('temperature') != [1.,1.,1.]:
        raise ValueError('Unexpected trained temperature; need an explicit calibration comparison')
    sample=records(data/'dev.jsonl')[0]
    warmup=agent.system_one(sample['state'], sample['questions'],max_len=2048,head_max_len=384)
    write(out/'warmup.json',warmup)
    gates=None;split_summaries={}
    for split in ('dev','calibration','test'):
        samples=[]
        path=out/(split+'.jsonl')
        with path.open('x',encoding='utf-8') as stream:
            for i,row in enumerate(records(data/(split+'.jsonl'))):
                torch.cuda.synchronize();start=time.perf_counter()
                raw=agent.system_one(row['state'],row['questions'],max_len=2048,head_max_len=384)
                torch.cuda.synchronize();latency=(time.perf_counter()-start)*1000
                sample=dict(index=i, text=row['state']['user_request'], context=row['state']['context'],
                            gold=row['expected'], raw=raw, latency_ms=round(latency,3))
                try: sample['parsed']=parse_prediction(raw)
                except ValueError as error: sample.update(parsed=None,error=str(error))
                stream.write(json.dumps(sample,ensure_ascii=False,allow_nan=False)+'\n');stream.flush()
                samples.append(sample)
        if split=='calibration':
            gates=fit_gates(samples)
            gates.update(checkpoint_sha256=sha(checkpoint/'model.safetensors'),
                         question_sha256=question_sha256(), question_file_sha256=sha(data/'questions.json'),
                         calibration_sha256=sha(data/'calibration.jsonl'))
            write(out/'gates.json',gates)
        effective_gates=gates or dict(version=VERSION,questions={})
        split_summaries[split]=summarize(samples,effective_gates)
        write(out/(split+'-advice.json'),samples)
        print(json.dumps({'checkpoint':str(checkpoint),'split':split,'summary':split_summaries[split]},ensure_ascii=False),flush=True)
    write(out/'summary.json',dict(checkpoint=str(checkpoint), checkpoint_sha256=sha(checkpoint/'model.safetensors'),
                                 temperature='Both arms preserve temperature=1; selective gates fitted only on calibration',
                                 inference_budget=dict(max_len=2048,head_max_len=384),splits=split_summaries))
    del agent;gc.collect();torch.cuda.empty_cache()
    return split_summaries

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--data',type=Path,required=True);p.add_argument('--checkpoint',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    if args.out.exists():raise ValueError('Use a new report directory')
    manifest=json.loads((args.data/'manifest.json').read_text(encoding='utf-8'))
    for split,details in manifest['outputs'].items():
        if sha(args.data/(split+'.jsonl'))!=details['sha256']:raise ValueError('Data changed since audit')
    args.out.mkdir(parents=True)
    write(args.out/'manifest.json',dict(data=manifest,script_sha256=sha(Path(__file__)),status='running',test_used_for_thresholds=False))
    results={}
    for label,path in [('original',Path('D:/model/laya-multilingual')),('trained',args.checkpoint)]:
        results[label]=evaluate_checkpoint(path,args.data,args.out/label)
    write(args.out/'comparison.json',results)
    write(args.out/'manifest.json',dict(data=manifest,script_sha256=sha(Path(__file__)),status='completed',test_used_for_thresholds=False))

if __name__=='__main__':main()
