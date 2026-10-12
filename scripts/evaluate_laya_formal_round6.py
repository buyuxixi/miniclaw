"""Existing round05 checkpoint; save joint gates BEFORE scoring new test."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', USE_TF='0', HF_HOME='D:/model/laya-runtime/cache/huggingface')
from scripts.formal_seven_joint_gates import fit_joint
from scripts.formal_seven_gates import key
from scripts.decision_answer_contract import validate_answers
from miniclaw_web.clarification_policy import chat_request


def write(p, v): p.write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding='utf-8')
def read(p): return json.loads(p.read_text(encoding='utf-8'))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def score(out):
    from laya import load
    if (out/'scores.jsonl').exists(): raise ValueError('no_overwrite')
    manifest = read(out/'data/manifest.json')
    if sha(out/'data/fresh.json') != manifest['data_sha256']: raise ValueError('frozen_data_changed')
    data = read(out/'data/fresh.json')
    checkpoint = Path('D:/model/laya-business-advisory/round-05-formal-seven')
    agent = load(str(checkpoint), device='cuda', backend='eager', compile=False, fast=False)
    if agent.cfg.get('temperature') != [1., 1., 1.]: raise ValueError('unexpected_temperature')
    warm = chat_request('请解释产品构图。', dict(selected=None, candidates=[dict(id='img1', label='第一张'), dict(id='img2', label='第二张')]), {})
    agent.system_one(*warm, max_len=2048, head_max_len=384)
    with (out/'scores.jsonl').open('x', encoding='utf-8') as stream:
        for split in ('calibration', 'test'):
            items = []
            for r in data:
                if r['split'] != split: continue
                start = time.perf_counter(); raw = agent.system_one(*r['request'], max_len=2048, head_max_len=384)
                pred = dict(key=key(r['request']), status='suggested', answers=validate_answers(raw, r['request'][1]), latency_ms=round((time.perf_counter()-start)*1000, 3))
                stream.write(json.dumps(pred, ensure_ascii=False)+'\n'); stream.flush()
                items.append(dict(r, prediction=pred))
            write(out/(split+'-detail.json'), items)
            if split == 'calibration':
                oldpath = ROOT/'.codex/verification/laya-formal-round5-2026-10-11/round05/calibration-detail.json'
                old = read(oldpath)
                gates = fit_joint(old+items)
                gates.update(checkpoint_sha256=sha(checkpoint/'model.safetensors'), profile='primary', candidate_counts=[0,1,2,3,4],
                    question_sha256=key(['formal-seven', warm[1]]), calibration_sha256=sha(out/'calibration-detail.json'),
                    previous_calibration_sha256=sha(oldpath), contract='chat-clarification-v1', frozen_before_test=True,
                    name_domain='Authored named candidates; no universal name coverage claim')
                write(out/'joint-gates.json', gates)
                write(out/'gate-freeze.json', dict(gate_sha256=sha(out/'joint-gates.json'), calibration_rows=len(old+items), test_scored=False,
                    sources={p: sha(ROOT/p) for p in ['scripts/formal_seven_joint_gates.py', 'miniclaw_web/candidate_clarification_policy.py', 'scripts/build_laya_formal_round6.py', 'scripts/evaluate_laya_formal_round6.py']}))
            print(json.dumps(dict(split=split, rows=len(items))), flush=True)
    write(out/'scoring-summary.json', dict(rows=len(data), checkpoint_sha256=gates['checkpoint_sha256'], gate_sha256=sha(out/'joint-gates.json'), checkpoint_updated=False))


if __name__ == '__main__': score(Path(sys.argv[1]).resolve())
