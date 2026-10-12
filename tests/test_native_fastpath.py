import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'hermes-agent')]
from scripts.decision_fastpath import route_question
from scripts.evaluate_native_fastpath import LiveCounter,run_case,NativePolicy
from scripts.evaluate_chat_harness import Budget
from miniclaw_web.clarifications import Clarifications
from miniclaw_web.store import Store
from miniclaw_web.decisions import JevDecisions,JevConfig

def task(text='把这张图旋转90度。',selected=None):
    return {'text':text,'confirmed':{},'context':{'semantic':{'selected':selected,
        'candidates':[{'id':'a','label':'第一张'},{'id':'b','label':'第二张'}]}}}

def decision(intent='execute_change',confidence=.95):
    return {'status':'available','answers':{
        'intent':{'choice':intent,'confidence':confidence,'probabilities':{intent:.96,'discuss':.04}},
        'target':{'choice':'ambiguous','confidence':confidence,'probabilities':{'ambiguous':.96,'a':.04}}}}

def test_high_score_can_only_propose_question_not_choose_object():
    q=route_question(task(),decision())
    assert q['template']=='Q_TARGET' and q['choices']==['第一张','第二张']
    assert 'target_id' not in q

@pytest.mark.parametrize('state,result',[
    (task(),decision(confidence=.5)),(task(selected='a'),decision()),
    (task('先讨论怎么修图'),decision()),(task('只写视频提示词'),decision()),
    (task(),{'status':'unavailable'}),
])
def test_low_score_resolved_readonly_or_unavailable_falls_back(state,result):
    assert route_question(state,result) is None

def test_answered_slot_never_reasks():
    state=task();state['confirmed']['Q_TARGET']='还没决定选哪张。'
    # Main model must interpret unresolved answer; classifier cannot blindly loop.
    assert route_question(state,decision()) is None

def test_rule_shortcut_is_counted_separately():
    assert route_question(task('可以，开始吧。'),rules=True)['template']=='Q_INTENT'
    assert route_question(task(),rules=True) is None

@pytest.mark.parametrize('text,args',[
    ('不要旋转这张图。',{'operation':'rotate','params':{'angle':90}}),
    ('客户说把这张图旋转90度。',{'operation':'rotate','params':{'angle':90}}),
    ('把这张图旋转90度。',{'operation':'rotate','params':{'angle':180}}),
    ('把这张图水平翻转。',{'operation':'flip','params':{'direction':'vertical'}}),
])
def test_bound_target_does_not_authorize_guessed_action_or_parameters(text,args):
    p=NativePolicy('main',None,None,None,'test')
    assert p.guard(task(text,selected='a'),'miniclaw_edit_image',{'source_id':'a',**args})['template']=='Q_CHANGE'

def test_new_reply_cannot_fall_back_to_old_action_after_negation():
    p=NativePolicy('main',None,None,None,'test');state=task(selected='a')
    state['context']['latest_user_reply']='不要旋转了。'
    assert p.guard(state,'miniclaw_edit_image',{'source_id':'a','operation':'rotate','params':{'angle':90}})['template']=='Q_CHANGE'

def test_network_exception_does_not_repeat_paid_request(tmp_path):
    called=[]
    def fail(**kwargs):called.append(1);raise RuntimeError('unknown_result')
    counter=LiveCounter(fail,Budget(tmp_path/'budget.json'),tmp_path/'calls.jsonl','test')
    with pytest.raises(RuntimeError):counter.create(messages=[])
    with pytest.raises(ValueError):counter.create(messages=[])
    assert called==[1] and json.loads((tmp_path/'calls.jsonl').read_text())['status']=='unknown'

@pytest.mark.parametrize('ask,unresolved',[(False,False),(True,False),(True,True)])
def test_actual_native_loop_and_plugin_transform_and_receipt(tmp_path,monkeypatch,ask,unresolved):
    from openai.types.chat import ChatCompletion
    from hermes_state import SessionDB
    home=tmp_path/'isolated';home.mkdir();monkeypatch.setenv('HERMES_HOME',str(home))
    (home/'config.yaml').write_text('memory:\n  memory_enabled: false\n  user_profile_enabled: false\n',encoding='utf-8')
    store=Store(home);service=Clarifications(store);decisions=JevDecisions(store,JevConfig(key=''))
    called=[]
    def fake_create(self,**kwargs):
        called.append(kwargs)
        if ask and len(called)==1:
            message={'role':'assistant','content':None,'tool_calls':[{'id':'ask','type':'function','function':{'name':'clarify','arguments':json.dumps({'questions':[{'id':'Q_TARGET','question':'修改哪张？','choices':['第一张','第二张']}]},ensure_ascii=False)}}]}
            finish='tool_calls'
        elif len(called)==1+int(ask):
            data=json.loads([m['content'] for m in kwargs['messages'] if m['role']=='user'][-1])
            args={'source_id':data['context']['selected'],'operation':'rotate','params':{'angle':90},'request_id':'native-test'}
            message={'role':'assistant','content':None,'tool_calls':[{'id':'call-rotate','type':'function','function':{'name':'miniclaw_edit_image','arguments':json.dumps(args)}}]}
            finish='tool_calls'
        else:message={'role':'assistant','content':'旋转完成。'};finish='stop'
        return ChatCompletion.model_validate({'id':'response','object':'chat.completion','created':0,'model':'test',
            'choices':[{'index':0,'finish_reason':finish,'message':message}],
            'usage':{'prompt_tokens':20,'completion_tokens':10,'total_tokens':30}})
    case={'id':'rotate','text':'把这张图旋转90度。','gold':{'question':None,'effect':'rotate','target':0}}
    if ask:case.update(selected=None,reply='第二张',gold={'question':'Q_TARGET','effect':'rotate','target':1})
    if unresolved:case.update(reply='还没决定选哪张。',gold={'question':'Q_TARGET','effect':'waiting'})
    with SessionDB(db_path=home/'history.db') as db,patch('openai.resources.chat.completions.Completions.create',new=fake_create):
        row=run_case(case,'main',0,None,'dummy',service,decisions,Budget(tmp_path/'budget.json'),db,tmp_path,
            hold_unresolved_target=unresolved)
        assert row['joint_match'] and row['originals_preserved']
        if unresolved:
            assert row['terminal']=='awaiting_input' and row['waiting_probe'] is True and not row['image_jobs']
            assert row['phases'][1]['api_calls']==0
        else:
            assert row['pixel_match'] and row['duplicate_probe'] is True and len(row['image_jobs'])==1
            assert len([m for m in db.get_messages('main-0-rotate') if m['role']=='tool'])==1+int(ask)
    assert len(called)==(1 if unresolved else 2+int(ask)) and called[0]['extra_body']['thinking']['type']=='disabled'
