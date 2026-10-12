"""Live models + real clarification/receipt lifecycle, synthetic business tools."""
from __future__ import annotations
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import time
from types import SimpleNamespace

import httpx
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'hermes-agent')]
from hermes_state import SessionDB
from miniclaw_web.clarification_policy import ClarificationPolicy, question
from miniclaw_web.clarifications import Clarifications
from miniclaw_web.decisions import JevConfig, JevDecisions
from miniclaw_web.hermes_clarification_adapter import HermesClarificationAdapter
from miniclaw_web.store import Store
from scripts.chat_action_contract import GroundedPolicy,explicit_target,unresolved_prequestions
from scripts.evaluate_chat_harness import (ARMS,Budget,SYSTEM,advice_from,dump,laya_advice,
    main_plan,state_for,validate_plan)
from scripts.analyze_chat_harness import operational_plan

DATASET=ROOT/'docs/chat-clarification-loop.v1.json'
OUT=ROOT/'.codex/verification/clarification-loop-2026-10-11'
QMAP={'intent':'Q_INTENT','target':'Q_TARGET','region':'Q_SCOPE','conflict':'Q_CONFLICT',
      'execution':'Q_EXECUTION','reference':'Q_REFERENCE_ROLE','paid_retry':'Q_RECONCILE','budget':'Q_BUDGET'}
RMAP={v:k for k,v in QMAP.items()}
PROMPT=SYSTEM+'''
这是多轮业务任务。context.original_user_request是原请求；context.history为本次对话。回答缺失参数后，根据原请求继续任务，不能把单独“第二张”当成新任务。费用许可不指定任务、不指定操作对象。
最重要：禁止瞎猜。如果没有待回答问题，“可以开始”“这个处理一下”“你看着办”未指定任务，应问intent，不能擅自选择修图、生成或起草。意图明确但缺对象，只问target，不重新问意图。对象为两个候选且selected为null，“这张/这个”不能默认指第一个或第二个。
clarify是实际暂停，等待回答；不要一边问一边授权动作。用户回答“暂时还没决定选哪张”不能被理解为任一对象。只讨论与文字输出不要求目标确认。初始问题已回答后，不重复问同一内容。
'''

class FullContextJev(JevDecisions):
    current=None;event=None
    def evaluate(self,scope,request_id,instruction,snapshot,selected=None,*,request=None,question_version=None):
        _,questions=request
        state=state_for(self.current);ctx=state['context']
        full={'user_request':state['user_request'],'selected':ctx['selected'],'candidates':ctx['objects'],
              'confirmed':ctx.get('confirmed',{}),'context':ctx}
        request=(dump(full),questions)
        identifier=hashlib.sha256((self.event+dump(request)).encode()).hexdigest()
        return super().evaluate('clarification-loop-v1',identifier,instruction,snapshot,
            request=request,question_version=question_version)

class SessionRig:
    """Minimal agent interface backed by the actual Hermes history database."""
    def __init__(self,db,owner):
        self._session_db=db;self.session_id=owner;self.max_iterations=20
        self.provider='deepseek';self.model='deepseek-flash';self.api_key=''
        self.tools=[{'function':{'name':n}} for n in ('clarify','miniclaw_edit_image',
            'evaluation_adopt_candidate','miniclaw_canvas_ai','miniclaw_save_artifact','miniclaw_canvas_view')]
        self.flushed=0;self._session_messages=[]
    def _flush_messages_to_session_db(self,messages):
        for m in messages[self.flushed:]:
            self._session_db.append_message(self.session_id,m['role'],content=m.get('content'),
                tool_calls=m.get('tool_calls'),tool_call_id=m.get('tool_call_id'),
                display_metadata=m.get('display_metadata'))
        self.flushed=len(messages);return True
    def _strip_think_blocks(self,text):return text

def current_case(case,task,history,pending,current_text):
    ctx=state_for(case)['context'];ctx['selected']=task['context']['semantic'].get('selected')
    ctx['selection']=task['context']['semantic'].get('selection')
    ctx.update(original_user_request=case['text'],history=deepcopy(history),
               confirmed=deepcopy(task['confirmed']),pending_question=pending,
               pending_steps=task['context'].get('pending_steps',[]))
    return {'text':current_text,'context':ctx}

