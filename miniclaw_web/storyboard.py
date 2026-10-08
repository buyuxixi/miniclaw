"""Narrated photo film with optional detail/scene images; fixed local recipe."""
import os
import re
import wave
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx

from .video import execute, font_path


STYLES = {
    'standard': ('Cherry', ''),
    'warm': ('Serena', '像和熟悉的人分享日常一样说话。自然温柔，语速舒缓但不拖长，短句连贯，句末轻轻收住。不要广告腔，不刻意气声，不夸张抒情。'),
    'narrative': ('Ethan', '沉稳自然的普通话旁白，清楚而松弛，语速适中，有克制的情绪和自然停顿。不要播音腔，不喊口号，不拉长每个字。'),
}


def settings(style='standard'):
    if style not in STYLES: raise ValueError('配音风格无效')
    voice, instructions = STYLES[style]
    result = {'configured': bool(os.environ.get('DASHSCOPE_API_KEY', '').strip()),
              'provider': 'dashscope', 'model': 'qwen3-tts-instruct-flash' if instructions else 'qwen3-tts-flash', 'voice': voice}
    if instructions: result.update(instructions=instructions, optimize_instructions=True)
    return result


def lines(script):
    if not isinstance(script, str) or not script.strip() or len(script) > 320:
        raise ValueError('口播短片需要1–320字主稿')
    result = [s.strip() for s in re.findall(r'[^。！？\n]+[。！？]?', script) if s.strip()]
    if not 1 <= len(result) <= 12 or any(len(s) > 36 for s in result):
        raise ValueError('请把主稿分成1–12个短句，每句不超过36字，使用句号或换行分隔')
    return result


def audio_url(value):
    """Only provider OSS results, never arbitrary browser URLs or redirects."""
    parsed = urlsplit(value)
    host = parsed.hostname or ''
    provider_host = re.fullmatch(r'dashscope-result-[a-z0-9-]+\.oss-[a-z0-9-]+\.aliyuncs\.com', host) or host == 'dashscope-a717.oss-cn-beijing.aliyuncs.com'
    if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password or parsed.port not in (None, 80, 443) or not provider_host:
        raise ValueError('语音服务返回的下载地址不受支持')
    return urlunsplit(('https', host, parsed.path, parsed.query, ''))


def synthesize(text, target, canceled, style='standard'):
    if canceled(): raise ValueError('合成已取消')
    key = os.environ.get('DASHSCOPE_API_KEY', '').strip()
    if not key: raise ValueError('未配置百炼语音Key')
    try:
        with httpx.Client(timeout=60, trust_env=False, follow_redirects=False) as client:
            cfg = settings(style)
            params = {'text': text, 'voice': cfg['voice'], 'language_type': 'Chinese'}
            if cfg.get('instructions'): params.update(instructions=cfg['instructions'], optimize_instructions=True)
            response = client.post('https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation',
                headers={'Authorization': 'Bearer ' + key}, json={'model': cfg['model'], 'input': params})
            if response.status_code != 200:
                raise ValueError(f'百炼语音请求失败（HTTP {response.status_code}），不会自动重试或切换Key')
            data = response.json()
            url = audio_url(data['output']['audio']['url'])
            if canceled(): raise ValueError('合成已取消')
            with client.stream('GET', url) as stream:
                if stream.status_code != 200: raise ValueError('语音文件下载失败')
                size = 0
                with Path(target).open('xb') as output:
                    for chunk in stream.iter_bytes(65536):
                        if canceled(): raise ValueError('合成已取消')
                        size += len(chunk)
                        if size > 8*1024*1024: raise ValueError('语音文件超过限制')
                        output.write(chunk)
        return {'request_id': data.get('request_id'), 'characters': data.get('usage', {}).get('characters')}
    except (httpx.HTTPError, KeyError, TypeError, OSError) as error:
        raise ValueError('语音服务或音频响应异常；请检查本机网络与百炼配置') from None


def clock(seconds):
    value = round(seconds*1000)
    hours, value = divmod(value, 3600000); minutes, value = divmod(value, 60000); sec, ms = divmod(value, 1000)
    return f'{hours:02}:{minutes:02}:{sec:02},{ms:03}'


def normalize_wav(source, target):
    """Measure bounded actual PCM, including provider streaming sentinel headers."""
    try:
        with wave.open(str(source), 'rb') as wav:
            channels, size, rate = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
            if wav.getcomptype() != 'NONE' or channels not in (1,2) or size not in (1,2,3,4) or not 8000 <= rate <= 48000: raise ValueError('语音编码无效')
            pcm = wav.readframes(min(wav.getnframes(), 4_000_001))
            if len(pcm) % (channels*size): raise ValueError('语音数据帧不完整')
            duration = len(pcm)/(channels*size*rate)
            if not .1 <= duration <= 30: raise ValueError('语音长度无效')
        with wave.open(str(target), 'wb') as wav:
            wav.setnchannels(channels); wav.setsampwidth(size); wav.setframerate(rate); wav.writeframes(pcm)
        return duration
    except (wave.Error, EOFError): raise ValueError('语音服务未返回有效WAV') from None


