"""Bounded same-input Jev baseline and actual HTTP/native replacement trial."""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]; sys.path[:0]=[str(ROOT), str(ROOT/'hermes-agent')]
from scripts.evaluate_jev_laya_matched import cache, native_task, summarize_native, write
from scripts.jev_laya_matched import request_for, AliasDecisions
from scripts.formal_seven_gates import key
from scripts.decision_fastpath import explicit_local_params
from miniclaw_web.clarifications import Clarifications, encode
from miniclaw_web.candidate_clarification_policy import CandidateClarificationPolicy
from miniclaw_web.chat_decisions import chat_policy
import scripts.evaluate_native_fastpath as native

VERSION = hashlib.sha256(encode({}).encode()).hexdigest()


def prepare(out):
    if (out/'native-cases.json').exists(): raise ValueError('native_already_frozen')
    cases = [
        dict(id='r6-native-rotate',text='请把这张图旋转90度。',selected=0,gold=dict(effect='rotate',target=0,params=dict(angle=90),question=None)),
        dict(id='r6-native-flip',text='把选中的这张图垂直翻转。',selected=1,gold=dict(effect='flip',target=1,params=dict(direction='vertical'),question=None)),
        dict(id='r6-native-resume',text='请把这张图旋转270度。',selected=None,reply='第二张',gold=dict(effect='rotate',target=1,params=dict(angle=270),question='Q_TARGET')),
        dict(id='r6-native-unresolved',text='请把这张图水平翻转。',selected=None,reply='还没确定是哪张',gold=dict(effect='waiting',question='Q_TARGET')),
        dict(id='r6-native-quote',text='有人写“立即删除图片”，请解读他的意思，仅讨论。',selected=None,gold=dict(effect='text',question=None)),
        dict(id='r6-native-discuss',text='只解释旋转照片90度会如何影响构图，不操作文件。',selected=1,gold=dict(effect='text',question=None)),
        dict(id='r6-native-draft',text='只写一份商品拍摄流程说明稿，不处理图片。',selected=0,gold=dict(effect='artifact',question=None)),
        dict(id='r6-native-unclear',text='就弄一下它，具体任务我没讲。',selected=None,gold=dict(effect='waiting_intent',question='Q_INTENT')),
    ]
    for c in cases:
        if c['gold']['effect'] in ('rotate','flip'):
            if explicit_local_params(c['text']) != (c['gold']['effect'], c['gold']['params']): raise ValueError('fixture_grammar_mismatch')
    requests = {key(r['request']):r['request'] for r in json.loads((out/'data/fresh.json').read_text(encoding='utf-8')) if r['split']=='test'}
    for c in cases:
        task=native_task(c); task['context']['semantic']['versions']=VERSION
        req=request_for(task); requests[key(req)]=req
    write(out/'native-cases.json',cases); write(out/'jev-requests.json',requests)
    write(out/'native-freeze.json',dict(cases=8, requests=len(requests), version_sha256=VERSION,
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), frozen_before_native_and_jev=True,
        limitation='Finite rotate/flip grammar known from earlier rounds; new lexical text, two-object fixtures'))
    print(json.dumps(dict(requests=len(requests),native_cases=8)))


def fetch(out):
    from dotenv import dotenv_values
    from miniclaw_web.decisions import JevConfig,JevDecisions
    from miniclaw_web.store import Store
    from scripts.decision_answer_contract import validate_answers
    cfg=JevConfig.from_env({**dotenv_values(ROOT/'.hermes/.env'),**os.environ}); cfg.max_calls=150; cfg.budget_micro_usd=50000
    if not cfg.key: raise ValueError('jev_key_missing')
    dec=JevDecisions(Store(out/'jev-isolated'),cfg); done=cache(out/'jev.jsonl') if (out/'jev.jsonl').exists() else {}; consecutive=0
    scope='round6-formal-v1'
    with (out/'jev.jsonl').open('a',encoding='utf-8') as stream:
        for ident,req in json.loads((out/'jev-requests.json').read_text(encoding='utf-8')).items():
            if ident in done: continue  # Unknown requests are never repeated.
            row=dec.evaluate(scope,ident,'same-input replacement comparison',{'revision':scope},request=req,question_version='chat-clarification-v1'); row['key']=ident
            if row.get('answers'):
                try: row['answers']=validate_answers(row,req[1])
                except ValueError: row.update(status='unavailable',answers={},reason='invalid_answers')
            stream.write(json.dumps(row,ensure_ascii=False)+'\n'); stream.flush(); done[ident]=row
            write(out/'jev-ledger.json',dec.ledger(scope))
            consecutive=0 if row.get('answers') else consecutive+1
            if row['status']=='budget_exhausted' or consecutive>=3: raise ValueError('budget_or_three_failures_no_retry')
    print(json.dumps(dict(requests=len(done),valid=sum(bool(r.get('answers')) for r in done.values()))))