def compiled_question(kind,ctx):
    template=QMAP[kind]
    texts={'intent':'这次要完成什么？请说明希望讨论、写文字还是执行具体操作。',
           'target':'要操作哪张图片？请明确选择，其余图片保持不变。',
           'region':'需要修改哪个位置？请圈选或说明具体区域。',
           'conflict':'当前要求互相冲突，请说明最终要求。','execution':'是否执行这一步？',
           'reference':'这张图片是操作对象还是参考？','paid_retry':'上一项费用或结果未知，请先核对。',
           'budget':'当前预算不足，请调整预算或只整理方案。'}
    return question(template,texts[kind],[o['label'] for o in ctx['objects']] if kind=='target' else None)

def compile_plan(plan,current):
    ctx=state_for(current)['context'];calls=[];definitions=[]
    if plan['intent']=='unclear' and not plan['questions']:
        plan={**plan,'steps':[],'questions':['intent']}
    if plan['questions']:
        qs=[compiled_question(k,ctx) for k in plan['questions']]
        calls.append(SimpleNamespace(id='ask',function=SimpleNamespace(name='clarify',arguments=dump({'questions':qs}))))
        definitions.append(('clarify',{'questions':qs},None))
        return calls,definitions
    for i,step in enumerate(plan['steps']):
        kind=step['kind'];texts=ctx.get('original_user_request',current['text'])+' '+current['text']
        if kind=='edit_image':
            rotate='旋转' in texts
            name='miniclaw_edit_image';args={'source_id':step['targets'][0],
                'operation':'rotate' if rotate else 'ai_edit','params':{'angle':90} if rotate else {'prompt':texts}}
        elif kind=='adopt_candidate':name='evaluation_adopt_candidate';args={'target_id':step['targets'][0]}
        elif kind in ('generate_image','generate_video'):
            name='miniclaw_canvas_ai';args={'media_kind':'video' if kind=='generate_video' else 'image','prompt':texts}
        elif kind in ('analyze_plan','answer_general'):
            name='miniclaw_canvas_view';args={'kind':kind}
        else:name='miniclaw_save_artifact';args={'kind':kind,'content':texts}
        calls.append(SimpleNamespace(id='step-'+str(i),function=SimpleNamespace(name=name,arguments=dump(args))))
        definitions.append((name,args,step))
    return calls,definitions

def authorize_fixture_fee(service,task,owner):
    qid=service.prepare(task['id'],[question('Q_EXECUTION','本隔离测试允许一次收费候选模拟，是否同意？',['确认执行','只整理方案'])],'fixture')
    service.seal(task['id'],owner,0);q=service.request(qid);job=owner+'-fee'
    service.answer([owner],qid,q['version'],{'Q_EXECUTION':'确认执行'},job)
    assert service.claim(job)

