"""Owned, immutable image versions and durable jobs shared by UI and Agent tools."""
import base64
import hashlib
import io
import json
import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageEnhance, ImageOps
from .attachments import public, upload
from .image_provider import edit_image, provider_status

OPERATIONS = ('adjust', 'crop', 'rotate', 'flip', 'resize', 'ai_edit')
ACTIVE = ('queued', 'running')


def number(value, lower, upper, integer=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
            or not lower <= value <= upper or (integer and int(value) != value)):
        raise ValueError('修图参数不在允许范围内')
    return int(value) if integer else value


def validate(operation, params):
    if operation not in OPERATIONS or not isinstance(params, dict):
        raise ValueError('未知修图操作或参数')
    allowed = {'adjust': {'brightness', 'contrast', 'saturation', 'sharpness'}, 'crop': {'ratio', 'rect'},
               'rotate': {'angle'}, 'flip': {'direction'}, 'resize': {'width', 'height'}, 'ai_edit': {'prompt'}}[operation]
    if set(params) - allowed:
        raise ValueError('修图请求包含未知参数')
    if operation == 'adjust':
        if not params:
            raise ValueError('请选择至少一项调色参数')
        return {key: number(value, -1, 1) for key, value in params.items()}
    if operation == 'crop':
        if len(params) != 1:
            raise ValueError('请选择裁剪比例或裁剪框其中一项')
        if 'ratio' in params:
            if params['ratio'] not in ('1:1', '4:3', '3:4', '16:9', '9:16'):
                raise ValueError('裁剪比例不支持')
            return params
        rect = params.get('rect')
        if not isinstance(rect, dict) or set(rect) != {'x', 'y', 'width', 'height'}:
            raise ValueError('裁剪框无效')
        return {'rect': {k: number(v, 0 if k in ('x', 'y') else 1, 20000, True) for k, v in rect.items()}}
    if operation == 'rotate':
        value = number(params.get('angle'), -270, 270, True)
        if value % 90:
            raise ValueError('第一版旋转仅支持90度的倍数')
        return {'angle': value}
    if operation == 'flip':
        if params.get('direction') not in ('horizontal', 'vertical'):
            raise ValueError('翻转方向无效')
        return {'direction': params['direction']}
    if operation == 'resize':
        return {key: number(params.get(key), 32, 4096, True) for key in ('width', 'height')}
    prompt = params.get('prompt')
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 2000:
        raise ValueError('请填写1至2000字的修图要求')
    return {'prompt': prompt.strip()}


def local_edit(raw, operation, params):
    params = validate(operation, params)
    with Image.open(io.BytesIO(raw)) as opened:
        image = ImageOps.exif_transpose(opened).convert('RGBA')
    if operation == 'adjust':
        alpha = image.getchannel('A')
        color = image.convert('RGB')
        classes = {'brightness': ImageEnhance.Brightness, 'contrast': ImageEnhance.Contrast,
                   'saturation': ImageEnhance.Color, 'sharpness': ImageEnhance.Sharpness}
        for key in classes:
            if key in params:
                color = classes[key](color).enhance(1 + params[key])
        image = color.convert('RGBA'); image.putalpha(alpha)
    elif operation == 'crop':
        if 'rect' in params:
            rect = params['rect']; left, top = rect['x'], rect['y']
            right, bottom = left + rect['width'], top + rect['height']
            if right > image.width or bottom > image.height:
                raise ValueError('裁剪框超出图片范围')
        else:
            a, b = map(int, params['ratio'].split(':'))
            width = min(image.width, max(1, int(image.height * a / b)))
            height = min(image.height, max(1, int(image.width * b / a)))
            left, top = (image.width - width) // 2, (image.height - height) // 2
            right, bottom = left + width, top + height
        image = image.crop((left, top, right, bottom))
    elif operation == 'rotate':
        image = image.rotate(-params['angle'], expand=True)
    elif operation == 'flip':
        image = ImageOps.mirror(image) if params['direction'] == 'horizontal' else ImageOps.flip(image)
    elif operation == 'resize':
        image = image.resize((params['width'], params['height']), Image.Resampling.LANCZOS)
    else:
        raise ValueError('AI编辑需由云端Provider处理')
    result = io.BytesIO(); image.save(result, 'PNG')
    return result.getvalue()


