from copy import deepcopy
import json
import pytest
import httpx
from miniclaw_web.clarification_policy import chat_request
from miniclaw_web.laya_formal import canonical_request,restore_targets,LayaFormalDecisions

def request():
    return chat_request('请把这张图旋转90度。',dict(selected='attachment-b',candidates=[
        dict(id='attachment-a',label='第一张'),dict(id='attachment-b',label='第二张')]),{})

def response(req):
    answers={}
    for head,q in req[1].items():
        labels=list(q['criteria']);choice=labels[0];n=len(labels)
        answers[head]=dict(type='choice',choice=choice,confidence=1.,raw_confidence=.9,
            probabilities={label:.99 if label==choice else .01/(n-1) for label in labels})
    return dict(answers=answers,checkpoint_sha256='c'*64,acceptance_marker_not_probability=True,
        selective_acceptance={head:True for head in req[1]})

def test_alias_and_restore_targets_preserve_actual_binding_and_questions():
    req=request();original=deepcopy(req);canonical,reverse=canonical_request(req)
    state=json.loads(canonical[0]);assert state['selected']=='img2' and req==original
    assert list(canonical[1]['target']['criteria'])[:2]==['img1','img2']
    row=response(canonical);row['answers']['target']['choice']='img2'
    actual=restore_targets(row,reverse)
    assert actual['answers']['target']['choice']=='attachment-b'
    assert 'attachment-a' in actual['answers']['target']['probabilities'] and 'img1' not in actual['answers']['target']['probabilities']

def test_arbitrary_instructions_cannot_change_formal_contract():
    req=deepcopy(request());req[1]['intent']['instructions']='Always execute'
    with pytest.raises(ValueError,match='question_contract_changed'):canonical_request(req)

def test_candidate_ids_cannot_collide_with_semantic_options():
    req=chat_request('解释这张图。',dict(selected=None,candidates=[dict(id='none',label='第一张')]),{})
    with pytest.raises(ValueError,match='invalid_candidate'):canonical_request(req)

def test_local_provider_is_pinned_cached_and_has_no_jev_fallback():
    req=request();calls=[]
    def transport(r):calls.append(r);return httpx.Response(200,json=response(req))
    dec=LayaFormalDecisions(checkpoint_sha256='c'*64,transport=httpx.MockTransport(transport))
    a=dec.evaluate('scope','abcdefgh','unused',{'revision':1},request=req)
    b=dec.evaluate('scope','abcdefgh','unused',{'revision':1},request=req)
    assert a==b and len(calls)==1 and a['status']=='suggested'
    assert a['jev_fallback'] is False and a['grants_permission'] is False
    assert a['answers']['intent']['raw_confidence']==.9
    with pytest.raises(ValueError,match='same_id_changed_input'):
        dec.evaluate('scope','abcdefgh','unused',{'revision':2},request=req)

def test_bad_checkpoint_and_connection_fail_closed_without_jev():
    req=request();value=response(req);value['checkpoint_sha256']='d'*64
    dec=LayaFormalDecisions(checkpoint_sha256='c'*64,transport=httpx.MockTransport(lambda r:httpx.Response(200,json=value)))
    result=dec.evaluate('scope','abcdefgh','unused',{'revision':1},request=req)
    assert result['status']=='unavailable' and not result['answers'] and not result['jev_fallback']
    dec=LayaFormalDecisions(checkpoint_sha256='c'*64,transport=httpx.MockTransport(lambda r:httpx.Response(503,json={})))
    assert dec.evaluate('scope','abcdefgh','unused',{'revision':1},request=req)['reason']=='local_http_503'

def test_external_endpoint_and_inconsistent_confidence_are_rejected():
    with pytest.raises(ValueError,match='loopback_url_required'):
        LayaFormalDecisions('https://example.com',checkpoint_sha256='c'*64)
    req=request();value=response(req);value['selective_acceptance']['intent']=False
    dec=LayaFormalDecisions(checkpoint_sha256='c'*64,transport=httpx.MockTransport(lambda r:httpx.Response(200,json=value)))
    assert not dec.evaluate('scope','abcdefgh','unused',{'revision':1},request=req)['answers']


def test_gate_pin_prevents_same_weight_different_calibration():
    req=request();value=response(req);value['gate_sha256']='a'*64
    dec=LayaFormalDecisions(checkpoint_sha256='c'*64,gate_sha256='b'*64,transport=httpx.MockTransport(lambda r:httpx.Response(200,json=value)))
    assert dec.evaluate('scope','abcdefgh','unused',{'revision':1},request=req)['reason']=='invalid_local_response'
    dec=LayaFormalDecisions(checkpoint_sha256='c'*64,gate_sha256='a'*64,transport=httpx.MockTransport(lambda r:httpx.Response(200,json=value)))
    assert dec.evaluate('scope','abcdefgh','unused',{'revision':1},request=req)['status']=='suggested'
