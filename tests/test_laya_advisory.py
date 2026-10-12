"""Host boundary regressions; model confidence must not become execution consent."""
from copy import deepcopy
import math
import pytest

from miniclaw_web.laya_advisory import VERSION, LayaAdvisoryClient, advisory, build_state, parse_prediction, questions, question_sha256
from scripts.build_laya_advisory_data import audit, parse_cases
from scripts.evaluate_laya_advisory import fit_gates


def raw(intent='execute_change', clarification='target'):
    answers={}
    for name,schema in questions().items():
        label=intent if name=='intent' else clarification if name=='clarification' else 'yes'
        labels=list(schema['criteria'])
        answers[name]={'choice':label,'probabilities':{key:.99 if key==label else .01/(len(labels)-1) for key in labels}}
    return {'answers':answers,'usage':{'truncated':False}}


def gates():
    return {'version':VERSION,'questions':{name:{'enabled':True,'threshold':.9,'labels':list(schema['criteria']),
                                                'direct_labels':['target','region']} for name,schema in questions().items()}}


def ctx(**kw):
    return {'needs_existing_target':True,'target_bound':False,'region_bound':False,**kw}


def test_direct_question_only_asks_and_never_authorizes():
    result=advisory(raw(),ctx(),gates())
    assert result['question']['template']=='Q_TARGET'
    assert result['main_model_required'] is False
    assert result['execution_authorized'] is False


@pytest.mark.parametrize('intent',['discuss','draft','propose_change','revise_task','cancel','new_topic','unclear'])
def test_read_only_and_controls_cannot_turn_into_target_questions(intent):
    result=advisory(raw(intent),ctx(),gates())
    assert result['question'] is None and result['main_model_required'] is True


@pytest.mark.parametrize('state',[
    ctx(target_bound=True),ctx(selected='already-bound'),ctx(draft_only=True),
    ctx(needs_existing_target=False),{},
])
def test_known_target_or_nonexisting_target_task_is_not_reasked(state):
    assert advisory(raw(),state,gates())['question'] is None


def test_region_question_requires_missing_location_not_just_model_score():
    r=raw(clarification='region')
    assert advisory(r,ctx(target_bound=True),gates())['question']['template']=='Q_SCOPE'
    assert advisory(r,ctx(target_bound=True,selection='top-left'),gates())['question'] is None
    assert advisory(r,ctx(target_bound=True,region_bound=True),gates())['question'] is None


@pytest.mark.parametrize('reason',['intent','conflict','none'])
def test_generic_model_judgments_remain_advisory(reason):
    assert advisory(raw(clarification=reason),ctx(),gates())['main_model_required'] is True


def test_no_calibration_or_insufficient_label_support_does_not_activate():
    r=raw()
    assert advisory(r,ctx(),None)['status']=='fallback'
    g=gates();g['questions']['intent']['labels']=[]
    assert advisory(r,ctx(),g)['intent'] is None
    g=gates();g['questions']['clarification']['direct_labels']=[]
    assert advisory(r,ctx(),g)['question'] is None


@pytest.mark.parametrize('change',[
    lambda r:r['usage'].update(truncated=True),
    lambda r:r['usage'].update(truncated_questions=['intent']),
    lambda r:r['usage'].update(options={'intent':{'total':10,'distinct':9}}),
    lambda r:r['answers'].pop('category_image'),
    lambda r:r['answers']['intent']['probabilities'].update(discuss=math.nan),
    lambda r:r['answers']['intent']['probabilities'].update(discuss=True),
    lambda r:r['answers']['intent'].update(choice='discuss'),
])
def test_invalid_incomplete_or_nonfinite_outputs_fall_back(change):
    r=raw();change(r)
    assert advisory(r,ctx(),gates())['status']=='fallback'


def test_multiple_business_categories_are_not_single_choice_route():
    result=advisory(raw(),ctx(),gates())
    assert 'narration' in result['categories'] and 'video' in result['categories']
    assert result['execution_authorized'] is False


