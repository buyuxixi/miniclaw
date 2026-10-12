"""Same-policy paid baseline and expanded real attachment tool trial."""
import argparse
import base64
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'hermes-agent')]
from scripts.evaluate_jev_laya_matched import cache,write,summarize_native
from scripts.jev_laya_matched import AliasDecisions
from scripts.prepare_laya_round7 import case_task,VERSION
from scripts.formal_seven_gates import key
from miniclaw_web.clarification_policy import chat_request,question,target_choices
from miniclaw_web.candidate_clarification_policy import CandidateClarificationPolicy
from miniclaw_web.literal_image_target import bind_named_attachment,named_operation
from miniclaw_web.clarifications import Clarifications
import scripts.evaluate_native_fastpath as native


def fetch(out):
    from dotenv import dotenv_values
    from miniclaw_web.decisions import JevConfig,JevDecisions
    from miniclaw_web.store import Store
    from scripts.decision_answer_contract import validate_answers
    cfg=JevConfig.from_env({**dotenv_values(ROOT/'.hermes/.env'),**os.environ});cfg.max_calls=400;cfg.budget_micro_usd=100000
    if not cfg.key:raise ValueError('jev_key_missing')
    dec=JevDecisions(Store(out/'jev-isolated'),cfg);done=cache(out/'jev.jsonl') if (out/'jev.jsonl').exists() else {};scope='round7-formal-v1';consecutive=0
    with (out/'jev.jsonl').open('a',encoding='utf-8') as stream:
        for ident,req in json.loads((out/'jev-requests.json').read_text(encoding='utf-8')).items():
            if ident in done:continue
            row=dec.evaluate(scope,ident,'frozen same-input comparison',{'revision':scope},request=req,question_version='chat-clarification-v1');row['key']=ident
            if row.get('answers'):
                try:row['answers']=validate_answers(row,req[1])
                except ValueError:row.update(status='unavailable',answers={},reason='invalid_answers')
            stream.write(json.dumps(row,ensure_ascii=False)+'\n');stream.flush();done[ident]=row
            write(out/'jev-ledger.json',dec.ledger(scope));consecutive=0 if row.get('answers') else consecutive+1
            if row['status']=='budget_exhausted' or consecutive>=3:raise ValueError('budget_or_three_failures_no_retry')
    print(json.dumps(dict(requests=len(done),valid=sum(bool(r.get('answers')) for r in done.values()))))


class BoundClarifications(Clarifications):
    def start(self,owner,text,context=None,**kwargs):
        context=deepcopy(context or {});context['versions']={};context.setdefault('semantic',{})['versions']=VERSION
        bound=bind_named_attachment(dict(text=text,confirmed={},context=context))
        return super().start(owner,text,bound if bound is not None else context,**kwargs)


class Round7NativePolicy(native.NativePolicy):
    def classify(self,task):
        result=CandidateClarificationPolicy(self.decisions).classify(task)
        self.records.append(dict(decision=result[1],shortcut_question=result[2][0] if result[2] else None));return result
    def guard(self,task,name,args):
        value=CandidateClarificationPolicy(self.decisions).guard(task,name,args)
        if value:return value
        if name!='miniclaw_edit_image':return None
        ctx=task['context'];target=ctx['semantic'].get('selected')
        command=named_operation(task['text'])
        if command:
            if not target or args.get('source_id')!=target:return question('Q_TARGET','请选定实际对象。',target_choices(ctx['semantic']['candidates']))
            if (args.get('operation'),args.get('params'))!=(command['operation'],command['params']):return question('Q_CHANGE','工具参数与明确用户指令不一致，请核对。')
            return None
        if any(word in task['text'] for word in ('圈选','局部','圈定','标注处')) and not ctx['semantic'].get('selection'):
            return question('Q_SCOPE','请先明确或圈选局部位置；现在不修改整图。')
        # A genuine execution confirmation may resume the unchanged original
        # finite command; the reply itself does not invent operation parameters.
        latest=ctx.get('latest_user_reply')
        if latest in ('确认执行','确认生成') and task['confirmed'].get('Q_EXECUTION')==latest:
            literal=native.explicit_local_params(task['text'])
            if literal and target and args.get('source_id')==target and literal==(args.get('operation'),args.get('params')):return None
        return native.NativePolicy.guard(self,task,name,args)


