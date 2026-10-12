"""Formal-seven local candidate protocol. No Jev fallback or tool authorization."""
from copy import deepcopy
import hashlib
import json
import threading
import time
from urllib.parse import urlsplit
from .clarification_policy import chat_request,RULE_VERSION

def canonical_request(request):
    if not isinstance(request,(list,tuple)) or len(request)!=2:raise ValueError('invalid_request')
    state=json.loads(request[0])
    required={'user_request','selected','candidates','confirmed','target_versions','rules_version'}
    if not isinstance(state,dict) or set(state)!=required or state['rules_version']!=RULE_VERSION:raise ValueError('formal_primary_only')
    if not isinstance(state['user_request'],str) or not 1<=len(state['user_request'])<=1200:raise ValueError('invalid_text')
    cs=state['candidates']
    if not isinstance(cs,list) or len(cs)>12:raise ValueError('invalid_candidates')
    ids=set()
    for c in cs:
        if (not isinstance(c,dict) or set(c)!={'id','label'} or
            not all(isinstance(c[k],str) and 1<=len(c[k])<=100 for k in ('id','label')) or c['id'] in ids or c['id'] in {'none','multiple','ambiguous'}):
            raise ValueError('invalid_candidate')
        ids.add(c['id'])
    if state['selected'] is not None and (not isinstance(state['selected'],str) or state['selected'] not in ids):raise ValueError('selected_outside_candidates')
    if not isinstance(state['confirmed'],dict):raise ValueError('invalid_confirmations')
    expected=chat_request(state['user_request'],dict(selected=state['selected'],candidates=cs,versions=state['target_versions']),state['confirmed'])
    if request[1]!=expected[1]:raise ValueError('question_contract_changed')
    if len(json.dumps(request,ensure_ascii=False).encode())>12000:raise ValueError('input_byte_budget')
    aliases={c['id']:f'img{i+1}' for i,c in enumerate(cs)};reverse={v:k for k,v in aliases.items()}
    state['candidates']=[dict(id=aliases[c['id']],label=c['label']) for c in cs]
    state['selected']=aliases.get(state['selected'],state['selected'])
    for k,v in list(state['confirmed'].items()):
        if isinstance(v,str):state['confirmed'][k]=aliases.get(v,v)
    questions=deepcopy(request[1]);questions['target']['criteria']={aliases.get(k,k):v for k,v in questions['target']['criteria'].items()}
    return (json.dumps(state,ensure_ascii=False),questions),reverse

def restore_targets(row,reverse):
    clean=deepcopy(row)
    a=clean.get('answers',{}).get('target')
    if a:
        a['choice']=reverse.get(a['choice'],a['choice'])
        a['probabilities']={reverse.get(k,k):v for k,v in a['probabilities'].items()}
    return clean

class LayaFormalDecisions:
    """Jev evaluate-compatible local candidate for explicitly constructed policies.

    The app's router supplies cloud fallback separately. Pure inference has no
    business side effects; direct experimental use still has no cloud fallback.
    """
    def __init__(self,url='http://127.0.0.1:8768',checkpoint_sha256=None,transport=None,gate_sha256=None,timeout=15):
        parsed=urlsplit(url)
        if parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment:
            raise ValueError('loopback_url_required')
        if parsed.port is not None and not 1<=parsed.port<=65535:raise ValueError('invalid_local_port')
        if not isinstance(checkpoint_sha256,str) or len(checkpoint_sha256)!=64 or any(c not in '0123456789abcdef' for c in checkpoint_sha256):raise ValueError('pinned_checkpoint_required')
        if gate_sha256 is not None and (not isinstance(gate_sha256,str) or len(gate_sha256)!=64 or any(c not in '0123456789abcdef' for c in gate_sha256)):raise ValueError('invalid_gate_pin')
        if type(timeout) not in (int,float) or not 0<timeout<=30:raise ValueError('invalid_local_timeout')
        self.timeout=timeout
        self.url=url.rstrip('/');self.checkpoint=checkpoint_sha256;self.gate_pin=gate_sha256;self.transport=transport;self.memo={};self.lock=threading.RLock()
    def evaluate(self,scope,request_id,instruction,snapshot,selected=None,*,request=None,question_version=RULE_VERSION):
        from scripts.decision_answer_contract import validate_answers
        import httpx
        if question_version!=RULE_VERSION:raise ValueError('unsupported_question_version')
        try:
            canonical_request(request)  # Service canonicalizes exactly once.
        except (ValueError,TypeError,KeyError):
            return dict(status='unavailable',answers={},provider='laya-local',mode='decision_candidate',
                fallback='main_or_manual',jev_fallback=False,grants_permission=False,reason='unsupported_host_request',
                checkpoint_sha256=self.checkpoint)
        signature=hashlib.sha256(json.dumps([request,snapshot['revision'],self.checkpoint,self.gate_pin],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        ident=(scope,request_id)
        with self.lock:
            if ident in self.memo:
                old,saved=self.memo[ident]
                if old!=signature:raise ValueError('same_id_changed_input')
                return deepcopy(saved)
            row=dict(status='unavailable',answers={},provider='laya-local',mode='decision_candidate',fallback='main_or_manual',
                jev_fallback=False,grants_permission=False,checkpoint_sha256=self.checkpoint)
            start=time.perf_counter()
            try:
                with httpx.Client(transport=self.transport,timeout=self.timeout,trust_env=False,follow_redirects=False) as client:
                    response=client.post(self.url+'/v1/formal',json=dict(question_version=question_version,request=request))
                if response.status_code!=200:row['reason']='local_http_'+str(response.status_code)
                else:
                    value=response.json()
                    if value.get('checkpoint_sha256')!=self.checkpoint:raise ValueError('checkpoint_mismatch')
                    if self.gate_pin is not None and value.get('gate_sha256')!=self.gate_pin:raise ValueError('gate_mismatch')
                    answers=validate_answers(value,request[1])
                    if value.get('acceptance_marker_not_probability') is not True:raise ValueError('missing_acceptance_semantics')
                    acceptance=value.get('selective_acceptance')
                    if not isinstance(acceptance,dict) or set(acceptance)!=set(request[1]):raise ValueError('missing_selective_acceptance')
                    for head,a in answers.items():
                        if type(acceptance[head]) is not bool or a['confidence']!=float(acceptance[head]):raise ValueError('inconsistent_acceptance_marker')
                        raw_conf=value['answers'][head].get('raw_confidence')
                        if type(raw_conf) not in (float,int) or not 0<=raw_conf<=1:raise ValueError('missing_raw_confidence')
                        a['raw_confidence']=raw_conf
                    row.update(value,answers=answers,status='suggested',provider='laya-local',jev_fallback=False,grants_permission=False)
            except httpx.HTTPError:row.update(reason='local_connection_or_timeout')
            except (ValueError,TypeError,KeyError,AttributeError):row.update(reason='invalid_local_response')
            row['latency_ms']=round((time.perf_counter()-start)*1000,3)
            if len(self.memo)>=256:self.memo.pop(next(iter(self.memo)))
            self.memo[ident]=(signature,deepcopy(row));return row
