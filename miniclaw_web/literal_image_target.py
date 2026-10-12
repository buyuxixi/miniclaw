"""Finite whole human commands bind owned attachments, never classifier guesses."""
from copy import deepcopy
import re

NAME = r'[「“"](?P<name>[^「」“”"\r\n]{1,100})[」”"]'
ACTION = r'(?P<action>旋转(?P<angle>90|180|270)度|(?P<direction>水平|垂直)翻转)'
COMMAND = re.compile(r'^(?:不要改当前选中项，)?(?:请|帮我|麻烦)?(?:把|将|只把)(?:名为|名称为)?(?:图片)?' + NAME + r'(?:的图片|这张图|图片)?' + ACTION + r'[。，]?(?:其余保持原样[。]?)?$')


def named_operation(text):
    match = COMMAND.fullmatch(text.strip())
    if not match:return None
    op = ('rotate', dict(angle=int(match['angle']))) if match['angle'] else ('flip', dict(direction='horizontal' if match['direction']=='水平' else 'vertical'))
    return dict(name=match['name'], operation=op[0], params=op[1])


def bind_named_attachment(task):
    """Return context only for a complete affirmative command naming an attachment."""
    if (task.get('context', {}).get('draft_only') or task.get('confirmed', {}).get('Q_TARGET') or task.get('confirmed', {}).get('target_id')
            or task.get('confirmed', {}).get('Q_EXECUTION')=='只整理方案' or task.get('confirmed', {}).get('Q_INTENT')=='先整理方案'):return None
    command=named_operation(task['text'])
    if not command:return None
    context=deepcopy(task['context']);semantic=context.get('semantic',{})
    owned=set(context.get('attachments',[]))
    candidates=semantic.get('candidates',[])
    matches=[c for c in candidates if c['label']==command['name']]
    selected=matches[0]['id'] if len(matches)==1 and matches[0]['id'] in owned else None
    semantic['selected']=selected;context['semantic']=semantic
    context['literal_target']=dict(method='whole-command-name-v1',status='resolved' if selected else 'unresolved',name=command['name'])
    return context
