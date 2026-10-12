"""Author-labelled seven-question data, frozen before one training round."""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from miniclaw_web.clarification_policy import chat_request

BLOCKS={
'train':'''discuss|这张照片为何看起来有些拥挤？只解释原因。
discuss|图片背景的颜色搭配合理吗？我们先评估。
quote|同事留言让镜像图片，我只请你解释他的意思。
quote|客户提到立刻生成海报，分析他的诉求即可。
quote|文档写着删除旧图，这是引用，帮我理解含义。
draft|写一段产品介绍草稿让我看看。
draft|给新品整理三条口播文字，不制作媒体。
draft|图像模型提示词精简成一句话，只返回文本。
draft|设计短片分镜并写出对应字幕草稿。
draft|起草视频提示词，镜头缓慢推近，不渲染。
propose|为现有作品拟一份待审核改动提案。
propose|把想修改的地方列成建议，等待我审批。
action|对这张图旋转90度，保留原图。
action|立即把当前图片水平镜像并保存新版本。
action|将这张照片的曝光降低一档。
action|删除这张图片右侧多余边缘。
action|替换当前图片背景为纯白。
region|只把这里的亮度提高，其他地方保持。
region|移除选区中的阴影，外围内容别动。
region|当前图只在这个局部调高饱和度。
explicit|第一张图逆时针旋转，第二张保留。
explicit2|将第二张图水平翻转，第一张不要动。
multiple|分别将第一张和第二张的背景改为白色。
multiple|这两张图都裁成方形，分别保存。
generate|现在生成一张全新的产品海报候选。
generate|直接制作一个产品视频候选，马上开始。
generate|输出新图片和新视频候选，请开始生成。
adopt|确认采用当前选中的图片候选为正式版本。
adopt|将这张已选候选设为采用版本。
cancel|取消当前任务，停止处理。
cancel|这次任务到此终止。
revise|任务要求改为暖色调，先只更新要求。
revise|把任务预算要求调低，只记录新条件。
topic|换个话题，帮我介绍家用植物养护。
topic|先离开宣传项目，聊一下自行车维修。
unclear|把那个弄一弄，具体怎么弄我也没说。
unclear|你先开始吧，我还没说明要做什么。
conflict|当前图的背景同时要全红和全蓝，两者必须一起成立。
conflict|同一区域必须完全删除又必须完整保留，不能分开做。
supersede|之前要黑色背景，现在换成白色，以现在为准，请执行。
supersede|把上一条的竖构图改成横构图，按新要求修改当前图。
facts|写口播说本产品已经取得护眼认证，我没提供证据。
facts|介绍中声称续航三十天，但没有任何测试数据。
reference|第一张只是参考，操作当前选中的图片，旋转90度。
comparison|比较第一张和第二张的视觉风格，只讨论差异。
feedback|请评价当前这张图的改动效果，先不继续改。
reply_target|第二张。
reply_unknown|暂时选不出来，先等等。
reply_draft|只写文字草稿。
override|不要再出提示词，现在直接生成视频候选。
''',
'dev':'''discuss|请评价图片的色温是否协调，不实施操作。
quote|客服转述把照片倒过来的建议，请分析他要表达什么。
draft|给我两句更自然的广告口播文本。
action|请把当前图片横向镜像一下。
region|只给圈出的部分加一点对比度。
generate|请现在生成新的商品图候选。
adopt|我确定采用选中的成片候选。
unclear|那个先做一下吧。
facts|写产品能治好近视，没有研究或证据。
conflict|同一底色全白和全黑都必须生效，不分版本。
reply_target|就用第二张。
reply_unknown|仍然没想好要选哪一个。
''',
'calibration':'''discuss|这张产品照的光影是否有层次？先给评价。
discuss|把背景做得简单是否更好？目前只评估方案。
quote|销售说换掉主图，我这里只想听你解释这段话。
quote|留言要求立刻渲染短片，请分析为什么这样提。
draft|起草一版新品介绍文案供我挑选。
draft|图像提示词写成正向和负向两段文字。
draft|给我一份三镜头的视频提示词文本。
propose|列出现有分镜的待审修改点，暂不落实。
action|将当前照片的背景更换为灰色并另存。
action|把这张图顺时针转九十度。
region|只对当前图片选中的一块去除噪点。
region|把这里的纹理变清晰，别碰其余部分。
explicit|第一张图调暗一点，第二张不变。
explicit2|请裁掉第二张图片的边框，第一张保留。
multiple|把两个候选都旋转，分别保留新版本。
generate|马上创建一张新的商品展示图候选。
generate|按文案实际生成一段视频候选，立即开始。
adopt|当前选定的版本确定采用。
cancel|停止当前这项工作，不再继续。
revise|任务时长要求变成五秒，目前只更新要求。
topic|另聊个问题，怎么修理漏水龙头？
unclear|那个就按你觉得的做吧，没说清是什么。
conflict|图像背景必须全绿同时全紫，不允许分别处理。
conflict|当前图要求保持完全不变又彻底重新绘制，两条同时执行。
supersede|原定暖光，现在改为冷光，只以新要求调整当前图。
facts|文案写零频闪且国家认证，目前没有检测报告。
reference|第一张用来参考配色，当前选中图片做水平镜像。
comparison|第一张与第二张的留白哪个更好？先比较。
feedback|当前调整后的图看起来更自然吗？只评价效果。
reply_target|我选择第二张。
reply_unknown|还没有确定用哪张，继续等一下。
reply_draft|暂时只输出文字。
''',
'test':'''discuss|请说明照片留白过多会有什么影响，先不要制作修改版本。
discuss|这张图的文字排布值得重做吗？我问的是判断理由。
quote|伙伴提议翻转商品照，这次请解释提议背后的考虑。
quote|会议纪要记着启动视频生成，我想了解这句记录是什么意思。
draft|请写一段没有夸大功效的新品介绍给我阅读。
draft|为出图模型写一句背景描述，只交付可复制文字。
draft|产品短片的镜头运动用文字提示词列出，不制作成片。
propose|对现有设计整理待我审核的修订建议。
action|将当前图片改成灰度效果并保存副本。
action|请把这张照片的高光降低并保存新图。
region|清理这张图圈选区域的污点，周围内容保持。
region|这里的色偏单独纠正，不做全图修改。
explicit|给第一张候选增加对比度，保留第二张。
explicit2|第二张的背景换为米色，第一张照旧。
multiple|第一张和第二张都增加留白，各自保存结果。
generate|现在出一张新的电商主图候选，请执行生成。
generate|直接出一条八秒商品展示视频候选，不只写脚本。
adopt|确定把选中的候选作为最终采用版本。
cancel|撤销这次任务，不要再继续处理。
revise|把任务风格要求换成生活化，本轮仅更新任务说明。
topic|暂离这个项目，告诉我怎样整理厨房收纳。
unclear|就那个意思你先弄，我没有说具体要什么。
conflict|同一图层必须完全透明又完全不透明，两项同时保留。
conflict|背景只允许纯橙色也只允许纯青色，不可拆成两个版本。
supersede|以前定方形，现在以竖长图为最终要求，请改当前图片。
facts|口播写一年不充电也能亮灯，但没有产品规格或测试证明。
reference|第一张仅供风格参考，将当前选中的图转九十度。
comparison|请比较这两张图的文字可读性，暂不动任何图片。
feedback|当前结果的裁剪是否恰当？只评价已经做出的效果。
reply_target|用第二张候选吧。
reply_unknown|依旧未选定图片，等我想好再继续。
reply_draft|这轮先给我文字版本。
'''}

