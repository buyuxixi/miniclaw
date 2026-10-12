"""Observable label support and lexical overlap, without inspecting model scores."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re

def grams(text):
    text=re.sub(r'[\s，。！？：、；,.!?;:]','',text)
    return {text[i:i+3] for i in range(max(1,len(text)-2))}

def audit(out):
    review=json.loads((out/'data/review.json').read_text(encoding='utf-8'));manifest=json.loads((out/'data/manifest.json').read_text(encoding='utf-8'))
    support={};families=defaultdict(set);identical={}
    for split in manifest['outputs']:
        path=out/'data'/(split+'.jsonl')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=manifest['outputs'][split]['sha256']:raise ValueError('data_hash_changed')
        support[split]={}
        for profile in ('primary','enriched'):
            subset=[r for r in review if r['split']==split and r['profile']==profile];heads={}
            for head,q in subset[0]['request'][1].items():
                heads[head]={label:len({r['family'] for r in subset if r['expected'][head]==label}) for label in q['criteria']}
            support[split][profile]=heads
    for r in review:
        families[r['family']].add(r['split']);ident=json.dumps(r['request'],sort_keys=True,ensure_ascii=False)
        if ident in identical:
            prior=identical[ident]
            if prior['split']!=r['split'] or prior['expected']!=r['expected']:raise ValueError('leak_or_conflicting_identical_input')
        identical[ident]=r
        if set(r['expected'])!=set(r['request'][1]):raise ValueError('missing_gold_head')
        if any(value not in r['request'][1][h]['criteria'] for h,value in r['expected'].items()):raise ValueError('gold_outside_options')
    if any(len(s)!=1 for s in families.values()):raise ValueError('cross_split_family')
    bases={split:{json.loads(r['request'][0])['user_request'] for r in review if r['split']==split and not r['wording_variant']} for split in manifest['outputs']}
    train={text:grams(text) for text in bases['train']};overlap=[]
    for text in bases['test']:
        g=grams(text);score,nearest=max((len(g & tg)/len(g | tg),t) for t,tg in train.items())
        overlap.append(dict(test=text,nearest_train=nearest,trigram_jaccard=round(score,4)))
    overlap.sort(key=lambda r:r['trigram_jaccard'],reverse=True)
    result=dict(status='passed',counts=manifest['outputs'],gold_family_support=support,unique_inputs=len(identical),
        no_exact_cross_split_input_leak=True,no_conflicting_identical_gold=True,
        lexical_overlap_top20=overlap[:20],lexical_similarity_not_equivalent_to_semantic_independence=True,
        unsupported_train_labels={p:{h:[label for label,n in counts.items() if not n] for h,counts in heads.items()} for p,heads in support['train'].items()},
        limitations=['synthetic authors; base lexical families can share semantic templates',
            'primary cannot infer pending relation without pending state',
            'four states per wording and prefix variants are correlated; not independent production users'])
    (out/'data-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(status=result['status'],missing_train_labels=result['unsupported_train_labels'],overlap=overlap[:3]),ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);audit(p.parse_args().out)
