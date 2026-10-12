"""Isolated rule ablation. Both models use this policy; production unchanged."""
from miniclaw_web.clarification_policy import ClarificationPolicy,high,question,READ_TOOLS

class OperationalClarificationPolicy(ClarificationPolicy):
    def classify(self,task):
        intent,result,qs=super().classify(task)
        semantic_intent=high(result,'intent')
        if semantic_intent is None and intent!='draft':
            # Abstention is handed to the main model. Keyword guesses cannot
            # create an execution classification or its premature slot questions.
            intent='unclear'
            qs=[q for q in qs if q['template']=='Q_CONFLICT']
            result=dict(result,semantic_abstention=True)
        elif semantic_intent=='unclear' and intent!='draft' and not any(q['template']=='Q_CONFLICT' for q in qs):
            qs=[question('Q_INTENT','请说明这次希望讨论、写文字，还是执行哪项具体修改？')]
        if intent=='generate_media' and high(result,'target')=='none':
            qs=[q for q in qs if q['template']!='Q_TARGET']
        if intent in ('execute_change','adopt_result') and high(result,'target')=='ambiguous' and not any(q['template']=='Q_TARGET' for q in qs):
            cs=task['context'].get('semantic',{}).get('candidates',[])
            qs.append(question('Q_TARGET','请明确要处理哪个对象；没有对象时请先提供。',[c['label'] for c in cs[:3]]))
        return intent,result,qs[:3]

    def guard(self,task,name,args):
        if task['context'].get('intent') in ('unclear','propose_change','revise_task','new_topic','cancel') and name not in READ_TOOLS|{'miniclaw_save_artifact','miniclaw_overlay_compile'}:
            if task['confirmed'].get('Q_EXECUTION')!='确认执行':
                return question('Q_EXECUTION','这一步将实际修改内容，是否确认执行？',['确认执行','只整理方案'])
        return super().guard(task,name,args)