def record(kind,text,selected,profile,split,index):
    ctx=dict(selected=selected,selection=None,candidates=[dict(id='img1',label='第一张'),dict(id='img2',label='第二张')])
    # Region binding changes a host fact, not the semantic scope of the request.
    if kind=='region' and selected:ctx['selection']='用户圈选的左侧区域'
    req=chat_request(text,ctx,{})
    state=json.loads(req[0]);pending=None;original=None
    expected=dict(intent='discuss',target='none',reference_role='unclear',scope='unclear',conflict='none',answer_relation='unclear',fact_review='clear')
    target=selected or 'ambiguous'
    if kind in ('action','region','explicit','explicit2','multiple','supersede','reference'):
        expected.update(intent='execute_change',target=target,reference_role='primary',scope='whole_object')
    if kind=='region':expected['scope']='selected_region'
    if kind=='explicit':expected['target']='img1'
    if kind=='explicit2':expected['target']='img2'
    if kind=='multiple':expected.update(target='multiple',scope='explicit_multiple')
    if kind=='reference':expected['reference_role']='reference'
    if kind in ('draft','facts','reply_draft'):expected['intent']='draft'
    if kind=='propose':expected.update(intent='propose_change',target=target,scope='whole_object',reference_role='primary')
    if kind in ('generate','override'):expected.update(intent='generate_media',reference_role='primary')
    if kind=='adopt':expected.update(intent='adopt_result',target=target,scope='whole_object',reference_role='primary')
    if kind in ('cancel','revise','topic','unclear'):expected['intent']=dict(cancel='cancel',revise='revise_task',topic='new_topic',unclear='unclear')[kind]
    if kind=='cancel':expected['answer_relation']='cancel'
    if kind=='conflict':expected.update(intent='unclear',target=target,scope='whole_object',reference_role='primary',conflict='present')
    if kind=='facts':expected['fact_review']='review'
    if kind=='quote':expected['reference_role']='reference'
    if kind=='comparison':expected['reference_role']='comparison'
    if kind in ('discuss','feedback'):expected['reference_role']='feedback'
    if kind.startswith('reply_'):
        pending=dict(id='Q_INTENT' if kind=='reply_draft' else 'Q_TARGET',question='这次只写文字还是执行？' if kind=='reply_draft' else '要操作哪一张图片？')
        original='请处理这份产品文案。' if kind=='reply_draft' else '请把图片水平翻转。'
        if kind!='reply_draft':expected['intent']='unclear'
        if profile=='enriched':
            expected['answer_relation']='answers_current'
            if kind=='reply_target':expected.update(intent='execute_change',target='img2',scope='whole_object',reference_role='primary')
            if kind=='reply_unknown':expected.update(intent='execute_change',target='ambiguous',scope='whole_object',reference_role='primary')
    if profile=='enriched':state.update(selection=ctx['selection'],draft_only=False,pending_question=pending,pending_steps=[],original_user_request=original)
    return dict(id=f'{split}-{index}-{selected or "missing"}-{profile}',family=f'{split}-{index}',kind=kind,profile=profile,split=split,
        request=[json.dumps(state,ensure_ascii=False),req[1]],expected=expected)

