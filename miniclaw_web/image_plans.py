"""Bounded editor proposals, shared by Chat and UI. Proposals never execute tools."""

import copy
import json
import time

from PIL import Image, ImageChops, ImageOps

from .canvas_document import ensure_unlocked, identifier, number, pixels, png, validate
from .images import local_edit, validate as validate_edit
from .store import digest

LABELS = {
    'adjust': '调整光色', 'flip': '翻转图片', 'move': '移动图层',
    'scale': '缩放图层', 'rotate': '旋转图层', 'opacity': '调整透明度',
    'visible': '显示或隐藏图层', 'text': '修改文字', 'reorder': '调整层级',
    'crop_canvas': '裁剪画面', 'resize_canvas': '调整画布尺寸',
    'background': '调整底色', 'split_subject': '拆分主体与背景',
    'replace_background': '保留主体换纯色背景', 'ai_edit': '生成AI候选',
}


def checked_steps(steps):
    if not isinstance(steps, list) or not 1 <= len(steps) <= 6:
        raise ValueError('修改方案需要1到6步')
    checked = []
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or set(step) != {'action', 'params'}:
            raise ValueError('步骤只接受action和params')
        action, params = step['action'], step['params']
        if not isinstance(action, str) or action not in LABELS or not isinstance(params, dict):
            raise ValueError('该修图动作尚未支持')
        if action in ('adjust', 'flip'):
            params = validate_edit(action, params)
        else:
            keys = {
                'move': {'x', 'y'}, 'scale': {'scale_x', 'scale_y'}, 'rotate': {'angle'},
                'opacity': {'opacity'}, 'visible': {'visible'}, 'text': {'text'},
                'reorder': {'position'}, 'crop_canvas': {'x', 'y', 'width', 'height'},
                'resize_canvas': {'width', 'height'}, 'background': {'color'},
                'split_subject': set(), 'replace_background': {'color'}, 'ai_edit': {'prompt', 'region'},
            }[action]
            if set(params) != keys:
                raise ValueError('修改方案参数不完整或有多余字段')
            params = copy.deepcopy(params)
            ranges = {
                'move': {'x': (-8192, 8192), 'y': (-8192, 8192)},
                'scale': {'scale_x': (.02, 20), 'scale_y': (.02, 20)},
                'rotate': {'angle': (-360, 360)}, 'opacity': {'opacity': (0, 1)},
                'reorder': {'position': (0, 39)},
                'crop_canvas': {'x': (0, 4096), 'y': (0, 4096), 'width': (16, 4096), 'height': (16, 4096)},
                'resize_canvas': {'width': (16, 4096), 'height': (16, 4096)},
            }.get(action, {})
            for key, (lo, hi) in ranges.items():
                number(params[key], lo, hi)
                if action in ('reorder', 'crop_canvas', 'resize_canvas') and type(params[key]) is not int:
                    raise ValueError('画面尺寸与层级需要整数')
            if action == 'visible' and type(params['visible']) is not bool:
                raise ValueError('显示状态需要布尔值')
            if action == 'text' and (not isinstance(params['text'], str) or len(params['text']) > 2000 or '\0' in params['text']):
                raise ValueError('文字最多2000字，不能包含空字符')
            if action in ('background', 'replace_background'):
                import re
                if not isinstance(params['color'], str) or not re.fullmatch(r'#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?', params['color']):
                    raise ValueError('底色需要十六进制RGB或RGBA')
            if action == 'ai_edit':
                prompt = params['prompt']
                if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 2000 or '\0' in prompt:
                    raise ValueError('修图要求需要1到2000字')
                if type(params['region']) is not bool:
                    raise ValueError('区域范围无效')
                if index != len(steps) - 1 or (params['region'] and len(steps) != 1):
                    raise ValueError('AI步骤只能排最后；选区AI请单独提案以保留选区')
        if action == 'split_subject' and any(s['action'] == action for s in checked):
            raise ValueError('同一方案只拆层一次')
        checked.append({'action': action, 'params': params, 'label': LABELS[action]})
    return checked


