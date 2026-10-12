from copy import deepcopy
import json
from scripts.build_laya_formal_round4 import expanded,build
from scripts.formal_seven_label_gates import fit_labels,apply_labels
from scripts.prepare_laya_round4 import new_cases

def sample(family,label,gold=None,p=.94):
    return dict(family=family,expected=dict(intent=gold or label),prediction=dict(answers=dict(intent=dict(
        choice=label,confidence=.3,probabilities={label:p,'other':1-p}))))

def test_variants_and_states_share_family_and_splits_are_disjoint(tmp_path):
    out=tmp_path/'data';build(out);review=json.loads((out/'review.json').read_text(encoding='utf-8'))
    locations={}
    for r in review:
        assert 'expected' not in json.loads(r['request'][0])
        locations.setdefault(r['family'],set()).add(r['split'])
    assert all(len(v)==1 for v in locations.values())
    manifest=json.loads((out/'manifest.json').read_text(encoding='utf-8'))
    assert manifest['outputs']['train']['rows']==800
    assert manifest['outputs']['train']['families']==96
    assert manifest['outputs']['calibration']['families']==96

def test_per_label_gates_retain_supported_discussion_despite_other_high_errors():
    from scripts.formal_seven_gates import fit
    rows=[sample(f'd{i//2}','discuss') for i in range(16)]
    rows += [sample(f'e{i//2}','execute_change',gold='discuss',p=.995) for i in range(16)]
    gates=fit_labels(rows)
    assert not fit(rows)['questions']['intent']['enabled']
    assert 'discuss' in gates['questions']['intent']['labels']
    assert 'execute_change' not in gates['questions']['intent']['labels']
    before=deepcopy(rows[0]['prediction']);result=apply_labels(before,gates)
    assert result['selective_acceptance']['intent'] and before==rows[0]['prediction']

def test_duplicates_cannot_create_calibration_family_support():
    gates=fit_labels([sample('same','discuss') for _ in range(30)])
    assert not gates['questions']['intent']['enabled']

def test_fresh_native_has_no_train_text_and_missing_target_reply_is_real():
    texts={text for _,_,text in expanded('train')}
    cases=new_cases();assert len(cases)==60
    assert not texts & {c['text'] for c in cases}
    actions=[c for c in cases if c['gold']['effect'] in ('rotate','flip') and c['selected'] is None]
    assert all(c['reply']=='第二张' and c['gold']['question']=='Q_TARGET' for c in actions)

def test_pixel_oracle_checks_new_angles_and_vertical_flip():
    from PIL import Image
    from scripts.evaluate_native_fastpath import expected_fixture_pixels
    im=Image.new('RGB',(2,3));im.putdata([(1,0,0),(2,0,0),(3,0,0),(4,0,0),(5,0,0),(6,0,0)])
    rotated=expected_fixture_pixels(im,dict(effect='rotate',params={'angle':180}))
    vertical=expected_fixture_pixels(im,dict(effect='flip',params={'direction':'vertical'}))
    assert [rotated.getpixel((x,y))[0] for y in range(3) for x in range(2)]==[6,5,4,3,2,1]
    assert [vertical.getpixel((x,y))[0] for y in range(3) for x in range(2)]==[5,6,3,4,1,2]
    assert expected_fixture_pixels(im,dict(effect='rotate')).size==(3,2)
