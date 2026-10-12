"""Freeze expanded real tool cases before classifier test/main inference."""
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'hermes-agent')]
from miniclaw_web.clarification_policy import chat_request
from miniclaw_web.literal_image_target import bind_named_attachment,named_operation
from miniclaw_web.clarifications import encode
from scripts.formal_seven_gates import key

VERSION=hashlib.sha256(encode({}).encode()).hexdigest()
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')

def case_task(case):
    cs=[dict(id=f'img{i+1}',label=label) for i,label in enumerate(case['labels'])]
    selected=cs[case['selected']]['id'] if case['selected'] is not None else None
    task=dict(id=case['id'],text=case['text'],confirmed={},context=dict(attachments=[c['id'] for c in cs],versions={},semantic=dict(selected=selected,candidates=cs,selection=None,versions=VERSION)))
    context=bind_named_attachment(task)
    if context is not None:task['context']=context
    return task


def prepare(out):
    if (out/'native-cases.json').exists():raise ValueError('already_frozen')
    cases=[]
    for count in (1,2,3,4):
        labels=['白瓷杯','竹编篮','银托盘','灰布袋'][:count]
        target=count-1;selected=0 if count>1 else None
        for op in ('rotate','flip'):
            text=f'请把「{labels[target]}」'+('旋转90度。' if op=='rotate' else '垂直翻转。')
            params=dict(angle=90) if op=='rotate' else dict(direction='vertical')
            cases.append(dict(id=f'r7-name-{count}-{op}',text=text,labels=labels,selected=selected,gold=dict(effect=op,target=target,params=params,question=None)))
    cases += [
        dict(id='r7-name-override',text='不要改当前选中项，只把「竹编篮」旋转180度。',labels=['白瓷杯','竹编篮','银托盘','灰布袋'],selected=3,gold=dict(effect='rotate',target=1,params=dict(angle=180),question=None)),
        dict(id='r7-name-missing',text='请把「未上传的图片」水平翻转。',labels=['白瓷杯','竹编篮','银托盘'],selected=1,gold=dict(effect='waiting',question='Q_TARGET')),
        dict(id='r7-name-duplicate',text='请把「同名杯子」旋转90度。',labels=['同名杯子','同名杯子','银托盘'],selected=1,gold=dict(effect='waiting',question='Q_TARGET')),
        dict(id='r7-name-duplicate-resume',text='请把「同名杯子」旋转90度。',labels=['同名杯子','同名杯子','银托盘'],selected=1,reply='银托盘',gold=dict(effect='rotate',target=2,params=dict(angle=90),question='Q_TARGET')),
        dict(id='r7-local-region',text='请把这张图圈选的部分调亮，圈外不动。',labels=['白瓷杯','竹编篮'],selected=1,gold=dict(effect='waiting_scope',question='Q_SCOPE')),
        dict(id='r7-local-region-text',text='当前照片局部边缘做修复，周围不动。',labels=['白瓷杯','竹编篮','银托盘'],selected=0,gold=dict(effect='waiting_scope',question='Q_SCOPE')),
        dict(id='r7-quoted-name',text='客户写“请把「竹编篮」旋转90度”，我只问这句是什么意思。',labels=['白瓷杯','竹编篮'],selected=0,gold=dict(effect='text',question=None)),
        dict(id='r7-negated-name',text='不要把「白瓷杯」旋转90度，只写这项操作的文字说明。',labels=['白瓷杯','竹编篮'],selected=1,gold=dict(effect='artifact',question=None)),
        dict(id='r7-draft',text='请写一份图片局部调整注意事项的文字稿，不执行。',labels=['白瓷杯','竹编篮','银托盘'],selected=2,gold=dict(effect='artifact',question=None)),
        dict(id='r7-vague',text='就弄好它吧，不过具体任务还没说。',labels=['白瓷杯','竹编篮','银托盘','灰布袋'],selected=None,gold=dict(effect='waiting_intent',question='Q_INTENT')),
    ]
    for c in cases:
        if c['gold']['effect'] in ('rotate','flip'):
            op=named_operation(c['text'])
            if not op or (op['operation'],op['params'])!=(c['gold']['effect'],c['gold']['params']):raise ValueError('grammar_preflight')
    requests={key(r['request']):r['request'] for r in json.loads((out/'data/fresh.json').read_text(encoding='utf-8')) if r['split']=='test'}
    for c in cases:
        t=case_task(c);req=chat_request(t['text'],t['context']['semantic'],t['confirmed']);requests[key(req)]=req
    write(out/'native-cases.json',cases);write(out/'jev-requests.json',requests)
    write(out/'native-freeze.json',dict(cases=len(cases),requests=len(requests),frozen_before_classifier_test=True,
        cases_sha256=hashlib.sha256((out/'native-cases.json').read_bytes()).hexdigest(),source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        scope='Owned attachment rotate/flip across1..4 actual images; scope cases must wait, not whole-image adjust; no media fees',version_sha256=VERSION))
    print(json.dumps(dict(native=len(cases),jev_requests=len(requests))))

if __name__=='__main__':prepare(Path(sys.argv[1]).resolve())
