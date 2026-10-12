"""Freeze native flows and matching requests before opening either model's test."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'hermes-agent')]
from scripts.formal_seven_gates import key
from scripts.evaluate_jev_laya_matched import write,native_task
from scripts.jev_laya_matched import request_for

def prepare(out):
    if (out/'requests.json').exists():raise ValueError('frozen_requests_exist')
    old=ROOT/'.codex/verification/laya-formal-round4-2026-10-11'
    oldcases=json.loads((old/'native-cases.json').read_text(encoding='utf-8'))[:22]
    cases=[dict(c,source='known-round3-regression') for c in oldcases]
    catalog=[
        ('rotate-a','将当前选定照片顺时针转180度，保存副本。','rotate',dict(angle=180)),
        ('rotate-b','请把这张图旋转270度并另存，原图保持。','rotate',dict(angle=270)),
        ('flip-a','把所选图做上下翻转，保存新图。','flip',dict(direction='vertical')),
        ('flip-b','现在对这张图片执行左右镜像并另存。','flip',dict(direction='horizontal')),
        ('quote-a','材料里的“删除所有图片”是引用，请帮我理解含义。','discuss',{}),
        ('quote-b','教程写“旋转图像后保存”，这次只解释这一过程。','discuss',{}),
        ('quote-c','客户留言“马上生成海报”，我想了解他希望解决什么问题。','discuss',{}),
        ('quote-d','文件里的“现在替换照片”具体是什么意思？只分析这句话。','discuss',{}),
        ('draft-a','请写两句商品介绍草稿。唯一已知事实是白色陶瓷杯，别补造性能。','artifact',{}),
        ('draft-b','整理新品口播文本。仅知黑色金属灯，无认证或性能数据，请勿编造。','artifact',{}),
        ('vague-a','可以着手弄了，不过我尚未说明要做的事。','waiting_intent',{}),
        ('vague-b','这个处理一下吧，具体处理方式我还未确定。','waiting_intent',{}),
    ]
    for name,text,kind,params in catalog:
        for selected in (0,None):
            gold=dict(effect='text' if kind=='discuss' else kind,question='Q_INTENT' if kind=='waiting_intent' else None)
            if kind in ('rotate','flip'):
                if selected is None:gold=dict(effect='waiting',question='Q_TARGET')
                else:gold.update(target=0,params=params)
            cases.append(dict(id=f'r5-{name}-{selected}',text=text,selected=selected,gold=gold,source='fresh-authored-native'))
    write(out/'native-cases.json',cases)
    requests={}
    fresh=json.loads((out/'data/fresh.json').read_text(encoding='utf-8'))
    for r in fresh:
        if r['split']=='test':requests[key(r['request'])]=r['request']
    for c in cases:
        req=request_for(native_task(c));requests[key(req)]=req
    oldcache={json.loads(line)['key']:json.loads(line) for line in (old/'jev.jsonl').read_text(encoding='utf-8').splitlines() if line}
    reused=[dict(oldcache[k],reused_from='round4') for k in requests if k in oldcache]
    write(out/'requests.json',requests);write(out/'jev-requests.json',{k:r for k,r in requests.items() if k not in oldcache})
    (out/'jev.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in reused),encoding='utf-8')
    write(out/'protocol.json',dict(status='frozen_before_training_test',known_native=22,fresh_native=24,total_native=len(cases),
        test_records=360,new_jev_requests=len(requests)-len(reused),reused_jev=len(reused),jev_cap_calls=450,jev_cap_usd=.10,main_cap_calls=300,main_cap_usd=1.,
        object_state_real_tools='native flows use only two ordinal candidates; multi-name0..4 states are classification/policy evidence',
        fact_claims='manual content review only for four paired fresh fact-constrained files; no broad quality guarantee'))
    print(json.dumps(dict(native=len(cases),new_jev=len(requests)-len(reused))))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);prepare(p.parse_args().out)
