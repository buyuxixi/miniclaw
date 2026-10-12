"""Separate loopback-only checkpoint preview, no business tools or main-model calls."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',USE_TF='0',
                  HF_HOME='D:/model/laya-runtime/cache/huggingface')
from miniclaw_web.laya_advisory import VERSION, build_state, questions, question_sha256, advisory

HTML = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Laya 业务辅助实验</title><style>body{font:16px system-ui;max-width:850px;margin:36px auto;padding:16px;background:#f5f8fa;color:#203331}textarea{box-sizing:border-box;width:100%;padding:14px;font:16px system-ui}button{padding:10px 20px;margin:12px 0;background:#246b62;color:white;border:0;border-radius:6px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:white;padding:18px;border:1px solid #dce7e4}label{display:block;margin:14px 0}</style>
<h1>Laya · 产品宣传业务辅助</h1><p>展示原始判断与校准后的辅助建议。类别可多选；本页不调用业务工具。低分或证据不足交给主模型。</p>
<textarea id="text" rows="4">这张图能不能还需要修吗？我们讨论一下</textarea>
<label><input type="checkbox" id="selected" checked> 已明确选中当前对象</label>
<label><input type="checkbox" id="existing"> 当前任务确定需要操作已有对象（用于校验澄清，不代表执行授权）</label>
<button id="run">判断</button><div id="status"></div><pre id="out">等待输入</pre>
<script>document.getElementById('run').onclick=async()=>{const b=document.getElementById('run');b.disabled=true;document.getElementById('status').textContent='判断中…';try{const sel=document.getElementById('selected').checked;const context={candidates:[{id:'preview-1',label:'第一张产品图'},{id:'preview-2',label:'第二张产品图'}],selected:sel?'preview-1':null,target_bound:sel,region_bound:false,needs_existing_target:document.getElementById('existing').checked};const start=performance.now();const r=await fetch('/v1/advice',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({contract_version:'laya-business-advisory-v1',state:{user_request:document.getElementById('text').value,context}})});const d=await r.json();document.getElementById('out').textContent=JSON.stringify(d,null,2);document.getElementById('status').textContent=`HTTP ${r.status} · ${Math.round(performance.now()-start)} ms`;}catch(e){document.getElementById('status').textContent='服务不可用：'+e.message;}finally{b.disabled=false;}};</script></html>'''

def create_app(checkpoint, gates_path):
    from fastapi import FastAPI, Request, HTTPException
    from fastapi.responses import HTMLResponse
    from laya import load
    with (checkpoint/'model.safetensors').open('rb') as stream:
        fingerprint=hashlib.file_digest(stream,'sha256').hexdigest()
    gates=json.loads(gates_path.read_text(encoding='utf-8'))
    if gates.get('version')!=VERSION or gates.get('checkpoint_sha256')!=fingerprint or gates.get('question_sha256')!=question_sha256():
        raise ValueError('Calibration does not match checkpoint and contract')
    agent=load(str(checkpoint),device='cuda',backend='eager',compile=False,fast=False)
    lock=threading.Lock()
    # Warm up before ready, and refuse unsupported inference coverage.
    warm=agent.system_one(build_state('讨论产品宣传方案。',{}),questions(),max_len=2048,head_max_len=384)
    from miniclaw_web.laya_advisory import parse_prediction
    parse_prediction(warm)
    app=FastAPI()

    @app.get('/')
    def home():return HTMLResponse(HTML)

    @app.get('/local/runtime')
    def runtime():
        return dict(contract_version=VERSION,checkpoint=str(checkpoint),checkpoint_sha256=fingerprint,
                    calibration=str(gates_path),production_service_changed=False,execution_tools=False,
                    inference_budget=dict(max_len=2048,head_max_len=384))

    async def advice_endpoint(request):
        body=bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>16384:raise HTTPException(413,'Request exceeds byte budget')
        try:
            payload=json.loads(body)
            if set(payload)!={'contract_version','state'} or payload['contract_version']!=VERSION:
                raise ValueError('Unsupported request contract')
            state=payload['state']
            if not isinstance(state,dict) or set(state)!={'user_request','context'}:
                raise ValueError('Unsupported state')
            state=build_state(state['user_request'],state['context'])
        except (ValueError,TypeError,KeyError) as error:raise HTTPException(422,str(error))
        from starlette.concurrency import run_in_threadpool
        def predict():
            with lock:return agent.system_one(state,questions(),max_len=2048,head_max_len=384)
        raw=await run_in_threadpool(predict)
        return dict(contract_version=VERSION,checkpoint_sha256=fingerprint,raw=raw,
                    advice=advisory(raw,state['context'],gates))
    # The locally imported Request must be a concrete annotation (future annotations
    # would otherwise ask FastAPI to resolve it in module globals).
    advice_endpoint.__annotations__['request']=Request
    app.post('/v1/advice')(advice_endpoint)
    return app

def main():
    p=argparse.ArgumentParser();p.add_argument('--checkpoint',type=Path,required=True)
    p.add_argument('--gates',type=Path,required=True);p.add_argument('--port',type=int,default=8767)
    args=p.parse_args()
    if not 1024<=args.port<=65535:raise ValueError('Invalid port')
    import uvicorn
    app=create_app(args.checkpoint,args.gates)
    uvicorn.run(app,host='127.0.0.1',port=args.port,workers=1,log_level='info')

if __name__=='__main__':main()
