"""Experimental conditional clarification shortcut; never grants tool execution."""
import re
from miniclaw_web.clarification_policy import high, question

VAGUE=re.compile(r'^(?:可以[，,]?开始吧|可以开始了|这个处理一下|你看着办吧)[。！!\s]*$')

def vague(text):
    return bool(VAGUE.fullmatch(text.strip()))

def read_only(text):
    return bool(re.search(r'讨论|分析|只写|只讨论|先讨论|只给|不动图片|不要修改|不修改图片|提示词|口播',text))

def explicit_local_params(text):
    """Finite affirmative command grammar used only by local fixture verification."""
    prefix=r'^(?:请|帮我|麻烦)?把(?:这张图|选中的这张图|第[一二]张图)'
    suffix=r'[。，,]?(?:第[一二]张别动[。]?)?$'
    rotate=re.fullmatch(prefix+r'旋转(90|180|270)度'+suffix,text.strip())
    if rotate:return 'rotate',{'angle':int(rotate[1])}
    flip=re.fullmatch(prefix+r'(水平|垂直)翻转'+suffix,text.strip())
    if flip:return 'flip',{'direction':'horizontal' if flip[1]=='水平' else 'vertical'}
    return None

def route_question(task,decision=None,*,rules=False):
    """Only a clarification may bypass the main model. No score binds a target.

    Threshold inherited from existing policy, deliberately not described as calibrated.
    The rules arm measures the independently useful, finite short-utterance grammar.
    """
    ctx=task['context'];latest=ctx.get('latest_user_reply') or task['text']
    if task['confirmed'].get('Q_INTENT') or task['confirmed'].get('Q_TARGET'):
        return None
    if rules:
        return question('Q_INTENT','这次希望讨论、写文字，还是执行具体操作？') if vague(latest) else None
    if not decision or decision.get('status') not in ('available','suggested','needs_review'):
        return None
    intent=high(decision,'intent')
    if intent=='unclear' and vague(latest):
        return question('Q_INTENT','这次希望讨论、写文字，还是执行具体操作？')
    semantic=ctx.get('semantic',{})
    if (intent in ('execute_change','adopt_result') and not read_only(latest)
            and not semantic.get('selected') and len(semantic.get('candidates',[]))>1
            and high(decision,'target')=='ambiguous'):
        return question('Q_TARGET','要操作哪张图片？请明确选择，其余图片保持不变。',
                        [c['label'] for c in semantic['candidates'][:3]])
    return None
