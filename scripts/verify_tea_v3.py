"""Read-only media/ZIP audit for the local tea sample; no model or publish calls."""
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from miniclaw_web.video import binaries,probe


def main():
    folder=ROOT/'outputs/tea-film-v3'
    report=json.loads((folder/'report.json').read_text(encoding='utf-8'))
    ffmpeg,ffprobe=binaries(ROOT)
    video=folder/'video.mp4';sha=hashlib.sha256(video.read_bytes()).hexdigest()
    assert sha==report['output']['sha256'], 'Local video differs from native output'
    with zipfile.ZipFile(folder/'publish-package.zip') as archive:
        assert hashlib.sha256(archive.read('video.mp4')).hexdigest()==sha
        assert hashlib.sha256(archive.read('cover.png')).hexdigest()==hashlib.sha256((folder/'cover.png').read_bytes()).hexdigest()
        (folder/'subtitles.srt').write_bytes(archive.read('srt.srt'))
        names=archive.namelist()
        assert json.loads(archive.read('manifest.json'))['video']['id']==report['output']['id']
    for seconds in (1,5,8,12,17,22):
        subprocess.run([ffmpeg,'-v','error','-nostdin','-y','-ss',str(seconds),'-i',str(video),'-frames:v','1',str(folder/f'frame-{seconds}.png')],check=True)
    log=subprocess.run([ffmpeg,'-hide_banner','-nostdin','-i',str(video),'-af','loudnorm=I=-18:TP=-2:LRA=7:print_format=json','-f','null','-'],capture_output=True,text=True,check=True).stderr
    stats=json.loads(log[log.rfind('{'):log.rfind('}')+1])
    production=report['output']['production'];meta=probe(video,ffprobe)
    assert (meta['width'],meta['height'])==(1080,1920) and abs(meta['duration']-23)<.15 and meta['audio']
    assert len(production['segments'])==5 and production['segments'][-1]['end']<meta['duration']
    for source in json.loads((folder/'sources.json').read_text(encoding='utf-8'))['sources']:
        assert hashlib.sha256((folder/f"pexels-{source['id']}-original.mp4").read_bytes()).hexdigest()==source['sha256']
    check={'metadata':meta,'sha256':sha,'zip_matches_video_cover':True,'zip_files':names,
           'subtitle_count':len(production['segments']),'last_subtitle_end':production['segments'][-1]['end'],
           'reused_audio_count':sum(bool(x.get('reused')) for x in production['requests']),
           'sentence_gap_seconds':production['sentence_gap_seconds'],'audio_measurement':stats,
           'verification_scope':'Technical media checks and extracted frames; aesthetic and voice preference remain user acceptance.'}
    (folder/'technical-check.json').write_text(json.dumps(check,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(check,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
