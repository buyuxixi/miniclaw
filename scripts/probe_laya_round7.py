"""Actual loopback parity and stored-confirmation pixel check; no paid model calls."""
from copy import deepcopy
import base64
import hashlib
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'hermes-agent')]
from scripts.evaluate_jev_laya_matched import cache,write
from scripts.formal_seven_gates import key
from scripts.formal_seven_joint_gates import apply_joint,inference_request
from miniclaw_web.laya_formal import LayaFormalDecisions,canonical_request,restore_targets
from miniclaw_web.clarification_policy import chat_request,question,RULE_VERSION


def probe(out):
    import httpx
    from PIL import Image
    from miniclaw_web.store import Store
    from miniclaw_web.clarifications import Clarifications
    from miniclaw_web.hermes_clarification_adapter import HermesClarificationAdapter
    from miniclaw_web.attachments import upload
    from miniclaw_web.images import ImageJobs
    from scripts.run_laya_round7_comparison import Round7NativePolicy
    gates=json.loads((out/'round07/joint-gates.json').read_text(encoding='utf-8'))
    pin=hashlib.sha256((out/'round07/joint-gates.json').read_bytes()).hexdigest()
    dec=LayaFormalDecisions('http://127.0.0.1:8771',gates['checkpoint_sha256'],gate_sha256=pin)
    scores=cache(out/'round07/scores.jsonl');rows=json.loads((out/'data/fresh.json').read_text(encoding='utf-8'))
    chosen={}
    for r in rows:
        if r['split']!='test':continue
        state=json.loads(r['request'][0]);count=len(state['candidates']);ident=(count,r['confirmation_profile'])
        chosen.setdefault(ident,r)
    checks=[];delta=0
    for i,((count,profile),r) in enumerate(sorted(chosen.items())):
        state=json.loads(r['request'][0]);aliases={c['id']:hashlib.sha256((str(i)+c['id']).encode()).hexdigest()[:32] for c in state['candidates']}
        state['candidates']=[dict(c,id=aliases[c['id']]) for c in state['candidates']]
        state['selected']=aliases.get(state['selected']);state['target_versions']='b'*64
        state['confirmed']={k:aliases.get(v,v) for k,v in state['confirmed'].items()}
        req=chat_request(state['user_request'],dict(selected=state['selected'],candidates=state['candidates'],versions=state['target_versions']),state['confirmed'])
        canonical,reverse=canonical_request(req);projected=inference_request(canonical,gates)
        expected=restore_targets(apply_joint(scores[key(projected)],gates,projected),reverse)
        result=dec.evaluate('probe',str(i),'same frozen request',{'revision':'round7'},request=req)
        assert result['status']=='suggested' and result['selective_acceptance']==expected['selective_acceptance']
        for head,a in expected['answers'].items():
            actual=result['answers'][head];assert actual['choice']==a['choice'] and actual['confidence']==a['confidence']
            for label,p in a['probabilities'].items():delta=max(delta,abs(actual['probabilities'][label]-p))
        assert delta<1e-6 and not result['jev_fallback'] and not result['grants_permission']
        checks.append(dict(candidate_count=count,confirmation_profile=profile,actual_ids_restored=True))
    invalid=[];base=json.loads(next(iter(chosen.values()))['request'][0])
    for label,change in [('unsupported_scope',{'confirmed':{'Q_SCOPE':'这里'}}),('unknown_confirmation',{'confirmed':{'hidden':'execute'}}),('bad_version',{'target_versions':'changed'}),('fifth_candidate',{'candidates':[dict(id=f'img{x}',label=f'图片{x}') for x in range(1,6)],'selected':None})]:
        s=dict(deepcopy(base),**change);req=chat_request(s['user_request'],dict(selected=s['selected'],candidates=s['candidates'],versions=s['target_versions']),s['confirmed'])
        result=dec.evaluate('invalid',label,'out of calibrated domain',{'revision':'round7'},request=req)
        assert result['status']=='unavailable' and not result['answers'] and result['reason']=='local_http_422'
        invalid.append(dict(case=label,status=result['status'],reason=result['reason']))
    attempt=sum(1 for p in out.glob('confirmation-pixels-*') if p.is_dir())+1
    folder=out/f'confirmation-pixels-{attempt}';folder.mkdir(exist_ok=False)
    store=Store(folder);service=Clarifications(store);images=ImageJobs(store);owner='confirmed-pixel-chat'
    original=Image.new('RGBA',(48,32),(80,120,200,255))
    for x in range(3,9):
        for y in range(4,12):original.putpixel((x,y),(250,10,50,255))
    stream=io.BytesIO();original.save(stream,'PNG');raw=stream.getvalue();image=upload(store,owner,'实际铜杯.png',base64.b64encode(raw).decode())
    saved=service.start(owner,'请把这张图旋转180度。',dict(attachments=[image['id']],versions={},semantic=dict(selected=image['id'],candidates=[dict(id=image['id'],label='实际铜杯')])))
    service.configure(saved['id'],intent='unclear')
    item=service.prepare(saved['id'],[question('Q_EXECUTION','确认执行？',['确认执行','只整理方案'])],'hook');service.seal(saved['id'],owner,0);item=service.request(item)
    service.answer([owner],item['id'],item['version'],{'Q_EXECUTION':'确认执行'},'real-pixel-answer');assert service.claim('real-pixel-answer')
    service.configure(saved['id'],latest_user_reply='确认执行')
    class NoDecision:
        def evaluate(self,*args,**kwargs):raise AssertionError('resume must not reclassify')
    policy=Round7NativePolicy('laya',{},None,NoDecision(),'probe')
    adapter=HermesClarificationAdapter(service,policy,dict(agent=SimpleNamespace(max_iterations=10)),saved['id'],resume_job='real-pixel-answer')
    assert adapter.before_model([]) is None
    args=dict(source_id=image['id'],operation='rotate',params=dict(angle=180));calls=[]
    def execute():
        calls.append(1)
        return json.dumps(images.submit(owner,image['id'],'rotate',{'angle':180},'real-pixel-operation'))
    receipt=adapter.dispatch('miniclaw_edit_image',args,'confirmed-operation',execute)
    images.executor.shutdown(wait=True)
    assert adapter.dispatch('miniclaw_edit_image',args,'duplicate',execute)==receipt and len(calls)==1
    jobs=store.image_jobs(owner);assert len(jobs)==1 and jobs[0]['state']=='succeeded'
    output=store.get('attachments',jobs[0]['output']['id'],owner)
    with Image.open(output['path']) as actual:assert actual.convert('RGBA').tobytes()==original.transpose(Image.Transpose.ROTATE_180).tobytes()
    assert Path(store.get('attachments',image['id'],owner)['path']).read_bytes()==raw
    with httpx.Client(timeout=5,trust_env=False) as client:runtime=client.get('http://127.0.0.1:8771/local/runtime').json()
    write(out/'live-probe.json',dict(status='passed',checks=checks,max_probability_delta=delta,unsupported=invalid,runtime=runtime,confirmation_pixels=dict(actual_saved_answer=True,actual_image_job=True,pixels_match=True,original_unchanged=True,duplicate_writes=0,decision_reclassification=0),paid_model_calls=0))
    print(json.dumps(dict(status='passed',checks=len(checks),max_probability_delta=delta,confirmation_pixels=True)))

if __name__=='__main__':probe(Path(sys.argv[1]).resolve())
