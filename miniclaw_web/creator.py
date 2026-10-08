"""Fixed personal creation tasks, immutable media and one local render queue."""
import copy
import hashlib
import io
import json
import re
import shutil
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

from .canvas import Conflict
from .overlay import parse_srt
from .video import MAX_MEDIA, binaries, command, execute, font_path, probe, validated_document
from . import storyboard, narrated

SLOTS = {'video': ('.mp4', '.mov', '.webm'), 'overlay': ('.mov',), 'srt': ('.srt',), 'plan': ('.json',), 'cover': ('.png', '.jpg', '.jpeg', '.webp')}
IMAGE_SLOTS = ('cover', 'detail', 'scene')
SLOTS.update({slot: SLOTS['cover'] for slot in IMAGE_SLOTS})
SLOTS['source'] = SLOTS['cover']
UPLOAD_IMAGE_SLOTS = (*IMAGE_SLOTS, 'source')
BRIEF_FIELDS = {'facts': 8000, 'selling_points': 4000, 'audience': 1000, 'style': 2000, 'constraints': 2000}
TEXT_FIELDS = {'name': 80, **BRIEF_FIELDS, 'script': 12000, 'caption': 4000, 'provenance': 4000}


def candidate_format(node):
    """App-owned reply contract; proposals still require explicit review and CAS."""
    if node == 'brief':
        return ('\n创作依据候选交付约定：本轮整理或修改创作依据时，先简短解释建议与待确认项，'
                '末尾给一个 creator-brief 代码块，JSON仅包含facts、selling_points、audience、style、constraints五个字符串字段。'
                '分别上限8000、4000、1000、2000、2000字，建议每项不超过350字。facts只写资料中有依据的商品事实及未知项，'
                '不要混入尺寸编辑记录、已有稿件或流程指令；购买理由和场景设想标为建议。候选不能直接写入项目，用户会预览确认。'
                '普通问答无需给候选。')
    if node == 'script':
        return ('\n口播候选交付约定：本轮生成或改写主稿时，将唯一主稿放入spoken-script代码块，仅放要朗读的文字；'
                '备选、分镜与说明放在块外。普通问答无需该块。')
    if node == 'video':
        return ('\n视频协作约定：在Chat讨论分镜、节奏与素材缺口，使用本项目已采用主稿。'
                '右侧视频面板负责素材上传、制作方式、配音与合成。当前没有自动视频合成工具；'
                '不得声称已执行合成或生成了成片，引导用户核对素材后点击合成。')
    return ''


