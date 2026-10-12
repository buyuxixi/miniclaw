"""Per-label experimental calibration fitted only on independent calibration data."""
from copy import deepcopy

def fit_labels(samples, min_families=4):
    gates=dict(version='formal-seven-per-label-v1',fit_split='calibration-primary-only',
        rule=f'per-label top1 grid .50..99; margin>=.20; >=8 records from >={min_families} base families; zero observed errors; not a probability guarantee',questions={})
    for head in samples[0]['expected']:
        labels=sorted({r['prediction'].get('answers',{}).get(head,{}).get('choice') for r in samples}-{None})
        rules={}
        for label in labels:
            for threshold in (i/100 for i in range(50,100)):
                accepted=[]
                for r in samples:
                    a=r['prediction'].get('answers',{}).get(head)
                    if not a or a['choice']!=label:continue
                    p=sorted(a['probabilities'].values(),reverse=True)
                    if len(p)>1 and p[0]>=threshold and p[0]-p[1]>=.2:accepted.append(r)
                families={r['family'] for r in accepted}
                if len(accepted)<8 or len(families)<min_families:continue
                if any(r['expected'][head]!=label for r in accepted):continue
                rules[label]=dict(threshold=threshold,accepted=len(accepted),families=len(families),errors=0)
                break
        gates['questions'][head]=dict(enabled=bool(rules),labels=rules)
    return gates

def apply_labels(row,gates):
    clean=deepcopy(row);accepted={}
    for head,a in clean.get('answers',{}).items():
        rule=gates['questions'].get(head,{}).get('labels',{}).get(a['choice'])
        p=sorted(a['probabilities'].values(),reverse=True)
        ok=bool(rule and len(p)>1 and p[0]>=rule['threshold'] and p[0]-p[1]>=.2)
        accepted[head]=ok;a['raw_confidence']=a['confidence'];a['confidence']=1. if ok else 0.
    clean['selective_acceptance']=accepted;clean['acceptance_marker_not_probability']=True
    return clean
