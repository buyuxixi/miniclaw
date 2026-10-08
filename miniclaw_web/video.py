"""Small original local compositor. No shell, network inputs or external renderer."""
import json
import math
import os
import shutil
import subprocess
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .overlay import compile_overlay, parse_srt

MAX_MEDIA = 256 * 1024 * 1024
MAX_DURATION = 180
FORMATS = {'portrait': (720, 1280), 'landscape': (1280, 720)}


def binaries(root):
    private = Path(root) / '.codex/tools/media-runtime'
    def find(name, fallback):
        explicit = os.environ.get('MINICLAW_' + name.upper())
        candidate = explicit or shutil.which(name) or str(fallback)
        return str(Path(candidate).resolve()) if Path(candidate).is_file() else None
    return find('ffmpeg', private / 'ffmpeg.exe'), find('ffprobe', private / 'node_modules/ffprobe-static/bin/win32/x64/ffprobe.exe')


def font_path():
    options = [os.environ.get('MINICLAW_VIDEO_FONT', ''), 'C:/Windows/Fonts/msyh.ttc',
               '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']
    return next((p for p in options if p and Path(p).is_file()), None)


def probe(path, ffprobe):
    try:
        with Path(path).open('rb') as stream: header = stream.read(16)
        if header[:4] != b'\x1aE\xdf\xa3' and header[4:8] not in (b'ftyp', b'moov', b'mdat', b'wide', b'free', b'skip'):
            raise ValueError()
        result = subprocess.run([ffprobe, '-v', 'error', '-protocol_whitelist', 'file', '-format_whitelist', 'mov,matroska,webm', '-show_entries', 'stream=codec_type,codec_name,width,height,pix_fmt,duration,start_time:stream_disposition=attached_pic:format=duration,format_name', '-of', 'json', str(path)],
                                capture_output=True, timeout=20, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        data = json.loads(result.stdout)
        streams = data['streams']
        if len(streams) > 16: raise ValueError()
        video = next(s for s in streams if s['codec_type'] == 'video' and not s.get('disposition', {}).get('attached_pic'))
        duration = float(video.get('duration') or data['format']['duration'])
        width, height = int(video['width']), int(video['height'])
        if result.returncode or not math.isfinite(duration) or not .5 <= duration <= MAX_DURATION or not 16 <= width <= 3840 or not 16 <= height <= 3840 or width * height > 3840 * 2160:
            raise ValueError()
        formats = set(data['format']['format_name'].split(','))
        if not formats.intersection({'mov', 'mp4', 'matroska', 'webm'}):
            raise ValueError()
        # Rotation is applied by FFmpeg, and final frames are fitted rather than cropped.
        audio = next((s for s in streams if s.get('codec_type') == 'audio'), None)
        audio_offset = float(audio.get('start_time', 0)) - float(video.get('start_time', 0)) if audio else 0
        if not math.isfinite(audio_offset) or abs(audio_offset) > duration: raise ValueError()
        return {'duration': duration, 'width': width, 'height': height, 'audio': bool(audio), 'audio_offset': audio_offset,
                'alpha': video.get('pix_fmt', '').startswith(('yuva', 'rgba', 'bgra', 'argb', 'abgr', 'gbrap')),
                'pixel_format': video.get('pix_fmt', ''), 'codec': video.get('codec_name', '')}
    except (OSError, ValueError, KeyError, StopIteration, TypeError, subprocess.TimeoutExpired):
        raise ValueError('需要可读取的MP4/MOV/WebM视频：0.5–180秒，最大3840×2160像素') from None


def validated_document(text, srt):
    """Recompile imported JSON against this exact subtitle. Ignore no unknown fields."""
    try:
        doc = json.loads(text)
        if set(doc) != {'version', 'theme', 'glow', 'cards'} or type(doc['version']) is not int or doc['version'] != 1 or doc['theme'] != 'dark' or doc['glow'] is not False:
            raise ValueError()
        cues = parse_srt(srt)
        cards = []
        defaults = {'theme': 'dark', 'offsetX': 0, 'offsetY': 0}
        for c in doc['cards']:
            if set(c) != {'id', 'kind', 'start', 'end', 'params'} or type(c['start']) not in (int, float) or type(c['end']) not in (int, float):
                raise ValueError()
            a = next(q['cue'] for q in cues if q['start'] == c['start'])
            b = next(q['cue'] for q in cues if q['end'] == c['end'])
            p = dict(c['params'])
            for key, value in defaults.items():
                candidate = p.pop(key)
                if type(candidate) is not type(value) or candidate != value: raise ValueError()
            if c['kind'] == 'quote-lockup' and p.pop('author') != '': raise ValueError()
            if c['kind'] == 'type-shift' and (p.pop('glass') != 'none' or p.pop('glassAlpha') != .6): raise ValueError()
            cards.append(dict(id=c['id'], kind=c['kind'], cue_start=a, cue_end=b, params=p))
        compiled = compile_overlay(srt, cards)
        if compiled != doc: raise ValueError()
        return compiled
    except (ValueError, KeyError, StopIteration, TypeError):
        raise ValueError('JSON需为本系统生成的动效编排，并匹配这份SRT；未知字段、改写时间或文字均拒绝') from None


def card_image(card, size, target, font):
    """Original compact layout; independent of Overlay Studio components."""
    width, height = size
    portrait = height > width
    margin = int(width * .07)
    safe_width = width - margin * 2
    maximum = int(width * (.054 if portrait else .037))
    p, kind = card['params'], card['kind']
    text = p.get('text') or p.get('quote') or p.get('lines')
    # Literal text only. No markup interpretation, file paths or filter interpolation.
    lines = []
    face = ImageFont.truetype(font, maximum)
    for segment in text.split('|'):
        current = ''
        for char in segment:
            if face.getlength(current + char) > safe_width - margin and current:
                lines.append(current); current = ''
            current += char
        lines.append(current)
    line_height = int(maximum * 1.5)
    box_height = len(lines) * line_height + maximum
    # Fail clearly rather than hide overflowing subtitles or reduce them to tiny type.
    if box_height > height * .42:
        raise ValueError('文字卡过长，请减少摘录或拆分卡片后重新生成JSON')
    box_width = min(safe_width, int(max(face.getlength(s) for s in lines) + maximum * 1.5))
    position = p.get('position', p.get('side', 'right'))
    x = margin if position in ('left', 'top-left') else width - margin - box_width if position in ('right', 'top-right') else (width-box_width)//2
    # Vertical center remains free in portrait; lower third stays above platform controls.
    y = int(height * .13) if position.startswith('top') else int(height * .68) - box_height if position == 'bottom' or portrait else (height-box_height)//2
    y = max(margin, min(y, height - margin - box_height))
    image = Image.new('RGBA', size)
    draw = ImageDraw.Draw(image)
    accents = {'blue': '#366FE8', 'alert': '#BB3850', 'orange': '#B85C1F'}
    background = accents[p['accent']] if kind == 'punch-pill' else '#172638'
    draw.rounded_rectangle((x, y, x+box_width, y+box_height), radius=maximum//2, fill=background)
    for i, line in enumerate(lines):
        draw.text((x+maximum*.7, y+maximum*.4+i*line_height), line, font=face, fill='white', stroke_width=0)
    image.save(target)


def command(source, metadata, output, work, ffmpeg, mode='portrait', overlay=None, overlay_meta=None, document=None, font=None):
    if mode not in FORMATS: raise ValueError('视频比例无效')
    width, height = FORMATS[mode]
    duration = metadata['duration']
    args = [ffmpeg, '-nostdin', '-hide_banner', '-v', 'error', '-n', '-protocol_whitelist', 'file', '-format_whitelist', 'mov,matroska,webm', '-i', str(source)]
    graph = [f'[0:v:0]setpts=PTS-STARTPTS,scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps=30[base]']
    current = 'base'
    if overlay:
        if not overlay_meta or not overlay_meta['alpha']: raise ValueError('动效层需要真实透明通道；普通不透明视频不能作为透明层')
        if mode != 'landscape' or overlay_meta['width'] * height != overlay_meta['height'] * width:
            raise ValueError('外部透明层目前仅支持16:9横版；竖版请选择JSON文字卡以重新排版')
        if overlay_meta['duration'] > duration + .15: raise ValueError('透明层长于原视频，请使用相同时间线的文件')
        args += ['-protocol_whitelist', 'file', '-format_whitelist', 'mov,matroska,webm', '-i', str(overlay)]
        graph += [f'[1:v:0]setpts=PTS-STARTPTS,scale={width}:{height},format=rgba[layer]', '[base][layer]overlay=eof_action=pass:repeatlast=0:format=auto[out]']
        current = 'out'
    elif document:
        if not font: raise ValueError('中文视频字体缺失，请配置MINICLAW_VIDEO_FONT后重试')
        for index, card in enumerate(document['cards'], 1):
            if card['end'] > duration + .15: raise ValueError('动效字幕超过视频时长，请提供同一录制版本')
            png = Path(work) / f'card-{index}.png'
            card_image(card, (width, height), png, font)
            args += ['-loop', '1', '-framerate', '30', '-protocol_whitelist', 'file', '-i', str(png)]
            start, end = card['start'], card['end']
            graph.append(f'[{index}:v]format=rgba,fade=t=in:st={start}:d=0.15:alpha=1,fade=t=out:st={end-.15}:d=0.15:alpha=1[c{index}]')
            graph.append(f'[{current}][c{index}]overlay=enable=\'gte(t,{start})*lt(t,{end})\':shortest=1:format=auto[v{index}]')
            current = f'v{index}'
    audio_offset = metadata.get('audio_offset', 0)
    audio_filter = f'atrim=start={-audio_offset},asetpts=PTS-STARTPTS' if audio_offset < 0 else f'asetpts=PTS-STARTPTS,adelay={round(audio_offset*1000)}:all=1'
    args += ['-filter_complex_threads', '1', '-filter_complex', ';'.join(graph), '-map', f'[{current}]', '-map', '0:a:0?',
             '-t', str(duration), '-map_metadata', '-1', '-map_chapters', '-1', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '22', '-maxrate', '4M', '-bufsize', '8M', '-pix_fmt', 'yuv420p',
             '-c:a', 'aac', '-b:a', '128k', '-af', audio_filter, '-movflags', '+faststart', '-threads', '2', str(output)]
    return args


def execute(args, work, canceled=lambda: False, timeout=600, cwd=None):
    log = Path(work) / 'encode-error.log'
    with log.open('wb') as stream:
        process = subprocess.Popen(args, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=stream,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                if canceled(): raise ValueError('合成已取消')
                if time.monotonic() > deadline: raise ValueError('合成超时，请缩短视频后重试')
                time.sleep(.15)
            if process.returncode: raise ValueError('视频合成失败，请核对素材格式；本机诊断日志已保存')
            if canceled(): raise ValueError('合成已取消')
        finally:
            if process.poll() is None: process.kill()
            process.wait()
