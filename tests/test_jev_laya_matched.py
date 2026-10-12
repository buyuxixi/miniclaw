from copy import deepcopy
import json
import pytest
from scripts.jev_laya_matched import AliasDecisions,formal_task,request_for,signature,validate_answers,replay,cases

def output(request,**choices):
    answers={}
    for head,q in request[1].items():
        choice=choices.get(head,next(iter(q['criteria'])))
        answers[head]=dict(type='choice',choice=choice,confidence=.99,
            probabilities={k:float(k==choice) for k in q['criteria']})
    return dict(status='suggested',answers=answers)

def test_missing_state_primary_collision_but_enriched_distinguishes():
    data,_=cases();pair=[c for c in data if c['family']=='region-binding']
    assert len(pair)==2
    assert request_for(formal_task(pair[0]))==request_for(formal_task(pair[1]))
    assert request_for(formal_task(pair[0]),'enriched',pair[0]['context'])!=request_for(formal_task(pair[1]),'enriched',pair[1]['context'])

def test_alias_restores_actual_target_without_altering_cached_evidence():
    task=formal_task(dict(id='x',text='旋转这张图90度',context={'selected':'img2'}))
    req=request_for(task);original=output(req,target='img2');frozen=deepcopy(original)
    state=json.loads(req[0]);state['selected']='actual-b';state['candidates'][0]['id']='actual-a';state['candidates'][1]['id']='actual-b'
    q=deepcopy(req[1]);q['target']['criteria']={dict(img1='actual-a',img2='actual-b').get(k,k):v for k,v in q['target']['criteria'].items()}
    result=AliasDecisions({signature(req):original}).evaluate(request=(json.dumps(state,ensure_ascii=False),q))
    assert result['answers']['target']['choice']=='actual-b'
    assert result['answers']['target']['probabilities']['actual-b']==1
    assert original==frozen

def test_alias_unavailable_has_no_semantic_invention():
    task=formal_task(dict(id='x',text='旋转这张图90度',context={}))
    req=request_for(task)
    result=AliasDecisions({signature(req):dict(status='unavailable')}).evaluate(request=req)
    assert result==dict(status='unavailable')

def test_invalid_or_incomplete_distribution_is_rejected():
    req=request_for(formal_task(dict(id='x',text='你好',context={})));raw=output(req)
    del raw['answers']['scope']
    with pytest.raises(ValueError,match='incomplete'):validate_answers(raw,req[1])
    raw=output(req);raw['answers']['intent']['probabilities']['draft']=float('nan')
    with pytest.raises(ValueError,match='distribution'):validate_answers(raw,req[1])

def test_shared_production_rules_still_override_model_on_explicit_draft():
    task=formal_task(dict(id='x',text='不要生成视频，只整理方案',context={}));req=request_for(task)
    result=replay(task,output(req,intent='generate_media',target='none',conflict='none'))
    assert result['intent']=='draft'
    assert result['questions']==[]
