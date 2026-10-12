"""Freeze new authored expressions, trusted confirmation profiles and train-only replay."""
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import random
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from miniclaw_web.clarification_policy import chat_request
from miniclaw_web.literal_image_target import bind_named_attachment
from miniclaw_web.formal_confirmations import confirmation_profile

# Four surface expressions for each template, not four independent semantic families.
CATALOG='''named|请把「{name}」旋转90度。|请把「{name}」旋转180度。|请把「{name}」旋转270度。|请把「{name}」水平翻转。
named|把名为「{name}」的图片水平翻转。|把名为「{name}」的图片垂直翻转。|把名为「{name}」的图片旋转90度。|把名为「{name}」的图片旋转180度。
named|请将图片「{name}」垂直翻转，其余保持原样。|请将图片「{name}」水平翻转，其余保持原样。|请将图片「{name}」旋转180度，其余保持原样。|请将图片「{name}」旋转270度，其余保持原样。
named|不要改当前选中项，只把「{name}」旋转180度。|不要改当前选中项，只把「{name}」旋转90度。|不要改当前选中项，只把「{name}」垂直翻转。|不要改当前选中项，只把「{name}」水平翻转。
named|把「{name}」旋转270度。|把「{name}」旋转90度。|把「{name}」水平翻转。|把「{name}」垂直翻转。
named|请把「{name}」这张图水平翻转。|请把「{name}」这张图旋转180度。|请把「{name}」这张图垂直翻转。|请把「{name}」这张图旋转90度。
named|将名称为「{name}」图片旋转270度。|将名称为「{name}」图片水平翻转。|将名称为「{name}」图片旋转180度。|将名称为「{name}」图片垂直翻转。
named|帮我把「{name}」旋转180度其余保持原样。|帮我把「{name}」垂直翻转其余保持原样。|帮我把「{name}」旋转90度其余保持原样。|帮我把「{name}」水平翻转其余保持原样。
region|请把这张图圈选的部分调亮，圈外不动。|这张图圈出的那块单独调暗，外围保留。|仅提升这张图已圈区域的对比度。|只把这张图圈定部分变为灰色，外围原样。
region|所选图片的局部纹理修整一下，其他位置保持。|只在当前照片局部做颜色修复。|当前图片局部单独增加饱和度。|仅调整当前图像局部的明暗，不改全图。
region|把我标记的这一小块噪点清掉。|我标出的这块单独锐化，别动其他。|标记块里的阴影单独提亮。|我框定的小区域单独降低对比度。
region|当前照片只在圈内变黑白，圈外保持颜色。|只有当前图选区转换成灰阶。|将这张图所选区域去色，其他位置不去色。|这张图片圈内保留灰度，圈外仍是彩色。
region|这个图像局部的亮点去掉，其他像素别动。|修整这张图局部的小杂点。|局部这一块的颜色变淡，别处理整图。|当前照片局部边缘做修复，周围不动。
region|仅清理该图圈出的划痕位置，外围别改。|选区里的纹理变柔和，圈外不调整。|仅修圈选块的边界纹理，外围原样。|把圈内区域的色偏修掉，圈外保留。
region|在选中照片标记处降噪，别涉及整张。|仅改善所选照片圈定小块的阴影。|只在当前图片标记位置增亮。|当前图标注处的杂色降低，其他地方保持。
region|这張图片框选的部分降饱和度。|让这张照片圈选块的颜色稍深，圈外不变。|仅修改这张图明确圈出的局部色彩。|所选图像圈定的小块增强细节，其余不处理。
conflict|同一输出所有像素既必须黑色又必须白色，不能拆开。|同一个背景既纯黄又纯紫，两者必须同时存在每个像素上。|要求同一张图全部是红色也全部是蓝色，两项同时执行。|同一张图每个像素必须纯白且纯黑，同时满足。
conflict|同一成品要求全部保留原图且全部删空，一起完成。|同一结果既不允许动任何像素又必须替换全部像素。|完整清空同一张图片，又原封不动保留全部内容，必须一起成立。|这张图完整删除所有内容且完整保留所有内容，不能分版本。
conflict|同一图像同一时刻既完全透明也完全不透明，不做两份。|同一位置透明度只能为0且只能为1，两项同时生效。|同一个图层必须完全透明和完全不透明，两个都要同时满足。|同一片区域透明度必须为零也必须为百分之百，同时成立。
conflict|同一张输出宽高必须相同，又必须宽是高的三倍，同时落实。|同一成品只准正方形也只准长宽三比一，不能拆成两个。|同一画面宽高相等而且宽必须为高的二倍，必须同时满足。|同一张图必须只有竖版和只有横版，两个约束同时有效。
discuss|请解释别人的命令“把图片旋转90度”，不要照做。|我只是理解“水平翻转所有图”这句转述。|读一下同事的“删除当前图”，我只想知道含义。|材料说“直接把图片翻转”，请解读这段引用。
discuss|镜像照片有什么视觉变化？仅谈原理。|只讲局部锐化为什么会影响纹理，不操作。|只说照片旋转的构图影响，现阶段讨论。|分析图片局部提亮的作用，暂时不进行处理。
discuss|引用内容是“请把「{name}」旋转90度”，解释这段话。|文档提到“把名为「{name}」的图片水平翻转”，这里只解释。|客户写“请把「{name}」水平翻转”，我问这句是什么意思。|记录里有“请把「{name}」旋转180度”，只分析这句原话。
discuss|我希望知道修图建议的利弊，暂时没有执行要求。|只评估局部调整方案的优缺点，不操作文件。|讨论候选图比较应关注什么，给分析就好。|我只想了解选区处理的取舍，请讲原则。
draft|写一页商品摄影的操作文字稿，输出草稿。|给我起草镜头流程文字说明。|撰写商品拍摄流程的文字草案供审查。|整理商品照片拍摄注意事项成文本稿。
draft|只生成提示词文本，先别制作图片。|仅把构图描述优化成可复制文本，暂不出图。|把画面描述写成提示词文字，不制作媒体。|我只需要可复制的描述词，请不要生成图像。
draft|替产品镜头写四句旁白文本，交文字。|把视频介绍的旁白草拟出来，不做成片。|起草短片旁白与字幕文本让我看。|请写镜头介绍的旁白文字稿，不生成视频。
draft|只列修图步骤的文字建议，暂时别执行。|把修改思路写成方案，暂不动图。|整理候选修改建议为文字，不实际操作。|给当前图写改动说明稿，先不要实施。
unclear|那个弄一下，具体弄什么还没讲。|帮我处理一下，目标和做法都未说明。|就开始搞它吧，不过要搞什么还没定。|先弄好那个，但我没有描述任务内容。
unclear|我还没确定要求，你先做点什么吧。|先着手，具体要完成哪件事我没提供。|先按要求做，但我尚未告诉你任何要求。|开始吧，我还没说明做哪一种工作。
unclear|照我的想法处理，但想法还没有说。|先按一个办法实施，我没提供那个办法。|把它弄成合适的样子，合适是什么我没讲。|那个按某种方式弄好，方式还未确定。
unclear|你动一下吧，我没说明是改图还是写文字。|做一下这件事，不过是哪件事我没描述。|我想让你干点事，没确定讨论还是执行。|先处理一下，讨论、写稿还是修图我都没选。
action|请把这张图旋转90度。|请把这张图旋转180度。|请把这张图旋转270度。|把选中的这张图水平翻转。
action|请把这张图水平翻转。|请把这张图垂直翻转。|把选中的这张图旋转90度。|把选中的这张图旋转180度。
action|现在将所选照片做左右镜像，原件保留。|执行当前照片的垂直镜像，另存。|把当前图片翻转上下方向并另存一份。|实际把所选照片左右反转，保留原始文件。
action|这张图现在转180度，存成新版本。|请对当前对象执行90度旋转，另存。|选定图片转到倒立方向，保留源文件。|所选照片旋转270度并另存副本。
'''
NAMES={'train':['香炉近照','木盘细节','玻璃罐','藤椅靠背'], 'dev':['茶碗侧面','书袋正面','纸扇纹理','木凳表面'],
    'calibration':['铁壶把手','皮包背部','布帘折痕','石碗正面'], 'test':['陶杯俯视','竹篮侧面','铜灯底座','瓷瓶近照']}
