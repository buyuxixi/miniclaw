"""Freeze author-written paired surface forms and correlated object states."""
import hashlib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from miniclaw_web.clarification_policy import chat_request

CATALOG = '''action|将所选图片向右旋转四分之一圈，输出副本。|选定照片顺时针转90度，原片留下。
action|给当前这张照片执行垂直镜像。|现在把当前图上下反转并另存。
action|这张图立刻左右翻转，保存另一份。|实际对当前图做水平镜像处理。
action|当前图片逆时针转90度，另存而不覆盖。|选中图像转270度，保留源文件。
named|对名叫「{name}」的照片执行水平翻转。|只旋转图片「{name}」90度，其余不动。
named|处理「{name}」这张，把它上下反转。|对象是「{name}」，请执行垂直镜像。
named|「{name}」转半圈保存，其他对象保留。|请将「{name}」旋转180度另存新图。
named|我要改「{name}」而非当前选中项，做水平镜像。|选中对象先别动，给「{name}」做左右翻转。
region|只将圈选部分调暗，选区之外照旧。|当前图已标出的区域单独提亮，外围不动。
region|把这张图圈选位置的噪点清掉，别动其余。|仅处理所选图片选区的杂点。
region|仅把圈内区域换成灰色，其他区域保持。|只改变我圈出的那一块色调。
region|将当前位置的局部纹理修整一下，不要整图修改。|修复这张图的圈选部分，圈外保持原样。
conflict|同一张输出必须全红又必须全蓝，两条同时满足且不能拆图。|要求同一背景全部绿色且全部黑色，同时满足不分版本。
conflict|所有像素都要保持原样，也要全部改为白色，同时落实。|这张图完整保留全部内容又完全清空，两条一起实施。
conflict|同一位置透明度必须为零又必须为百分之百，同时生效。|同一块区域要求完全透明且完全不透明，不能取其一。
conflict|同一张成品长宽相等，也要求宽度是高度两倍，不分版本。|同一个画面只能竖向也只能横向，两项同时成立。
unclear|就搞一下那个，搞哪件事我还没说明。|先给我弄好吧，但我没有说要做什么。
unclear|开始动手吧，我还没有确定任何操作要求。|你先处理，我尚未交代处理目标和方法。
unclear|照着某个办法做一下，不过办法我没讲。|弄一弄它，具体改法尚未提供。
unclear|我希望你做点事，但没说讨论、写稿还是改图。|完成那个任务吧，但哪个任务我尚未说明。
discuss|请解释资料中“立刻翻转照片”的文字含义。|原文写“现在删除图像”，这次请解读这句话。
discuss|我们只聊旋转照片与镜像的差异，不操作文件。|帮我分析水平翻转会如何影响构图，仅讨论。
discuss|引用里的“立即付费生成”为什么这样说？只分析原话。|请解释同事说的“替换所有图片”，此处只是转述。
discuss|讲讲局部提亮的视觉原理，现阶段仅做解释。|讨论选区与全图调整各有哪些影响，不进行修改。
draft|替商品图写一段介绍文本供我查看。|起草这张商品照片的简短文字介绍。
draft|给镜头安排写一页说明稿，交付文字。|写出视频镜头安排的文字草案让我审核。
draft|只优化绘图描述句，交付提示词，不生成图片。|提供可复制的图像提示词文本，暂不出图。
draft|把修改建议整理成文本草稿，先不执行。|请写修图方案说明，暂时不要实际处理照片。
'''
NAMES = {'calibration': ['石雕近景', '玻璃杯侧照', '纸灯罩', '织物纹理'],
         'test': ['铜铃正面', '编织袋细节', '餐椅背部', '瓷碟侧照']}
STATES = [(0, False), (1, True), (2, False), (3, True), (4, False)]


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def build(out):
    if out.exists(): raise ValueError('new_directory_required')
    previous = json.loads((ROOT/'.codex/verification/laya-formal-round5-2026-10-11/data/fresh.json').read_text(encoding='utf-8'))
    old_texts = {json.loads(r['request'][0])['user_request'] for r in previous}
    data = []; texts = {}; inputs = set()
    for split, col in [('calibration', 1), ('test', 2)]:
        for i, line in enumerate(CATALOG.strip().splitlines()):
            kind, *phrases = line.split('|')
            for count, bound in STATES:
                cs = [dict(id=f'img{j+1}', label=NAMES[split][j]) for j in range(count)]
                selected = cs[-1]['id'] if bound else None
                selection = bool(bound and i % 2 == 0) if kind == 'region' else False
                ctx = dict(candidates=cs, selected=selected, selection=selection)
                text = phrases[col-1].format(name=NAMES[split][0])
                gold = dict(intent='discuss', target='none', reference_role='unclear', scope='unclear', conflict='none', answer_relation='unclear', fact_review='clear')
                qs = []
                if kind in ('action', 'named', 'region', 'conflict'):
                    gold.update(intent='execute_change', target=selected or ('img1' if count == 1 else 'ambiguous'), reference_role='primary', scope='whole_object')
                if kind == 'named': gold['target'] = 'img1' if count else 'ambiguous'
                if kind == 'region': gold['scope'] = 'selected_region'
                if kind == 'conflict': gold.update(intent='unclear', conflict='present'); qs = ['Q_CONFLICT']
                elif kind == 'unclear': gold['intent'] = 'unclear'; qs = ['Q_INTENT']
                elif kind in ('action', 'named', 'region'):
                    if gold['target'] == 'ambiguous': qs.append('Q_TARGET')
                    if kind == 'region' and not selection: qs.append('Q_SCOPE')
                elif kind == 'draft': gold['intent'] = 'draft'
                elif kind == 'discuss': gold['reference_role'] = 'reference' if i in (20, 22) else 'feedback'
                req = chat_request(text, ctx, {})
                ident = json.dumps(req, ensure_ascii=False, sort_keys=True)
                if text in old_texts or (text in texts and texts[text] != split) or ident in inputs:
                    raise ValueError('exact_text_leak_or_duplicate')
                texts[text] = split; inputs.add(ident)
                data.append(dict(id=f'r6-{split}-{i}-{count}', family=f'r6-{split}-{i}', split=split, kind=kind,
                    request=req, context=ctx, expected=gold, expected_questions=qs, source='synthetic-author',
                    state_variant=dict(candidate_count=count, bound=bound)))
    out.mkdir(parents=True)
    write(out/'fresh.json', data)
    write(out/'manifest.json', dict(rows=len(data), families_per_split=28, correlated_states_per_family=5,
        data_sha256=hashlib.sha256((out/'fresh.json').read_bytes()).hexdigest(),
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), frozen_before_scoring=True,
        limitation='Shared semantic templates across cal/test; exact surface separation, synthetic, not independent real-user distribution'))
    print(json.dumps(dict(rows=len(data), per_split=140)))


if __name__ == '__main__': build(Path(sys.argv[1]))