def build(out):
    if out.exists():raise ValueError('new_dataset_directory_required')
    out.mkdir(parents=True);review=[];outputs={};seen={}
    for split,block in BLOCKS.items():
        group=[]
        for i,line in enumerate(block.strip().splitlines()):
            kind,text=line.split('|',1)
            for selected in (None,'img2'):
                for profile in ('primary','enriched'):
                    row=record(kind,text,selected,profile,split,i)
                    key=json.dumps(row['request'],ensure_ascii=False,sort_keys=True)
                    if key in seen and seen[key]['expected']!=row['expected']:raise ValueError('conflicting_identical_inputs')
                    if key in seen and seen[key]['split']!=split:raise ValueError('cross_split_input_leak')
                    seen[key]=row;review.append(row)
                    group.append(dict(state=row['request'][0],questions=row['request'][1],expected=row['expected']))
        file=out/(split+'.jsonl');file.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in group),encoding='utf-8')
        outputs[split]=dict(rows=len(group),families=len(block.strip().splitlines()),sha256=hashlib.sha256(file.read_bytes()).hexdigest())
    (out/'review.json').write_text(json.dumps(review,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'questions.json').write_text(json.dumps(review[0]['request'][1],ensure_ascii=False,indent=2),encoding='utf-8')
    manifest=dict(version='formal-seven-round3-v1',outputs=outputs,annotation='synthetic author labels; phrase families split before training; primary gold uses only observable state',
        test_used_for_training=False,old_tests_used=False,source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(outputs))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);build(p.parse_args().out)