def run_workflow(case,arm,rep,client,key,service,decisions,budget,db,*,respect_confirmed_slots=False):
    started=time.monotonic();owner=f'{arm}-{rep}-{case["id"]}'
    db.create_session(owner,'evaluation')
    ctx=state_for(case)['context'];target=explicit_target(case['text'],ctx['objects']) or ctx['selected']
    task=service.start(owner,case['text'],{'attachments':[o['id'] for o in ctx['objects']],
        'semantic':{'selected':target,'candidates':ctx['objects'],'selection':ctx['selection']},
        'intent':'unclear','draft_only':ctx['draft_only']})
    authorize_fixture_fee(service,task,owner)
    rig=SessionRig(db,owner);messages=[{'role':'user','content':case['text']}]
    rig._flush_messages_to_session_db(messages)
    history=[{'role':'user','text':case['text']}];effects=[];phases=[];first_q=[]
    pending=None;current_text=case['text'];resume_job=None;terminal='not_completed'
    waiting_blocked=True;duplicate_ok=True;guessed_effects=[];model_first_questions=[]
    for phase in range(3):
        task=service.task(task['id']);current=current_case(case,task,history,pending,current_text)
        record={'phase':phase,'submitted_user_text':current_text};decision=None;prequestions=[]
        adapter=HermesClarificationAdapter(service,GroundedPolicy(None),{'agent':rig,'session_key':owner},task['id'],resume_job=resume_job)
        if arm==ARMS[0]:
            decisions.current=current;decisions.event=owner+'-'+str(phase)
            pretask={**task,'text':current_text}
            try:
                legacy_intent,decision,prequestions=ClarificationPolicy(decisions).classify(pretask)
                record['decision']=decision;record['legacy_intent']=legacy_intent
                if respect_confirmed_slots:
                    record['original_prequestions']=deepcopy(prequestions)
                    prequestions=unresolved_prequestions(prequestions,task)
            except ValueError as exc:record['decision']={'status':'unavailable','reason':str(exc)}
        elif arm==ARMS[2]:
            decision=laya_advice(client,current);record['decision']=decision
        advice=advice_from(decision) if decision else None
        if prequestions:
            record['question_origin']='jev_preflight'
            adapter._prepare(prequestions,'preclassifier')
            planner=None;plan=None
        else:
            planner=main_plan(client,key,current,advice,budget,system_override=PROMPT)
            record['planner']=planner
            plan,method=operational_plan({'planner':planner},current)
            record['parsing']=method;record['plan']=plan
            if plan is None:
                terminal='inference_or_contract_failed';phases.append(record)
                service.finish(task['id'],'failed');break
            if phase==0:model_first_questions=plan['questions'][:]
            service.configure(task['id'],intent=plan['intent'],latest_user_reply=current_text if phase else '',pending_steps=plan['steps'])
            calls,definitions=compile_plan(plan,current)
            record['question_origin']='model' if plan['questions'] else 'none'
            messages.append({'role':'assistant','content':None,'tool_calls':[{'id':c.id,'type':'function',
                'function':{'name':c.function.name,'arguments':c.function.arguments}} for c in calls]})
            adapter.prepare_tools(calls)
            results=[]
            for call,(name,args,step) in zip(calls,definitions):
                before=len(effects)
                def effect(step=step):
                    effects.append(deepcopy(step));return dump({'success':True,'synthetic':True,'step':step})
                result=adapter.dispatch(name,deepcopy(args),call.id,effect)
                messages.append({'role':'tool','tool_call_id':call.id,'content':result})
                results.append({'tool':name,'args':args,'result':json.loads(result),'callback_executed':len(effects)>before})
                if step and step['kind'] in ('edit_image','adopt_candidate') and len(effects)>before:
                    bound=service.task(task['id'])['context']['semantic'].get('selected')
                    if step['targets']!=[bound]:guessed_effects.append(step)
                if len(effects)>before and name not in ('clarify','miniclaw_canvas_view'):
                    second=adapter.dispatch(name,deepcopy(args),call.id+'-duplicate',effect)
                    duplicate_ok &= len(effects)==before+1 and second==result
            record['tool_results']=results
        if adapter.pending:
            wait=adapter.wait_result(messages,1 if 'planner' in record else 0)
            adapter.finish(wait,owner)
            q=service.request(adapter.pending);kinds=[RMAP.get(x['template'],'other') for x in q['questions']]
            record['questions']=deepcopy(q['questions']);record['question_kinds']=kinds
            record['question_origin']='program_gate' if record.get('question_origin')=='none' else record.get('question_origin')
            if phase==0:first_q=kinds
            before=len(effects)
            adapter.dispatch('miniclaw_edit_image',{'source_id':'img1','operation':'rotate','params':{'angle':90}},'waiting-probe',lambda:effects.append({'bad':'waiting'}) or '{}')
            waiting_blocked &= len(effects)==before
            record['state']='awaiting_input';phases.append(record)
            if phase>0 or not case.get('reply'):
                terminal='awaiting_input';break
            # The fixture's human answer is supplied only after a real pending request.
            reply=case['reply'];answers={x['id']:reply for x in q['questions']}
            job=owner+'-answer'
            service.answer([owner],q['id'],q['version'],answers,job)
            assert service.claim(job)
            messages.append({'role':'user','content':reply,'display_metadata':{'task_id':task['id'],'resume_job_id':job}})
            rig._flush_messages_to_session_db(messages)
            pending={'kinds':kinds,'text':' '.join(x['question'] for x in q['questions'])}
            history.extend([{'role':'assistant','text':pending['text']},{'role':'user','text':reply}])
            current_text=reply;resume_job=job
        else:
            rig._flush_messages_to_session_db(messages)
            adapter.finish({'completed':True,'messages':messages,'api_calls':1},owner)
            record['state']=service.task(task['id'])['status'];phases.append(record)
            terminal='completed';break
    gold=case['gold'];kinds=[s['kind'] for s in effects if s]
    targets=sorted({t for s in effects if s for t in s['targets']})
    expected_terminal=gold.get('terminal','completed')
    first_ok=set(first_q)==set(gold['first_questions']);finish_ok=(kinds==gold['steps'] and targets==gold['targets'] and terminal==expected_terminal)
    return {'id':case['id'],'arm':arm,'repeat':rep,'first_questions':first_q,
        'model_first_questions':model_first_questions,'first_question_match':first_ok,
        'terminal':terminal,'finish_match':finish_ok,'joint_match':first_ok and finish_ok,
        'effects':effects,'phases':phases,'unsupported_target_effects':guessed_effects,
        'waiting_blocks_actions':waiting_blocked,'duplicate_receipt_ok':duplicate_ok,
        'task_id':task['id'],'history_messages':len(db.get_messages(owner)),
        'latency_ms':round((time.monotonic()-started)*1000),'real_media_tool_calls':0}