class ImageJobs:
    def __init__(self, store, executor=None):
        self.store = store
        self.lock = threading.RLock()
        self.executor = executor or ThreadPoolExecutor(max_workers=2, thread_name_prefix='miniclaw-image')
        self.futures = {}
        # A previous process may have submitted a billable request. Never replay it.
        for record in store.image_jobs():
            if record['state'] in ACTIVE:
                record.update(state='failed', error='服务已重启，任务结果未确认；不会自动重新调用或计费', updated=time.time())
                store.put('image_jobs', record['id'], record, record['owner'])

    def get(self, owner, identifier):
        return self.public(self.store.get('image_jobs', identifier, owner))

    @staticmethod
    def public(record):
        return {key: value for key, value in record.items() if key not in ('owner', 'request_hash')}

    def history(self, owner):
        return {'images': [public(r) for r in self.store.images(owner)],
                'jobs': [self.public(r) for r in self.store.image_jobs(owner)[:100]], 'cloud': provider_status()}

    def submit(self, owner, source_id, operation, params, request_id, on_accept=None):
        if not isinstance(source_id, str) or not re.fullmatch(r'[a-f0-9]{32}', source_id):
            raise ValueError('图片ID无效，请选择本对话已上传的图片')
        if not isinstance(request_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{8,80}', request_id):
            raise ValueError('修图请求标识无效')
        params = validate(operation, params)
        source = self.store.get('attachments', source_id, owner)
        if source.get('kind') != 'image':
            raise ValueError('请先上传图片')
        identifier = hashlib.sha256((owner + ':' + request_id).encode()).hexdigest()[:32]
        request_hash = hashlib.sha256(json.dumps([source_id, operation, params], sort_keys=True).encode()).hexdigest()
        with self.lock:
            try:
                existing = self.store.get('image_jobs', identifier, owner)
            except ValueError:
                existing = None
            if existing:
                if existing['request_hash'] != request_hash:
                    raise ValueError('同一请求标识不能用于不同修图参数')
                return self.public(existing)
            active = [j for j in self.store.image_jobs() if j['state'] in ACTIVE]
            if any(j['owner'] == owner for j in active):
                raise ValueError('本对话已有修图任务，请等待完成或取消')
            if len(active) >= 8:
                raise ValueError('修图服务繁忙，请稍后再试')
            if operation == 'ai_edit' and not provider_status()['configured']:
                raise ValueError('未配置百炼DASHSCOPE_API_KEY；本地修图仍可使用')
            if on_accept:
                on_accept()
            now = time.time()
            record = dict(id=identifier, owner=owner, source=public(source), operation=operation, params=params,
                          request_hash=request_hash, state='queued', created=now, updated=now,
                          provider='dashscope' if operation == 'ai_edit' else 'local',
                          root_id=source.get('root_id', source['id']))
            self.store.put('image_jobs', identifier, record, owner)
            future = self.executor.submit(self._execute, owner, identifier)
            self.futures[identifier] = future
            future.add_done_callback(lambda _: self.futures.pop(identifier, None))
        return self.get(owner, identifier)

    def _execute(self, owner, identifier):
        try:
            with self.lock:
                record = self.store.get('image_jobs', identifier, owner)
                if record['state'] != 'queued': return
                record.update(state='running', updated=time.time())
                self.store.put('image_jobs', identifier, record, owner)
            source = self.store.get('attachments', record['source']['id'], owner)
            raw = __import__('pathlib').Path(source['path']).read_bytes()
            provider_id = None
            if record['operation'] == 'ai_edit':
                result, provider_id = edit_image(raw, source['mime'], record['params']['prompt'])
            else:
                result = local_edit(raw, record['operation'], record['params'])
            with self.lock:
                latest = self.store.get('image_jobs', identifier, owner)
                if latest['state'] != 'running': return
                output = upload(self.store, owner, 'edit-' + identifier[:8] + '.png', base64.b64encode(result).decode())
                stored = self.store.get('attachments', output['id'], owner)
                stored.update(root_id=record['root_id'], parent_id=source['id'], image_job_id=identifier)
                self.store.put('attachments', stored['id'], stored, owner)
                latest.update(state='succeeded', output=output, updated=time.time(), provider_request_id=provider_id)
                self.store.put('image_jobs', identifier, latest, owner)
        except Exception as error:
            with self.lock:
                record = self.store.get('image_jobs', identifier, owner)
                if record['state'] != 'running': return
                # Only our bounded validation errors are suitable for product UI.
                message = str(error) if isinstance(error, ValueError) else '修图处理失败，原图已保留'
                record.update(state='failed', error=message, updated=time.time())
                self.store.put('image_jobs', identifier, record, owner)

    def wait(self, owner, identifier, seconds=15):
        future = self.futures.get(identifier)
        if future:
            try: future.result(timeout=seconds)
            except TimeoutError: pass
        return self.get(owner, identifier)

    def cancel(self, owner, identifier):
        with self.lock:
            record = self.store.get('image_jobs', identifier, owner)
            if record['state'] in ACTIVE:
                record.update(state='canceled', updated=time.time(), error='已取消本地结果接收；已提交的云端请求可能仍计费')
                self.store.put('image_jobs', identifier, record, owner)
            return self.public(record)


_service = None


def set_service(service):
    global _service
    _service = service


def image_tool(name, args, session_id):
    from tui_gateway import server
    try:
        if _service is None or not session_id:
            raise ValueError('修图工具仅支持本机Web工作台的运行会话')
        session = next((s for s in server._sessions.values() if s.get('session_key') == session_id
                        or getattr(s.get('agent'), 'session_id', None) == session_id), None)
        if not session:
            raise ValueError('修图会话不可用')
        agent = session.get('agent')
        if name not in {d['function']['name'] for d in getattr(agent, 'tools', [])}:
            raise ValueError('本对话未加载此修图工具')
        owner = session['session_key']
        if not isinstance(args, dict): raise ValueError('工具参数无效')
        if name == 'miniclaw_image_list':
            if args: raise ValueError('图片列表无需参数')
            result = _service.history(owner)
            result['images'] = result['images'][:20]
            result['jobs'] = result['jobs'][:10]
        elif name == 'miniclaw_image_status':
            if set(args) != {'job_id'}: raise ValueError('需要job_id')
            result = _service.wait(owner, args['job_id'])
        else:
            if set(args) != {'source_id', 'operation', 'params', 'request_id'}:
                raise ValueError('需要图片ID、操作、参数和请求标识')
            result = _service.submit(owner, args['source_id'], args['operation'], args['params'], args['request_id'])
            result = _service.wait(owner, result['id'])
        return json.dumps({'success': result.get('state') not in ('failed', 'canceled'), **result}, ensure_ascii=False)
    except (ValueError, OSError, KeyError, TypeError) as error:
        message = str(error) if isinstance(error, ValueError) else '修图请求无效，请核对图片ID、工具配置与参数'
        return json.dumps({'success': False, 'error': message}, ensure_ascii=False)