def test_input_refuses_silent_truncation_and_annotation_leakage():
    with pytest.raises(ValueError):build_state('x'*1201,{})
    with pytest.raises(ValueError):build_state('讨论一下',{'gold':'discuss'})
    with pytest.raises(ValueError):build_state('讨论一下',{'selected':'foreign','candidates':[]})


def test_family_and_full_input_overlap_are_rejected():
    rows=parse_cases('discuss|none|image|先讨论图片。|missing','dev',('陶瓷杯',))
    duplicate=deepcopy(rows[0]);duplicate.update(id='different-id',split='test')
    with pytest.raises(ValueError):audit(rows+[duplicate])
    duplicate['text']='评价一下图片。'
    with pytest.raises(ValueError):audit(rows+[duplicate])


def test_threshold_fit_cannot_enable_unseen_labels_or_tiny_samples():
    r=raw('discuss','none');parsed=parse_prediction(r)
    gold={name:item['choice'] for name,item in parsed.items()}
    assert not fit_gates([{'parsed':parsed,'gold':gold}]*3)['questions']['intent']['enabled']
    fitted=fit_gates([{'parsed':parsed,'gold':gold}]*12)
    assert fitted['questions']['intent']['labels']==['discuss']
    assert fitted['questions']['clarification']['direct_labels']==[]


@pytest.mark.parametrize('url',['https://127.0.0.1:8767','http://example.com','http://user:password@localhost',
                               'http://localhost/path','http://localhost?token=secret'])
def test_client_refuses_remote_or_credentialled_endpoints(url):
    with pytest.raises(ValueError):LayaAdvisoryClient(url,gates())


@pytest.mark.parametrize('wrong_checkpoint',[False,True])
def test_real_http_client_checks_identity_and_derives_advice_locally(wrong_checkpoint):
    import json
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    import threading
    gate=gates();gate.update(question_sha256=question_sha256(),checkpoint_sha256='a'*64)
    requests=[]
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            payload={'contract_version':VERSION,'checkpoint_sha256':('b' if wrong_checkpoint else 'a')*64,
                     'raw':raw('discuss','none'),'advice':{'execution_authorized':True}}
            body=json.dumps(payload).encode()
            self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    try:
        client=LayaAdvisoryClient(f'http://127.0.0.1:{server.server_port}',gate)
        result=client.evaluate('这张图需要修改吗？先讨论。',ctx())
        assert requests[0]['state']['user_request'].endswith('先讨论。')
        assert result['advice']['execution_authorized'] is False
        assert result['advice']['question'] is None
        assert result['status']==('fallback' if wrong_checkpoint else 'received')
    finally:
        server.shutdown();server.server_close();worker.join()


def test_native_auxiliary_score_cannot_override_read_only_or_bind_unknown_target():
    from scripts.evaluate_native_fastpath import NativePolicy
    policy=NativePolicy('laya_business',{},None,None,'isolated')
    task={'text':'这张图要不要旋转？我们只讨论。','confirmed':{},
          'context':{'semantic':{'selected':None,'candidates':[{'id':'one','label':'第一张'}]}}}
    policy.business_result={'status':'received','advice':{'intent':'execute_change','question':None}}
    assert policy.guard(task,'miniclaw_edit_image',{'source_id':'one','operation':'rotate','params':{'angle':90}})['template']=='Q_INTENT'
    task['text']='把这张图旋转90度'
    assert policy.guard(task,'miniclaw_edit_image',{'source_id':'one','operation':'rotate','params':{'angle':90}})['template']=='Q_TARGET'


def test_question_fingerprint_ignores_file_newlines_but_preserves_option_order(tmp_path):
    import json,hashlib
    value=questions()
    path=tmp_path/'questions.json'
    path.write_bytes(json.dumps(value,ensure_ascii=False,indent=2).replace('\n','\r\n').encode('utf-8'))
    recovered=json.loads(path.read_text(encoding='utf-8'))
    fingerprint=lambda q:hashlib.sha256(json.dumps(q,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    assert fingerprint(recovered)==question_sha256()
    recovered['intent']['criteria']=dict(reversed(list(recovered['intent']['criteria'].items())))
    assert fingerprint(recovered)!=question_sha256()
