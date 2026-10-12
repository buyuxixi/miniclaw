from copy import deepcopy
import json
from scripts.build_laya_formal_data import BLOCKS,record
from scripts.formal_seven_gates import fit,apply_gates
from miniclaw_web.clarification_policy import chat_request

def sample(family,choice='discuss',gold='discuss',prob=.96):
    return dict(family=family,expected={'intent':gold},prediction=dict(answers=dict(intent=dict(choice=choice,confidence=.2,
        probabilities={choice:prob,('draft' if choice!='draft' else 'discuss'):1-prob}))))

def test_same_input_without_pending_has_consistent_observable_labels():
    a=record('reply_target','第二张。',None,'primary','train',1)
    b=record('reply_target','第二张。',None,'enriched','train',1)
    assert a['expected']['answer_relation']=='unclear'
    assert b['expected']['answer_relation']=='answers_current'
    assert a['expected']['intent']=='unclear' and b['expected']['intent']=='execute_change'
    assert 'expected' not in json.loads(a['request'][0])

def test_questions_are_exact_production_contract_and_region_state_not_scope():
    a=record('region','只修改这里',None,'primary','test',1)
    b=record('region','只修改这里','img2','enriched','test',1)
    assert a['request'][1]==chat_request('',{'candidates':[dict(id='img1',label='第一张'),dict(id='img2',label='第二张')]},{})[1]
    assert a['expected']['scope']==b['expected']['scope']=='selected_region'
    assert json.loads(b['request'][0])['selection']

def test_calibration_requires_independent_families_and_keeps_high_error_disabled():
    repeated=[sample('one-family') for _ in range(20)]
    assert not fit(repeated)['questions']['intent']['enabled']
    errors=[sample(str(i),gold='draft') for i in range(20)]
    assert not fit(errors)['questions']['intent']['enabled']

def test_selective_acceptance_is_marker_not_probability_and_does_not_mutate_raw():
    samples=[sample(str(i//2)) for i in range(12)];gates=fit(samples)
    assert gates['questions']['intent']['enabled']
    raw=samples[0]['prediction'];before=deepcopy(raw);gated=apply_gates(raw,gates)
    assert raw==before and gated['answers']['intent']['confidence']==1.
    assert gated['answers']['intent']['raw_confidence']==.2
    assert gated['acceptance_marker_not_probability']
    wrong=sample('x',choice='draft')['prediction']
    assert apply_gates(wrong,gates)['answers']['intent']['confidence']==0.

def test_split_text_families_are_disjoint():
    seen={}
    for split,block in BLOCKS.items():
        for line in block.strip().splitlines():
            text=line.split('|',1)[1]
            assert text not in seen
            seen[text]=split
