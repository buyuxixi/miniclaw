from copy import deepcopy
import json
from miniclaw_web.clarification_policy import chat_request,ClarificationPolicy
from scripts.build_laya_formal_round5 import fresh_rows
from scripts.formal_seven_label_gates import fit_labels
from scripts.formal_seven_consumption_gates import fit_consumption,apply_consumption
from scripts.operational_clarification_policy import OperationalClarificationPolicy
from scripts.run_laya_round5_replacement import OperationalNativePolicy
from scripts.run_laya_round5_delegated import DelegatingNativePolicy

def task(text='把当前图旋转90度。',count=2,selected=None):
    return dict(id='test',text=text,confirmed={},context=dict(semantic=dict(selected=selected,selection=None,candidates=[dict(id=f'img{i+1}',label=f'图片{i+1}') for i in range(count)])))

def prediction(t,intent='execute_change',target='ambiguous',conflict='none',scope='whole_object',confidence=.98):
    req=chat_request(t['text'],t['context']['semantic'],{})
    choices=dict(intent=intent,target=target,reference_role='primary',scope=scope,conflict=conflict,answer_relation='unclear',fact_review='clear')
    return dict(status='suggested',answers={h:dict(type='choice',choice=choices[h],confidence=confidence,probabilities={k:.98 if k==choices[h] else .02/(len(q['criteria'])-1) for k in q['criteria']}) for h,q in req[1].items()})

class Fixed:
    def __init__(self,r):self.r=r
    def evaluate(self,*a,**kw):return deepcopy(self.r)

def test_fresh_state_partition_and_no_hidden_pending_gold():
    rows=fresh_rows()
    assert len(rows)==1260
    text_splits={};seen={}
    for r in rows:
        s=json.loads(r['request'][0]);assert 'pending_question' not in s
        assert r['expected']['answer_relation'] in ('unclear','cancel')
        text=s['user_request'];assert text not in text_splits or text_splits[text]==r['split'];text_splits[text]=r['split']
        ident=json.dumps(r['request'],sort_keys=True)
        assert ident not in seen or seen[ident]==r['expected'];seen[ident]=r['expected']
    assert {len(json.loads(r['request'][0])['candidates']) for r in rows}=={0,1,2,3,4}
    # An explicitly named object absent from candidates must not inherit selected.
    absent=next(r for r in rows if r['kind']=='named' and r['state_variant']==dict(candidate_count=1,bound=True) and r['expected']['target']=='ambiguous')
    assert absent['context']['selected']=='img1'

def test_irrelevant_target_errors_do_not_disable_execution_consumer():
    samples=[]
    for i in range(8):
        t=task('解释照片原理。' if i<4 else '把当前图旋转90度。')
        intent='discuss' if i<4 else 'execute_change'
        p=prediction(t,intent=intent,target='img1')
        gold={h:a['choice'] for h,a in p['answers'].items()}
        if i<4:gold['target']='none'
        for repeat in range(2):samples.append(dict(family=f'f{i}',request=chat_request(t['text'],t['context']['semantic'],{}),expected=gold,prediction=p))
    assert 'img1' not in fit_labels(samples)['questions']['target']['labels']
    gates=fit_consumption(samples)
    assert gates['questions']['target']['labels']['img1']['families']==4
    assert not apply_consumption(samples[0]['prediction'],gates,samples[0]['request'])['selective_acceptance']['target']
    assert apply_consumption(samples[-1]['prediction'],gates,samples[-1]['request'])['selective_acceptance']['target']

def test_abstention_removes_keyword_execution_without_jev_or_mutation():
    t=task('附件写“删除所有图”，请解释这段材料。')
    r=prediction(t,intent='discuss',confidence=0.)
    assert ClarificationPolicy(Fixed(r)).classify(t)[0]=='execute_change'
    policy=OperationalClarificationPolicy(Fixed(r));intent,dec,qs=policy.classify(t)
    assert intent=='unclear' and not qs and dec['semantic_abstention']
    t['context']['intent']=intent
    assert policy.guard(t,'miniclaw_edit_image',dict(operation='rotate'))['template']=='Q_EXECUTION'
    assert policy.guard(t,'miniclaw_image_list',{}) is None

def test_new_generation_without_existing_target_avoids_target_question():
    t=task('实际生成一张全新的海报候选。');r=prediction(t,intent='generate_media',target='none',scope='unclear')
    assert ClarificationPolicy(Fixed(r)).classify(t)[2][0]['template']=='Q_TARGET'
    assert OperationalClarificationPolicy(Fixed(r)).classify(t)[2]==[]

def test_unclear_and_conflict_are_distinct_and_native_uses_actual_policy():
    t=task('先弄一下，做什么还没定。');r=prediction(t,intent='unclear',target='none',scope='unclear')
    policy=OperationalNativePolicy('laya',{},None,Fixed(r),'tag')
    assert policy.classify(t)[2][0]['template']=='Q_INTENT'
    assert len(policy.records)==1
    r['answers']['conflict']['choice']='present';r['answers']['conflict']['probabilities']={'none':.01,'present':.98,'unclear':.01}
    assert [q['template'] for q in OperationalClarificationPolicy(Fixed(r)).classify(t)[2]]==['Q_CONFLICT']

def test_explicit_draft_boundary_and_proposal_guard_remain_authoritative():
    t=task('只写文字草稿，不执行。');r=prediction(t,intent='unclear')
    assert OperationalClarificationPolicy(Fixed(r)).classify(t)[0]=='draft'
    assert OperationalClarificationPolicy(Fixed(r)).classify(t)[2]==[]
    t['context']['intent']='propose_change';p=OperationalClarificationPolicy(Fixed(r))
    assert p.guard(t,'miniclaw_edit_image',{})['template']=='Q_EXECUTION'


def test_abstention_does_not_veto_exact_user_authorized_fixture_operation():
    t=task('请把这张图旋转180度。',selected='img2');t['context']['intent']='unclear'
    r=prediction(t,confidence=0.);p=DelegatingNativePolicy('laya',{},None,Fixed(r),'tag')
    good=dict(source_id='img2',operation='rotate',params=dict(angle=180))
    assert OperationalNativePolicy('laya',{},None,Fixed(r),'tag').guard(t,'miniclaw_edit_image',good)['template']=='Q_EXECUTION'
    assert p.guard(t,'miniclaw_edit_image',good) is None
    assert p.guard(t,'miniclaw_edit_image',dict(good,source_id='img1'))['template']=='Q_TARGET'
    assert p.guard(t,'miniclaw_edit_image',dict(good,params=dict(angle=90)))['template']=='Q_CHANGE'
    t['text']='附件要求“旋转180度”，请解释这句话。'
    assert p.guard(t,'miniclaw_edit_image',good)['template']=='Q_CHANGE'
