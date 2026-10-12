"""Expanded seven-question data with explicit correlated-family accounting."""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.build_laya_formal_data import record
from scripts.laya_round4_catalog import BLOCKS

TARGETS=dict(train=200,dev=50,calibration=100,test=100)

def expanded(split):
    bases=[line.split('|',1) for line in BLOCKS[split].strip().splitlines()]
    result=[]
    for i,(kind,text) in enumerate(bases):
        result.append((i,kind,text))
    # Additional wording is explicitly correlated and stays in its family.
    prefixes=('我的请求是：','这次的要求：','我现在想要的是：')
    extra=TARGETS[split]-len(result)
    for j in range(extra):
        i=j%len(bases);kind,text=bases[i]
        result.append((i,kind,prefixes[j//len(bases)]+text))
    return result

def build(out):
    if out.exists():raise ValueError('new_dataset_directory_required')
    review=[];seen={};texts={};outputs={}
    for split in BLOCKS:
        rows=[]
        for variant,(i,kind,text) in enumerate(expanded(split)):
            if text in texts and texts[text]!=split:raise ValueError('cross_split_text')
            texts[text]=split
            for selected in (None,'img2'):
                for profile in ('primary','enriched'):
                    r=record(kind,text,selected,profile,split,variant)
                    r['family']=f'round4-{split}-family-{i}'
                    r['source']='synthetic-author';r['wording_variant']=variant>=len(BLOCKS[split].strip().splitlines())
                    ident=json.dumps(r['request'],ensure_ascii=False,sort_keys=True)
                    if ident in seen and (seen[ident]['expected']!=r['expected'] or seen[ident]['split']!=split):
                        raise ValueError('conflicting_or_leaking_input')
                    seen[ident]=r;review.append(r)
                    rows.append(dict(state=r['request'][0],questions=r['request'][1],expected=r['expected']))
        outputs[split]=dict(rows=len(rows),utterances=len(expanded(split)),families=len(BLOCKS[split].strip().splitlines()),
            kind_counts=dict(Counter(k for _,k,_ in expanded(split))))
        outputs[split]['raw_rows']=rows
    # No accidental exact reuse of previously observed test phrases.
    previous=ROOT/'.codex/verification/laya-formal-round3-2026-10-11/data/review.json'
    if previous.exists():
        old={json.loads(r['request'][0])['user_request'] for r in json.loads(previous.read_text(encoding='utf-8'))}
        if old & {json.loads(r['request'][0])['user_request'] for r in review}:raise ValueError('previous_phrase_reused')
    out.mkdir(parents=True)
    for split,info in outputs.items():
        rows=info.pop('raw_rows');path=out/(split+'.jsonl')
        path.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
        info['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    (out/'review.json').write_text(json.dumps(review,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'questions.json').write_text(json.dumps(review[0]['request'][1],ensure_ascii=False,indent=2),encoding='utf-8')
    manifest=dict(version='formal-seven-round4-v1',outputs=outputs,
        annotation='author synthetic; base-expression families, variants and states correlated; split by base family; gold uses supplied state only',
        test_used_for_training=False,old_tests_used=False,source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        catalog_sha256=hashlib.sha256((ROOT/'scripts/laya_round4_catalog.py').read_bytes()).hexdigest())
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(outputs,ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);build(p.parse_args().out)