def render(p, assets, ffmpeg, work, canceled, speaker=synthesize):
    """Subtitle boundaries come from individual WAV lengths, not estimated reading speed."""
    texts = lines(p['script']); segments = []; requests = []; cursor = 0
    if 'cover' not in assets: raise ValueError('请先准备项目采用图')
    width, height = (1080, 1920) if p['mode'] == 'portrait' else (1920, 1080)
    font = font_path()
    if not font: raise ValueError('中文字体未准备')
    # Filter paths are fixed job-local names; script only goes into UTF-8 text files.
    font_copy = work / 'subtitle-font.ttc'; font_copy.write_bytes(Path(font).read_bytes())
    cues = []; clips = []
    for index, text in enumerate(texts):
        audio = work / f'speech-{index}.wav'
        requests.append(speaker(text, audio, canceled))
        normalized = work / f'speech-{index}-normalized.wav'
        speech = normalize_wav(audio, normalized)
        audio = normalized
        lead = .8 if index == 0 else .2
        tail = 1.5 if index == len(texts)-1 else .35
        duration = speech + lead + tail
        if cursor + duration > 180: raise ValueError('口播短片超过3分钟')
        cues.append(f'{index+1}\n{clock(cursor+lead)} --> {clock(cursor+lead+speech)}\n{text}\n')
        # Opening/closing poster, macro and wider scene alternate between them.
        slot = 'cover' if index in (0, len(texts)-1) else ('detail' if index % 2 else 'scene')
        if slot not in assets: slot = 'cover'
        image = work / f'frame-{index}{assets[slot].suffix}'
        image.write_bytes(assets[slot].read_bytes())
        subtitle = work / f'line-{index}.txt'; subtitle.write_text(text, encoding='utf-8')
        count = round(duration*30)
        # Two-line subtitles for long phrases; no pixel edits to source images.
        if len(text) > 20:
            split = text.rfind('，', 0, 21)+1 or len(text)//2
            subtitle.write_text(text[:split]+'\n'+text[split:], encoding='utf-8')
        size = 40 if width == 1080 else 34
        vf = (f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0xFAFAF7,setsar=1,'
              f"zoompan=z='1+0.045*on/{count}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d={count}:s={width}x{height}:fps=30,"
              f"drawtext=fontfile=subtitle-font.ttc:textfile=line-{index}.txt:expansion=none:fontsize={size}:fontcolor=white:borderw=2:bordercolor=black@0.5:box=1:boxcolor=0x302D2E@0.65:boxborderw=18:line_spacing=12:x=(w-text_w)/2:y=h-240:enable='between(t,{lead},{lead+speech})',"
              'fade=t=in:st=0:d=0.2,fade=t=out:st='+str(duration-.2)+':d=0.2')
        clip = work / f'clip-{index}.mp4'
        args = [ffmpeg, '-v', 'error', '-nostdin', '-i', image.name, '-i', audio.name, '-vf', vf,
                '-af', f'adelay={round(lead*1000)}:all=1,apad', '-t', str(count/30), '-c:v', 'libx264', '-preset', 'fast', '-crf', '19', '-maxrate', '6M', '-bufsize', '12M',
                '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2', '-map_metadata', '-1', '-threads', '2', clip.name]
        # execute supports only argv; cwd is explicit to keep filter paths safe on Windows.
        execute(args, work, canceled=canceled, cwd=work)
        clips.append(clip); segments.append({'text': text, 'start': round(cursor+lead,3), 'end': round(cursor+lead+speech,3), 'slot': slot})
        cursor += count/30
    (work/'generated.srt').write_text('\n'.join(cues), encoding='utf-8')
    (work/'clips.txt').write_text(''.join(f"file '{clip.name}'\n" for clip in clips), encoding='utf-8')
    execute([ffmpeg, '-v', 'error', '-nostdin', '-f', 'concat', '-safe', '1', '-i', 'clips.txt', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-af', 'loudnorm=I=-18:TP=-2:LRA=7,aresample=48000', '-movflags', '+faststart', '-map_metadata', '-1', 'video.mp4'], work, canceled=canceled, cwd=work)
    return {'speech': settings(p.get('speech_style', 'standard')), 'requests': requests, 'segments': segments, 'subtitle_file': str((work/'generated.srt').relative_to(work.parent)),
            'recipe': 'original-three-image-motion-editorial-v2' if all(slot in assets for slot in ('cover','detail','scene')) else 'original-photo-motion-editorial-v3', 'subtitle_timing': 'measured-per-sentence-wav', 'audio_normalization': {'integrated_lufs': -18, 'true_peak_db': -2}}
