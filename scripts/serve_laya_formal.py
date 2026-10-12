"""Loopback formal-seven candidate using the real checkpoint and frozen gates."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',USE_TF='0',HF_HOME='D:/model/laya-runtime/cache/huggingface')
from miniclaw_web.laya_formal import canonical_request,restore_targets
from miniclaw_web.clarification_policy import chat_request,RULE_VERSION
from scripts.decision_answer_contract import validate_answers
from scripts.formal_seven_label_gates import apply_labels
from scripts.formal_seven_consumption_gates import apply_consumption,candidate_domain
from scripts.formal_seven_joint_gates import apply_joint,inference_request
from scripts.formal_seven_gates import key

def create_handler(checkpoint,gates_path):
    from laya import load
    with (checkpoint/'model.safetensors').open('rb') as stream:fingerprint=hashlib.file_digest(stream,'sha256').hexdigest()
    gates=json.loads(gates_path.read_text(encoding='utf-8'))
    gate_sha256=hashlib.sha256(gates_path.read_bytes()).hexdigest()
    warm=chat_request('请解释产品构图。',dict(selected=None,candidates=[dict(id='img1',label='第一张'),dict(id='img2',label='第二张')]),{})
    if (gates.get('version') not in ('formal-seven-per-label-v1','formal-seven-consumption-v1','formal-seven-joint-v1','formal-seven-joint-v2') or gates.get('profile')!='primary' or
        gates.get('checkpoint_sha256')!=fingerprint or gates.get('question_sha256')!=key(['formal-seven',warm[1]])):
        raise ValueError('checkpoint_or_question_gate_mismatch')
    agent=load(str(checkpoint),device='cuda',backend='eager',compile=False,fast=False);lock=threading.Lock()
    if agent.cfg.get('temperature')!=[1.,1.,1.]:raise ValueError('temperature_outside_calibration')
    validate_answers(agent.system_one(*warm,max_len=2048,head_max_len=384),warm[1])
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*unused):pass
        def reply(self,code,value):
            data=json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8')
            self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(data)))
            self.end_headers();self.wfile.write(data)
        def do_GET(self):
            if self.path!='/local/runtime':return self.reply(404,dict(error='not_found'))
            self.reply(200,dict(provider='laya-local',contract=RULE_VERSION,checkpoint_sha256=fingerprint,
                gate_version=gates['version'],gate_sha256=gate_sha256,execution_tools=False,jev_fallback=False,production_selected=False,
                calibration_candidate_count=2 if gates['version']=='formal-seven-per-label-v1' else None,
                calibration_labels=['第一张','第二张'] if gates['version']=='formal-seven-per-label-v1' else None,
                calibration_candidate_counts=gates.get('candidate_counts',[2]),name_domain=gates.get('name_domain','ordinal labels only'),
                version_projection=gates.get('version_projection'), nonempty_confirmations_supported=gates['version']=='formal-seven-joint-v2',
                confirmation_profiles=gates.get('confirmation_profiles',['none'])))
        def do_POST(self):
            if self.path!='/v1/formal':return self.reply(404,dict(error='not_found'))
            try:
                n=int(self.headers.get('Content-Length','0'))
                if not 0<n<=16384:return self.reply(413,dict(error='input_byte_budget'))
                body=json.loads(self.rfile.read(n))
                if set(body)!={'question_version','request'} or body['question_version']!=RULE_VERSION:raise ValueError('invalid_contract')
                request,reverse=canonical_request(body['request']);state=json.loads(request[0])
                # Calibration was on two labelled candidates. Expose the gap and
                # decline unsupported states instead of pretending calibrated coverage.
                if gates['version'] in ('formal-seven-joint-v1','formal-seven-joint-v2'):
                    request=inference_request(request,gates);supported=True
                else:supported=(candidate_domain(gates,state) and not state['confirmed'] and state['target_versions'] is None if gates['version']=='formal-seven-consumption-v1' else
                    len(state['candidates'])==2 and [c['label'] for c in state['candidates']]==['第一张','第二张'])
                if not supported:
                    return self.reply(422,dict(error='candidate_state_outside_calibration'))
            except (ValueError,TypeError,KeyError):return self.reply(422,dict(error='invalid_request'))
            try:
                start=time.perf_counter()
                with lock:raw=agent.system_one(*request,max_len=2048,head_max_len=384)
                validated=dict(raw,answers=validate_answers(raw,request[1]))
                gated=(apply_joint(validated,gates,request) if gates['version'] in ('formal-seven-joint-v1','formal-seven-joint-v2') else
                    apply_consumption(validated,gates,request) if gates['version']=='formal-seven-consumption-v1' else apply_labels(validated,gates))
                result=restore_targets(gated,reverse)
                result.update(checkpoint_sha256=fingerprint,gate_sha256=gate_sha256,provider='laya-local',jev_fallback=False,grants_permission=False,
                    latency_ms=round((time.perf_counter()-start)*1000,3))
                return self.reply(200,result)
            except Exception:return self.reply(503,dict(error='inference_unavailable'))
    return Handler

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--gates',type=Path,required=True);p.add_argument('--port',type=int,default=8768);a=p.parse_args()
    if not 1024<=a.port<=65535:raise ValueError('invalid_port')
    handler=create_handler(a.checkpoint,a.gates)
    print(json.dumps(dict(status='ready',port=a.port)),flush=True)
    ThreadingHTTPServer(('127.0.0.1',a.port),handler).serve_forever()