def signature(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class Creator:
    def __init__(self, store, root, executor=None):
        self.store, self.root = store, Path(root)
        self.folder = store.home / 'creator'
        self.folder.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix='creator-video')
        with store.connect() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS creator_projects (id TEXT PRIMARY KEY, data TEXT NOT NULL); CREATE TABLE IF NOT EXISTS creator_jobs (id TEXT PRIMARY KEY, project TEXT NOT NULL, data TEXT NOT NULL);')
            for identifier, raw in db.execute('SELECT id,data FROM creator_jobs').fetchall():
                job = json.loads(raw)
                if job['state'] in ('queued', 'running'):
                    job.update(state='failed', error='服务重启，合成未完成；请手动重做，不自动重放')
                    self._save_job(db, job)

    @staticmethod
    def _save(db, p):
        db.execute('INSERT OR REPLACE INTO creator_projects VALUES (?,?)', (p['id'], json.dumps(p, ensure_ascii=False)))

    @staticmethod
    def _save_job(db, j):
        db.execute('INSERT OR REPLACE INTO creator_jobs VALUES (?,?,?)', (j['id'], j['project'], json.dumps(j, ensure_ascii=False)))

    def _get(self, db, identifier):
        row = db.execute('SELECT data FROM creator_projects WHERE id=?', (identifier,)).fetchone()
        if not row: raise ValueError('创作任务不存在')
        p = json.loads(row[0])
        for field in BRIEF_FIELDS: p.setdefault(field, '')
        return p

    def create(self, name='新创作任务'):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80: raise ValueError('任务名需要1–80字')
        p = dict(id=uuid.uuid4().hex, name=name.strip(), **{field: '' for field in BRIEF_FIELDS}, script='', caption='', provenance='', revision=0,
                 mode='portrait', method='plan', assets={}, outputs=[], packages=[], updated=time.time())
        with self.lock, self.store.connect() as db: self._save(db, p)
        return self.get(p['id'])

    @staticmethod
    def render_key(p):
        if p['method'] == 'narrated':
            return signature({'video':p['assets'].get('video',{}).get('id'),'script':p['script'],'mode':p['mode'],'method':p['method'],
                              'recipe':'intact-footage-narration-v2','keep_source_audio':p.get('keep_source_audio',False),'speech':{k:v for k,v in storyboard.settings(p.get('speech_style','standard')).items() if k!='configured'}})
        if p['method'] == 'storyboard':
            return signature({'assets': {s: p['assets'].get(s, {}).get('id') for s in IMAGE_SLOTS}, 'script': p['script'], 'mode': p['mode'], 'method': p['method'], 'recipe': 'photo-film-v2-normalized', 'speech': {k:v for k,v in storyboard.settings(p.get('speech_style','standard')).items() if k != 'configured'}})
        slots = ('video', 'srt', 'plan') if p['method'] == 'plan' else ('video', 'overlay')
        return signature({'assets': {s: p['assets'].get(s, {}).get('id') for s in slots}, 'mode': p['mode'], 'method': p['method']})

    def get(self, identifier):
        with self.store.connect() as db:
            p = self._get(db, identifier)
            p['jobs'] = [json.loads(r[0]) for r in db.execute('SELECT data FROM creator_jobs WHERE project=? ORDER BY rowid DESC LIMIT 20', (identifier,))]
        key = self.render_key(p)
        for o in p['outputs']: o['current'] = o['render_key'] == key
        package_key = self.package_key(p)
        for z in p['packages']: z['current'] = z['package_key'] == package_key
        p['steps'] = {'facts': bool(p['facts'].strip()), 'script': bool(p['script'].strip()), 'cover': 'cover' in p['assets'],
                      'video': any(o['current'] for o in p['outputs']), 'package': any(z['current'] for z in p['packages'])}
        basis = p.get('adopted_basis', {})
        p['flow'] = {
            'brief': 'ready' if p['facts'].strip() else 'empty',
            **{node: 'empty' if not present else 'adopted' if basis.get(node) == self.node_basis(p, node) else 'review'
               for node, present in (('cover', 'cover' in p['assets']), ('script', bool(p['script'].strip())))},
        }
        return p

    @staticmethod
    def node_basis(p, node):
        brief = signature({field: p.get(field, '') for field in BRIEF_FIELDS})
        if node == 'brief': return brief
        inputs = {'brief': brief, 'source': p['assets'].get('source', {}).get('id')}
        if node in ('script', 'video'): inputs['cover'] = p['assets'].get('cover', {}).get('id')
        if node == 'video': inputs.update(script=p['script'], render_key=Creator.render_key(p))
        return signature(inputs)

    def turn_context(self, context, owner):
        if not isinstance(context, dict) or set(context) != {'project_id', 'node'}:
            raise ValueError('创作上下文需要项目ID与节点')
        if not isinstance(context['project_id'], str) or context['node'] not in ('brief', 'cover', 'script', 'video'):
            raise ValueError('创作节点无效')
        p = self.get(context['project_id'])
        if p.get('chat_id') != owner: raise ValueError('创作项目未关联当前聊天，请从项目重新进入')
        snapshot = dict(project_id=p['id'], revision=p['revision'], node=context['node'], basis=self.node_basis(p, context['node']))
        data = {**snapshot, 'name': p['name'], 'brief': {f: p[f] for f in BRIEF_FIELDS}, 'script': p['script'], 'flow': p['flow'],
                'assets': {slot: {k: v for k, v in asset.items() if k in ('id', 'name', 'sha256', 'width', 'height')}
                           for slot, asset in p['assets'].items() if slot in UPLOAD_IMAGE_SLOTS}}
        if context['node'] == 'video':
            data['video'] = {k: p.get(k) for k in ('method', 'mode', 'speech_style', 'keep_source_audio')}
            data['video']['materials'] = {slot: {k: v for k, v in asset.items() if k in ('id', 'name', 'duration', 'audio')}
                                          for slot, asset in p['assets'].items() if slot not in UPLOAD_IMAGE_SLOTS}
            data['video']['has_current_output'] = p['steps']['video']
        return snapshot, data

    def link_chat(self, identifier, revision, owner):
        if not isinstance(owner, str) or not re.fullmatch(r'[\w-]{1,128}', owner): raise ValueError('对话标识无效')
        with self.lock, self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');p=self._get(db,identifier);self._cas(p,revision)
            p.update(chat_id=owner,revision=p['revision']+1,updated=time.time());self._save(db,p)
        return self.get(identifier)

    def list(self, owner=None):
        with self.store.connect() as db:
            projects = [json.loads(r[0]) for r in db.execute('SELECT data FROM creator_projects ORDER BY rowid DESC')]
        projects.sort(key=lambda p: p.get('updated', 0), reverse=True)
        if owner is not None:
            if not isinstance(owner, str) or not re.fullmatch(r'[\w-]{1,128}', owner): raise ValueError('对话标识无效')
            projects = [p for p in projects if p.get('chat_id') == owner]
        return [dict(id=p['id'], name=p['name'], updated=p['updated'], chat_id=p.get('chat_id'),
                     preview=p['assets'].get('cover') or p['assets'].get('source'), script_preview=p['script'][:100],
                     progress={'brief': bool(p['facts'].strip()), 'cover': 'cover' in p['assets'] and p.get('adopted_basis', {}).get('cover') == self.node_basis(p, 'cover'), 'script': bool(p['script'].strip()) and p.get('adopted_basis', {}).get('script') == self.node_basis(p, 'script'),
                               'video': any(o.get('render_key') == self.render_key(p) for o in p['outputs'])})
                for p in projects[:100]]

    def patch(self, identifier, params):
        if not isinstance(params, dict) or set(params) - set(TEXT_FIELDS) - {'revision', 'mode', 'method', 'remove', 'speech_style', 'keep_source_audio', 'confirm'}: raise ValueError('任务字段无效')
        with self.lock, self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            p = self._get(db, identifier)
            self._cas(p, params.get('revision'))
            script_edited = 'script' in params and (params['script'] != p['script'] or set(params) == {'revision', 'script'})
            for field, limit in TEXT_FIELDS.items():
                if field in params:
                    text = params[field]
                    if not isinstance(text, str) or len(text) > limit or '\0' in text or (field == 'name' and not text.strip()): raise ValueError(f'{field}内容为空或超过{limit}字')
                    p[field] = text
            if 'mode' in params:
                if params['mode'] not in ('portrait', 'landscape'): raise ValueError('视频比例无效')
                p['mode'] = params['mode']
            if 'method' in params:
                if params['method'] not in ('plan', 'overlay', 'storyboard', 'narrated'): raise ValueError('合成方式无效')
                p['method'] = params['method']
            if 'speech_style' in params:
                if not isinstance(params['speech_style'],str): raise ValueError('配音风格无效')
                storyboard.settings(params['speech_style']);p['speech_style']=params['speech_style']
            if 'keep_source_audio' in params:
                if type(params['keep_source_audio']) is not bool: raise ValueError('原声选项无效')
                p['keep_source_audio']=params['keep_source_audio']
            if 'remove' in params:
                if params['remove'] not in SLOTS: raise ValueError('素材类型无效')
                p['assets'].pop(params['remove'], None)
            if script_edited:
                p.setdefault('adopted_basis', {})['script'] = self.node_basis(p, 'script')
            if 'confirm' in params:
                node = params['confirm']
                if node not in ('cover', 'script') or not ('cover' in p['assets'] if node == 'cover' else p['script'].strip()):
                    raise ValueError('只能核对已有图片或口播稿')
                p.setdefault('adopted_basis', {})[node] = self.node_basis(p, node)
            p.update(revision=p['revision']+1, updated=time.time())
            self._save(db, p)
        return self.get(identifier)

    @staticmethod
    def _cas(p, revision):
        if type(revision) is not int or revision != p['revision']: raise Conflict('任务已变化，请刷新后重试；不会覆盖新内容')

    def project_folder(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch('[a-f0-9]{32}', identifier): raise ValueError('任务ID无效')
        folder = self.folder / identifier
        folder.mkdir(exist_ok=True)
        return folder

    def _budget(self, db, identifier, extra, exclude=None):
        folder = self.project_folder(identifier)
        used = sum(f.stat().st_size for f in folder.rglob('*') if f.is_file() and f != exclude)
        reserved = sum((512 if json.loads(r[0]).get('method') in ('storyboard','narrated') else 128)*1024*1024 for r in db.execute('SELECT data FROM creator_jobs WHERE project=?', (identifier,)) if json.loads(r[0])['state'] in ('queued','running'))
        if used + reserved + extra > 1024*1024*1024: raise ValueError('该任务达到1 GiB存储预算，请另建任务；旧版本保留')

    def capabilities(self):
        ffmpeg, ffprobe = binaries(self.root)
        return {'video': bool(ffmpeg and ffprobe), 'font': bool(font_path()), 'speech': storyboard.settings(), 'storyboard_min_images': 1, 'max_bytes': MAX_MEDIA, 'max_seconds': 180}

    def import_file(self, identifier, revision, slot, name, temp, source=None):
        if slot not in SLOTS or not isinstance(name, str) or name != Path(name).name or '/' in name or '\\' in name or len(name) > 160 or Path(name).suffix.lower() not in SLOTS[slot]: raise ValueError('素材文件名或类型无效')
        size = temp.stat().st_size
        limit = 64*1024 if slot in ('srt', 'plan') else 5*1024*1024 if slot in UPLOAD_IMAGE_SLOTS else MAX_MEDIA
        if not 0 < size <= limit: raise ValueError('素材为空或超过大小限制')
        info = {}
        if slot in ('srt', 'plan'):
            try: text = temp.read_text(encoding='utf-8-sig')
            except UnicodeError: raise ValueError('字幕与JSON需为UTF-8文本') from None
            if slot == 'srt': info['cues'] = len(parse_srt(text))
            else:
                try: json.loads(text)
                except ValueError: raise ValueError('JSON格式无效') from None
        elif slot in UPLOAD_IMAGE_SLOTS:
            try:
                with Image.open(temp) as im:
                    if im.format not in ('PNG', 'JPEG', 'WEBP') or im.width * im.height > 16_000_000: raise ValueError()
                    im.load(); info.update(width=im.width, height=im.height)
            except (OSError, ValueError, Image.DecompressionBombError): raise ValueError('封面需为可读取的PNG/JPEG/WebP，最多1600万像素') from None
            expected = {'.png': 'PNG', '.jpg': 'JPEG', '.jpeg': 'JPEG', '.webp': 'WEBP'}[Path(name).suffix.lower()]
            if im.format != expected: raise ValueError('图片内容与扩展名不一致，请按实际图片格式保存后再上传')
        else:
            _, ffprobe = binaries(self.root)
            if not ffprobe: raise ValueError('FFprobe未准备，请先配置本机视频工具')
            info = probe(temp, ffprobe)
            if slot == 'overlay' and not info['alpha']: raise ValueError('透明层需为带透明通道的MOV')
        if source is not None: info['source'] = source
        aid = uuid.uuid4().hex
        folder = self.project_folder(identifier)
        target = folder / (aid + Path(name).suffix.lower())
        with self.lock, self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            p = self._get(db, identifier); self._cas(p, revision)
            if slot == 'cover' and source is not None and p.get('chat_id') and source.get('owner') != p['chat_id']:
                raise ValueError('修图结果不属于当前项目聊天')
            # Disk budget includes replaced immutable files, not just current metadata.
            self._budget(db, identifier, size, exclude=temp)
            with temp.open('rb') as stream: sha = hashlib.file_digest(stream, 'sha256').hexdigest()
            temp.replace(target)
            p['assets'][slot] = dict(id=aid, name=name, bytes=size, file=target.name, sha256=sha, **info)
            if slot == 'cover': p.setdefault('adopted_basis', {})['cover'] = self.node_basis(p, 'cover')
            p.update(revision=p['revision']+1, updated=time.time()); self._save(db, p)
        return self.get(identifier)

    def adopt_cover(self, identifier, revision, owner, attachment):
        if not isinstance(owner, str) or not owner or not isinstance(attachment, str): raise ValueError('需要对话与图片标识')
        record = self.store.get('attachments', attachment, owner)
        if record.get('kind') != 'image': raise ValueError('只能采用图片作为封面')
        temp = self.project_folder(identifier) / ('adopt-' + uuid.uuid4().hex + '.tmp')
        try:
            shutil.copyfile(record['path'], temp)
            source = {'kind': 'canvas' if record.get('canvas_project_id') else 'chat-image', 'owner': owner, 'attachment': attachment}
            if record.get('canvas_project_id'): source['canvas_project_id'] = record['canvas_project_id']
            return self.import_file(identifier, revision, 'cover', record['name'], temp, source=source)
        finally: temp.unlink(missing_ok=True)

    def _asset_path(self, p, slot):
        a = p['assets'].get(slot)
        if not a: raise ValueError(f'缺少{slot}素材')
        return self.project_folder(p['id']) / a['file']

    def render(self, identifier, revision):
        ffmpeg, ffprobe = binaries(self.root)
        if not ffmpeg or not ffprobe: raise ValueError('FFmpeg/FFprobe未准备，Chat和修图仍可使用')
        with self.lock, self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            p = self._get(db, identifier); self._cas(p, revision)
            self._budget(db, identifier, (512 if p['method'] in ('storyboard','narrated') else 128)*1024*1024)
            if len(p['outputs']) >= 20: raise ValueError('本任务已有20份成片，请另建任务')
            if any(json.loads(r[0])['state'] in ('queued', 'running') for r in db.execute('SELECT data FROM creator_jobs')): raise Conflict('已有视频正在合成，请完成或取消后重试')
            if p['method'] in ('storyboard','narrated'):
                storyboard.lines(p['script'])
                if not storyboard.settings()['configured']: raise ValueError('未配置百炼语音Key')
                if not font_path(): raise ValueError('中文字体未准备')
                for slot in (tuple(s for s in IMAGE_SLOTS if s=='cover' or s in p['assets']) if p['method']=='storyboard' else ('video',)): self._asset_path(p, slot)
                if p['method']=='narrated' and p.get('keep_source_audio') and not p['assets']['video'].get('audio'): raise ValueError('镜头片没有原音轨，请关闭保留背景音')
            elif p['method'] == 'plan':
                self._asset_path(p, 'video')
                doc = validated_document(self._asset_path(p, 'plan').read_text(encoding='utf-8-sig'), self._asset_path(p, 'srt').read_text(encoding='utf-8-sig'))
                if not font_path(): raise ValueError('中文字体未准备')
                if max(c['end'] for c in doc['cards']) > p['assets']['video']['duration']+.15: raise ValueError('字幕动效超过视频时长')
            else:
                self._asset_path(p, 'video'); self._asset_path(p, 'overlay')
            job = dict(id=uuid.uuid4().hex, project=identifier, state='queued', render_key=self.render_key(p), method=p['method'], created=time.time(), revision=revision)
            self._save_job(db, job)
        try: self.executor.submit(self._run, job['id'], copy.deepcopy(p), ffmpeg, ffprobe)
        except RuntimeError:
            with self.store.connect() as db:
                job.update(state='failed', error='执行器不可用，请重新启动后重试'); self._save_job(db, job)
            raise ValueError('执行器不可用') from None
        return job

    def job(self, identifier, job_id):
        with self.store.connect() as db:
            row = db.execute('SELECT data FROM creator_jobs WHERE id=? AND project=?', (job_id, identifier)).fetchone()
            if not row: raise ValueError('任务结果不存在')
            return json.loads(row[0])

    def cancel(self, identifier, job_id):
        with self.lock, self.store.connect() as db:
            j = self.job(identifier, job_id)
            if j['state'] in ('queued', 'running'):
                j.update(state='canceled'); self._save_job(db, j)
        return j

    def _run(self, job_id, p, ffmpeg, ffprobe):
        work = self.project_folder(p['id']) / ('job-' + job_id); work.mkdir()
        output = work / 'video.mp4'
        try:
            with self.lock, self.store.connect() as db:
                j = self.job(p['id'], job_id)
                if j['state'] != 'queued': return
                j['state'] = 'running'; self._save_job(db, j)
            canceled = lambda: self.job(p['id'], job_id)['state'] != 'running'
            extra = {}
            if p['method'] in ('storyboard','narrated'):
                # Re-editing shots should not pay for identical narration again.
                # Reuse only this project's retained completed job WAVs, same model/voice/text.
                speech_cfg = {k:v for k,v in storyboard.settings(p.get('speech_style','standard')).items() if k != 'configured'}
                cached = {}
                for old in reversed(p['outputs']):
                    production = old.get('production', {})
                    if {k:v for k,v in production.get('speech', {}).items() if k != 'configured'} != speech_cfg: continue
                    for i, segment in enumerate(production.get('segments', [])):
                        source = self.project_folder(p['id']) / ('job-' + old['id']) / f'speech-{i}.wav'
                        requests = production.get('requests', [])
                        if source.is_file() and source.stat().st_size <= 8*1024*1024 and i < len(requests):
                            cached.setdefault(segment['text'], (source, requests[i]))
                def speaker(text, target, stop):
                    if stop(): raise ValueError('合成已取消')
                    if text in cached:
                        source, receipt = cached[text];shutil.copyfile(source, target)
                        return {**receipt, 'reused': True}
                    return storyboard.synthesize(text, target, stop, style=p.get('speech_style','standard'))
                if p['method']=='narrated':
                    extra=narrated.render(p,self._asset_path(p,'video'),ffmpeg,work,canceled,speaker=speaker)
                else:
                    extra = storyboard.render(p, {s: self._asset_path(p, s) for s in IMAGE_SLOTS if s in p['assets']}, ffmpeg, work, canceled, speaker=speaker)
            else:
                kwargs = {}
                if p['method'] == 'plan': kwargs['document'] = validated_document(self._asset_path(p, 'plan').read_text(encoding='utf-8-sig'), self._asset_path(p, 'srt').read_text(encoding='utf-8-sig'))
                else: kwargs.update(overlay=self._asset_path(p, 'overlay'), overlay_meta=p['assets']['overlay'])
                args = command(self._asset_path(p, 'video'), p['assets']['video'], output, work, ffmpeg, p['mode'], font=font_path(), **kwargs)
                execute(args, work, canceled=canceled)
            metadata = probe(output, ffprobe)
            with output.open('rb') as stream: sha = hashlib.file_digest(stream, 'sha256').hexdigest()
            with self.lock, self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                j = self.job(p['id'], job_id)
                if j['state'] != 'running': return
                current = self._get(db, p['id'])
                artifact = dict(id=job_id, name='video.mp4', file=str(output.relative_to(self.project_folder(p['id']))), bytes=output.stat().st_size, sha256=sha,
                                render_key=j['render_key'], method=p['method'], mode=p['mode'], created=time.time(), production=extra, **metadata)
                current['outputs'].append(artifact); current.update(revision=current['revision']+1, updated=time.time()); self._save(db, current)
                j.update(state='succeeded', output_id=job_id); self._save_job(db, j)
        except Exception as e:
            with self.lock, self.store.connect() as db:
                j = self.job(p['id'], job_id)
                if j['state'] in ('queued', 'running'):
                    j.update(state='failed', error=str(e) if isinstance(e, ValueError) else '本机视频处理失败，请检查工具与素材'); self._save_job(db, j)

    @staticmethod
    def package_key(p):
        current = next((o['id'] for o in reversed(p['outputs']) if o['render_key'] == Creator.render_key(p)), None)
        return signature({'output': current, 'texts': {f: p[f] for f in TEXT_FIELDS}, 'cover': p['assets'].get('cover', {}).get('id'), 'srt': p['assets'].get('srt', {}).get('id')})

    def package(self, identifier, revision):
        with self.lock, self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            p = self._get(db, identifier); self._cas(p, revision)
            output = next((o for o in reversed(p['outputs']) if o['render_key'] == self.render_key(p)), None)
            if not output: raise ValueError('没有当前素材对应的成片，请先合成')
            if not p['caption'].strip(): raise ValueError('请填写发布文案并保存')
            self._budget(db, identifier, output['bytes'] + sum(p['assets'].get(s,{}).get('bytes',0) for s in ('cover','srt')) + 256*1024)
            if len(p['packages']) >= 20: raise ValueError('本任务已有20份发布包，请另建任务')
            zid = uuid.uuid4().hex; target = self.project_folder(identifier) / (zid + '.zip')
            manifest = {'version': 1, 'status': 'ready_for_manual_publish', 'name': p['name'], 'revision': revision,
                        'created': time.time(), 'video': {k: v for k, v in output.items() if k != 'file'},
                        'materials': {slot: {k: v for k, v in a.items() if k != 'file'} for slot, a in p['assets'].items()},
                        'chat_id': p.get('chat_id'), 'provenance': p['provenance'], 'notes': '本包未向任何平台发布；请核对素材许可、内容事实、声音、字幕与封面。'}
            with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_STORED) as archive:
                archive.write(self.project_folder(identifier) / output['file'], 'video.mp4')
                for slot in ('cover', 'srt'):
                    if slot == 'srt' and output.get('production', {}).get('subtitle_file'):
                        archive.write(self.project_folder(identifier) / output['production']['subtitle_file'], 'srt.srt')
                        continue
                    if slot in p['assets']: archive.write(self._asset_path(p, slot), slot + Path(p['assets'][slot]['file']).suffix)
                for field in ('facts', 'script', 'caption'):
                    archive.writestr(field + '.txt', p[field])
                archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
            item = dict(id=zid, name='publish-package.zip', file=target.name, package_key=self.package_key(p), bytes=target.stat().st_size, created=time.time())
            p['packages'].append(item); p.update(revision=p['revision']+1, updated=time.time()); self._save(db, p)
        return self.get(identifier)

    def file(self, identifier, file_id):
        p = self.get(identifier)
        items = list(p['assets'].values()) + p['outputs'] + p['packages']
        a = next((v for v in items if v['id'] == file_id), None)
        if not a: raise ValueError('素材不属于当前任务')
        return self.project_folder(identifier) / a['file'], a['name']
