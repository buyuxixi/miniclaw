"""Audit the local concept film and native package without any cloud calls."""
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from miniclaw_web.video import binaries,probe
from miniclaw_web.overlay import parse_srt


def sha(value):
    return hashlib.sha256(value).hexdigest()


def main():
    folder=ROOT/'outputs/serum-film-v4'
    report=json.loads((folder/'report.json').read_text(encoding='utf-8'))
    ffmpeg,ffprobe=binaries(ROOT)
    video=folder/'video.mp4';digest=sha(video.read_bytes())
    assert digest==report['output']['sha256'], 'Local file differs from native output'
    with zipfile.ZipFile(folder/'publish-package.zip') as archive:
        assert sha(archive.read('video.mp4'))==digest
        assert sha(archive.read('cover.png'))==sha((folder/'cover.png').read_bytes())
        subtitles=archive.read('srt.srt')
        (folder/'subtitles.srt').write_bytes(subtitles)
        manifest=json.loads(archive.read('manifest.json'))
        assert manifest['video']['id']==report['output']['id']
        names=archive.namelist()
    meta=probe(video,ffprobe)
    assert (meta['width'],meta['height'])==(1080,1920)
    assert abs(meta['duration']-18)<.12 and meta['audio'] and meta['codec']=='h264'
    production=report['output']['production'];segments=production['segments']
    cues=parse_srt(subtitles.decode('utf-8'))
    assert len(segments)==len(cues)==4
    for segment,cue in zip(segments,cues):
        assert abs(segment['start']-cue['start'])<.002
        assert abs(segment['end']-cue['end'])<.002
        assert segment['text']==cue['text']
    assert segments[-1]['end']<=meta['duration']-1.19
    sources=json.loads((folder/'sources.json').read_text(encoding='utf-8'))
    for asset in sources['image_assets']:
        assert sha((folder/asset['file']).read_bytes())==asset['sha256']
    for shot in sources['shots'][:-1]:
        media=folder/(shot['name']+'-wan.mp4')
        assert sha(media.read_bytes())==shot['source_sha256']
        info=probe(media,ffprobe)
        assert info['width']>=1080 and info['height']>=1900 and abs(info['duration']-5)<.1 and not info['audio']
    for seconds in (.2,3.5,5.3,7.5,9.7,10.5,13,14.8,16,17.7):
        subprocess.run([ffmpeg,'-v','error','-nostdin','-y','-ss',str(seconds),'-i',str(video),'-frames:v','1',str(folder/f'final-at-{seconds}.jpg')],capture_output=True,check=True)
    log=subprocess.run([ffmpeg,'-hide_banner','-nostdin','-i',str(video),'-af','loudnorm=I=-18:TP=-2:LRA=7:print_format=json','-f','null','-'],capture_output=True,text=True,check=True).stderr
    stats=json.loads(log[log.rfind('{'):log.rfind('}')+1])
    assert float(stats['input_tp'])<=-1.5
    assert -23<=float(stats['input_i'])<=-14
    result={'metadata':meta,'sha256':digest,'zip_matches_video_cover':True,'zip_files':names,
            'subtitle_count':len(cues),'segments':segments,'last_subtitle_end':segments[-1]['end'],
            'sentence_gap_seconds':production['sentence_gap_seconds'],'audio_measurement':stats,
            'video_requests_submitted':len(sources['jobs']),'video_seconds_purchased':sum(j.get('usage',{}).get('output_video_duration',0) for j in sources['jobs'].values()),
            'video_list_price_estimate_cny':sum(j.get('usage',{}).get('output_video_duration',0)*.25 for j in sources['jobs'].values()),
            'verification_scope':'Technical audit and sampling; actual shot actions need visual review; user decides aesthetic acceptance.'}
    (folder/'technical-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
