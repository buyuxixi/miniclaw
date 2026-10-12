"""Opt-in decision policy. Host answers, bindings and permissions remain authoritative."""
from .clarification_policy import ClarificationPolicy, high, question, READ_TOOLS, target_choices


class CandidateClarificationPolicy(ClarificationPolicy):
    def classify(self, task):
        intent, result, questions = super().classify(task)
        # Resolving a contradiction precedes choosing execution parameters.
        if high(result, 'conflict') == 'present':
            return 'unclear', result, [question('Q_CONFLICT', '当前要求中有冲突，请说明最终要保留哪项要求。')]
        if task['confirmed'].get('Q_EXECUTION')=='只整理方案' or task['confirmed'].get('Q_INTENT')=='先整理方案':
            return 'draft', result, []
        if task['context'].get('literal_target',{}).get('status')=='unresolved':
            cs=task['context'].get('semantic',{}).get('candidates',[])
            # Unresolved identity does not erase an accepted operation intent.
            # The host still blocks writes until a genuine target answer binds it.
            intent='execute_change' if high(result,'intent')=='execute_change' else 'unclear'
            return intent, result, [question('Q_TARGET','指定名称没有对应的唯一附件，请选择实际对象。',target_choices(cs))]
        semantic_intent = high(result, 'intent')
        if semantic_intent is None and intent != 'draft':
            intent, questions = 'unclear', []
            result = dict(result, semantic_abstention=True)
        elif semantic_intent == 'unclear' and intent != 'draft':
            questions = [question('Q_INTENT', '请说明这次希望讨论、写文字，还是执行哪项具体修改？')]
        if intent == 'generate_media' and high(result, 'target') == 'none':
            questions = [q for q in questions if q['template'] != 'Q_TARGET']
        if intent in ('execute_change', 'adopt_result') and high(result, 'target') == 'ambiguous' and not any(q['template'] == 'Q_TARGET' for q in questions):
            cs = task['context'].get('semantic', {}).get('candidates', [])
            questions.append(question('Q_TARGET', '请明确要处理哪个对象；没有对象时请先提供。', target_choices(cs)))
        return intent, result, questions[:3]

    def guard(self, task, name, args):
        if task['context'].get('intent') in ('unclear', 'propose_change', 'revise_task', 'new_topic', 'cancel') and name not in READ_TOOLS | {'miniclaw_save_artifact', 'miniclaw_overlay_compile'}:
            if task['confirmed'].get('Q_EXECUTION') != '确认执行':
                return question('Q_EXECUTION', '这一步将实际修改内容，是否确认执行？', ['确认执行', '只整理方案'])
        return super().guard(task, name, args)
