"""Original subtitle compiler targeting a small public OverlayDoc contract.

No renderer, source paths, arbitrary CSS, URLs or guessed timestamps are accepted.
"""
import re

KINDS = ('punch-pill', 'quote-lockup', 'type-shift')
TOOL = 'miniclaw_overlay_compile'
_store = None


def parse_srt(text):
    if not isinstance(text, str) or not text.strip() or len(text.encode('utf-8')) > 64 * 1024:
        raise ValueError('SRT需要非空UTF-8文本，最大64 KiB')
    blocks = re.split(r'\n[ \t]*\n', text.lstrip('\ufeff').replace('\r\n', '\n').strip())
    if len(blocks) > 500:
        raise ValueError('第一版最多500条字幕')
    cues, previous, indexes = [], 0, set()
    clock = r'(\d{2,3}):([0-5]\d):([0-5]\d)[,.](\d{3})'
    for ordinal, block in enumerate(blocks, 1):
        rows = block.splitlines()
        if len(rows) < 3 or not re.fullmatch(r'\d{1,6}', rows[0].strip()):
            raise ValueError(f'第{ordinal}条字幕缺少有效编号、时间或正文')
        index = int(rows[0].strip())
        if index < 1 or index in indexes:
            raise ValueError(f'第{ordinal}条字幕原编号无效或重复')
        indexes.add(index)
        match = re.fullmatch(clock + r'\s*-->\s*' + clock, rows[1].strip())
        body = '\n'.join(rows[2:]).strip()
        if not match or not body or len(body) > 1000 or any(ord(c) < 32 and c not in '\n\t' for c in body):
            raise ValueError(f'第{ordinal}条字幕时间格式或正文无效')
        values = [int(n) for n in match.groups()]
        start, end = [(values[i] * 3600 + values[i+1] * 60 + values[i+2]) * 1000 + values[i+3] for i in (0, 4)]
        if not 0 <= start < end <= 7_200_000 or start < previous:
            raise ValueError(f'第{ordinal}条字幕倒序、重叠或超出2小时范围')
        cues.append(dict(cue=ordinal, original_index=index, start=start / 1000, end=end / 1000, text=body))
        previous = end
    return cues


