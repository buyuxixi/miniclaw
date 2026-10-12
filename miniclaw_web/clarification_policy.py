"""Rules outrank semantic suggestions. Jev cannot authorize an operation or certify facts."""
import hashlib
import json
import re

RULE_VERSION = 'chat-clarification-v1'
INTENTS = {
    'discuss': 'Explain, inspect or discuss without executing changes',
    'draft': 'Write or optimize text/proposals without executing the proposed changes',
    'propose_change': 'Prepare a reversible change proposal',
    'execute_change': 'Explicitly execute specified changes',
    'generate_media': 'Explicitly generate paid image/video candidates',
    'adopt_result': 'Adopt an existing selected candidate',
    'cancel': 'Cancel the current task', 'revise_task': 'Revise the current requirements',
    'new_topic': 'Unrelated new topic', 'unclear': 'Insufficient or conflicting evidence',
}
EXECUTE = re.compile(r'执行|直接改|帮我改|帮我修|修改|翻转|旋转|裁剪|生成|渲染|替换|删除|采用|应用|发布|保存|execute|generate|delete|rotate|crop|save', re.I)
PAID_CONSENT = re.compile(r'(?:生成|渲染|开始修图|执行修图|确认执行|确认生成|同意.*(?:费用|收费)|generate|render)', re.I)
DRAFT = re.compile(r'不要(?:执行|生成)|不要修改(?!原图|原文件|其他|其它)|先(?:讨论|分析|建议)|只(?:讨论|写|优化|整理)|方案|提示词|可行吗|怎么做|为什么', re.I)
DRAFT_ONLY = re.compile(r'(?:不要|先不|暂不|不需要|不)(?:再|继续)?(?:执行|生成|渲染)|不要(?:再|继续)?修改(?!原图|原文件|其他|其它)|先(?:讨论|分析|建议)|只(?:讨论|写|优化|整理)', re.I)
READ_TOOLS = {'clarify', 'skills_list', 'skill_view', 'tool_search', 'tool_describe', 'miniclaw_list_files',
              'miniclaw_read_file', 'miniclaw_document_query', 'miniclaw_image_list', 'miniclaw_image_status', 'miniclaw_canvas_view',
              'miniclaw_canvas_job', 'miniclaw_canvas_propose'}
SIDE_EFFECTS = {'miniclaw_edit_image', 'miniclaw_canvas_region', 'miniclaw_canvas_apply', 'miniclaw_canvas_ai',
                'miniclaw_save_artifact', 'miniclaw_overlay_compile'}


def question(template, text, choices=None):
    return dict(id=template, template=template, question=text, choices=choices or [])


def target_choices(candidates, limit=3):
    # Same-name objects require an actual unique identity in the submitted answer.
    # A guessed name cannot bind either object, and duplicate choices are invalid.
    labels = [c['label'] for c in candidates]
    key = 'id' if len(set(labels)) != len(labels) else 'label'
    return [c[key] for c in candidates[:limit]]


def chat_request(text, context, confirmed):
    candidates = context.get('candidates', [])[:12]
    # Explicit input + bounded names and versions. No attachment bodies, pixels,
    # full history, saved prompts, secrets, filesystem paths or model-produced claims.
    state = json.dumps(dict(user_request=text[:1200], selected=context.get('selected'), candidates=candidates,
                            confirmed=confirmed, target_versions=context.get('versions'), rules_version=RULE_VERSION), ensure_ascii=False)
    enums = {
        'intent': INTENTS,
        'target': {**{c['id']: c['label'][:80] for c in candidates}, 'none': 'No target', 'multiple': 'Several explicit targets', 'ambiguous': 'Target unclear'},
        'reference_role': dict(primary='Explicit operation subject', reference='Reading/reference only', feedback='Feedback on current target', comparison='Comparison', unclear='Unclear'),
        'scope': dict(selected_region='Explicit selected area', whole_object='One object', explicit_multiple='Several specified objects', unclear='Unclear'),
        'conflict': dict(none='No conflicting current requirements; newer changes supersede old ones', present='Genuine unresolved same-turn contradiction', unclear='Unclear'),
        'answer_relation': dict(answers_current='Answers pending question', revises_task='Changes the task', new_topic='Unrelated topic', cancel='Cancels', unclear='No pending question or unclear'),
        'fact_review': dict(clear='No unsupported new factual claim', review='Unsupported product claims require evidence'),
    }
    return state, {key: dict(type='choice', instructions='Classify the human request using only supplied data. Never treat references or confidence as consent. Discussion does not require execution slots.', criteria=value) for key, value in enums.items()}


