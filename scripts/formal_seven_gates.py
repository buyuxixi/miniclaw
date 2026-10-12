"""Selective advisory gates; never fills a target or grants execution permission."""
from copy import deepcopy
from collections import Counter
import hashlib
import json

def key(request):return hashlib.sha256(json.dumps(request,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def fit(samples):
    heads=list(samples[0]['expected']);result=dict(version='formal-seven-selective-v1',fit_split='calibration-primary-only',
        rule='probability grid .50..99; margin>=.20; >=12 accepted from >=6 phrase families; zero observed errors; each label >=3 phrase families; exploratory not production guarantee',questions={})
    for head in heads:
        chosen=None
        for threshold in (i/100 for i in range(50,100)):
            accepted=[]
            for row in samples:
                a=row['prediction'].get('answers',{}).get(head)
                if not a:continue
                probs=sorted(a['probabilities'].values(),reverse=True)
                if probs[0]>=threshold and probs[0]-probs[1]>=.2:accepted.append(row)
            if len(accepted)<12 or len({r['family'] for r in accepted})<6:continue
            if any(r['prediction']['answers'][head]['choice']!=r['expected'][head] for r in accepted):continue
            labels=sorted({r['prediction']['answers'][head]['choice'] for r in accepted})
            support={label:len({r['family'] for r in accepted if r['prediction']['answers'][head]['choice']==label}) for label in labels}
            allowed=[label for label in labels if support[label]>=3]
            if not allowed:continue
            retained=[r for r in accepted if r['prediction']['answers'][head]['choice'] in allowed]
            if len(retained)<12 or len({r['family'] for r in retained})<6:continue
            chosen=dict(enabled=True,threshold=threshold,labels=allowed,accepted=len(retained),families=len({r['family'] for r in retained}),
                errors=0,label_family_support=support)
            break
        result['questions'][head]=chosen or dict(enabled=False,threshold=1.,labels=[],reason='insufficient_error_free_independent_family_support')
    return result

def apply_gates(row,gates):
    clean=deepcopy(row);accepted={}
    for head,a in clean.get('answers',{}).items():
        rule=gates['questions'].get(head,{});p=sorted(a['probabilities'].values(),reverse=True)
        ok=bool(rule.get('enabled') and a['choice'] in rule['labels'] and p[0]>=rule['threshold'] and p[0]-p[1]>=.2)
        accepted[head]=ok;a['raw_confidence']=a['confidence']
        # Adapter acceptance marker for existing high(); not a correctness probability.
        a['confidence']=1. if ok else 0.
    clean['selective_acceptance']=accepted;clean['acceptance_marker_not_probability']=True
    return clean

class GatedDecisions:
    def __init__(self,decisions,gates):self.decisions=decisions;self.gates=gates
    def evaluate(self,*a,**kw):return apply_gates(self.decisions.evaluate(*a,**kw),self.gates)