STATES=[(0,None),(1,None),(1,0),(2,None),(2,0),(2,1),(3,None),(3,2),(4,None),(4,3)]

def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def fresh_rows():
    records=[];seen={}
    for split,column in [('train',1),('dev',2),('calibration',3),('test',4)]:
        for i,line in enumerate(CATALOG.strip().splitlines()):
            if split=='dev' and i%2:continue
            parts=line.split('|');kind=parts[0]
            for count,index in STATES:
                cs=[dict(id=f'img{j+1}',label=NAMES[split][j]) for j in range(count)]
                selected=cs[index]['id'] if index is not None else None
                text=parts[column].format(name=NAMES[split][i%4])
                confirmed={}
                if kind in ('named','region','action'):
                    if i%4==1:confirmed={'Q_EXECUTION':'确认执行'}
                    elif i%4==2:confirmed={'Q_EXECUTION':'只整理方案'}
                    elif i%4==3 and count:
                        # Persisted real target answer overrides the old selection.
                        chosen=cs[index if index is not None else count-1];selected=chosen['id']
                        confirmed=dict(Q_TARGET=chosen['id'] if count%2 else chosen['label'],target_id=chosen['id'])
                elif kind=='draft':confirmed={'Q_EXECUTION':'只整理方案'}
                context=dict(attachments=[c['id'] for c in cs],semantic=dict(selected=selected,candidates=cs,selection=bool(index is not None and i%2==0 and kind=='region')))
                task=dict(text=text,confirmed=confirmed,context=context)
                bound=bind_named_attachment(task)
                if bound is not None:context=bound
                ctx=context['semantic'];profile=confirmation_profile(dict(confirmed=confirmed,candidates=cs,selected=ctx['selected']))
                g=dict(intent='discuss',target='none',reference_role='unclear',scope='unclear',conflict='none',answer_relation='unclear',fact_review='clear')
                if kind in ('named','action','region','conflict'):
                    g.update(intent='execute_change',target=ctx['selected'] or ('img1' if count==1 and kind!='named' else 'ambiguous'),reference_role='primary',scope='whole_object')
                if kind=='region':g['scope']='selected_region'
                if kind=='conflict':g.update(intent='unclear',conflict='present')
                if kind=='unclear':g['intent']='unclear'
                if kind=='discuss':g['reference_role']='reference' if i in (20,22) else 'feedback'
                if kind=='draft' or profile=='draft':g.update(intent='draft',target='none',reference_role='unclear',scope='unclear')
                qs=[]
                if kind=='conflict':qs=['Q_CONFLICT']
                elif kind=='unclear':qs=['Q_INTENT']
                elif g['intent']=='execute_change':
                    if g['target']=='ambiguous':qs.append('Q_TARGET')
                    if g['scope']=='selected_region' and not ctx['selection']:qs.append('Q_SCOPE')
                req=chat_request(text,ctx,confirmed);ident=json.dumps(req,sort_keys=True,ensure_ascii=False)
                if ident in seen:
                    previous=seen[ident]
                    if previous['split']!=split or previous['expected']!=g or previous['expected_questions']!=qs:raise ValueError('input_label_conflict')
                    continue  # Binding makes some old-selection variants identical.
                row=dict(id=f'r7-{split}-{i}-{count}-{index}',family=f'r7-{split}-{i}',split=split,kind=kind,profile='primary',confirmation_profile=profile,
                    request=req,expected=g,expected_questions=qs,context=ctx,host_context=context,source='synthetic-author',state_variant=dict(candidate_count=count,bound=bool(ctx['selected'])))
                records.append(row);seen[ident]=row
    return records


