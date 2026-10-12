"""Versioned, opt-in Laya business advice. Advice never grants tool permission."""
from __future__ import annotations

import json
import math
import hashlib
from copy import deepcopy

VERSION = 'laya-business-advisory-v1'
INTENTS = {
    'discuss': '讨论、评价、比较、解释；不实施操作。',
    'draft': '在回复中起草或优化文字，包括方案、口播、提示词；不写入正式版本。',
    'propose_change': '为已有作品列待审修改提案，尚不实施。',
    'execute_change': '现在修改已有作品或写入正式字段；不含生成新媒体。',
    'generate_media': '现在调用模型生成新的图片或视频候选。',
    'adopt_result': '明确采用已有候选为正式版本；评价不算采用。',
    'cancel': '明确终止当前任务。',
    'revise_task': '只更新任务要求，暂不改作品。',
    'new_topic': '明确转到与产品宣传无关的新话题。',
    'unclear': '无法确定本轮目的或同轮要求矛盾；单纯缺对象不改变明确意图。',
}
CLARIFICATIONS = {
    'none': '可以理解请求并开始处理；讨论和文字起草不需要执行对象。',
    'intent': '无法确定要讨论、写文字还是实施，须问目的；低分本身不等于意图不清。',
    'target': '要操作现有作品，但上下文及文字均不能唯一定位对象。',
    'region': '明确只操作某局部，但没有圈选或位置描述。',
    'conflict': '当前同一对象的有效要求互相矛盾，需要明确取舍。',
}
CATEGORIES = {
    'scheme': '宣传方案、受众、风格、分镜方案的讨论、起草或调整。',
    'image': '图片视觉评价、修图、图片生成或采用图片候选。',
    'image_prompt': '图像或修图提示词的解释、起草、优化或保存。',
    'video_prompt': '视频提示词的解释、起草、优化或保存。',
    'narration': '产品宣传口播文字的评价、起草、优化或采用。',
    'video': '视频成片的评价、剪辑、生成或采用；只写视频提示词不算成片操作。',
}


def questions():
    out = {
        'intent': dict(type='choice', instructions='按完整请求和可信会话状态判断本轮目的。引用、假设、否定不是实施授权。', criteria=INTENTS.copy()),
        'clarification': dict(type='choice', instructions='判断开始本轮处理前必要的澄清；已确认信息不重复询问。只讨论不追问修改对象。新要求替代旧要求不是冲突。', criteria=CLARIFICATIONS.copy()),
    }
    for name, description in CATEGORIES.items():
        out['category_' + name] = dict(type='choice', instructions='独立判断本轮是否涉及此业务，允许同时涉及多个类别。忽略被明确排除的动作和旧话题；控制请求按正在控制的业务判断。',
                                      criteria={'no': '本轮不涉及：' + description, 'yes': '本轮涉及：' + description})
    return out


