"""Read-only, owned canvas references and immutable per-turn image snapshots."""
import base64
import re
from pathlib import Path

from .attachments import decode_upload

MAX_REFERENCES = 6
MAX_PIXELS = 8


def resolve_references(studio, workspace, state, identifiers, owner):
    if not isinstance(identifiers, list) or len(identifiers) > MAX_REFERENCES or any(not isinstance(i, str) for i in identifiers) or len(set(identifiers)) != len(identifiers):
        raise ValueError('画布引用无效，最多引用6项，请移除重复项')
    assets = {a['id']: a for a in state['assets']}
    objects = {o['id']: (kind, o) for kind, rows in [('image', state['assets']), ('shot', state['shots']), ('note', state['notes'])] for o in rows}
    snapshots, paths, cache = [], [], {}

    def image(asset):
        file = asset.get('file', '')
        if file in cache:
            return {**cache[file], 'id': asset['id'], 'name': asset['name']}
        if len(paths) >= MAX_PIXELS:
            raise ValueError('本轮引用图片超过8张，请减少镜头或参考图')
        if file in {'source.png', 'macro.png', 'hero.png', 'frame-end.png'}:
            raw, name = (studio.folder / file).read_bytes(), file
        elif re.fullmatch(r'data:image/(?:png|jpeg|webp);base64,[a-zA-Z0-9+/=]+', file):
            ext = {'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp'}[file[5:].split(';')[0]]
            raw, name = base64.b64decode(file.split(',', 1)[1]), 'image.' + ext
        elif re.fullmatch(r'/studio/media/objects/[a-f0-9]{64}', file):
            identifier = file.rsplit('/', 1)[1]
            with studio.store.connect() as db:
                if not db.execute('SELECT 1 FROM media_grants WHERE scope=? AND object_id=?', (workspace, identifier)).fetchone():
                    raise ValueError('引用图片不属于该工作区')
            obj = studio.store.media.get(identifier)
            ext = {'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp'}.get(obj['mime'])
            if not ext:
                raise ValueError('引用素材不是图片')
            raw, name = studio.store.media.materialize(identifier).read_bytes(), 'image.' + ext
        elif re.fullmatch(r'/api/precision/projects/[a-f0-9]{32}/assets/[a-f0-9]{32}', file):
            parts = file.split('/')
            if studio.canvas.get(parts[4])['chat_id'] != owner:
                raise ValueError('引用图片不属于当前对话')
            raw, name = Path(studio.canvas.asset(parts[4], parts[6])['path']).read_bytes(), 'image.png'
        else:
            raise ValueError('引用图片来源已失效，请重新加入画布')
        raw, kind, mime, _ = decode_upload(name, base64.b64encode(raw).decode())
        if kind != 'image':
            raise ValueError('引用素材不是图片')
        obj = studio.store.media.put_bytes(raw, mime)
        with studio.store.connect() as db:
            db.execute('INSERT OR IGNORE INTO media_grants VALUES (?,?)', (workspace, obj['id']))
        path = str(studio.store.media.materialize(obj['id']))
        if path not in paths:
            paths.append(path)
        cache[file] = {'file': '/studio/media/objects/' + obj['id'], 'image_index': paths.index(path) + 1}
        return {**cache[file], 'id': asset['id'], 'name': asset['name']}

    for identifier in identifiers:
        if identifier not in objects:
            raise ValueError('引用对象已删除，请移除后重新引用')
        kind, node = objects[identifier]
        snapshot = {'id': identifier, 'name': node.get('name', node.get('title', '创意')), 'kind': kind, 'images': []}
        if kind == 'image':
            snapshot['images'] = [image(node)]
        elif kind == 'shot':
            snapshot['text'] = node.get('prompt', '')
            snapshot['images'] = [image(assets[i]) for i in studio.shot_inputs(node) if i in assets]
        else:
            snapshot['text'] = node.get('text', '')
        snapshots.append(snapshot)
    return snapshots, paths
