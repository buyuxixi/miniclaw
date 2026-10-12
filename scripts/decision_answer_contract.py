"""Dependency-free contract shared by remote and local inference workers."""
from copy import deepcopy
import math

CHECKPOINT_SHA='d0259edb48466726cf12e99789a265e84c26895de8ff289f1c4aff58e6a05825'

def validate_answers(raw,questions):
    if not isinstance(raw,dict) or not isinstance(raw.get('answers'),dict) or set(raw['answers'])!=set(questions):
        raise ValueError('incomplete_answers')
    usage=raw.get('usage',{})
    if usage.get('truncated') or usage.get('truncated_questions') or usage.get('options'):
        raise ValueError('incomplete_inference_coverage')
    result={}
    for name,q in questions.items():
        a=raw['answers'][name];probs=a.get('probabilities')
        if (a.get('type')!='choice' or not isinstance(probs,dict) or set(probs)!=set(q['criteria'])
            or any(type(p) not in (float,int) or not math.isfinite(p) or not 0<=p<=1 for p in probs.values())
            or abs(sum(probs.values())-1)>.025 or a.get('choice') not in probs
            or probs[a['choice']]+.001<max(probs.values())):raise ValueError('invalid_distribution:'+name)
        confidence=a.get('confidence')
        if type(confidence) not in (float,int) or not math.isfinite(confidence) or not 0<=confidence<=1:
            raise ValueError('invalid_confidence:'+name)
        result[name]=dict(type='choice',choice=a['choice'],confidence=confidence,probabilities=deepcopy(probs))
    return result
