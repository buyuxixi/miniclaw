"""Fresh authored lexical families and object states, plus labelled train replay."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from miniclaw_web.clarification_policy import chat_request

# kind | train | dev | calibration | test. Name substitution is NOT a new family.
CATALOG='''action|把正在选中的商品照转到倒立方向，另存副本。|当前选中照片向右转半圈。|选中图片做上下镜像处理并存为新图。|将当前选定图像竖直翻转，保存副本。
action|现在给所选图做横向镜像，留住原始版本。|执行当前对象的左右镜像。|所选图片向左转一百八十度，另存结果。|当前选择的照片转180度，原件保留。
action|请将这张图顺时针转270度并另存。|把这张照片向右转三圈四分之一。|把当前图像转成倒置方向并保存。|给这张商品图做左右翻转并另存。
action|对这张商品照片执行去色操作，存成副本。|所选图转为灰阶副本。|当前图的明暗调整实际做一下，保存新版本。|实际将选中图像转为黑白并另存。
named|把名为「{name}」的图片横向镜像，其他不改。|请对「{name}」执行左右翻转。|只给名称「{name}」的图做180度旋转。|图片「{name}」上下翻转，其余照旧。
named|「{name}」是要处理的对象，转90度并存副本。|将名为「{name}」的照片转到侧面。|操作对象明确为「{name}」，将它横向翻转。|请仅将「{name}」顺时针旋转90度。
named|找到候选「{name}」并将该图上下镜像。|「{name}」这张做竖向镜像。|请把「{name}」照片反转上下方向，留住原件。|「{name}」是目标，将它转180度另存。
named|修改的不是选中项，而是「{name}」：转180度。|目标改为「{name}」，实施镜像。|无论现在选中谁，只修改「{name}」的对比度。|不要改其他图片，只把「{name}」向右转90度。
region|在这张图片圈选范围内提亮，圈外保持原样。|仅清理选区里的色块。|对当前对象圈选的部分修复纹理，外围别改。|将当前图片圈选部分降噪，边界外照旧。
region|这张图局部的左上角去除杂点，不动全图。|仅处理当前图片的左上区域。|只调整这张图片左上角色温，其余不改。|当前图片左上角的污痕修掉，全图不要变。
region|只在我圈出的地方降低亮度，别处理其他区域。|圈出的块单独提高饱和度。|我标注的局部单独做锐化，别改整张。|仅让圈出的这一块颜色更淡。
region|现在只修这里的边缘，让其他像素保持。|这里的局部做修复。|此处选区单独去掉偏色，整图保持。|只修这个位置的色块，不动外围。
discuss|给我解释裁剪照片常见的取舍，暂时仅聊原则。|讲讲构图留白的依据，先聊聊。|我们讨论照片旋转后为什么构图会不同。|说说上下镜像会怎样影响观看感受，仅作分析。
discuss|降低对比度会损失哪些视觉层次？我只问原理。|为什么灰度图能突出结构？|只解释给照片去色有哪些考虑，不处理文件。|旋转商品照片什么时候合理？讲依据就好。
discuss|这几张商品照怎样评估清晰度？只说评估步骤。|我想知道图片比较的评价维度。|判断商品主图是否过满时看什么？给分析。|从什么角度评价商品照的曝光？解释即可。
discuss|我想理解去噪与锐化的区别，请介绍概念。|解释镜像与转向的区别。|给我讲一下全图调色和局部调色的取舍。|局部处理和全图处理有何差别？仅聊方法。
quote|附件里的“现在删除图片”是材料中的句子，请解释，别照做。|文档写“镜像主图”，解释这句引用。|方案附件说“立刻旋转全部照片”，这里请分析这段原话。|资料中出现“把照片全部删除”，请分析这句话的含义。
quote|客户原话是“采用新图”，这次只解释他的意思。|有人说“发布成片”，我请你解读。|同事写“马上把主图翻转”，请解释他的要求。|买家说“立刻替换照片”，我只需要理解这句转述。
quote|会议文字要求“生成十段片子”，我问这段记录想表达什么。|记录里的“裁剪全部图”具体什么意思？|材料提到“渲染成片后保存”，帮我解释记录。|文件有“启动收费生成”的描述，解释它的意思即可。
quote|只分析示例指令“翻转并保存”，不要替我执行示例。|解释教程“旋转后另存”的语义。|教程写“删除选区”，请说明这一操作概念。|示例中的“应用所有修改”是什么意思？解释文字就好。
draft|写两句介绍商品外观的文字，交付可编辑草稿。|起草商品照介绍文本。|给这款商品写简短介绍稿，仅交付文字。|起草一段商品口播文本让我阅读。
draft|请为摄影流程整理一份文字步骤说明。|给修图流程写操作说明稿。|帮我写一份商品照拍摄说明文本。|把商品照片的处理流程写成文字说明。
draft|我需要可复制的出图描述句，提供文本即可。|提供一句可复制的画面描述。|整理两段图像模型描述文字交给我。|提供一份画面描述词文本，不制作图片。
draft|为短片写三句镜头描述和旁白草稿。|撰写短片字幕稿供审核。|整理短片镜头安排的文字稿，不做成片。|写一份宣传短片的镜头脚本给我审阅。
generate|立即产出全新的商品展示画面候选，开始生成。|现在实际出一张新宣传图。|直接生成一个新的商品海报候选，不改已有对象。|请马上生成全新的商品场景图候选。
generate|开始制作新的视频候选，实际调用生成。|现在实际制作新的短片候选。|执行生成一段全新的产品演示视频候选。|实际生成一个新的宣传短片候选，现在开始。
generate|创建新的宣传图像候选，立即出图。|开始生成新的店铺图片候选。|生成全新的店铺场景图片候选，请开始。|请创建全新的陈列展示图候选并立即生成。
generate|请直接制作新的横版产品视频候选，不只写稿。|执行新视频生成，不停在文稿。|现在真正出一个新横版短片候选。|立即生成新的横向产品展示视频候选。
conflict|把同一张图完全删掉，同时要求完整保留它；两条同时做。|同一图同时全黑和全白，不拆分。|同一对象背景必须纯红又必须纯绿，不能分版本。|同一张图片背景既全白又全蓝，两者同时成立。
conflict|同一片区域必须纯白也必须纯黑，不能拆成版本。|同一局部必须完全透明也完全不透明。|同一块选区一律删除又一律保留，必须一起做。|同一区域同时保持原色和完全去色，禁止拆分版本。
conflict|将整图完全不改同时彻底重画，一起实施这两条。|整张图像保留全部像素且全部替换。|当前图所有内容全部删除同时原封不动保留。|这张图必须保持全部像素不变又将全部像素重绘。
conflict|只允许方形，又只允许长宽比二比一，要求同一结果同时满足。|同一画面既仅竖版又仅横版。|输出同一张图仅横向和仅竖向，两项同时有效。|同一张输出必须且只能是方形，也必须且只能是宽幅。
unclear|处理一下吧，怎样处理以及对象我都没指定。|先弄一个，我还没确定内容。|就做点调整吧，还没想好要调整什么。|动一动那个吧，我没说明具体改法。
unclear|你开始弄吧，不过我没有明确任务。|随便帮我搞一个，细节没定。|先开始吧，我尚未描述要完成哪件事。|请处理一下，但我没说是讨论、写稿还是修改。
unclear|把那个搞好，具体“搞好”指什么我也没说。|就按某个意思弄吧，我没说具体目标。|那个先弄一下，做什么还没讲清。|弄到合适的样子，但没指定对象或操作。
unclear|先照办，我尚未提供任何需要照办的要求。|先实施一下，我还没讲要求。|按我想的处理，可我尚未说我的想法。|可以开始做了，不过我的任务还未说明。
facts|宣传文字称产品拿到专业认证，但我没有给认证材料。|介绍稿写续航一个月，没有测量。|请写产品通过安全认证，尚无证书或测试依据。|口播声称产品获得认证，但没有提供任何认证证据。
facts|文稿写能治疗眼病，当前完全没有研究证明。|写产品功效已获临床验证，没有研究。|介绍称能治愈近视，没有给任何医学研究。|介绍稿写保证改善视力，没有证据支持。
propose|为这张图写待审的改动提案，等我审查再落实。|列出供审核的修改提议。|整理针对当前对象的待审变更提议，供我批准。|对当前图片给出待审核的变更提案，等待批准。
cancel|终止当前工作，到这里为止。|这项任务现在中止。|停止本次任务，后面无需再做。|本次任务终止，请结束处理。
'''
NAMES={'train':['春季主图','金属水杯','木架陈列','陶罐侧面'], 'dev':['灰色箱包','红色围巾','银色手表','绿色盆栽'],
       'calibration':['落地灯正面','蓝色靠垫','花瓶背面','餐盘俯拍'], 'test':['茶壶细节','书架正面','壁画近照','坐垫侧面']}

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')

def fresh_rows():
    rows=[]
    for split,col in [('train',1),('dev',2),('calibration',3),('test',4)]:
        for i,line in enumerate(CATALOG.strip().splitlines()):
            if split=='dev' and i%2:continue
            parts=line.split('|');kind=parts[0]
            for count in range(5):
                for bound in ([False] if count==0 else [False,True]):
                    cs=[dict(id=f'img{j+1}',label=NAMES[split][j]) for j in range(count)]
                    selected=cs[-1]['id'] if bound else None
                    requested_index=i%4 if kind=='named' else 0
                    text=parts[col].format(name=NAMES[split][requested_index])
                    selection='宿主已圈选区域' if kind=='region' and bound and i%2==0 else None
                    ctx=dict(selected=selected,selection=selection,candidates=cs)
                    request=chat_request(text,ctx,{})
                    g=dict(intent='discuss',target='none',reference_role='unclear',scope='unclear',conflict='none',answer_relation='unclear',fact_review='clear')
                    target=selected or ('img1' if count==1 else 'ambiguous')
                    if kind in ('action','named','region','propose','conflict'):
                        g.update(intent='execute_change',target=target,reference_role='primary',scope='whole_object')
                    if kind=='named':g['target']=f'img{requested_index+1}' if requested_index<count else 'ambiguous'
                    if kind=='region':g['scope']='selected_region'
                    if kind=='propose':g['intent']='propose_change'
                    if kind=='conflict':g.update(intent='unclear',conflict='present')
                    if kind=='unclear':g['intent']='unclear'
                    if kind in ('draft','facts'):g['intent']='draft'
                    if kind=='facts':g['fact_review']='review'
                    if kind=='generate':g.update(intent='generate_media',reference_role='primary')
                    if kind=='cancel':g.update(intent='cancel',answer_relation='cancel')
                    if kind=='quote':g['reference_role']='reference'
                    if kind=='discuss':g['reference_role']='feedback'
                    qs=[]
                    if kind=='conflict':qs=['Q_CONFLICT']
                    elif kind=='unclear':qs=['Q_INTENT']
                    elif kind in ('action','named','region'):
                        if g['target']=='ambiguous':qs.append('Q_TARGET')
                        if kind=='region' and not selection:qs.append('Q_SCOPE')
                    rows.append(dict(id=f'r5-{split}-{i}-{count}-{int(bound)}',family=f'r5-{split}-{i}',split=split,profile='primary',
                        kind=kind,request=request,expected=g,expected_questions=qs,context=ctx,source='synthetic-author',state_variant=dict(candidate_count=count,bound=bound)))
    return rows

def build(out):
    if out.exists():raise ValueError('new_directory_required')
    old=ROOT/'.codex/verification/laya-formal-round4-2026-10-11/data'
    fresh=fresh_rows();seen={};texts={};previous=json.loads((old/'review.json').read_text(encoding='utf-8'))
    old_texts={json.loads(r['request'][0])['user_request'] for r in previous}
    for r in fresh:
        ident=json.dumps(r['request'],sort_keys=True,ensure_ascii=False);text=json.loads(r['request'][0])['user_request']
        if text in old_texts:raise ValueError('old_phrase_reused_as_fresh')
        if text in texts and texts[text]!=r['split']:raise ValueError('cross_split_text')
        texts[text]=r['split']
        if ident in seen and (seen[ident]['split']!=r['split'] or seen[ident]['expected']!=r['expected']):raise ValueError('input_conflict_or_leak')
        seen[ident]=r
    replay=[dict(r,source='round4-train-replay') for r in previous if r['split']=='train']
    combined=replay+fresh;out.mkdir(parents=True);outputs={}
    for split in ('train','dev','calibration','test'):
        group=[r for r in combined if r['split']==split]
        p=out/(split+'.jsonl');p.write_text(''.join(json.dumps(dict(state=r['request'][0],questions=r['request'][1],expected=r['expected']),ensure_ascii=False)+'\n' for r in group),encoding='utf-8')
        outputs[split]=dict(rows=len(group),families=len({r['family'] for r in group}),fresh_families=len({r['family'] for r in group if r['source']=='synthetic-author'}),sha256=sha(p))
    write(out/'review.json',combined);write(out/'fresh.json',fresh)
    write(out/'manifest.json',dict(version='formal-seven-round5-state-v1',outputs=outputs,source_sha256=sha(Path(__file__)),
        previous_train_sha256=sha(old/'train.jsonl'),candidate_counts=[0,1,2,3,4],annotation='40 authored families per split; 9 correlated object states per family; dev20; train includes800 prior train-only replay; no real-user data; primary lacks pending state',frozen_before_training=True))
    print(json.dumps(outputs))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);build(p.parse_args().out)
