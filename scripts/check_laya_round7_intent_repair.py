"""Disclose post-flow shared host repair; retain original scores and failures."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'hermes-agent')]
from scripts.evaluate_jev_laya_matched import cache,write
from scripts.formal_seven_gates import key
from scripts.formal_seven_joint_gates import apply_joint
from scripts.analyze_laya_round5 import Fixed
from miniclaw_web.candidate_clarification_policy import CandidateClarificationPolicy


def check(out):
    source='miniclaw_web/candidate_clarification_policy.py';old=out/'source-before-intent-repair/candidate_clarification_policy.py'
    namespace={'__name__':'miniclaw_web.pre_intent_repair','__package__':'miniclaw_web'}
    exec(compile(old.read_bytes(),str(old),'exec'),namespace);oldpolicy=namespace['CandidateClarificationPolicy']
    rows=json.loads((out/'data/fresh.json').read_text(encoding='utf-8'));checks=0;changed_intents=0
    for model in ('jev','round05','round07'):
        saved=cache(out/('jev.jsonl' if model=='jev' else model+'/scores.jsonl'))
        gate=json.loads((out/model/'joint-gates.json').read_text(encoding='utf-8')) if model!='jev' else None
        for r in rows:
            if r['split'] not in ('calibration','test'):continue
            raw=saved.get(key(r['request']))
            if not raw or not raw.get('answers'):continue
            state=json.loads(r['request'][0]);t=dict(id=r['id'],text=state['user_request'],confirmed=state['confirmed'],context=deepcopy(r['host_context']))
            for pred in ([raw] if model=='jev' else [raw,apply_joint(raw,gate,r['request'])]):
                before=oldpolicy(Fixed(pred)).classify(deepcopy(t));after=CandidateClarificationPolicy(Fixed(pred)).classify(deepcopy(t))
                assert before[2]==after[2] and before[1]==after[1]
                if before[0]!=after[0]:
                    assert before[0]=='unclear' and after[0]=='execute_change' and t['context']['literal_target']['status']=='unresolved'
                    changed_intents+=1
                checks+=1
    repair=dict(status='passed',source_path=source,original_sha256=hashlib.sha256(old.read_bytes()).hexdigest(),current_sha256=hashlib.sha256((ROOT/source).read_bytes()).hexdigest(),
        applied_after_original_native_flows=True,original_flows_and_analysis_retained=True,frozen_question_comparisons=checks,changed_persisted_intents=changed_intents,
        classifier_probabilities_and_gates_unchanged=True,reason='Unresolved target identity erased an already accepted execution intent; real Q_TARGET reply then unnecessarily reasked Q_EXECUTION')
    write(out/'intent-repair.json',repair)
    trial=out/'intent-repair-trial';trial.mkdir(exist_ok=False);(trial/'round07').mkdir()
    for name in ('jev.jsonl',): (trial/name).write_bytes((out/name).read_bytes())
    (trial/'round07/joint-gates.json').write_bytes((out/'round07/joint-gates.json').read_bytes())
    cases=json.loads((out/'native-cases.json').read_text(encoding='utf-8'));case=next(c for c in cases if c['id']=='r7-name-duplicate-resume')
    write(trial/'native-cases.json',[case]);print(json.dumps(repair))

if __name__=='__main__':check(Path(sys.argv[1]).resolve())
