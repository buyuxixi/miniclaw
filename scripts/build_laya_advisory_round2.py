"""Second development round; round-one test becomes dev, never the new test."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.build_laya_advisory_data import parse_cases,audit
from miniclaw_web.laya_advisory import VERSION,CATEGORIES,questions,build_state

TRAIN='''
discuss|none|image|我只是询问提亮的必要性，没有请求实施，说明判断依据。|missing
discuss|none|image|现在是在评估裁剪的利弊，请不要把评估理解成裁图要求。|region
discuss|none|image|只问改背景有没有价值，不要求改动任何一张图。|missing
discuss|none|image|图片处理先别开始，我问的是背景是否适合。|ready
discuss|none|image|对这些图的建议我们聊聊，哪张要操作还不用确定。|missing
discuss|none|image|客户留言让旋转主图，我只想知道他这段话表达什么。|ready
discuss|none|video|不要求你渲染，我仅问宣传视频为何需要景深。|ready
discuss|none|video|别人建议现在开始生成视频，帮我分析建议的合理性。|ready
discuss|none|scheme|方案修改的方向有哪些？本轮只做比较。|ready
discuss|none|narration|这句口播是不是有夸大的问题？先判断。|ready
execute_change|none|image|能不能帮我把已选图片水平翻转？现在就执行。|ready
execute_change|none|image|麻烦把当前图旋转九十度可以吗？请立即保存。|ready
generate_media|none|video|可以帮我生成一条视频吗？请现在启动生成。|ready
generate_media|none|image|请生成一张图片，口播不用修改。|ready
draft|none|image_prompt|给我一段图像生成提示词文本，构图简洁。|ready
draft|none|image_prompt|修图prompt加上保留标签文字的约束，返回新prompt。|ready
draft|none|image_prompt|背景替换指令写成图片编辑提示词供我复制。|ready
draft|none|image_prompt|写产品海报的图像模型提示词，不需要生成图片。|ready
draft|none|image_prompt|把重绘背景的prompt润色一下，本轮只写prompt。|ready
draft|none|image_prompt|输出用于图片生成的中文正向和负向提示词。|ready
draft|none|image_prompt|请把主图出图指令翻译为英文提示词。|ready
draft|none|image_prompt|重写这段图片提示词，强调不要改变包装。|ready
discuss|none|image_prompt|这个修图提示词会误删包装文字吗？分析提示词。|ready
propose_change|none|image_prompt|对现有图片提示词列一份待审修改表，不合并正文。|ready
revise_task|none|image_prompt|图像提示词优化任务加入禁止改变主体的要求，只更新任务。|ready
execute_change|none|image_prompt|把已经确认的图片prompt保存到当前主图节点。|ready
draft|none|video_prompt|写一版固定产品、背景缓慢变化的视频prompt文字。|ready
draft|none|video_prompt|视频运镜指令精简成三句，给我新版提示词。|ready
discuss|none|video_prompt|视频提示词里绕拍和固定镜头是否冲突？请评估描述。|ready
propose_change|none|video_prompt|对视频prompt做待审核的修改建议，先不要保存。|ready
revise_task|none|video_prompt|视频提示词优化要求改为镜头不移动，任务继续但先只记录。|ready
execute_change|none|video_prompt|确认这份视频提示词作为节点字段，立即写入。|ready
draft|none|scheme,narration|起草三段分镜和对应口播稿，不生成媒体。|ready
draft|none|scheme,image_prompt|宣传方案附一份海报图像提示词，交文字给我。|ready
draft|none|narration,video_prompt|口播稿和视频提示词各写一份，暂不调用生成。|ready
draft|none|image_prompt,video_prompt|分别优化出图prompt和视频prompt，只要两段文字。|ready
generate_media|none|image,video|先生成新品海报，再生成配套短视频，都出候选。|ready
execute_change|none|image,narration|当前图左右镜像，确认的新口播也保存进正式稿。|ready
draft|none|scheme|列出宣传片的受众和镜头安排，只给方案。|ready
draft|none|narration|让口播更像朋友介绍，输出两版口播文本。|ready
execute_change|target|image|直接把某张候选旋转一百八十度，但还没指定哪张。|missing
execute_change|region|image|选中图的那一部分提高亮度，没有说明区域位置。|region
unclear|conflict|image|这轮背景必须变红同时必须变蓝，不允许分版本或分先后。|ready
unclear|intent||先来一下那个，具体做什么你猜。|empty
'''

CAL='''
discuss|none|scheme|宣传分镜是不是太密？只讨论方案。|ready
draft|none|scheme|写一份校园受众的宣传方案供我看。|ready
propose_change|none|scheme|给现有方案准备改动提案，等待审阅。|ready
revise_task|none|scheme|任务新增简洁风格要求，只记录要求。|ready
draft|none|image_prompt|帮我写一段主图生成提示词，不出图。|ready
draft|none|image_prompt|优化这个修图prompt的光线描述，只给文字。|ready
discuss|none|image_prompt|这份图像提示词可能把商标弄错吗？分析文本。|ready
execute_change|none|image_prompt|确定的新图像提示词写到主图节点。|ready
draft|none|video_prompt|写短视频的镜头提示词，本轮不要制作视频。|ready
draft|none|video_prompt|视频prompt减少花哨运动，返回改写文本。|ready
discuss|none|video_prompt|解释视频提示词中的横移是什么。|ready
execute_change|none|video_prompt|把确认的视频prompt存进当前节点。|ready
draft|none|narration|口播重新写成一句自然的介绍，给我文本。|ready
discuss|none|narration|口播结尾听起来夸张吗？评价一下。|ready
propose_change|none|narration|给口播拟待审核的调整清单，别改主稿。|ready
adopt_result|none|narration|当前选择的口播版本正式采用。|ready
discuss|none|image|我只问图片背景的必要改动，不是在要求修图。|missing
execute_change|none|image|当前主图左右翻转一次并保存新版本。|ready
generate_media|none|image|立即生成一张新海报候选。|ready
adopt_result|none|image|确认当前已选的图片候选为采用版本。|ready
discuss|none|video|先聊视频的运动节奏，不操作成片。|ready
generate_media|none|video|现在制作一个七秒视频候选。|ready
cancel|none|video|当前视频生成任务停止并终止。|ready
adopt_result|none|video|已选视频候选设为正式采用。|ready
draft|none|scheme,narration|写出宣传分镜以及口播，暂不制作。|ready
draft|none|image_prompt,video_prompt|图像和视频提示词各写一版，只交文本。|ready
draft|none|narration,video_prompt|口播和配套视频prompt都给我改写文本。|ready
generate_media|none|narration,video|先写口播再实际生成配套视频候选。|ready
new_topic|none||离开产品项目，另聊阳台种菜。|ready
unclear|intent||那样那个，你帮我来一下。|empty
execute_change|target|image|选择一个图来改，但我还未说是哪张。|missing
execute_change|target|image|裁一张产品图，尚未确定要裁哪一张。|missing
adopt_result|target|video|采用一个片段，还不知道采用哪段。|missing
execute_change|region|image|修改已选图片的这里，位置没有提供。|region
unclear|conflict|image|同一背景必须保持原样同时彻底替换，两条不能分开执行。|ready
discuss|none|image|没有选中对象也不影响讨论，我只想问照片亮度是否适合。|missing
'''

TEST='''
discuss|none|image|我是在问主图需不需要换色，还没有下达换色操作。|missing
discuss|none|image|请评价裁成方形是否合适，评价本身不能当作裁剪授权。|region
discuss|none|image|客户写着“立刻重绘”，分析他想强调什么，别动图。|ready
discuss|none|image|暂时不改照片，聊聊产品旁边留白的作用。|ready
discuss|none|video|用产品图制作动画会有哪些风险？先说可行性。|ready
discuss|none|narration|现在只评价口播感染力，不需要给我新稿。|ready
discuss|none|scheme|从营销角度比较当前两种方案，先讨论。|ready
draft|none|image_prompt|把图片生成的prompt整理成我能复制的一段话。|ready
draft|none|image_prompt|写修图的负向提示词，强调不得扭曲标签。|ready
draft|none|video_prompt|请给我视频模型的文字提示词，镜头缓缓拉远。|ready
draft|none|video_prompt|把视频prompt中的动态背景换成静态描述，返回新文字。|ready
draft|none|narration|给新品写一段不夸功效的口播草稿。|ready
draft|none|scheme|写个面向初次购买者的宣传方案，包含镜头安排。|ready
propose_change|none|image|现有图整理成待审修图清单，等我确认后再执行。|ready
propose_change|none|scheme|为现有分镜写修改提案，正式方案先保留。|ready
execute_change|none|image|能帮我对当前图片做垂直镜像吗？请现在保存为新版本。|ready
execute_change|none|image_prompt|把这份已确认的修图prompt存到主图字段。|ready
execute_change|none|video_prompt|立即用确认的视频提示词覆盖当前节点的提示词字段。|ready
generate_media|none|image|这次要实际出一张新图候选，不只是写prompt。|ready
generate_media|none|video|执行视频制作，使用确认好的提示词生成一次。|ready
adopt_result|none|image|不用另生成，选中的图片版本就正式用这一张。|ready
adopt_result|none|video|当前选定片段设成最终采用视频。|ready
cancel|none|image|本次修图任务撤销，不再继续处理。|ready
cancel|none|scheme|终止本轮方案设计任务。|ready
revise_task|none|narration|只更新口播任务要求：自然口语，暂时不写新稿。|ready
revise_task|none|video|视频任务继续，但要求改成十六比九，这轮先记录。|ready
new_topic|none||先退出宣传项目，另外聊家用书桌怎么整理。|ready
unclear|intent||之前说的那什么，你先那样处理吧。|empty
execute_change|target|image|在候选图片中操作一张，具体哪张我还未指明。|missing
adopt_result|target|image|把一个候选设为最终主图，候选还没有选定。|missing
execute_change|region|image|只编辑当前图某一处，但我没有告诉你是哪一处。|region
unclear|conflict|video|此次必须制作视频，也禁止此次制作视频，两条必须一起成立。|ready
draft|none|scheme,narration|写一套短片分镜并附上逐镜口播文本。|ready
draft|none|image_prompt,video_prompt|出图prompt和视频prompt分别做文字润色，不生成素材。|ready
draft|none|narration,video_prompt|给我更自然的口播和对应的视频提示词两份文字。|ready
generate_media|none|image,video|先实际生成海报，然后实际生成配套短视频候选。|ready
discuss|none|image|“请裁剪这张图”是旧留言，当前我只想探讨这种裁法的好处。|missing
draft|none|image_prompt|不要求AI修图，把应怎样修写成图像编辑提示词即可。|ready
discuss|none|video_prompt|请解释这段视频prompt会产生何种运镜，不制作成片。|ready
draft|none|scheme,image_prompt|新品宣传方案和海报用的图像prompt一起写成文本。|ready
'''

def main():
    p=argparse.ArgumentParser();p.add_argument('--previous',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    if args.out.exists():raise ValueError('Use a new version')
    prior=json.loads((args.previous/'review.json').read_text(encoding='utf-8'))
    rows=[]
    for r in prior:
        if r['split'] not in ('train','dev','test'):continue
        if r['split']=='test':r.update(split='dev',source='round1_test_promoted_to_development')
        rows.append(r)
    rows+=parse_cases(TRAIN,'r2-train',('茶壶','护手霜'))
    for r in rows:
        if r['split']=='r2-train':r['split']='train'
    # Explicitly contextualized short replies all stay in a training family.
    for intent,cats,request in [
        ('discuss',['image'],'是否只讨论图片问题，不改图？'),
        ('draft',['video_prompt'],'是否只写视频提示词，不生成视频？'),
        ('execute_change',['image'],'是否将已选主图水平翻转并保存？'),
        ('generate_media',['video'],'是否按确认提示词现在生成一个视频候选？'),
        ('adopt_result',['image'],'是否采用已选图片候选？'),
        ('cancel',['video'],'是否终止当前视频任务？'),
        ('revise_task',['scheme'],'是否只更新任务风格要求，暂不制作？'),
    ]:
        r=parse_cases(f'{intent}|none|{",".join(cats)}|好，就按刚才的问题办。|ready','short-confirm-'+intent,('陶瓷杯',))[0]
        r.update(split='train',family_id='short-confirm-all-r2')
        r['context'].update(pending_task='产品宣传任务',pending_question=request,needs_existing_target=intent in ('execute_change','adopt_result'))
        rows.append(r)
    rows+=parse_cases(CAL,'calibration',('香薰瓶',))
    rows+=parse_cases(TEST,'test',('保温壶',))
    # Prefix fresh calibration/test families so none aliases the promoted old test.
    for r in rows:
        if r['split'] in ('calibration','test'):r.update(id='r2-'+r['id'],family_id='r2-'+r['family_id'])
    summary=audit(rows);args.out.mkdir(parents=True)
    def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    write(args.out/'questions.json',questions());write(args.out/'review.json',rows)
    outputs={}
    for split in summary:
        path=args.out/(split+'.jsonl')
        records=[]
        for r in rows:
            if r['split']!=split:continue
            expected=dict(intent=r['intent'],clarification=r['clarification'])
            expected.update({'category_'+c:'yes' if c in r['categories'] else 'no' for c in CATEGORIES})
            records.append(dict(state=build_state(r['text'],r['context']),questions=questions(),expected=expected))
        path.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records),encoding='utf-8')
        outputs[split]=dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),**summary[split])
    report=dict(version=VERSION,data_version='advisory-v2',outputs=outputs,
                previous_manifest_sha256=hashlib.sha256((args.previous/'manifest.json').read_bytes()).hexdigest(),
                annotation='Synthetic author labels, not external blind/production data.',
                rationale='Round-one observed failures guide new training examples. Round-one test is now dev. New calibration and test families are frozen before training.',test_used_for_training=False)
    write(args.out/'manifest.json',report)
    print(json.dumps({split:info['rows'] for split,info in summary.items()}))

if __name__=='__main__':main()
