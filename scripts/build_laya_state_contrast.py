"""Freeze author-labelled state contrasts before any live evaluation; no training."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.evaluate_chat_harness import state_for
from miniclaw_web.laya_advisory import build_state


def advice_context(case):
    ctx = state_for(case)['context']
    # These are supplied fixture state facts, never reconstructed from gold labels.
    return dict(candidates=ctx['objects'], selected=ctx['selected'], selection=ctx['selection'],
                target_bound=bool(ctx['selected']), region_bound=bool(ctx['selection'] or ctx.get('confirmed', {}).get('Q_SCOPE')),
                draft_only=ctx['draft_only'], confirmed=ctx.get('confirmed', {}),
                pending_question=ctx['pending_question'],
                pending_task={'steps':ctx['pending_steps'], 'original_user_request':ctx.get('original_user_request')})


def dataset():
    cases = []
    def pair(family, text, variants, categories):
        for index, (context, steps, qs, targets) in enumerate(variants):
            row = dict(id=f'{family}-{index}', family=family, text=text, context=context,
                       gold=dict(steps=steps, questions=qs, targets=targets), categories=categories)
            build_state(text, advice_context(row))
            cases.append(row)

    pair('rotate-binding', '请把这张图旋转90度。', [
        ({'selected':None}, [], ['target'], []), ({'selected':'img2'}, ['edit_image'], [], ['img2'])], ['image'])
    pair('flip-binding', '把这张图水平翻转。', [
        ({'selected':None}, [], ['target'], []), ({'selected':'img1'}, ['edit_image'], [], ['img1'])], ['image'])
    pair('discussion-binding', '旋转这张图会更合适吗？先讨论必要性，不执行。', [
        ({'selected':None}, ['analyze_plan'], [], []), ({'selected':'img2'}, ['analyze_plan'], [], [])], ['image'])
    pair('quote-binding', '同事说把这张图水平翻转，我只想了解这句话的含义。', [
        ({'selected':None}, ['analyze_plan'], [], []), ({'selected':'img2'}, ['analyze_plan'], [], [])], ['image'])
    pair('region-binding', '把这里的亮度调高一点，其他位置别动。', [
        ({'selected':'img1','selection':None}, [], ['region'], []),
        ({'selected':'img1','selection':{'x':0,'y':0,'width':20,'height':20}}, ['edit_image'], [], ['img1'])], ['image'])
    pair('answered-region', '把这里的杂物去掉。', [
        ({'selected':'img1','confirmed':{}}, [], ['region'], []),
        ({'selected':'img1','confirmed':{'Q_SCOPE':'左下角'},'selection':None}, ['edit_image'], [], ['img1'])], ['image'])
    pair('draft-region', '先写一份这里的修图方案，暂时不修图。', [
        ({'selection':None}, ['write_plan'], [], []),
        ({'selection':{'description':'左下角'}}, ['write_plan'], [], [])], ['scheme'])
    pair('pending-purpose', '可以，就这样做。', [
        ({'pending_question':'是否只起草一段产品口播？','pending_steps':['optimize_narration'],
          'original_user_request':'写一段产品口播文字。'}, ['optimize_narration'], [], []),
        ({'pending_question':'是否生成一条产品视频候选？','pending_steps':['generate_video'],
          'original_user_request':'现在生成一条产品视频。'}, ['generate_video'], [], [])], None)
    cases[-2]['categories'] = ['narration']; cases[-1]['categories'] = ['video']
    pair('pending-target', '第二张。', [
        ({'selected':None,'pending_question':'旋转哪张图片？','pending_steps':['edit_image'],
          'original_user_request':'把这张图旋转90度。','confirmed':{'Q_TARGET':'第二张'}}, ['edit_image'], [], ['img2']),
        ({'selected':None,'pending_question':None,'pending_steps':[]}, [], ['intent'], [])], None)
    cases[-2]['categories'] = ['image']; cases[-1]['categories'] = []
    pair('unresolved-answer', '我还没决定。', [
        ({'selected':None,'pending_question':'这次旋转哪张图片？','pending_steps':['edit_image'],
          'original_user_request':'把这张图旋转90度。'}, [], ['target'], []),
        ({'selected':None,'pending_question':'你想讨论还是实际修改图片？','pending_steps':[]}, [], ['intent'], [])], ['image'])
    pair('prompt-or-media', '就按这段提示词来。', [
        ({'pending_question':'是否优化视频提示词文字？','pending_steps':['optimize_video_prompt'],
          'original_user_request':'优化桌面台灯慢慢转动的视频提示词，只要文字。'}, ['optimize_video_prompt'], [], []),
        ({'pending_question':'是否按该提示词生成视频候选？','pending_steps':['generate_video'],
          'original_user_request':'使用已确认的提示词生成视频。'}, ['generate_video'], [], [])], None)
    cases[-2]['categories'] = ['video_prompt']; cases[-1]['categories'] = ['video']
    pair('compound-text', '写一段台灯宣传口播，再写对应的视频提示词，只要两段文字。', [
        ({'selected':None}, ['optimize_narration','optimize_video_prompt'], [], []),
        ({'selected':'img2'}, ['optimize_narration','optimize_video_prompt'], [], [])], ['narration','video_prompt'])
    pair('compound-generation', '先优化口播，再按这个口播生成视频候选。', [
        ({'selected':None}, ['optimize_narration','generate_video'], [], []),
        ({'selected':'img1'}, ['optimize_narration','generate_video'], [], [])], ['narration','video'])
    pair('image-prompt', '重写台灯主图的图片生成提示词，给我文字，暂不出图。', [
        ({'selected':None}, ['optimize_image_prompt'], [], []),
        ({'selected':'img2'}, ['optimize_image_prompt'], [], [])], ['image_prompt'])
    pair('explicit-target', '请把第二张图旋转90度，第一张别动。', [
        ({'selected':None}, ['edit_image'], [], ['img2']),
        ({'selected':'img1'}, ['edit_image'], [], ['img2'])], ['image'])
    pair('confirmed-purpose', '这张图的背景太暗，给我调整建议。', [
        ({'selected':None}, ['analyze_plan'], [], []),
        ({'selected':'img1','confirmed':{'Q_EXECUTION':'只整理方案'},'draft_only':True}, ['analyze_plan'], [], [])], ['image'])

    native = []
    for family, text, effect in [
        ('rotate', '请把这张图旋转90度。', 'rotate'),
        ('flip', '把这张图水平翻转。', 'flip'),
        ('discuss', '旋转这张图会更合适吗？先讨论必要性，不执行。', 'text'),
        ('quote', '同事说把这张图水平翻转，我只想了解这句话的含义。', 'text'),
        ('prompt', '写一份台灯的视频提示词并保存，只要文字，不生成视频。', 'artifact'),
        ('compound', '台灯口播和视频提示词各写一段，分别标注口播和视频提示词，合成一份文本保存，不生成媒体。', 'artifact'),
    ]:
        for selected in (None, 1):
            missing = selected is None and effect in ('rotate','flip')
            native.append(dict(id=f'{family}-{"missing" if selected is None else "bound"}', text=text,
                selected=selected, reply='第二张' if missing else None,
                gold=dict(question='Q_TARGET' if missing else None, effect=effect, target=1)))
    for answer, effect in [('第二张','rotate'), ('还没决定选哪张。','waiting')]:
        native.append(dict(id='resume-' + effect, text='请把这张图旋转90度。', selected=None,
                           reply=answer, gold=dict(question='Q_TARGET',effect=effect,target=1)))
    return dict(version='laya-state-contrast-v1',
        provenance='Author-labelled synthetic diagnostic set. No production user logs or external blind labels. Same utterance changes state; both variants stay in the same diagnostic partition. Not used for training or recalibration.',
        planning=cases, native=native,
        known_regressions=['rotation binding and unknown target answer repeat known failure families'],
        limitations=['Planning includes paid media and region editing only as previews. Native executes local fixture rotate/flip and saves text.',
                     'Native text content checked separately; existence alone does not prove content quality.'])


def main():
    target = ROOT/'docs/chat-laya-state-contrast.v1.json'
    data = dataset()
    with target.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(data,stream,ensure_ascii=False,indent=2)
        stream.write('\n')
    print(json.dumps(dict(path=str(target),planning=len(data['planning']),native=len(data['native']),
                         sha256=hashlib.sha256(target.read_bytes()).hexdigest())))


if __name__ == '__main__': main()
