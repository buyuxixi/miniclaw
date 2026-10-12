"""Identical formal seven-question contracts; experimental cached replacement only."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'hermes-agent')]
from miniclaw_web.clarification_policy import ClarificationPolicy,chat_request
from scripts.evaluate_chat_harness import state_for
from scripts.evaluate_native_fastpath import NativePolicy
from scripts.decision_answer_contract import CHECKPOINT_SHA,validate_answers


def signature(request):
    return hashlib.sha256(json.dumps(request,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def formal_task(case):
    ctx=state_for(case)['context']
    return dict(id=case['id'],text=case['text'],confirmed=deepcopy(ctx.get('confirmed',{})),
        context=dict(draft_only=ctx['draft_only'],semantic=dict(selected=ctx['selected'],selection=ctx['selection'],
            candidates=[{'id':'img1','label':'第一张'},{'id':'img2','label':'第二张'}])))


def request_for(task,profile='primary',extra=None):
    request=chat_request(task['text'],task['context']['semantic'],task['confirmed'])
    if profile=='enriched':
        value=json.loads(request[0]);ctx=extra or {}
        value.update(selection=task['context']['semantic'].get('selection'),
            draft_only=task['context'].get('draft_only',False),pending_question=ctx.get('pending_question'),
            pending_steps=ctx.get('pending_steps',[]),original_user_request=ctx.get('original_user_request'))
        request=(json.dumps(value,ensure_ascii=False),request[1])
    elif profile!='primary':raise ValueError('invalid_profile')
    return request


class FrozenDecisions:
    """Replay validated actual model outputs, with no hidden semantic correction."""
    def __init__(self,cache,probability_gate=False):self.cache=cache;self.probability_gate=probability_gate
    def evaluate(self,*unused,request,**kwargs):
        row=deepcopy(self.cache[signature(request)])
        if self.probability_gate:
            for a in row.get('answers',{}).values():a['confidence']=max(a['probabilities'].values())
        return row


def replay(task,record,request=None,probability_gate=False):
    request=request or request_for(task)
    # Force this exact seven-question input while retaining production rules.
    class Fixed:
        def evaluate(self,*args,**kwargs):
            row=deepcopy(record)
            if probability_gate:
                for a in row.get('answers',{}).values():a['confidence']=max(a['probabilities'].values())
            return row
    intent,decision,qs=ClarificationPolicy(Fixed()).classify(deepcopy(task))
    return dict(intent=intent,questions=qs,decision_status=decision.get('status'))


class MatchedNativePolicy(NativePolicy):
    def classify(self,task):
        intent,result,qs=ClarificationPolicy.classify(self,task)
        self.records.append(dict(decision=result,shortcut_question=qs[0] if qs else None))
        return intent,result,qs
    def guard(self,task,name,args):
        formal=ClarificationPolicy.guard(self,task,name,args)
        return formal or NativePolicy.guard(self,task,name,args)


class AliasDecisions:
    """Both classifiers see shared fixture aliases, never randomized attachment IDs."""
    def __init__(self,cache):self.cache=cache
    def evaluate(self,*unused,request,**kwargs):
        state=json.loads(request[0]);candidates=state['candidates']
        aliases={c['id']:f'img{i+1}' for i,c in enumerate(candidates)}
        reverse={v:k for k,v in aliases.items()}
        state['candidates']=[dict(id=aliases[c['id']],label=c['label']) for c in candidates]
        state['selected']=aliases.get(state['selected'],state['selected'])
        for k,v in list(state['confirmed'].items()):
            if isinstance(v,str):state['confirmed'][k]=aliases.get(v,v)
        q=deepcopy(request[1]);q['target']['criteria']={aliases.get(k,k):v for k,v in q['target']['criteria'].items()}
        key=signature((json.dumps(state,ensure_ascii=False),q))
        row=deepcopy(self.cache[key])
        if row.get('answers',{}).get('target'):
            target=row['answers']['target'];target['choice']=reverse.get(target['choice'],target['choice'])
            target['probabilities']={reverse.get(k,k):v for k,v in target['probabilities'].items()}
        return row


def cases():
    data=json.loads((ROOT/'docs/chat-laya-state-contrast.v1.json').read_text(encoding='utf-8'))
    result=deepcopy(data['planning'])
    for row in result:
        ident=row['id'];family=row['family'];index=int(ident.rsplit('-',1)[1])
        steps=row['gold']['steps'];qs=row['gold']['questions']
        intent='unclear' if qs==['intent'] else 'execute_change' if ('edit_image' in steps or qs in (['target'],['region'])) else 'generate_media' if any(s.startswith('generate_') for s in steps) else 'draft' if any(s.startswith('optimize_') or s=='write_plan' for s in steps) else 'discuss'
        if family=='unresolved-answer' and index==1:intent='unclear'
        target=row['gold']['targets'][0] if row['gold']['targets'] else 'ambiguous' if qs in (['target'],['region']) else 'none'
        if family in ('region-binding','answered-region'):target='img1'
        if family=='unresolved-answer' and index==1:target='ambiguous'
        gold=dict(intent=intent,target=target,conflict='none',fact_review='clear',
            answer_relation='answers_current' if row.get('context',{}).get('pending_question') else 'unclear')
        if family in ('region-binding','answered-region'):gold['scope']='selected_region'
        elif intent=='execute_change' and target in ('img1','img2'):gold['scope']='whole_object'
        row['formal_gold']=gold
    extra=[
        ('discussion-question','这张图是不是需要修改？我们讨论一下。',None,dict(intent='discuss',target='none',conflict='none',fact_review='clear'),[]),
        ('negated-prompt','不要再生成提示词了，现在直接生成视频候选。','img1',dict(intent='generate_media',target='none',conflict='none',fact_review='clear'),[]),
        ('quoted-video','客户说生成视频，我想了解他说的具体意思。','img1',dict(intent='discuss',target='none',conflict='none',fact_review='clear'),[]),
        ('real-conflict','请把同一张图的背景同时改成纯红和纯蓝，不允许分版本。','img1',dict(conflict='present',target='img1',fact_review='clear'),['conflict']),
        ('superseded','之前要求背景用红色，现在改成纯蓝，以现在的要求为准。','img1',dict(intent='execute_change',target='img1',conflict='none',scope='whole_object',fact_review='clear'),[]),
        ('unproved-claim','口播直接写这盏台灯已经通过国家护眼认证；我没有提供认证证据。','img1',dict(intent='draft',target='none',conflict='none',fact_review='review'),[]),
        ('reference-only','新增的第一张图片只作参考，继续把选中的第二张图旋转90度。','img2',dict(intent='execute_change',target='img2',reference_role='reference',scope='whole_object',conflict='none',fact_review='clear'),[]),
        ('cancel','取消当前任务。','img1',dict(intent='cancel',target='none',conflict='none',answer_relation='cancel',fact_review='clear'),[]),
    ]
    for ident,text,selected,gold,qs in extra:
        result.append(dict(id=ident,family=ident,text=text,context=dict(selected=selected),formal_gold=gold,
                           gold=dict(steps=[],questions=qs,targets=[])))
    return result,data['native']
