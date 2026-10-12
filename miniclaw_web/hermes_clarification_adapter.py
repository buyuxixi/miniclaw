"""Opted-in Hermes host callbacks; paired with the pinned compatibility patch.

No global replacement of the Agent loop. Each running miniclaw task owns one adapter.
"""
import hashlib
import json

from .clarifications import encode
from .clarification_policy import READ_TOOLS, question, target_choices

COMPAT_VERSION = 3
PINNED_COMMIT = 'f97608f178d1ffeca59860195ab7da295f7c8e5f'


def verify_compatibility(root):
    import subprocess
    from agent.turn_tool_round import HOSTED_TURN_ADAPTER_VERSION
    if HOSTED_TURN_ADAPTER_VERSION != COMPAT_VERSION:
        raise RuntimeError('Hermes澄清适配版本不兼容，请运行安装脚本应用固定补丁')
    actual = subprocess.run(['git','-C',str(root / 'hermes-agent'),'rev-parse','HEAD'], capture_output=True,text=True,check=True).stdout.strip()
    if actual != PINNED_COMMIT:
        raise RuntimeError('Hermes提交与澄清兼容补丁不匹配，未启用新恢复流程')


class HermesClarificationAdapter:
    def __init__(self, service, policy, session, task_id, validate=None, resume_job=None, refresh=None, recovery=None, trace=None):
        self.service, self.policy, self.session, self.task_id = service, policy, session, task_id
        self.agent = session['agent']
        self.validate, self.resume_job = validate, resume_job
        self.refresh = refresh
        self.recovery = recovery
        from .chat_trace import ChatTrace, TraceStore
        self.trace = trace or ChatTrace(TraceStore(service.store), service.task(task_id), self.agent, resume_job)
        if recovery:
            recovery.trace = self.trace
        self.pending = None
        self.preflight_done = False
        self.finished = False
        self.original_limit = getattr(self.agent, 'max_iterations', 100)

    def metadata(self):
        return dict(task_id=self.task_id, **({'resume_job_id': self.resume_job} if self.resume_job else {}))

    def _prepare(self, value, channel, call_id=None):
        self.pending = self.service.prepare(self.task_id, value, channel, call_id)
        self.trace.decision('waiting', channel, clarification_id=self.pending, call_id=call_id)
        return encode(dict(status='awaiting_input', clarification_id=self.pending, task_id=self.task_id,
                           instructions='No answer has been supplied. Resume only after a real user answer.'))

    def before_model(self, messages):
        if self.preflight_done:
            return None
        self.preflight_done = True
        self.trace.capture_public_messages(messages)
        if self.recovery:
            from .chat_recovery import RecoveryStopped
            try:
                self.recovery.start()
            except RecoveryStopped as exc:
                self.recovery.reason = exc.reason
                return self.recovery.failure(messages, 0)
        task = self.service.task(self.task_id)
        remaining = task['max_calls'] - task['used_calls']
        if remaining <= 0:
            raise ValueError('任务累计调用预算已用完，请取消后重新规划')
        self.agent.max_iterations = min(self.original_limit, remaining)
        if not self.resume_job:
            from .literal_image_target import bind_named_attachment
            bound_context = bind_named_attachment(task)
            if bound_context is not None:
                self.service.configure(self.task_id, **bound_context)
                task = self.service.task(self.task_id)
            intent, decision, value = self.policy.classify(task)
            self.service.configure(self.task_id, intent=intent, decision=decision)
            if value:
                self._prepare(value, 'preclassifier')
        return self.wait_result(messages, 0)

    def prepare_tools(self, calls):
        task = self.service.task(self.task_id)
        loaded = {d['function']['name'] for d in getattr(self.agent, 'tools', [])}
        required = set(task['context'].get('required_tools', []))
        required.update(call.function.name for call in calls if call.function.name in loaded - READ_TOOLS)
        self.service.configure(self.task_id, required_tools=sorted(required))
        # An explicit clarification anywhere in this batch suspends all mutations,
        # even when a model emitted the modifying call before clarify.
        for call in calls:
            if call.function.name != 'clarify':
                continue
            args = call.function.arguments
            try:
                args = json.loads(args) if isinstance(args, str) else args
                value = args.get('questions') or [dict(question=args.get('question'), choices=args.get('choices'), multi_select=args.get('multi_select', False))]
                self._prepare(value, 'tool', call.id)
                break
            except (ValueError, TypeError, KeyError):
                # Bad clarify arguments must not authorize the rest of the batch.
                self._prepare([question('Q_CHANGE', '请补充这次要完成的目标和需要保留的内容。')], 'tool', call.id)
                break

    def dispatch(self, name, args, call_id, execute):
        execution = {'attempt': 0, 'operation_id': None}

        def traced_execute():
            execution['attempt'] += 1
            identifier = self.trace.tool_start(name, args, call_id, execution['attempt'], execution['operation_id'])
            try:
                result = execute()
            except BaseException as error:
                self.trace.tool_end(identifier, error=error, operation_id=execution['operation_id'])
                raise
            self.trace.tool_end(identifier, result, operation_id=execution['operation_id'])
            return result

        result = self._dispatch(name, args, call_id, traced_execute, execution)
        if not execution['attempt']:
            self.trace.skipped_tool(name, args, call_id, result)
        return result

    def _dispatch(self, name, args, call_id, execute, execution):
        if self.recovery:
            self.recovery.check()
        if self.pending:
            return encode(dict(status='awaiting_input' if name == 'clarify' else 'not_executed_awaiting_input',
                               clarification_id=self.pending, task_id=self.task_id, executed=False))
        if name == 'clarify':
            value = args.get('questions') or [dict(question=args.get('question'), choices=args.get('choices'), multi_select=args.get('multi_select', False))]
            return self._prepare(value, 'tool', call_id)
        task = self.service.task(self.task_id)
        if task['status'] != 'running':
            return encode(dict(status='not_executed', executed=False, error='任务已停止'))
        selected = task['context'].get('semantic',{}).get('selected')
        candidates = task['context'].get('semantic',{}).get('candidates',[])
        unresolved_name = task['context'].get('literal_target', {}).get('status') == 'unresolved'
        if name == 'miniclaw_edit_image' and not selected and (len(candidates)>1 or unresolved_name):
            return self._prepare([question('Q_TARGET','这次要修改哪张图片？其余图片会保留。',target_choices(candidates))],'hook',call_id)
        if name == 'miniclaw_edit_image' and selected in task['context'].get('attachments',[]) and args.get('source_id') != selected:
            return encode(dict(status='not_executed',executed=False,reason='用户已确认另一张图片为修改对象，请使用已确认目标',source_id=selected))
        if task['confirmed'].get('Q_EXECUTION') == '只整理方案' and name not in READ_TOOLS | {'miniclaw_save_artifact','miniclaw_overlay_compile'}:
            return encode(dict(status='not_executed', executed=False, reason='用户已选择只整理方案，请按回答输出文字或提案'))
        value = self.policy.guard(task, name, args)
        if value:
            return self._prepare([value], 'hook', call_id)
        if name in READ_TOOLS:
            # A saved proposal is advisory to business policy, but still a write.
            return self.recovery.read_tool(name, execute) if self.recovery and name != 'miniclaw_canvas_propose' else execute()
        if self.validate:
            self.validate(task, self.session)
        # request_id is model-created noise; the business key is task + semantic
        # parameters + source versions. Repeated successful steps reuse the receipt.
        parameters = {k: v for k, v in args.items() if k != 'request_id'}
        versions = task['context'].get('versions', {})
        paid = name == 'miniclaw_canvas_ai' or name == 'miniclaw_edit_image' and args.get('operation') == 'ai_edit'
        identifier, status, saved = self.service.operation(self.task_id, name, parameters, versions, paid=paid)
        execution['operation_id'] = identifier
        if status == 'needs_consent':
            return self._prepare([question('Q_EXECUTION','上一项收费调用已提交。继续生成或重试会新增费用，是否再执行一次？',['确认执行','只整理方案'])],'hook',call_id)
        if status in ('succeeded','failed') and saved.get('result') is not None:
            self.trace.decision('reuse', status, operation_id=identifier, call_id=call_id)
            return saved['result']
        if status in ('reserved','running','unknown'):
            self.trace.decision('reconcile', status, operation_id=identifier, call_id=call_id)
            return self._prepare([question('Q_RECONCILE', '上一步结果尚未确认，已停止自动重试。请先核对任务记录；若需要改变目标，请修改需求。')], 'hook', call_id)
        if 'request_id' in args:
            args['request_id'] = identifier[:64]
        self.service.operation_result(identifier, 'running')
        try:
            result = execute()
        except BaseException:
            self.service.operation_result(identifier, 'unknown')
            raise
        try:
            parsed = json.loads(result) if isinstance(result, str) else result
        except (ValueError, TypeError):
            parsed = {}
        failed = isinstance(parsed, dict) and (parsed.get('success') is False or parsed.get('error') or parsed.get('state') in ('failed','canceled'))
        # Network/tool timeouts are unknown effects, not evidence of safe failure.
        from .chat_recovery import unknown_effect
        unknown = unknown_effect(parsed)
        self.service.operation_result(identifier, 'unknown' if unknown else 'failed' if failed else 'succeeded', result)
        if not failed and not unknown and self.refresh:
            self.refresh(self.service.task(self.task_id))
        return result

    def wait_result(self, messages, calls):
        if not self.pending:
            return None
        from agent.message_metadata import append_message
        text = '需要你补充信息，任务已暂停。回答下方问题后继续；已完成的结果会保留。'
        append_message(messages, dict(role='assistant', content=text,
                                    display_metadata=dict(task_id=self.task_id, clarification_id=self.pending)))
        self.agent._session_messages = messages
        if self.agent._flush_messages_to_session_db(messages) is False:
            raise OSError('澄清历史保存失败，未进入可回答状态')
        return dict(messages=messages, final_response=text, awaiting_input=dict(task_id=self.task_id, clarification_id=self.pending),
                    completed=False, failed=False, api_calls=calls)

    def finish(self, result, owner, warning=None):
        if self.finished:
            return
        if self.recovery:
            self.recovery.finish(result)
        if warning or not isinstance(result, dict):
            self.service.finish(self.task_id, 'reconciling', owner=owner)
        elif result.get('awaiting_input') and not result.get('error'):
            self.service.seal(self.task_id, owner, len(result.get('messages', [])), result.get('api_calls', 0))
        else:
            status = 'aborted' if result.get('interrupted') else 'failed' if result.get('failed') or result.get('error') else 'completed'
            self.service.finish(self.task_id, status, result.get('api_calls', 0), owner)
        self.trace.finish(result, warning, self.recovery.snapshot() if self.recovery else None)
        self.agent.max_iterations = self.original_limit
        self.finished = True


def semantic_context(studio=None, canvas=None, attachments=None):
    candidates = []
    selected = None
    if studio:
        candidates = [dict(id=o['id'], label=o.get('name') or o['id']) for o in studio.get('assets', []) + studio.get('shots', [])]
        selected = (studio.get('target') or {}).get('id')
    elif canvas:
        selected = canvas.get('layer_id')
    elif attachments:
        candidates = [dict(id=a['id'], label=a['name']) for a in attachments if a['kind'] == 'image']
        # Uploaded images are reference data, not automatically selected targets.
    return dict(selected=selected, candidates=candidates)
