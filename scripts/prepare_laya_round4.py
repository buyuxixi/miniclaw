"""Freeze same-condition replacement requests and fresh native fixtures."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.formal_seven_gates import key
from scripts.evaluate_jev_laya_matched import write,cache,native_task
from scripts.jev_laya_matched import request_for

OLD=ROOT/'.codex/verification/laya-formal-round3-2026-10-11'

def new_cases():
    actions=['把这张图旋转180度。','请把这张图旋转270度。','帮我把这张图垂直翻转。',
        '麻烦把这张图旋转180度。','请把选中的这张图水平翻转。','把选中的这张图旋转270度。',
        '帮我把选中的这张图旋转90度。','麻烦把选中的这张图垂直翻转。',
        '请把选中的这张图旋转270度。','帮我把选中的这张图垂直翻转。','麻烦把选中的这张图旋转180度。','帮我把这张图旋转270度。']
    quotes=['审核单上写水平翻转产品照，我只问这句话是什么意思。',
        '供应商提议旋转90度，请解释他的建议含义。',
        '设计师留言删除旧照片，我要你概括留言意思。',
        '附件里写立即生成广告片，请说明它在表达什么。',
        '翻转照片这种建议的目的是什么？这里只讨论。',
        '客户提出替换背景，我要理解他的需求。',
        '截图记录了裁剪命令，解释文字即可。',
        '工单上说立即渲染视频，请分析这项指令的意思。']
    drafts=['写一段新品外观介绍和视频提示词，分别标注两部分，保存成文本。',
        '起草简短口播及图像提示词，分别标注两部分，作为文字文件保存。',
        '只写餐具介绍文字，保存草稿，不制作媒体。',
        '给我一份背景描述提示词，保存文字版本。',
        '根据唯一资料“白色陶瓷杯”，写介绍并保存文字；其他性能均无资料，不得声称认证或功效。',
        '资料只说明“黑色金属台灯”，请保存文字介绍；没有亮度、续航、认证或护眼证据，不补这些事实。']
    unknown=['可以开始吧。','这个处理一下。','你看着办吧。','可以开始了。']
    result=[]
    for group,texts in (('action',actions),('quote',quotes),('draft',drafts),('unknown',unknown)):
        for i,text in enumerate(texts):
            for selected in (None,1):
                missing=selected is None
                effect=('rotate' if '旋转' in text else 'flip') if group=='action' else 'text' if group=='quote' else 'artifact' if group=='draft' else 'none'
                if group=='unknown':effect='waiting_intent'
                q='Q_TARGET' if group=='action' and missing else 'Q_INTENT' if group=='unknown' else None
                params=({'angle':180 if '180' in text else 270 if '270' in text else 90} if effect=='rotate' else
                        {'direction':'vertical' if '垂直' in text else 'horizontal'} if effect=='flip' else None)
                result.append(dict(id=f'r4-{group}-{i}-{selected}',text=text,selected=selected,
                    reply='第二张' if group=='action' and missing else None,
                    gold=dict(question=q,effect=effect,target=1,params=params),source='fresh-author-synthetic; finite tool grammar; correlated selected/missing states'))
    assert len(result)==60
    return result

def prepare(out):
    if (out/'requests.json').exists():raise ValueError('already_frozen')
    review=json.loads((out/'data/review.json').read_text(encoding='utf-8'))
    fixtures=deepcopy(json.loads((OLD/'native-cases.json').read_text(encoding='utf-8')))+new_cases()
    requests=json.loads((OLD/'requests.json').read_text(encoding='utf-8'))
    jev_requests={}
    for r in review:
        if r['split']=='test':requests[key(r['request'])]=r['request'];jev_requests[key(r['request'])]=r['request']
    for case in fixtures:
        req=request_for(native_task(case));requests[key(req)]=req;jev_requests[key(req)]=req
    training={json.loads(r['request'][0])['user_request'] for r in review if r['split']=='train'}
    if training & {c['text'] for c in fixtures}:raise ValueError('native_train_text_leak')
    # Carry unknown/error results too; never paid-repeat a previously attempted key.
    previous=cache(OLD/'jev.jsonl');reused={k:v for k,v in previous.items() if k in requests}
    write(out/'requests.json',requests);write(out/'native-cases.json',fixtures)
    write(out/'jev-requests.json',{k:v for k,v in jev_requests.items() if k not in reused})
    (out/'jev.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in reused.values()),encoding='utf-8')
    write(out/'manifest.json',dict(frozen_before_training=True,native_cases=len(fixtures),fresh_native=60,known_native=22,
        new_jev_requests=len([k for k in jev_requests if k not in reused]),reused_jev=len(reused),
        known_regression_source=str(OLD),goal='replace Jev decision recognition; main model remains main planner',
        planned_training=dict(epochs=2,encoder_lr=1e-5,head_lr=1e-4,label_smoothing=.03),
        replacement_arms=['jev','round04_label_gated'],diagnostic_arms=['round03_raw','round04_raw','round04_global_gated'],
        main_budget=dict(max_calls=480,usd=1.6),jev_budget=dict(max_calls=600,usd=.1)))
    print(json.dumps(dict(native=len(fixtures),requests=len(requests),new_jev=len([k for k in jev_requests if k not in reused]))))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);prepare(p.parse_args().out)
