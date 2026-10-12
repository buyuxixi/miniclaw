"""Build explicitly annotated synthetic development data; no database writes."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from miniclaw_web.laya_advisory import VERSION, INTENTS, CATEGORIES, CLARIFICATIONS, build_state, questions

# intent | necessary clarification | requested business categories | request | state mode
# Each line is a scenario family, not an independently sampled user.
EXTRA_TRAIN = '''
execute_change|target|image|把其中一张宣传图转九十度，我还没选是哪张。|missing
execute_change|target|image|给那张图提亮一点，现在做，但我没有指定图片。|missing
execute_change|target|image|这几张里帮我裁一张，具体选哪个还没说。|missing
adopt_result|target|image|采用一张图片候选，我还没有选中候选。|missing
adopt_result|target|video|把一段视频设成正式版本，哪段待定。|missing
execute_change|target|scheme|删掉一个镜头并保存，我还没决定删哪一个。|missing
execute_change|region|image|把这张图的这里提亮，位置没有标出来。|region
execute_change|region|image|只改当前图的那一小块颜色，但没有圈选。|region
execute_change|region|image|把当前主图的某个地方裁掉，我还没指出是哪部分。|region
execute_change|region|image|局部加点饱和度，我的圈选还没提交。|region
unclear|conflict|image|当前图本轮必须旋转九十度，而且本轮不允许旋转，两个要求同时有效。|ready
unclear|conflict|video|现在生成视频，同时禁止本轮生成，不接受先后安排。|ready
unclear|conflict|narration|口播本轮必须逐字保留也必须删掉全部文字，两条都有效。|ready
unclear|intent|scheme|那个宣传的事，你就那什么一下。|ready
unclear|intent||随便弄一下，你知道我的意思吧。|empty
unclear|intent|image|这些图处理一下，讨论还是修改我没决定。|missing
draft|none|narration,video_prompt|先重写口播，再给我对应的视频提示词，这轮只交文字。|ready
generate_media|none|narration,video|先写一句口播，然后按这句生成一段五秒视频。|ready
draft|none|scheme,image_prompt|写宣传方案，并附上主图生成提示词，暂时不用出图。|ready
execute_change|none|image,narration|旋转当前选中图九十度，然后把已确认口播写入正式稿。|ready
discuss|none|image,video|比较这张主图和这段视频的传播效果，我们只讨论。|ready
draft|none|image_prompt|写一版背景重绘提示词，不要真的重绘。|ready
draft|none|video_prompt|把旧提示词中的环绕相机改成固定机位，只返回新提示词。|ready
discuss|none|image|客户说“把图直接改掉”，我问的是这句话有没有歧义。|ready
discuss|none|video|如果取消视频生成会影响什么？这句话不是要求取消。|ready
revise_task|none|video|旧时长作废，视频需求改为六秒，这轮仅更新需求。|ready
draft|none|image_prompt|我说的生成只是提示词里的词，请帮我改写这段图像提示词。|ready
discuss|none|image|这里可能需要提亮吗？我们先判断必要性，不处理图片。|region
'''

DEV = '''
discuss|none|image|主图有必要换背景么？先说说理由。|missing
draft|none|image_prompt|给我一段去除背景杂物的修图提示词，我自己复制去用。|ready
draft|none|video_prompt|把相机横移描述写成英文视频提示词，别提交生成。|ready
draft|none|narration|口播太长，重写成十秒能说完的版本给我。|ready
propose_change|none|scheme|给现有宣传分镜准备修改清单，等待我审阅。|ready
execute_change|none|image|当前图上下翻转，立即保存新版本。|ready
generate_media|none|video|用确定的首帧制作一条六秒视频候选。|ready
adopt_result|none|image|当前选中图片就是最终稿，确认采用。|ready
cancel|none|video|正在做的视频任务到这里停止，不要继续。|ready
revise_task|none|scheme|只把任务受众要求改成学生，作品稍后再做。|ready
new_topic|none||宣传项目先留着，我们另聊读书。|ready
unclear|intent||弄那个，差不多就行。|empty
execute_change|target|image|从这些图里改一张尺寸，具体哪张没定。|missing
execute_change|region|image|当前图只动那块，区域我还没指出。|region
unclear|conflict|image|本轮同时要求背景全部删除和背景完整保留，不分先后。|ready
draft|none|narration,video_prompt|写两句口播，再配套写视频提示词，只要文本。|ready
'''

CALIBRATION = '''
discuss|none|image|这张图片是不是还该调整？聊聊，不用动图。|missing
discuss|none|video|让产品旋转的视频看起来会自然吗？现在先讨论。|ready
discuss|none|narration|口播第二句会让人误会吗？给我分析就好。|ready
draft|none|scheme|拟一份新品宣传计划供我阅读。|ready
draft|none|image_prompt|把画面要求整理成图片提示词，别出图。|ready
draft|none|video_prompt|我要新的视频提示词文本，不是视频。|ready
draft|none|narration|口播换个更口语的表达，写出来给我。|ready
propose_change|none|image|为现有图列改动建议待审核，先别实施。|ready
execute_change|none|image|选中这张裁成一比一，新建版本保留原图。|ready
execute_change|none|video_prompt|把确定的新提示词保存到当前视频节点。|ready
generate_media|none|image|启动一次图像生成，生成一张新海报候选。|ready
generate_media|none|video|现在运行视频生成，输出一个竖屏候选。|ready
adopt_result|none|narration|选中的口播候选设为正式稿，确认采用。|ready
cancel|none|image|终止本次主图修改任务。|ready
revise_task|none|video|先把任务比例要求改成横屏，暂不制作。|ready
new_topic|none||产品宣传先放一边，另聊整理书架。|ready
unclear|intent||这事你看着来，做什么我还没想好。|empty
execute_change|target|image|替换一张主图的背景，还没说替换哪张。|missing
adopt_result|target|video|采用一段视频候选，具体采用哪个未确定。|missing
execute_change|region|image|选中图只调局部，哪块区域还没标。|region
unclear|conflict|video|这轮必须输出新视频且不得产生新视频，两条同时生效。|ready
draft|none|scheme,image_prompt|写推广方案，再写配套主图提示词，暂时不用生成。|ready
generate_media|none|narration,video|先拟口播再实际生成对应视频，我要视频候选。|ready
draft|none|narration,video_prompt|口播和视频提示词都优化成新文字版本发给我。|ready
'''

TEST = '''
discuss|none|image|这张图能不能还需要修吗？我们讨论一下|missing
discuss|none|image|你说修图更好，究竟好在哪里？我还没有让你修。|ready
discuss|none|scheme|两种宣传方案哪个更贴合新品？比较优缺点。|ready
discuss|none|video|图片变视频的可行性如何？不用生成，先评估。|ready
discuss|none|image|有人写“旋转90度”，请解释这条指令是否明确。|missing
draft|none|image_prompt|给我准确的修图指令文本，我会自己拿去执行。|ready
draft|none|video_prompt|视频prompt太空泛，请补充运镜细节并返回文字。|ready
draft|none|narration|别照着说明书念，给我重写两句自然的口播稿。|ready
draft|none|scheme|写一个十五秒广告的分镜方案，当前只要方案。|ready
propose_change|none|image|现有海报提出待审改动清单，我审核前图片不能改变。|ready
propose_change|none|narration|现有口播拟一份调整提案，别合并正式稿。|ready
execute_change|none|image|把当前选中图顺时针转一百八十度并保留原件。|ready
execute_change|none|narration|将确认的新口播写入当前项目的正式口播字段。|ready
generate_media|none|image|实际生成一张新品宣传图候选，不自动采用。|ready
generate_media|none|video|按已定分镜启动视频生成，要一个视频候选。|ready
adopt_result|none|image|这次正式采用当前选中的主图，不再出新图。|ready
adopt_result|none|scheme|已选的方案作为最终采用方案。|ready
cancel|none|video|视频制作这项任务我撤销，别继续了。|ready
cancel|none|narration|口播优化的任务不再做，结束任务。|ready
revise_task|none|image|更正需求：产品颜色不能动，先把要求记下来。|ready
revise_task|none|video|不是取消，视频任务继续，时长要求换成八秒。|ready
new_topic|none||另开无关话题讨论周末爬山，产品项目稍后再看。|ready
unclear|intent||就那件事，用另一种弄一下吧。|empty
execute_change|target|image|这里有几张图，找一张改成竖版；我还没有选择。|missing
adopt_result|target|image|从候选图中采用一张，我尚未决定用哪张。|missing
execute_change|region|image|我指当前图的那个小地方，只改那里，没有任何标记。|region
unclear|conflict|image|当前背景必须换成纯白，也必须维持当前黑色，两项同时成立。|ready
draft|none|image_prompt,video_prompt|图像提示词和视频提示词各改一版，只返回文字。|ready
draft|none|scheme,narration|给我广告分镜方案，再写对应的口播稿，这轮不制作。|ready
generate_media|none|narration,video|先写自然口播，然后实际生成配套视频。|ready
discuss|none|image|虽然没选中任何图，我只是问主图要不要提亮，不要求修改。|missing
discuss|none|image|别把我的讨论当修图授权，我们判断是否有必要裁剪。|region
'''


def default_context(mode, product):
    if mode == 'empty':
        return {'product': product}
    return dict(product=product, selected='asset-2' if mode != 'missing' else None,
                candidates=[{'id': 'asset-' + str(i), 'label': product + '候选' + str(i)} for i in range(1, 4)],
                selection='已确认的左上区域' if mode == 'ready' else None,
                confirmed={}, target_bound=mode != 'missing', region_bound=mode == 'ready')


def parse_cases(block, split, products):
    result = []
    for i, line in enumerate(block.strip().splitlines()):
        intent, clarification, cats, text, mode = line.split('|')
        for j, product in enumerate(products):
            context = default_context(mode, product)
            context['needs_existing_target'] = clarification in ('target', 'region')
            result.append(dict(id=f'{split}-{i:03}-{j}', family_id=f'{split}-{i:03}', split=split,
                               source='synthetic_hand_annotated', text=text.replace('{product}', product), context=context,
                               intent=intent, clarification=clarification, categories=cats.split(',') if cats else []))
    return result


def seed_training(seed_path):
    sys.path.insert(0, str(seed_path.parent))
    spec = importlib.util.spec_from_file_location('laya_business_seed', seed_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = []
    domain_map = {'scheme': ['scheme'], 'image_edit': ['image'], 'video': ['video'],
                  'spoken': ['narration'], 'prompt': ['video_prompt']}
    overrides = {('discuss', 5): ['video'], ('draft', 0): ['image_prompt'], ('draft', 2): ['video_prompt'],
                 ('generate_media', 5): ['image']}
    for intent, patterns in module.PATTERNS.items():
        for i, (domain, text, note) in enumerate(patterns):
            cats = [] if intent == 'new_topic' else overrides.get((intent, i), domain_map[domain])
            clarification = 'conflict' if intent == 'unclear' and i in (2, 3, 6) else 'intent' if intent == 'unclear' else 'none'
            for j, product in enumerate(('陶瓷杯', '香水瓶')):
                ctx = default_context('ready', product)
                ctx['needs_existing_target'] = intent in ('execute_change', 'adopt_result')
                if domain == 'prompt':
                    ctx['pending_task'] = '优化产品视频提示词'
                result.append(dict(id=f'seed-{intent}-{i}-{j}', family_id=f'seed-{intent}-{i}', split='train',
                                   source='reused_synthetic_intent_template', text=text.format(product=product), context=ctx,
                                   intent=intent, clarification=clarification, categories=cats, note=note))
    return result


def audit(rows):
    seen = {}
    families = {}
    for row in rows:
        assert row['intent'] in INTENTS and row['clarification'] in CLARIFICATIONS
        assert set(row['categories']) <= set(CATEGORIES) and len(set(row['categories'])) == len(row['categories'])
        state = build_state(row['text'], row['context'])
        key = json.dumps(state, sort_keys=True, ensure_ascii=False)
        if key in seen:
            raise ValueError('Duplicate model input: ' + row['id'] + ', ' + seen[key])
        seen[key] = row['id']
        family = row['family_id']
        if family in families and families[family] != row['split']:
            raise ValueError('Scenario family leakage')
        families[family] = row['split']
    return {split: dict(rows=sum(r['split'] == split for r in rows),
                        families=len({r['family_id'] for r in rows if r['split'] == split}),
                        intents=dict(Counter(r['intent'] for r in rows if r['split'] == split)),
                        clarifications=dict(Counter(r['clarification'] for r in rows if r['split'] == split)),
                        categories=dict(Counter(c for r in rows if r['split'] == split for c in r['categories'])))
            for split in ('train', 'dev', 'calibration', 'test')}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--seed-source', type=Path, default=Path('D:/model/laya-runtime/finetune/build_business_dataset.py'))
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError('Use a new dataset version')
    rows = seed_training(args.seed_source)
    rows += parse_cases(EXTRA_TRAIN, 'extra-train', ('乳白茶壶', '绿色洗面奶'))
    for row in rows:
        row['split'] = 'train'
    # Different wording and scenario families per partition, no product-only random split.
    rows += parse_cases(DEV, 'dev', ('桌面台灯',))
    rows += parse_cases(CALIBRATION, 'calibration', ('口红',))
    rows += parse_cases(TEST, 'test', ('保温杯',))
    summary = audit(rows)
    args.out.mkdir(parents=True)
    write = lambda path, value: path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    write(args.out / 'questions.json', questions())
    write(args.out / 'review.json', rows)
    outputs = {}
    for split in summary:
        records = []
        for row in rows:
            if row['split'] != split:
                continue
            expected = dict(intent=row['intent'], clarification=row['clarification'])
            expected.update({'category_' + c: 'yes' if c in row['categories'] else 'no' for c in CATEGORIES})
            records.append(dict(state=build_state(row['text'], row['context']), questions=questions(), expected=expected))
        path = args.out / (split + '.jsonl')
        path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in records), encoding='utf-8')
        outputs[split] = dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(), **summary[split])
    report = dict(version=VERSION, status='synthetic_development_only', outputs=outputs,
                  source_hash=hashlib.sha256(args.seed_source.read_bytes()).hexdigest(),
                  annotation='Author labels; not user approved or an external blind test. No production-user records.',
                  known_regression='First test request is the previously observed user discussion regression; not unseen.',
                  partition='Explicit scenario families; no input or family crosses partitions. Semantic similarity can remain.',
                  test_used_for_training=False)
    write(args.out / 'manifest.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