class ImagePlans:
    def __init__(self, canvas):
        self.canvas = canvas
        with canvas.store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS canvas_plans (id TEXT PRIMARY KEY, project TEXT NOT NULL, data TEXT NOT NULL)')

    def _read(self, db, project, plan_id):
        row = db.execute('SELECT data FROM canvas_plans WHERE id=? AND project=?', (plan_id, project)).fetchone()
        if not row:
            raise ValueError('方案不属于当前图片项目')
        return json.loads(row[0])

    @staticmethod
    def _write(db, plan):
        db.execute('UPDATE canvas_plans SET data=? WHERE id=? AND project=?',
                   (json.dumps(plan, ensure_ascii=False), plan['id'], plan['project']))

    @staticmethod
    def public(plan):
        return {k: v for k, v in plan.items() if k not in ('document', 'selection_hash')}

    def get(self, project, plan_id):
        self.canvas.get(project)
        with self.canvas.store.connect() as db:
            return self.public(self._read(db, project, plan_id))

    def list(self, project):
        self.canvas.get(project)
        with self.canvas.store.connect() as db:
            return [self.public(json.loads(r[0])) for r in db.execute(
                'SELECT data FROM canvas_plans WHERE project=? ORDER BY rowid DESC LIMIT 20', (project,))]

    def _guard(self, plan, revision):
        row = self.canvas.get(plan['project'])
        self.canvas._cas(row, revision)
        if row['archived'] or row['chat_id'] != plan['chat_id']:
            raise ValueError('项目归属或关联聊天已变化，请重新提案')
        if revision != plan['revision']:
            from .canvas import Conflict
            raise Conflict('工作图已变化，旧方案不能执行；请重新提案')
        if plan.get('selection_id') and digest(json.dumps(self.canvas.selection(plan['project']), sort_keys=True)) != plan['selection_hash']:
            from .canvas import Conflict
            raise Conflict('主体或区域选区已变化，请重新提案')
        return row

    def propose(self, project, revision, layer_id, goal, preserve, steps):
        for value in (goal, preserve):
            if not isinstance(value, str) or len(value) > 1000 or '\0' in value:
                raise ValueError('目标和保留项最多1000字')
        if not goal.strip():
            raise ValueError('请说明这次修改目标')
        steps = checked_steps(steps)
        split_index = next((i for i, s in enumerate(steps) if s['action'] == 'split_subject'), None)
        if split_index is not None and split_index != 0:
            raise ValueError('拆层需要先使用原始主体选区，请把拆层排第一步')
        if any(s['action'] == 'replace_background' for s in steps):
            if steps[0]['action'] != 'replace_background' or any(s['action'] in ('adjust', 'flip', 'split_subject', 'replace_background', 'ai_edit') for s in steps[1:]):
                raise ValueError('保留主体换背景必须排第一步，之后只允许排版修改')
        if steps[-1]['action'] == 'ai_edit' and len(steps[-1]['params']['prompt']) + (len(preserve.strip()) + 7 if preserve.strip() else 0) > 2000:
            raise ValueError('修改要求与保留项合计超过2000字')
        with self.canvas.lock, self.canvas.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self.canvas._get(db, project)
            self.canvas._cas(row, revision)
            layer = next((l for l in row['document']['layers'] if l['id'] == layer_id), None)
            if not layer:
                raise ValueError('本轮目标图层不存在')
            selection = self.canvas.selection(project)
            needs_selection = any(s['action'] in ('split_subject', 'replace_background') or s['action'] == 'ai_edit' and s['params']['region'] for s in steps)
            if needs_selection:
                self.canvas._selection(project, row, layer, selection['id'] if selection else 'missing')
            plan = dict(id=identifier(), project=project, revision=revision, input_revision=revision,
                        chat_id=row['chat_id'], layer_id=layer_id, goal=goal.strip(), preserve=preserve.strip(),
                        steps=steps, state='proposed', created=time.time(),
                        selection_id=selection['id'] if needs_selection else None,
                        selection_hash=digest(json.dumps(selection, sort_keys=True)))
            # Validate geometry, layer type, locks and bounds before persisting; no assets yet.
            self._build(plan, row, materialize=False)
            db.execute('INSERT INTO canvas_plans VALUES (?,?,?)', (plan['id'], project, json.dumps(plan, ensure_ascii=False)))
            return self.public(plan)

    def _build(self, plan, row, materialize=True):
        document = copy.deepcopy(row['document'])
        layer = next(l for l in document['layers'] if l['id'] == plan['layer_id'])
        for step in plan['steps']:
            action, p = step['action'], step['params']
            if layer['locked'] and action not in ('crop_canvas', 'resize_canvas', 'background'):
                raise ValueError('请先解锁目标图层')
            if action == 'ai_edit':
                if layer['kind'] != 'image' or layer['locked'] or not layer['visible']:
                    raise ValueError('AI候选需要未锁定的图片图层')
                continue
            if action in ('adjust', 'flip', 'split_subject', 'replace_background'):
                if layer['kind'] != 'image' or layer['locked']:
                    raise ValueError('该修改需要未锁定的图片图层')
                if action == 'replace_background':
                    mask = self.canvas._selection(plan['project'], row, layer, plan['selection_id']).point(lambda v: 255 if v >= 128 else 0)
                    if not mask.getbbox() or not ImageOps.invert(mask).getbbox():
                        raise ValueError('主体选区需要同时留下主体与背景')
                if materialize:
                    source = pixels(layer, lambda a: self.canvas.asset(plan['project'], a))
                    if action == 'replace_background':
                        output = Image.composite(source, Image.new('RGBA', source.size, p['color']), mask)
                        asset = self.canvas.add_asset(plan['project'], png(output), 'subject-background.png')
                        layer['asset_id'] = asset['id']
                    elif action == 'split_subject':
                        mask = self.canvas._selection(plan['project'], row, layer, plan['selection_id']).point(lambda v: 255 if v >= 128 else 0)
                        if not mask.getbbox() or not ImageOps.invert(mask).getbbox():
                            raise ValueError('主体选区需要同时留下主体与背景')
                        subject, background = source.copy(), source.copy()
                        subject.putalpha(ImageChops.multiply(source.getchannel('A'), mask))
                        background.putalpha(ImageChops.multiply(source.getchannel('A'), ImageOps.invert(mask)))
                        foreground = self.canvas.add_asset(plan['project'], png(subject), 'subject.png')
                        back = self.canvas.add_asset(plan['project'], png(background), 'background.png')
                        subject_layer = {**layer, 'id': identifier(), 'name': '保留主体', 'asset_id': foreground['id']}
                        document['layers'].insert(document['layers'].index(layer) + 1, subject_layer)
                        layer.update(name='可编辑背景', asset_id=back['id'])
                    else:
                        output = self.canvas.add_asset(plan['project'], local_edit(png(source), action, p), 'plan-edit.png')
                        layer['asset_id'] = output['id']
                elif action == 'split_subject':
                    document['layers'].insert(document['layers'].index(layer) + 1, {**layer, 'id': identifier()})
            elif action == 'move':
                layer.update(p)
            elif action == 'scale':
                layer.update(p)
            elif action == 'rotate':
                layer['rotation'] = p['angle']
            elif action in ('opacity', 'visible'):
                layer.update(p)
            elif action == 'text':
                if layer['kind'] != 'text':
                    raise ValueError('请先选中要修改的文字图层')
                layer.update(p)
            elif action == 'reorder':
                if p['position'] >= len(document['layers']):
                    raise ValueError('层级位置超出画布图层数')
                document['layers'].remove(layer)
                document['layers'].insert(p['position'], layer)
            elif action == 'crop_canvas':
                if p['x'] + p['width'] > document['width'] or p['y'] + p['height'] > document['height']:
                    raise ValueError('裁剪范围超出当前画面')
                for l in document['layers']:
                    l['x'] -= p['x']; l['y'] -= p['y']
                document.update(width=p['width'], height=p['height'])
            elif action == 'resize_canvas':
                document.update(p)
            elif action == 'background':
                document['background'] = p['color']
        document = validate(document, lambda a: self.canvas.asset(plan['project'], a))
        ensure_unlocked(row['document'], document)
        return document

    def preview(self, project, plan_id, revision):
        with self.canvas.lock:
            with self.canvas.store.connect() as db:
                plan = self._read(db, project, plan_id)
            if plan['state'] not in ('proposed', 'ready'):
                raise ValueError('该方案已应用或取消')
            row = self._guard(plan, revision)
            if all(s['action'] == 'ai_edit' for s in plan['steps']):
                raise ValueError('AI方案请直接生成候选，模型结果不能提前预览')
            if plan['state'] == 'proposed':
                plan['document'] = self._build(plan, row)
                plan['state'] = 'ready'
                with self.canvas.store.connect() as db:
                    self._write(db, plan)
            return self.canvas.preview(project, revision, plan['document'])

    def apply(self, project, plan_id, revision):
        with self.canvas.lock:
            clarification_service = getattr(self.canvas, 'clarifications', None)
            if clarification_service: clarification_service.guard_manual(project=project)
            with self.canvas.store.connect() as db:
                plan = self._read(db, project, plan_id)
            self._guard(plan, revision)
            if plan['state'] != 'ready':
                raise ValueError('请先预览本地修改')
            return self.canvas.save(project, revision, plan['document'], '应用修改方案', plan_id=plan_id)

    def generate(self, project, plan_id, revision):
        with self.canvas.lock:
            with self.canvas.store.connect() as db:
                plan = self._read(db, project, plan_id)
            if plan['state'] == 'canceled':
                raise ValueError('方案已取消')
            if plan.get('job_id'):
                return self.canvas.job(project, plan['job_id'])
            row = self._guard(plan, revision)
            if plan['steps'][-1]['action'] != 'ai_edit' or plan['state'] not in ('proposed', 'prepared'):
                raise ValueError('请先应用本地预览，再生成最后的AI候选')
            if plan['state'] == 'proposed' and len(plan['steps']) != 1:
                raise ValueError('请先预览并应用本地修改')
            p = plan['steps'][-1]['params']
            prompt = (p['prompt'] + '\n必须保留：' + plan['preserve']) if plan['preserve'] else p['prompt']
            if len(prompt) > 2000:
                raise ValueError('修改要求与保留项合计超过2000字，请精简后重新提案')
            job = self.canvas.submit(project, revision, plan['layer_id'], prompt,
                                     'image-plan-' + plan['id'], p['region'],
                                     selection_id=plan['selection_id'] if p['region'] else None,
                                     visible_only=True)
            plan.update(state='submitted', job_id=job['id'])
            with self.canvas.store.connect() as db:
                self._write(db, plan)
            return job

    def cancel(self, project, plan_id):
        with self.canvas.lock, self.canvas.store.connect() as db:
            plan = self._read(db, project, plan_id)
            if plan.get('job_id'):
                # Close this read connection before Canvas.cancel's write transaction.
                job_id = plan['job_id']
            else:
                job_id = None
            plan['state'] = 'canceled'
            self._write(db, plan)
        if job_id:
            job = self.canvas.job(project, job_id)
            if job['state'] in ('queued', 'running'):
                self.canvas.cancel(project, job_id)
        return self.public(plan)
