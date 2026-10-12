"""Experimental action grounding used only by the isolated clarification study."""
import re
from miniclaw_web.clarification_policy import ClarificationPolicy, question

MUTATING={'miniclaw_edit_image','evaluation_adopt_candidate','miniclaw_canvas_ai'}
POSITIONS=('左上角','右上角','左下角','右下角','上半部分','下半部分','左侧','右侧')

def region_resolved(task):
    ctx=task['context']
    if ctx.get('semantic',{}).get('selection'):return True
    confirmed=task['confirmed'].get('Q_SCOPE','')
    text=confirmed or (task['text']+' '+ctx.get('latest_user_reply',''))
    if re.search(r'不确定|没决定|也许|或者|或|不是|不要|不知道|随便|不清楚',text):return False
    return sum(p in text for p in POSITIONS)==1

def unresolved_prequestions(questions,task):
    """A slot already grounded by the user is not a new clarification blocker."""
    result=[]
    for q in questions:
        if q['template']=='Q_SCOPE' and region_resolved(task):continue
        if q['template']=='Q_TARGET' and task['context'].get('semantic',{}).get('selected'):continue
        result.append(q)
    return result

def explicit_target(text,candidates):
    """Conservative imperative grammar, not a general Chinese reference parser."""
    match=re.match(r'^(?:请|帮我|麻烦)?把第([一二])张(?:图片|图|候选图)?([^，。！？\n]*)',text.strip())
    if not match:return None
    tail=match[2]
    if re.search(r'不要|先不|暂不|别|保留|不动|不改',tail):return None
    if not re.search(r'旋转|裁剪|改成|改为|修改|去掉|替换',tail):return None
    index={'一':0,'二':1}[match[1]]
    return candidates[index]['id'] if len(candidates)>index else None

class GroundedPolicy(ClarificationPolicy):
    """Common experimental gate; no model score can fill a missing target."""
    def guard(self,task,name,args):
        ctx=task['context'];intent=ctx.get('intent','unclear')
        if name in MUTATING and intent in ('unclear','discuss','draft','propose_change'):
            return question('Q_INTENT','这次希望先讨论或写方案，还是执行具体操作？')
        if name in ('miniclaw_edit_image','evaluation_adopt_candidate'):
            semantic=ctx.get('semantic',{});target=semantic.get('selected')
            requested=args.get('source_id') if name=='miniclaw_edit_image' else args.get('target_id')
            if not target or requested!=target:
                return question('Q_TARGET','要操作哪张图片？请明确选择，其余图片保持不变。',
                                [c['label'] for c in semantic.get('candidates',[])])
            text=task['text']+' '+ctx.get('latest_user_reply','')
            if (name=='miniclaw_edit_image' and re.search(r'这里|这块|这个位置',text)
                    and not region_resolved(task)):
                return question('Q_SCOPE','需要修改哪个位置？请圈选或说明具体区域。')
        # Adoption has the same permission semantics as the actual canvas apply
        # tool; the synthetic callback name must not introduce an extra gate.
        checked_name='miniclaw_canvas_apply' if name=='evaluation_adopt_candidate' else name
        return super().guard(task,checked_name,args)