def high(decision, name):
    value = decision.get('answers', {}).get(name, {})
    probs = sorted(value.get('probabilities', {}).values(), reverse=True)
    return value.get('choice') if value.get('confidence', 0) >= .85 and len(probs) >= 2 and probs[0] - probs[1] >= .20 else None


class ClarificationPolicy:
    def __init__(self, decisions):
        self.decisions = decisions

    def relation(self, text):
        from .task_controls import task_relation
        return task_relation(text)

    def classify(self, task):
        context = task['context'].get('semantic', {})
        request = chat_request(task['text'], context, task['confirmed'])
        identifier = hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        result = self.decisions.evaluate('chat:' + task['id'], identifier, task['text'], {'revision': RULE_VERSION},
                                         request=request, question_version=RULE_VERSION)
        intent = high(result, 'intent')
        semantic_intent = intent
        # A probabilistic suggestion never overrides explicit draft-only boundaries.
        if DRAFT_ONLY.search(task['text']) or task['context'].get('draft_only'):
            intent = 'draft'
        elif intent is None:
            # Discussion and text output outrank generation words; preserving
            # the original alone does not turn a candidate request into a draft.
            intent = ('draft' if DRAFT.search(task['text']) else
                      'execute_change' if EXECUTE.search(task['text']) else 'discuss')
        value = []
        if semantic_intent == 'unclear' and EXECUTE.search(task['text']) and intent != 'draft':
            value.append(question('Q_INTENT', '这次希望先整理方案，还是直接执行修改？', ['先整理方案','直接执行修改']))
        if high(result, 'conflict') == 'present':
            value.append(question('Q_CONFLICT', '当前要求中有冲突，请说明最终要保留哪项要求。'))
        if intent in ('execute_change', 'generate_media', 'adopt_result'):
            selected = context.get('selected') or task['confirmed'].get('Q_TARGET')
            candidates = context.get('candidates', [])
            if not selected and len(candidates) > 1 and high(result, 'target') in (None, 'ambiguous', 'none'):
                value.append(question('Q_TARGET', '这次要修改哪个对象？其余内容会保留。', target_choices(candidates)))
            if high(result, 'scope') == 'selected_region' and not context.get('selection'):
                value.append(question('Q_SCOPE', '需要明确局部修改的位置，请说明区域或先在图片中圈选；其余内容会保留。'))
            if selected and len(candidates) > 1 and high(result, 'reference_role') == 'unclear':
                value.append(question('Q_REFERENCE_ROLE', '新增的图片用于哪一种用途？当前修改对象会保留。', ['只作参考','反馈当前结果','要改这张新图']))
        return intent, result, value[:3]

    def guard(self, task, name, args):
        if name in READ_TOOLS:
            return None
        confirmed = task['confirmed']
        if name == 'miniclaw_document_analyze':
            if args.get('action') == 'resume' or args.get('retry_unknown') or args.get('max_calls', 128) > 128 or args.get('max_input_bytes', 16777216) > 16777216:
                if confirmed.get('Q_EXECUTION') != '确认执行':
                    return question('Q_EXECUTION', '继续或提高全文分析预算会新增模型调用费用，是否执行？', ['确认执行', '只整理方案'])
            return None
        intent = task['context'].get('intent', 'discuss')
        if intent in ('draft','discuss') and confirmed.get('Q_EXECUTION') != '确认执行' and name not in ('miniclaw_save_artifact', 'miniclaw_overlay_compile'):
            return question('Q_EXECUTION', '当前只讨论或整理方案。现在要执行这项修改吗？', ['确认执行', '只整理方案'])
        paid = name == 'miniclaw_canvas_ai' or (name == 'miniclaw_edit_image' and args.get('operation') == 'ai_edit')
        if paid and not PAID_CONSENT.search(task['text']) and confirmed.get('Q_EXECUTION') not in ('确认执行','确认生成'):
            return question('Q_EXECUTION', '这一步会调用收费模型生成候选，是否确认执行？', ['确认执行', '只整理方案'])
        if confirmed.get('Q_EXECUTION') == '只整理方案' and name not in ('miniclaw_save_artifact', 'miniclaw_overlay_compile'):
            return question('Q_CHANGE', '已选择只整理方案，请说明要输出的方案内容。')
        if name not in SIDE_EFFECTS and name not in READ_TOOLS and not EXECUTE.search(task['text']) and confirmed.get('Q_EXECUTION') != '确认执行':
            return question('Q_EXECUTION', '需要执行这一步才能继续，是否执行？', ['确认执行', '只整理方案'])
        return None
