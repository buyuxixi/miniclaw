"""Keep an edited footage sequence intact; replace its audio with project narration."""
import array
import wave
from pathlib import Path

from . import storyboard
from .video import execute, font_path


def render(p, source, ffmpeg, work, canceled, speaker):
    if p.get('keep_source_audio') and not p['assets']['video'].get('audio'): raise ValueError('镜头片没有原音轨，请关闭保留背景音')
    texts = storyboard.lines(p['script'])
    requests, segments, cues, chunks = [], [], [], []
    rate = 48000
    cursor = .35
    for index, text in enumerate(texts):
        if canceled(): raise ValueError('合成已取消')
        raw = work / f'speech-{index}.wav'
        requests.append(speaker(text, raw, canceled))
        normalized = work / f'speech-{index}-normalized.wav'
        seconds = storyboard.normalize_wav(raw, normalized)
        # One fixed PCM format avoids sample-rate drift at sentence joins.
        decoded = work / f'pcm-{index}.wav'
        execute([ffmpeg, '-v', 'error', '-nostdin', '-i', normalized.name, '-ar', str(rate), '-ac', '1', '-c:a', 'pcm_s16le', decoded.name], work, canceled=canceled, cwd=work)
        with wave.open(str(decoded), 'rb') as wav:
            chunk = array.array('h');chunk.frombytes(wav.readframes(wav.getnframes()))
        seconds = len(chunk)/rate
        chunks.append(chunk)
        end = cursor+seconds
        if end+1.2 > p['assets']['video']['duration']+.03:
            raise ValueError('镜头片不足以容纳旁白与片尾停顿，请缩短稿件或提供更长镜头片；后续句子未继续请求')
        pause = .28 if index < len(texts)-1 else 1.2
        cursor=end+pause
    source_duration = p['assets']['video']['duration']
    if cursor > source_duration+.03:
        raise ValueError(f'旁白和停顿需要{cursor:.1f}秒，镜头片只有{source_duration:.1f}秒；请缩短稿件或提供更长镜头片')
    # Give shots room between sentences instead of a long dead tail. This is
    # measured spacing, not semantic synchronization to unknown shot cuts.
    speech_seconds=sum(len(chunk)/rate for chunk in chunks)
    gap=min(2.5,max(.28,(source_duration-.35-1.2-speech_seconds)/(len(texts)-1))) if len(texts)>1 else .28
    cursor=.35;pcm=array.array('h',[0]*round(cursor*rate))
    for index,(text,chunk) in enumerate(zip(texts,chunks)):
        pcm.extend(chunk);end=cursor+len(chunk)/rate
        cues.append(f'{index+1}\n{storyboard.clock(cursor)} --> {storyboard.clock(end)}\n{text}\n')
        segments.append({'text':text,'start':round(cursor,3),'end':round(end,3),'slot':'video'})
        pause=gap if index<len(texts)-1 else 1.2
        pcm.extend([0]*round(pause*rate));cursor=end+pause
    # Preserve the whole uploaded edit, including its silent end card.
    pcm.extend([0]*max(0,round(source_duration*rate)-len(pcm)))
    with wave.open(str(work/'narration.wav'), 'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(rate);wav.writeframes(pcm.tobytes())
    (work/'generated.srt').write_text('\n'.join(cues),encoding='utf-8')
    font = font_path()
    if not font: raise ValueError('中文字体未准备')
    (work/'subtitle-font.ttc').write_bytes(Path(font).read_bytes())
    width,height = (1080,1920) if p['mode']=='portrait' else (1920,1080)
    vf=f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0xFAFAF7,setsar=1,fps=30'
    for index,s in enumerate(segments):
        text=s['text']
        if len(text)>20:
            split=text.rfind('，',0,21)+1 or len(text)//2
            text=text[:split]+'\n'+text[split:]
        (work/f'line-{index}.txt').write_text(text,encoding='utf-8')
        vf += f",drawtext=fontfile=subtitle-font.ttc:textfile=line-{index}.txt:expansion=none:fontsize=42:fontcolor=white:borderw=2:bordercolor=black@0.5:shadowcolor=black@0.5:shadowx=1:shadowy=2:line_spacing=12:x=(w-text_w)/2:y=h-250:enable='between(t,{s['start']},{s['end']})'"
    mix = ['-map','1:a:0','-af','loudnorm=I=-18:TP=-2:LRA=7,aresample=48000']
    if p.get('keep_source_audio'):
        # The uploaded edit owns any music/ambience; narration ducks its bed.
        offset=p['assets']['video'].get('audio_offset',0)
        align=f'atrim=start={-offset},asetpts=PTS-STARTPTS' if offset<0 else f'asetpts=PTS-STARTPTS,adelay={round(offset*1000)}:all=1'
        mix=['-filter_complex',f'[1:a]loudnorm=I=-18:TP=-2:LRA=7,aresample=48000,asplit=2[voice][side];[0:a]{align},aresample=48000,volume=0.35[bed];[bed][side]sidechaincompress=threshold=0.04:ratio=8:attack=20:release=400[duck];[voice][duck]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.89:level=false[a]','-map','[a]']
    execute([ffmpeg,'-v','error','-nostdin','-protocol_whitelist','file','-format_whitelist','mov,matroska,webm','-i',str(source),'-i','narration.wav',
             '-map','0:v:0','-vf',vf,*mix,'-t',str(source_duration),
             '-c:v','libx264','-preset','fast','-crf','18','-maxrate','6M','-bufsize','12M','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-ac','2','-threads','2',
             '-map_metadata','-1','-map_chapters','-1','-movflags','+faststart','video.mp4'],work,canceled=canceled,cwd=work)
    return {'speech':storyboard.settings(p.get('speech_style','standard')),'requests':requests,'segments':segments,
            'subtitle_file':str((work/'generated.srt').relative_to(work.parent)),'recipe':'intact-footage-narration-v2',
            'subtitle_timing':'measured-per-sentence-wav','sentence_gap_seconds':round(gap,3),'source_audio':'ducked-under-narration' if p.get('keep_source_audio') else 'replaced-with-narration','audio_normalization':{'integrated_lufs':-18,'true_peak_db':-2}}
