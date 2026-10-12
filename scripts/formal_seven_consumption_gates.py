"""Calibrate only observable runtime consumers; never filter with test gold."""
from copy import deepcopy
import json
from scripts.formal_seven_label_gates import fit_labels,apply_labels

EXECUTING={'execute_change','generate_media','adopt_result'}

def consumed(head,state,prediction):
    """Same mask at fit and serve, using accepted predictions and host facts."""
    if head not in ('target','scope','reference_role'):return True
    if not prediction.get('selective_acceptance',{}).get('intent'):return False
    intent=prediction.get('answers',{}).get('intent',{}).get('choice')
    if intent not in EXECUTING:return False
    if head=='reference_role':return bool(state.get('selected') and len(state['candidates'])>1)
    return True

def fit_consumption(samples):
    # Fit intent on ALL samples first, then freeze the actual consumer mask.
    base=fit_labels(samples);result=deepcopy(base)
    result['version']='formal-seven-consumption-v1'
    result['rule']+='; target/scope only accepted executing intent; role only selected multi-object executing; no gold-based eligibility'
    for head in ('target','scope','reference_role'):
        subset=[r for r in samples if consumed(head,json.loads(r['request'][0]),apply_labels(r['prediction'],base))]
        if subset:
            fitted=fit_labels(subset)['questions'][head]
        else:fitted=dict(enabled=False,labels={})
        fitted['consumer_records']=len(subset);fitted['consumer_families']=len({r['family'] for r in subset})
        result['questions'][head]=fitted
    return result

def apply_consumption(row,gates,request):
    result=apply_labels(row,gates);state=json.loads(request[0])
    for head in ('target','scope','reference_role'):
        if not consumed(head,state,result):
            if head in result.get('answers',{}):result['answers'][head]['confidence']=0.
            result['selective_acceptance'][head]=False
    return result

def candidate_domain(gates,state):
    """Names are open text; calibrated counts are explicit, not universal coverage."""
    return len(state['candidates']) in gates.get('candidate_counts',[])