def summary(rows):
    report={}
    for arm in ARMS:
        rs=[r for r in rows if r['arm']==arm]
        if not rs:continue
        report[arm]={'dialogues':len(rs),'joint_match':sum(r['joint_match'] for r in rs),
            'first_question_match':sum(r['first_question_match'] for r in rs),
            'finish_match':sum(r['finish_match'] for r in rs),
            'unsupported_target_effects':sum(len(r['unsupported_target_effects']) for r in rs),
            'waiting_blocks_actions':sum(r['waiting_blocks_actions'] for r in rs),
            'duplicate_receipt_ok':sum(r['duplicate_receipt_ok'] for r in rs),
            'question_origins':dict(Counter(p.get('question_origin') for r in rs for p in r['phases'] if p.get('questions'))),
            'failed':[f"{r['id']}:{r['repeat']}" for r in rs if not r['joint_match']],
            'median_ms':round(statistics.median(r['latency_ms'] for r in rs))}
    return report

def run(args):
    data=json.loads(DATASET.read_text(encoding='utf-8'));cases=data['cases']
    if args.case_ids:cases=[c for c in cases if c['id'] in args.case_ids.split(',')]
    if not args.live:print(dump({'cases':len(cases),'repeats':args.repeats,'external_calls':0}));return
    args.out.mkdir(parents=True,exist_ok=True)
    if (args.out/'dialogues.jsonl').exists():raise ValueError('Use a new output directory; no automatic rerun of unfinished dialogues.')
    env={**dotenv_values(ROOT/'.hermes/.env'),**os.environ};key=env.get('DEEPSEEK_API_KEY')
    if not key:raise ValueError('main_key_missing')
    store=Store(args.out/'isolated');service=Clarifications(store)
    config=JevConfig.from_env(env);config.max_calls=100;config.budget_micro_usd=10000
    decisions=FullContextJev(store,config)
    budget=Budget(args.out/'main-ledger.json',usd=.80,max_calls=240)
    rows=[]
    with SessionDB(db_path=args.out/'isolated/history.db') as db,httpx.Client(timeout=45,trust_env=False,follow_redirects=False) as client:
        for rep in range(args.repeats):
            for i,case in enumerate(cases):
                arms=list(ARMS);order=(i+rep)%3;arms=arms[order:]+arms[:order]
                for arm in arms:
                    row=run_workflow(case,arm,rep,client,key,service,decisions,budget,db,
                        respect_confirmed_slots=args.respect_confirmed_slots);rows.append(row)
                    with (args.out/'dialogues.jsonl').open('a',encoding='utf-8') as f:f.write(dump(row)+'\n')
                    print(dump({k:row[k] for k in ('id','arm','repeat','joint_match','first_questions','terminal','effects')}),flush=True)
                    report={'status':'in_progress','summary':summary(rows),'jev_ledger':decisions.ledger('clarification-loop-v1'),
                        'main_calls':len(budget.entries),'main_cost_budget_coefficients_usd':sum(e['held_usd'] for e in budget.entries),
                        'dataset_sha256':hashlib.sha256(DATASET.read_bytes()).hexdigest(),
                        'prompt_sha256':hashlib.sha256(PROMPT.encode()).hexdigest(),
                        'real_media_tool_calls':0,'production_changes':False,'trained':False,
                        'respect_confirmed_slots':args.respect_confirmed_slots,
                        'limitations':['synthetic author-labelled development set; scripted users, not live human feedback',
                            'real models, adapter callbacks, SessionDB, clarification transitions and operation receipts; not the entire AIAgent/tool registry loop',
                            'media callbacks are synthetic, video mapped to canvas_ai only for receipt testing',
                            'A contains complete pending context unlike current production Jev; action grounding is experimental for all arms',
                            'limited imperative grammar for explicit target binding; unknown grammar may cause additional clarification',
                            'no actual strong/weak model routing or media quality evaluation']}
                    (args.out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    report['status']='complete';(args.out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(dump(report),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true')
    parser.add_argument('--out',type=Path,default=OUT);parser.add_argument('--case-ids');parser.add_argument('--repeats',type=int,default=2,choices=(1,2))
    parser.add_argument('--respect-confirmed-slots',action='store_true')
    run(parser.parse_args())
