"""Conservative task commands from the current human input, never quoted data."""
import re


_PREFIX = r'(?:(?:请|麻烦|帮我|我们|现在|那就)\s*)?'
_CANCEL = re.compile(_PREFIX + r'(?:取消|终止|停止|放弃)(?:一下)?(?:(?:刚才|当前|这个|原来)(?:的)?)?(?:任务|操作|请求|生成|修图)(?:吧|了)?[。！!\s]*$')
_REVISE = re.compile(_PREFIX + r'(?:(?:修改|调整|更改|变更)(?:一下)?(?:(?:刚才|当前|这个|原来)(?:的)?)?(?:需求|要求|任务)|(?:把|将)(?:需求|要求|任务)改(?:成|为))')
_TOPIC = re.compile(_PREFIX + r'(?:换(?:个|一个)?话题|另聊(?:个|一个)?话题|聊(?:点|些)?别的)')
_ENGLISH = re.compile(r'^(cancel|revise|change|new topic|switch topic)\s*(?:the\s+)?(?:current\s+)?(?:task|request|requirements)?\s*(?::\s*(.*))?$', re.I)


def task_relation(text):
    """Return an explicit command; short answers and hypothetical commands stay unclear.

    We deliberately do not infer task mutation from uncalibrated semantic scores.
    Payload is current human input and is submitted through the usual guarded turn.
    """
    value = text.strip()
    if _CANCEL.fullmatch(value):
        return dict(action='cancel', text='', source='explicit_rule')
    for pattern, action in ((_REVISE, 'revise'), (_TOPIC, 'new_topic')):
        match = pattern.match(value)
        if match:
            rest = value[match.end():]
            # Require a boundary: “修改需求的流程是什么” is a question, not a command.
            if rest and rest[0] not in ':：,，;；。\n \t':
                return None
            payload = rest.lstrip(':：,，;；。\n \t').strip()
            if payload.endswith(('吗', '吗？', '吗?', '？', '?')) and not rest.lstrip(' \t').startswith((':', '：', '\n')):
                return None
            return dict(action=action, text=payload, source='explicit_rule')
    match = _ENGLISH.fullmatch(value)
    if match:
        kind, payload = match.groups()
        action = 'cancel' if kind.lower() == 'cancel' else 'new_topic' if 'topic' in kind.lower() else 'revise'
        if action == 'cancel' and payload:
            return None
        return dict(action=action, text=(payload or '').strip(), source='explicit_rule')
    return None
