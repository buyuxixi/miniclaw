"""Freeze BOTH same-algorithm gates before any round7 test score is computed."""
import gc
import hashlib
import json
import os
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',USE_TF='0',HF_HOME='D:/model/laya-runtime/cache/huggingface')
from scripts.formal_seven_joint_gates import fit_joint
from scripts.formal_seven_gates import key
from scripts.decision_answer_contract import validate_answers
from miniclaw_web.clarification_policy import chat_request

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def score(out):
    import torch
    from laya import load
    manifest=read(out/'data/manifest.json');data=read(out/'data/fresh.json')
    for split,info in manifest['outputs'].items():
        if sha(out/'data'/f'{split}.jsonl')!=info['sha256']:raise ValueError('frozen_data_changed')
    warm=chat_request('请解释产品构图。',dict(selected=None,candidates=[dict(id='img1',label='第一张'),dict(id='img2',label='第二张')]),{})
    models={label:Path(f'D:/model/laya-business-advisory/round-{label[-2:]}-formal-seven') for label in ('round05','round07')}
    for label in models:
        folder=out/label
        if folder.exists():raise ValueError('no_overwrite_scores')
        folder.mkdir()
    frozen={}
    for phase in ('fit','test'):
        for label,checkpoint in models.items():
            folder=out/label;agent=load(str(checkpoint),device='cuda',backend='eager',compile=False,fast=False)
            if agent.cfg.get('temperature')!=[1.,1.,1.]:raise ValueError('temperature_changed')
            agent.system_one(*warm,max_len=2048,head_max_len=384)
            scores={r['key']:r for r in [json.loads(s) for s in (folder/'scores.jsonl').read_text(encoding='utf-8').splitlines()]} if phase=='test' else {}
            with (folder/'scores.jsonl').open('a' if phase=='test' else 'x',encoding='utf-8') as stream:
                def infer(req):
                    ident=key(req)
                    if ident in scores:return scores[ident]
                    start=time.perf_counter();raw=agent.system_one(*req,max_len=2048,head_max_len=384)
                    pred=dict(key=ident,status='suggested',answers=validate_answers(raw,req[1]),latency_ms=round((time.perf_counter()-start)*1000,3))
                    stream.write(json.dumps(pred,ensure_ascii=False)+'\n');stream.flush();scores[ident]=pred;return pred
                for split in (('dev','calibration') if phase=='fit' else ('test',)):
                    items=[dict(r,prediction=infer(r['request'])) for r in data if r['split']==split]
                    write(folder/(split+'-detail.json'),items)
                    if split=='calibration':
                        gates=fit_joint(items)
                        profiles={p:{'records':sum(r['confirmation_profile']==p for r in items),'families':len({r['family'] for r in items if r['confirmation_profile']==p})} for p in ('none','execute','draft','target')}
                        supported=[p for p,v in profiles.items() if v['records']>=8 and v['families']>=4]
                        gates.update(version='formal-seven-joint-v2',profile='primary',candidate_counts=[0,1,2,3,4],confirmation_profiles=supported,
                            confirmation_support=profiles,checkpoint_sha256=sha(checkpoint/'model.safetensors'),question_sha256=key(['formal-seven',warm[1]]),
                            calibration_sha256=manifest['outputs']['calibration']['sha256'],contract='chat-clarification-v1',frozen_before_test=True,
                            name_domain='Authored literal named attachment commands; host binding separate from model')
                        write(folder/'joint-gates.json',gates);frozen[label]=sha(folder/'joint-gates.json')
                    print(json.dumps(dict(model=label,split=split,n=len(items))),flush=True)
                if phase=='test':
                    for req in read(out/'jev-requests.json').values():
                        # Opaque host digest projected exactly as in the server, not learned random text.
                        from miniclaw_web.laya_formal import canonical_request
                        from scripts.formal_seven_joint_gates import inference_request
                        canonical,_=canonical_request(req);infer(inference_request(canonical,read(folder/'joint-gates.json')))
                    known=ROOT/'.codex/verification/laya-formal-round6-2026-10-11/data/fresh.json'
                    for r in read(known):
                        if r['split']=='test':infer(r['request'])
                    write(folder/'summary.json',dict(checkpoint_sha256=sha(checkpoint/'model.safetensors'),unique_inferences=len(scores),temperatures=agent.cfg['temperature']))
            del agent;gc.collect();torch.cuda.empty_cache()
        if phase=='fit':
            sources=['scripts/formal_seven_joint_gates.py','miniclaw_web/formal_confirmations.py','miniclaw_web/literal_image_target.py',
                'miniclaw_web/candidate_clarification_policy.py','miniclaw_web/hermes_clarification_adapter.py','scripts/build_laya_formal_round7.py','scripts/evaluate_laya_formal_round7.py']
            write(out/'gate-freeze.json',dict(gates=frozen,test_scored=False,sources={p:sha(ROOT/p) for p in sources}))

if __name__=='__main__':score(Path(sys.argv[1]).resolve())