def run(out):
    import httpx
    from dotenv import dotenv_values
    from PIL import Image
    from miniclaw_web.attachments import upload
    from miniclaw_web.store import Store
    from miniclaw_web.laya_formal import LayaFormalDecisions
    from scripts.evaluate_chat_harness import Budget
    from hermes_state import SessionDB
    folder=out/'native';folder.mkdir(exist_ok=True)
    if (folder/'flows.jsonl').exists():raise ValueError('no_paid_replay')
    gates=json.loads((out/'round07/joint-gates.json').read_text(encoding='utf-8'))
    models=dict(jev=AliasDecisions(cache(out/'jev.jsonl')),laya=LayaFormalDecisions('http://127.0.0.1:8771',gates['checkpoint_sha256'],gate_sha256=hashlib.sha256((out/'round07/joint-gates.json').read_bytes()).hexdigest()))
    cases=json.loads((out/'native-cases.json').read_text(encoding='utf-8'));paired=[];excluded=[]
    for c in cases:
        t=case_task(c);req=chat_request(t['text'],t['context']['semantic'],{})
        if models['jev'].evaluate(request=req).get('answers'):paired.append(c)
        else:excluded.append(c['id'])
    env={**dotenv_values(ROOT/'.hermes/.env'),**os.environ};secret=env.get('DEEPSEEK_API_KEY')
    if not secret:raise ValueError('main_key_missing')
    isolated=folder/'isolated';isolated.mkdir();os.environ['HERMES_HOME']=str(isolated)
    (isolated/'config.yaml').write_text('memory:\n  memory_enabled: false\n  user_profile_enabled: false\nauxiliary:\n  title_generation:\n    enabled: false\n  background_review:\n    enabled: false\n',encoding='utf-8')
    service=BoundClarifications(Store(isolated));budget=Budget(folder/'main-ledger.json',max_calls=100,usd=.50)
    original=native.plugin_tools
    def typed(workspace):
        schemas,handlers=original(workspace);item=schemas[0]['function']['parameters']['properties']['questions']['items']
        for field in ('id','template'):item['properties'][field]['enum']+=['Q_EXECUTION','Q_CONFLICT','Q_REFERENCE_ROLE']
        return schemas,handlers
    current={}
    def images(store,owner):
        result=[]
        for i,label in enumerate(current['case']['labels']):
            im=Image.new('RGBA',(96,64),(100+i*30,200-i*20,140,255))
            x0,y0=[(5,5),(35,20),(65,35),(10,40)][i]
            for x in range(x0,x0+12):
                for y in range(y0,y0+10):im.putpixel((x,y),(255,0,0,255))
            buf=io.BytesIO();im.save(buf,'PNG');data=buf.getvalue()
            row=upload(store,owner,label+'.png',base64.b64encode(data).decode())
            result.append(dict(id=row['id'],label=label,sha256=hashlib.sha256(data).hexdigest()))
        return result
    paths=['scripts/run_laya_round7_comparison.py','scripts/evaluate_native_fastpath.py','miniclaw_web/clarification_policy.py','miniclaw_web/candidate_clarification_policy.py','miniclaw_web/hermes_clarification_adapter.py','miniclaw_web/literal_image_target.py']
    write(out/'native-runtime-freeze.json',dict(before_first_flow=True,cases_sha256=hashlib.sha256((out/'native-cases.json').read_bytes()).hexdigest(),sources={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}))
    collected=[]
    with patch.object(native,'plugin_tools',side_effect=typed),patch.object(native,'fixture_images',side_effect=images),SessionDB(db_path=isolated/'history.db') as db,httpx.Client(timeout=45,trust_env=False) as client:
        for i,c in enumerate(paired):
            current['case']=c
            for arm in (('jev','laya') if i%2==0 else ('laya','jev')):
                row=native.run_case(c,arm,0,client,secret,service,models[arm],budget,db,folder,hold_unresolved_target=True,clear_discussion=True,policy_factory=Round7NativePolicy)
                if c['gold']['effect']=='waiting_scope':
                    # The older finite oracle only recognises waiting-target.
                    # This explicit independent scope oracle checks persisted wait,
                    # actual question identity and absence of ANY image/file write.
                    last=row['phases'][-1]
                    row['effect_match']=bool(row['terminal']=='awaiting_input' and not row['image_jobs'] and not row['artifacts'] and len(last['questions'])==1 and last['questions'][0]['template']=='Q_SCOPE')
                    row['joint_match']=bool(row['effect_match'] and row['question_match'] and row['originals_preserved'])
                collected.append(row)
                with (folder/'flows.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
                write(folder/'report.json',dict(summarize_native(collected,'in_progress'),excluded=excluded,jev_fallback=False,actual_laya_http=True,production_default_changed=False))
                print(json.dumps({k:row[k] for k in ('id','arm','joint_match','first_question','main_calls','terminal')}),flush=True)
    write(folder/'report.json',dict(summarize_native(collected,'complete'),excluded=excluded,jev_fallback=False,actual_laya_http=True,production_default_changed=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['jev','native']);p.add_argument('out',type=Path);a=p.parse_args();dict(jev=fetch,native=run)[a.phase](a.out.resolve())
