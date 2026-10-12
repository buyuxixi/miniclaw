"""Prove the post-scoring name repair cannot change the frozen unique-name comparisons."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'hermes-agent')]
from scripts.analyze_laya_round5 import task_for,result_for
from scripts.formal_seven_joint_gates import apply_joint
from scripts.formal_seven_consumption_gates import apply_consumption
from miniclaw_web.candidate_clarification_policy import CandidateClarificationPolicy


def audit(out):
    def read(p):return json.loads(p.read_text(encoding='utf-8'))
    def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
    frozen=read(out/'gate-freeze.json');original=out/'source-before-name-repair/candidate_clarification_policy.py'
    name='miniclaw_web._round6_frozen_candidate'
    spec=importlib.util.spec_from_file_location(name,original);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    assert sha(original)==frozen['sources']['miniclaw_web/candidate_clarification_policy.py']
    old=ROOT/'.codex/verification/laya-formal-round5-2026-10-11'
    gates=read(out/'joint-gates.json');previous=read(old/'round05/consumption-gates.json');n=0
    for p in [out/'calibration-detail.json',out/'test-detail.json',old/'round05/calibration-detail.json',old/'round05/test-detail.json']:
        for row in read(p):
            for prediction in (row['prediction'],apply_consumption(row['prediction'],previous,row['request']),apply_joint(row['prediction'],gates,row['request'])):
                task=task_for(row)
                assert result_for(task,prediction,module.CandidateClarificationPolicy)==result_for(task,prediction,CandidateClarificationPolicy)
                n+=1
    paths=['miniclaw_web/candidate_clarification_policy.py','miniclaw_web/clarification_policy.py','miniclaw_web/hermes_clarification_adapter.py']
    record=dict(status='passed',frozen_unique_name_behavior_comparisons=n,
        original_candidate_sha256=sha(original),repaired_sources={p:sha(ROOT/p) for p in paths},
        timing='after scoring/gate freeze, before native flows; no weights, scores, labels or gates changed',
        finding='Duplicate candidate labels produced invalid duplicate Q_TARGET choices; use unique actual IDs for those choices. Same-name free reply does not bind; user ID choice can bind.',
        limitation='Not a model improvement; common host repair applies to both providers. Existing production process not restarted.')
    (out/'name-repair.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(status='passed',comparisons=n)))


if __name__=='__main__':audit(Path(sys.argv[1]).resolve())