class VersionedClarifications(Clarifications):
    def start(self,owner,text,context=None,**kwargs):
        context=deepcopy(context or {}); context['versions']={}
        context.setdefault('semantic',{})['versions']=VERSION
        return super().start(owner,text,context,**kwargs)


class JointNativePolicy(native.NativePolicy):
    def classify(self,task):
        result=CandidateClarificationPolicy(self.decisions).classify(task)
        self.records.append(dict(decision=result[1],shortcut_question=result[2][0] if result[2] else None))
        return result
    def guard(self,task,name,args):
        # Exercise the opt-in production guard first in both arms. The additional
        # finite fixture guard verifies actual IDs/parameters and cannot grant
        # permission denied by the production policy on classifier abstention.
        value=CandidateClarificationPolicy(self.decisions).guard(task,name,args)
        if value:return value
        if name=='miniclaw_edit_image':return native.NativePolicy.guard(self,task,name,args)
        return None


def run(out):
    import httpx
    from dotenv import dotenv_values
    from miniclaw_web.store import Store
    from scripts.evaluate_chat_harness import Budget
    from hermes_state import SessionDB
    folder=out/'native'; folder.mkdir(exist_ok=True)
    if (folder/'flows.jsonl').exists(): raise ValueError('no_paid_replay')
    gates=json.loads((out/'joint-gates.json').read_text(encoding='utf-8'))
    env={**dotenv_values(ROOT/'.hermes/.env'),**os.environ}; secret=env.get('DEEPSEEK_API_KEY')
    if not secret: raise ValueError('main_key_missing')
    provider=chat_policy(None,dict(MINICLAW_CHAT_DECISION_PROVIDER='laya',MINICLAW_LAYA_CHECKPOINT_SHA256=gates['checkpoint_sha256'],
        MINICLAW_LAYA_GATE_SHA256=hashlib.sha256((out/'joint-gates.json').read_bytes()).hexdigest()))
    models=dict(jev=AliasDecisions(cache(out/'jev.jsonl')),laya=provider.decisions)
    cases=json.loads((out/'native-cases.json').read_text(encoding='utf-8')); paired=[]; excluded=[]
    for c in cases:
        task=native_task(c); task['context']['semantic']['versions']=VERSION
        if models['jev'].evaluate(request=request_for(task)).get('answers'): paired.append(c)
        else: excluded.append(c['id'])
    isolated=folder/'isolated'; isolated.mkdir(); os.environ['HERMES_HOME']=str(isolated)
    (isolated/'config.yaml').write_text('memory:\n  memory_enabled: false\n  user_profile_enabled: false\nauxiliary:\n  title_generation:\n    enabled: false\n  background_review:\n    enabled: false\n',encoding='utf-8')
    service=VersionedClarifications(Store(isolated)); budget=Budget(folder/'main-ledger.json',usd=.30,max_calls=60)
    original=native.plugin_tools
    def typed(workspace):
        schemas,handlers=original(workspace); item=schemas[0]['function']['parameters']['properties']['questions']['items']
        for field in ('id','template'): item['properties'][field]['enum']+=['Q_EXECUTION','Q_CONFLICT','Q_REFERENCE_ROLE']
        return schemas,handlers
    collected=[]
    with patch.object(native,'plugin_tools',side_effect=typed),SessionDB(db_path=isolated/'history.db') as db,httpx.Client(timeout=45,trust_env=False) as client:
        for i,c in enumerate(paired):
            for arm in (('jev','laya') if i%2==0 else ('laya','jev')):
                row=native.run_case(c,arm,0,client,secret,service,models[arm],budget,db,folder,
                    hold_unresolved_target=True,clear_discussion=True,policy_factory=JointNativePolicy)
                collected.append(row)
                with (folder/'flows.jsonl').open('a',encoding='utf-8') as f: f.write(json.dumps(row,ensure_ascii=False)+'\n')
                write(folder/'report.json',dict(summarize_native(collected,'in_progress'),excluded=excluded,jev_fallback=False,
                    actual_laya_http=True, version_digest_in_request=True, production_default_changed=False))
                print(json.dumps({k:row[k] for k in ('id','arm','joint_match','first_question','main_calls','terminal')}),flush=True)
    write(folder/'report.json',dict(summarize_native(collected,'complete'),excluded=excluded,jev_fallback=False,
        actual_laya_http=True,version_digest_in_request=True,production_default_changed=False))


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('phase',choices=['prepare','jev','native']); p.add_argument('out',type=Path); a=p.parse_args()
    dict(prepare=prepare,jev=fetch,native=run)[a.phase](a.out.resolve())