def question_sha256():
    # Preserve option order, but do not bind deployment to filesystem CRLF/LF.
    return hashlib.sha256(json.dumps(questions(), ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def build_state(text, context):
    """A caller supplies trusted metadata; full prompts/history/gold never enter state."""
    if not isinstance(text, str) or not text.strip() or len(text) > 1200:
        raise ValueError('Request must contain 1..1200 characters; no silent truncation')
    if not isinstance(context, dict):
        raise ValueError('Context must be an object')
    allowed = {'product', 'selected', 'candidates', 'selection', 'pending_task', 'pending_question',
               'confirmed', 'draft_only', 'target_bound', 'region_bound', 'needs_existing_target'}
    if set(context) - allowed:
        raise ValueError('Unknown context fields')
    for key in ('draft_only', 'target_bound', 'region_bound', 'needs_existing_target'):
        if key in context and type(context[key]) is not bool:
            raise ValueError('Binding facts must be booleans')
    candidates = context.get('candidates', [])
    if not isinstance(candidates, list) or len(candidates) > 12:
        raise ValueError('Invalid candidate list')
    ids = set()
    for candidate in candidates:
        if (not isinstance(candidate, dict) or set(candidate) != {'id', 'label'}
                or not all(isinstance(v, str) and 0 < len(v) <= 100 for v in candidate.values())
                or candidate['id'] in ids):
            raise ValueError('Invalid candidate')
        ids.add(candidate['id'])
    if context.get('selected') is not None and context['selected'] not in ids:
        raise ValueError('Selected object is outside the conversation candidates')
    state = {'user_request': text, 'context': deepcopy(context)}
    if len(json.dumps(state, ensure_ascii=False).encode('utf-8')) > 8000:
        raise ValueError('Context exceeds the input budget')
    return state


def parse_prediction(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get('answers'), dict):
        raise ValueError('Missing model answers')
    usage = raw.get('usage')
    if (not isinstance(usage, dict) or usage.get('truncated') is not False
            or usage.get('truncated_questions') or usage.get('options')):
        raise ValueError('Incomplete input/options coverage')
    expected = questions()
    if set(raw['answers']) != set(expected):
        raise ValueError('Incomplete question coverage')
    result = {}
    for name, schema in expected.items():
        answer = raw['answers'][name]
        if not isinstance(answer, dict):
            raise ValueError('Invalid answer')
        probs = answer.get('probabilities')
        if (not isinstance(probs, dict) or set(probs) != set(schema['criteria'])
                or any(type(v) not in (float, int) or not math.isfinite(v) or not 0 <= v <= 1 for v in probs.values())
                or abs(sum(probs.values()) - 1) > .001):
            raise ValueError('Invalid probabilities')
        choice = answer.get('choice')
        if choice not in probs or probs[choice] < max(probs.values()) - 1e-6:
            raise ValueError('Invalid top answer')
        ordered = sorted(probs.values(), reverse=True)
        result[name] = dict(choice=choice, probability=probs[choice], margin=ordered[0] - ordered[1])
    return result


def advisory(raw, context, gates):
    """Only calibrated suggestions. Deterministic missing facts gate a direct question."""
    fallback = dict(version=VERSION, status='fallback', intent=None, categories=[],
                    clarification=None, question=None, main_model_required=True,
                    execution_authorized=False)
    try:
        parsed = parse_prediction(raw)
    except ValueError as error:
        return {**fallback, 'reason': str(error)}
    if not isinstance(gates, dict) or gates.get('version') != VERSION:
        return {**fallback, 'reason': 'No compatible independent calibration'}

    def accepted(name):
        gate = gates.get('questions', {}).get(name, {})
        score = parsed[name]
        return (gate.get('enabled') is True and type(gate.get('threshold')) in (float, int)
                and .5 <= gate['threshold'] <= 1 and score['probability'] >= gate['threshold']
                and score['margin'] >= .1 and score['choice'] in gate.get('labels', []))

    out = {**fallback, 'reason': None}
    if accepted('intent'):
        out['intent'] = parsed['intent']['choice']
    out['categories'] = [name for name in CATEGORIES
                         if accepted('category_' + name) and parsed['category_' + name]['choice'] == 'yes']
    if accepted('clarification'):
        out['clarification'] = parsed['clarification']['choice']
    out['status'] = 'advisory' if out['intent'] or out['categories'] or out['clarification'] else 'fallback'
    # Keep generic ambiguity/conflict with the main model in this first version.
    # A classifier cannot decide whether a target is already bound by the host.
    if (out['intent'] in ('execute_change', 'adopt_result', 'generate_media')
            and not context.get('draft_only') and context.get('needs_existing_target') is True):
        kind = out['clarification']
        direct = kind in gates.get('questions', {}).get('clarification', {}).get('direct_labels', [])
        if direct and kind == 'target' and context.get('target_bound') is False and not context.get('selected'):
            out.update(question=dict(id='Q_TARGET', template='Q_TARGET', question='这次要操作哪个对象？请明确选择。', choices=[]), main_model_required=False)
        elif direct and kind == 'region' and context.get('target_bound') is True and context.get('region_bound') is False and not context.get('selection'):
            out.update(question=dict(id='Q_SCOPE', template='Q_SCOPE', question='需要修改哪个区域？请描述位置或圈选。', choices=[]), main_model_required=False)
    return out


class LayaAdvisoryClient:
    """Explicit loopback client. Nothing constructs this in the production path by default."""
    def __init__(self, base_url, gates, *, timeout=2.):
        from urllib.parse import urlsplit
        url = urlsplit(base_url)
        if (url.scheme != 'http' or url.hostname not in ('127.0.0.1', 'localhost', '::1')
                or url.username or url.password or url.query or url.fragment or url.path not in ('', '/')
                or not 0 < timeout <= 10):
            raise ValueError('Advisory endpoint must be a bounded loopback HTTP service')
        if (not isinstance(gates, dict) or gates.get('version') != VERSION
                or gates.get('question_sha256') != question_sha256()
                or not isinstance(gates.get('checkpoint_sha256'), str) or len(gates['checkpoint_sha256']) != 64):
            raise ValueError('Gate artifact does not match the question contract/checkpoint')
        self.url = base_url.rstrip('/') + '/v1/advice'
        self.gates = deepcopy(gates)
        self.timeout = timeout

    def evaluate(self, text, context):
        from urllib.request import Request, ProxyHandler, build_opener, HTTPRedirectHandler
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, *unused): return None
        try:
            state = build_state(text, context)
            payload = json.dumps(dict(contract_version=VERSION, state=state), ensure_ascii=False).encode('utf-8')
            request = Request(self.url, data=payload, headers={'Content-Type': 'application/json'}, method='POST')
            with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=self.timeout) as response:
                body = response.read(65537)
            if len(body) > 65536:
                raise ValueError('Advisory response exceeds the byte budget')
            data = json.loads(body)
            if data.get('contract_version') != VERSION or data.get('checkpoint_sha256') != self.gates['checkpoint_sha256']:
                raise ValueError('Checkpoint/version changed; recalibration required')
            # Derive suggestions locally from raw scores and original trusted context.
            result = advisory(data.get('raw'), context, self.gates)
            return dict(advice=result, raw=data.get('raw'), status='received')
        except (ValueError, OSError, TypeError, AttributeError) as error:
            result = advisory(None, context, self.gates)
            result['reason'] = type(error).__name__
            return dict(advice=result, raw=None, status='fallback')