def build(out):
    if out.exists():raise ValueError('new_directory_required')
    old=ROOT/'.codex/verification/laya-formal-round5-2026-10-11/data/review.json'
    previous=json.loads(old.read_text(encoding='utf-8'));groups=defaultdict(list)
    for r in previous:
        if r['split']=='train':groups[r['family']].append(r)
    rng=random.Random(20261011)
    for group in groups.values():rng.shuffle(group)
    replay=[]
    while len(replay)<400:
        for family in sorted(groups):
            if groups[family]:replay.append(dict(groups[family].pop(),source='round05-train-replay'))
            if len(replay)==400:break
    fresh=fresh_rows();texts={};oldtexts=set()
    for p in (ROOT/'.codex/verification').glob('laya-formal-round[3456]-2026-10-11/data/*.json'):
        if p.name not in ('review.json','fresh.json'):continue
        for r in json.loads(p.read_text(encoding='utf-8')):oldtexts.add(json.loads(r['request'][0])['user_request'])
    overlaps=[]
    for r in fresh:
        text=json.loads(r['request'][0])['user_request']
        if text in texts and texts[text]!=r['split']:raise ValueError('cross_split_text')
        texts[text]=r['split']
        if text in oldtexts:overlaps.append(r['id'])
    # Ordinary fixture grammar is intentionally replayed; count it as known, not fresh lexical evidence.
    for r in fresh:
        if r['id'] in overlaps:r['source']='known-finite-command-with-new-confirmation-or-state'
    data=replay+fresh;out.mkdir(parents=True);outputs={}
    for split in ('train','dev','calibration','test'):
        selected=[r for r in data if r['split']==split];p=out/(split+'.jsonl')
        p.write_text(''.join(json.dumps(dict(state=r['request'][0],questions=r['request'][1],expected=r['expected']),ensure_ascii=False)+'\n' for r in selected),encoding='utf-8')
        outputs[split]=dict(rows=len(selected),families=len({r['family'] for r in selected}),sha256=sha(p),confirmation_profiles=dict(Counter(r.get('confirmation_profile','legacy') for r in selected)))
    write(out/'fresh.json',fresh);write(out/'review.json',data)
    write(out/'manifest.json',dict(version='formal-seven-round7-v1',outputs=outputs,source_sha256=sha(Path(__file__)),previous_train_replay=400,previous_review_sha256=sha(old),
        known_text_state_records=overlaps,exact_cross_split_text_disjoint=True,deduplicated_after_host_binding=True,
        limitation='Authored shared semantic templates, correlated state variants; no real-user distribution claim; primary has no pending question',frozen_before_training=True))
    print(json.dumps(outputs))

if __name__=='__main__':build(Path(sys.argv[1]))
