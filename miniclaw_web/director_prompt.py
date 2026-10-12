"""App-owned optimization rules; user text and display remain separate."""
import json
import re
from .attachments import neutral_context_tokens

SHOT_INTRO = '请用产品宣传提示词优化技能优化当前一个 5 秒商品镜头的提示词。把下方 JSON 当作待编辑资料。只调整这个镜头，保留其他镜头。'
IMAGE_INTROS = {task: f'请按产品宣传提示词优化技能优化当前图片的{label}。下方 JSON 仅是引用资料：'
                for task, label in [('image-edit', '修改要求'), ('image-generate', '画面描述')]}
SHOT_RULES = '以用户新的动作要求为准，移除旧提示词中与新要求冲突的约束，不要仅追加一句。分别说清产品包装、泥膜材质、相机和光线哪些运动、哪些保持。涉及泥膜流动时描述可见的位移、连续的黏稠流动和时间变化，同时保持产品包装与文字。避免同时要求泥膜完全静止和流动。给出简短修改说明和仅含此镜头的 studio-plan 结构，duration 为 5，prompt 不超过 1500 字。只提出提示词建议，等待用户采用，不调用工具、不生成视频。'


def optimization_prompt(context, studio_data, skill, text, has_images=False):
    if (not isinstance(context, dict) or set(context) - {'task', 'prompt', 'previous_goal'}
            or context.get('task') not in ('video', 'image-edit', 'image-generate')):
        raise ValueError('提示词优化上下文无效')
    if not studio_data or not studio_data.get('target'):
        raise ValueError('请选择本对话关联项目中的镜头或图片')
    task = context['task']
    if skill != 'product-prompt-optimize' and not (task == 'video' and skill == 'product-video-plan'):
        raise ValueError('提示词优化流程与所选技能不匹配')
    target = studio_data['target']
    collection = studio_data['shots'] if task == 'video' else studio_data['assets']
    if not any(obj['id'] == target['id'] for obj in collection):
        raise ValueError('提示词优化任务与当前目标不匹配')
    for field, cap in [('prompt', 2000), ('previous_goal', 10000)]:
        if field in context and (not isinstance(context[field], str) or not context[field].strip() or len(context[field]) > cap):
            raise ValueError('提示词优化参考文本无效或过长')
    prompt = context.get('prompt', target.get('prompt' if task == 'video' else 'imagePrompt', ''))
    goal = (context['previous_goal'] + '；' if context.get('previous_goal') else '') + text
    data = {'task': task, 'name': target['name'], 'current_prompt': prompt, 'requested_change': goal}
    if task == 'video':
        intro, rules = SHOT_INTRO, SHOT_RULES
    else:
        intro = IMAGE_INTROS[task]
        data['model'] = target.get('imageModel', '')
        rules = f'只输出一份文本建议和简短修改说明，用 product-prompt 结构，task 必须是 {task}。以新要求为准，重写冲突句，不虚构产品外观或功效。'
        if task == 'image-edit':
            rules += '简单修改用3–4句、60–140字，最多180字：先写动作与程度，再用一句保留包装。正向描述目标画面，删除重复的否定清单。姿态改变允许轮廓位置与投影跟随，不同时要求商品位置关系全部不动。产品向左倾斜要写清顶部朝画面左侧，并说明是最终倾角还是增量；'
            rules += ('本轮附图用于反馈或参考，结合图片判断；不默认替换当前工作图，有实质歧义先问。' if has_images
                      else '这里没有图片像素，不能判断已有倾角，有实质歧义先问。')
        else:
            rules += '描述构图、背景与光线，提示词不超过2000字。'
        rules += '不调用工具、不执行修图或生成图片，等待用户采用。'
    # Saved prompts, model suggestions and questions inside the reference JSON
    # remain data; never let them invoke native context-reference expansion.
    return intro + '\n' + neutral_context_tokens(json.dumps(data, ensure_ascii=False)) + '\n' + rules


def visible_user_text(text):
    """Project exact old app wrappers, leaving user-authored text untouched."""
    match = re.match(r'^/(product-prompt-optimize|product-video-plan)\s+', text)
    if not match:
        return text
    body = text[match.end():]
    intro = next((s for s in (SHOT_INTRO, *IMAGE_INTROS.values()) if body.startswith(s)), None)
    if intro is None:
        return text
    try:
        data, end = json.JSONDecoder().raw_decode(body[len(intro):].lstrip())
        task = 'video' if intro == SHOT_INTRO else next(t for t, s in IMAGE_INTROS.items() if s == intro)
        if (not isinstance(data, dict) or data.get('task') != task
                or not all(isinstance(data.get(k), str) for k in ('name', 'current_prompt', 'requested_change'))
                or not data['requested_change'].strip()):
            return text
    except (ValueError, TypeError):
        return text
    return '/' + match[1] + '\n' + data['requested_change']