def compile_overlay(srt, cards):
    cues = parse_srt(srt)
    if not isinstance(cards, list) or not 1 <= len(cards) <= 32:
        raise ValueError('需要1至32张文字动效卡')
    ids, output = set(), []
    for n, card in enumerate(cards, 1):
        if not isinstance(card, dict) or set(card) != {'id', 'kind', 'cue_start', 'cue_end', 'params'}:
            raise ValueError(f'第{n}张卡字段无效，只接受id、kind、cue_start、cue_end、params')
        identifier, kind = card['id'], card['kind']
        if not isinstance(identifier, str) or not re.fullmatch(r'[\w-]{1,64}', identifier) or identifier in ids:
            raise ValueError(f'第{n}张卡id无效或重复')
        ids.add(identifier)
        if kind not in KINDS:
            raise ValueError(f'第{n}张卡类型不支持')
        a, b = card['cue_start'], card['cue_end']
        if type(a) is not int or type(b) is not int or not 1 <= a <= b <= len(cues):
            raise ValueError(f'第{n}张卡字幕序号越界，请使用文件顺序的cue编号')
        start, end = cues[a-1]['start'], cues[b-1]['end']
        if not .6 <= end - start <= 30:
            raise ValueError(f'第{n}张卡需覆盖0.6至30秒的真实字幕')
        params = card['params']
        common = {'accent'}
        specific = {'punch-pill': {'text', 'position'}, 'quote-lockup': {'quote', 'side'}, 'type-shift': {'lines', 'position', 'shiftAtMs'}}[kind]
        if not isinstance(params, dict) or set(params) - common - specific:
            raise ValueError(f'第{n}张卡包含未知参数；不接受媒体、样式、偏移或署名')
        accent = params.get('accent', 'blue')
        if accent not in ('blue', 'alert', 'orange'):
            raise ValueError(f'第{n}张卡强调色无效')
        field, maximum = {'punch-pill': ('text', 60), 'quote-lockup': ('quote', 100), 'type-shift': ('lines', 120)}[kind]
        value = params.get(field)
        if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
            raise ValueError(f'第{n}张卡文字需为1至{maximum}字单行文本')
        normalize = lambda s: re.sub(r'\s+', '', s)
        source = normalize(''.join(c['text'] for c in cues[a-1:b]))
        pieces = value.split('|') if kind != 'punch-pill' else [value]
        if any(not normalize(p.lstrip('*—-').strip()) or normalize(p.lstrip('*—-').strip()) not in source for p in pieces):
            raise ValueError(f'第{n}张卡文字必须摘自引用字幕，不增加新事实')
        compiled = dict(theme='dark', accent=accent, offsetX=0, offsetY=0, **{field: value.strip()})
        if kind == 'quote-lockup':
            side = params.get('side', 'right')
            if side not in ('left', 'right'):
                raise ValueError(f'第{n}张卡落位无效')
            compiled.update(side=side, author='')
        else:
            position = params.get('position', 'top-left' if kind == 'punch-pill' else 'left')
            if position not in (('bottom', 'top-left', 'top-right') if kind == 'punch-pill' else ('center', 'left', 'right')):
                raise ValueError(f'第{n}张卡落位无效')
            compiled['position'] = position
        if kind == 'type-shift':
            shift = params.get('shiftAtMs', 1600)
            if type(shift) is not int or not 800 <= shift <= 4000 or shift + 300 > (end-start) * 1000:
                raise ValueError(f'第{n}张卡重排时刻超出800至4000ms或卡片时长')
            compiled.update(shiftAtMs=shift, glass='none', glassAlpha=.6)
        output.append(dict(id=identifier, kind=kind, start=start, end=end, params=compiled))
    output.sort(key=lambda c: c['start'])
    if any(next_['start'] < current['end'] for current, next_ in zip(output, output[1:])):
        raise ValueError('第一版文字动效卡不能互相重叠，请减少或调整cue范围')
    return dict(version=1, theme='dark', glow=False, cards=output)


def set_store(store):
    global _store
    _store = store


def overlay_tool(args, session_id):
    """Return validated text to the plugin's existing exclusive artifact writer."""
    from tui_gateway import server
    from .store import digest
    try:
        if not _store or not session_id:
            raise ValueError('编排工具仅支持本机Web聊天')
        session = next((s for s in server._sessions.values() if s.get('session_key') == session_id or getattr(s.get('agent'), 'session_id', None) == session_id), None)
        if not session or TOOL not in {d['function']['name'] for d in getattr(session.get('agent'), 'tools', [])}:
            raise ValueError('本对话未加载视频编排工具')
        if not isinstance(args, dict) or set(args) != {'source_id', 'name', 'cards'}:
            raise ValueError('需要source_id、name和cards')
        ctx = session.get('miniclaw_overlay_turn') or {}
        source = args['source_id']
        if not isinstance(source, str) or source not in ctx:
            raise ValueError('只能使用本轮上传的SRT附件，请重新附加字幕')
        record = _store.get('attachments', source, session['session_key'])
        if record['kind'] != 'text' or not record['name'].lower().endswith('.srt') or digest(record['text']) != ctx[source]:
            raise ValueError('字幕引用已变化或不是本轮SRT')
        document = compile_overlay(record['text'], args['cards'])
        return dict(success=True, document=document, source_id=source, source_hash=ctx[source], card_count=len(document['cards']), subtitle_end=parse_srt(record['text'])[-1]['end'])
    except (ValueError, KeyError, OSError, TypeError) as error:
        return dict(success=False, error=str(error) if isinstance(error, ValueError) else '编排请求无效，请核对字幕ID和参数')
