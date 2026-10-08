import { useEffect, useState } from 'react';
import { creatorBase, creatorBlob, saveCreator, uploadCreator, type CreatorProject, type CreatorTarget } from './creator-api';
import { readApi, writeApi } from './management-api';

type Capabilities = {video:boolean; font:boolean; speech:{configured:boolean}; storyboard_min_images?:number};
const names:Record<string,string>={cover:'项目采用图',detail:'特写图',scene:'场景图',video:'镜头视频',srt:'字幕 SRT',plan:'动效 JSON',overlay:'透明动效视频'};
export function scriptVideoIssue(script:string) {
  if(!script.trim()) return '先在口播中起稿并采用主稿。';
  const sentences=(script.match(/[^。！？\n]+[。！？]?/g)||[]).map(s=>s.trim()).filter(Boolean);
  if(!sentences.length) return '主稿需要包含可朗读的句子，请先到口播修改。';
  if(Array.from(script).length>320) return '主稿超过 320 字，请先缩短篇幅。';
  if(sentences.length>12) return '主稿超过 12 句，请先合并或删减。';
  if(sentences.some(s=>Array.from(s).length>36)) return '部分句子超过 36 字，请先拆成短句再配音。';
  return '';
}

export function ProjectVideo({ project:p, image, busy, onRun, onSuggest, onNavigate }: {
  project:CreatorProject; busy:boolean; onRun:(fn:()=>Promise<void>)=>Promise<void>;
  onSuggest:(text:string,skill?:string)=>void; onNavigate?:(node:CreatorTarget['node'])=>void;
  image?:string;
}) {
  const [cap,setCap]=useState<Capabilities>();
  const [capError,setCapError]=useState('');
  const [capAttempt,setCapAttempt]=useState(0);
  const [url,setUrl]=useState('');
  const [previewError,setPreviewError]=useState('');
  const [historyOpen,setHistoryOpen]=useState(()=>window.innerWidth>650);
  const output=p.outputs.find(o=>o.current)||p.outputs[0];
  const running=p.jobs.some(j=>j.state==='queued'||j.state==='running');
  const blocked=busy||running;
  useEffect(()=>{const abort=new AbortController(); setCap(undefined);setCapError('');
    void readApi<Capabilities>(`${creatorBase}/capabilities`,abort.signal).then(value=>{if(!abort.signal.aborted)setCap(value);}).catch(()=>{if(!abort.signal.aborted)setCapError('视频能力读取失败。');});
    return()=>abort.abort();
  },[capAttempt]);
  useEffect(()=>{let link='';const abort=new AbortController();setUrl('');setPreviewError('');
    if(output) void creatorBlob(p.id,output.id,abort.signal).then(blob=>{if(!abort.signal.aborted){link=URL.createObjectURL(blob);setUrl(link);}}).catch(()=>{if(!abort.signal.aborted)setPreviewError('成片预览读取失败，请稍后重试。');});
    return()=>{abort.abort();if(link)URL.revokeObjectURL(link);};
  },[p.id,output?.id]);
  const speech=p.method==='storyboard'||p.method==='narrated';
  // Older servers still require three images. Negotiate before advertising the simpler recipe.
  const needed=p.method==='storyboard' ? cap?.storyboard_min_images===1?['cover']:['cover','detail','scene'] : p.method==='narrated'?['video']:p.method==='plan'?['video','srt','plan']:['video','overlay'];
  const missing=needed.filter(slot=>!p.assets[slot]);
  const scriptIssue=speech?scriptVideoIssue(p.script):'';
  const reviewScript=speech&&p.flow?.script!=='adopted';
  const reviewCover=p.method==='storyboard'&&p.flow?.cover!=='adopted';
  const scriptCount=Array.from(p.script.replace(/\s/g,'')).length;
  const voice={standard:'明亮女声',warm:'自然温柔',narrative:'沉稳旁白'}[p.speech_style||'standard']||p.speech_style;
  const reason=capError || (!cap?'正在检查合成能力…':!cap.video?'本机缺少 FFmpeg / ffprobe，暂时不能合成。':p.method!=='overlay'&&!cap.font?'字幕字体尚未准备，请先配置视频字体。':speech&&!cap.speech.configured?'语音服务尚未配置，需要在后端配置百炼配音凭据。':
    reviewCover?'请先到修图核对并采用工作图。':scriptIssue|| (reviewScript?'项目资料已变化，请到口播核对并确认主稿。':missing.length?`还需准备：${missing.map(s=>names[s]).join('、')}。`:''));
  function method(value:string) {void onRun(async()=>{await saveCreator(p,{method:value});});}
  function material(slot:string) {return <label className="video-material-row" key={slot}><span>{names[slot]}<small>{p.assets[slot]?.name||'待上传'}</small></span><span className="video-upload">{p.assets[slot]?'替换':'上传'}<input type="file" aria-label={`视频素材 ${names[slot]}`} disabled={blocked} accept={['cover','detail','scene'].includes(slot)?'image/png,image/jpeg,image/webp':slot==='srt'?'.srt':slot==='plan'?'.json':'video/*'} onChange={e=>{const file=e.target.files?.[0];e.target.value='';if(file)void onRun(async()=>{await uploadCreator(p,slot,file);});}}/></span></label>;}
  return <section className="project-video" aria-label="视频制作">
    <div className="video-start-modes" role="group" aria-label="选择制作路径">
      <button aria-pressed={p.method==='storyboard'} disabled={blocked} onClick={()=>method('storyboard')}><strong>图片口播</strong><span>采用图 + 主稿，自动配音和字幕</span></button>
      <button aria-pressed={p.method==='narrated'} disabled={blocked} onClick={()=>method('narrated')}><strong>镜头配口播</strong><span>上传实拍视频，配上采用主稿</span></button>
    </div>
    <details className="video-advanced" open={!speech}><summary>专业动效 · 已有视频与字幕</summary><div>
      <label>制作方式<select aria-label="视频制作方式" value={p.method} disabled={blocked} onChange={e=>method(e.target.value)}><option value="storyboard">图片口播</option><option value="narrated">镜头配口播</option><option value="plan">字幕文字动效</option><option value="overlay">透明动效叠加</option></select></label>
      {p.method==='plan'&&<><p>此方式需要原视频、与视频对齐的 SRT 和动效编排。第一次制作，建议选择上方“图片口播”。</p><button disabled={blocked} onClick={()=>onSuggest('根据我本轮上传的真实 SRT，选取少量重点，使用编排工具生成经过校验的文字动效 JSON。没有 SRT 时先说明需要上传，不估算时间。','overlay-plan')}>让 Chat 编排字幕动效</button></>}
      {p.method==='overlay'&&<p>上传原视频和在外部动效工作台导出的透明 MOV，然后合成预览。</p>}
    </div></details>
    <section className="video-input-summary" aria-label="本次生成使用的素材">
      <div>{p.method==='storyboard'&&image&&p.assets.cover&&<img src={image} alt="本次短片采用图"/>}<strong>{p.method==='storyboard'?'采用图片': '镜头视频'}</strong><span>{p.assets[p.method==='storyboard'?'cover':'video']?.name||'待准备'}{reviewCover?' · 待核对':''}</span>{p.method==='storyboard'&&<button disabled={blocked||!onNavigate} onClick={()=>onNavigate?.('cover')}>{reviewCover?'核对采用图':'查看采用图'}</button>}</div>
      {speech?<><div><strong>采用口播</strong><span>{scriptCount?`${scriptCount} 字 · 约 ${Math.max(1,Math.round(scriptCount/4))} 秒${reviewScript?' · 待核对':''}`:'尚未采用'}</span><button disabled={blocked||!onNavigate} onClick={()=>onNavigate?.('script')}>{reviewScript||scriptIssue?'核对口播主稿':'查看口播主稿'}</button></div><div><strong>成片设置</strong><span>{voice} · {p.mode==='portrait'?'竖版 9:16':'横版 16:9'}</span></div></>:<div><strong>动效素材</strong><span>{needed.filter(s=>s!=='video').map(s=>`${names[s]}${p.assets[s]?' 已准备':' 待准备'}`).join(' · ')}</span></div>}
    </section>
    <div className="video-render-action"><div><strong>{speech?"生成配音字幕短片":"合成动效视频"}</strong>{speech&&<p>使用百炼配音，会消耗额度；字幕自动生成。</p>}{reason&&<p role={capError?'alert':'status'}>{reason}</p>}</div>{capError&&<button disabled={blocked} onClick={()=>setCapAttempt(v=>v+1)}>重新检查能力</button>}<button className="primary-button" disabled={blocked||!!reason} onClick={()=>void onRun(async()=>{await writeApi(`${creatorBase}/projects/${p.id}/render`,'POST',{revision:p.revision});})}>{running?'正在合成…':speech?'生成配音字幕短片':'合成动效视频'}</button></div>
    <div className="video-workgrid"><div className="video-preview-column">
      {output&&!output.current?<details className="video-history-preview" open={historyOpen} onToggle={e=>setHistoryOpen(e.currentTarget.open)}><summary>查看之前的成片 · {output.name}</summary>{url&&<><div className="studio-video-stage"><video controls src={url} aria-label="历史成片预览"/></div><a className="studio-download" href={url} download={output.name}>下载之前的成片 ↗</a></>}<p className="companion-note">资料已变化，这是之前的成片，需要重新生成。</p></details>:<>
      <header className="studio-output-actions"><div><strong>{output?output.current?'当前成片':'之前的成片':'成片预览'}</strong>{output&&<span>{output.name}</span>}</div>{url&&<a className="studio-download" href={url} download={output?.name}>下载成片 ↗</a>}</header>
      {url?<div className="studio-video-stage"><video controls src={url} aria-label="成片预览"/></div>:<div className="video-empty"><strong>{output?'正在读取成片…':'用这件商品，做第一支短片'}</strong><p>{speech?'准备图片或镜头，采用口播，生成配音字幕短片。':'准备原视频与动效素材，再合成预览。'}</p><button disabled={blocked} onClick={()=>onSuggest('基于本项目已采用的口播稿与图片，制定一份短视频分镜方案，说明还需要哪些素材。先讨论方案，不执行合成。')}>先和 Chat 讨论分镜</button></div>}
      </>}
      {previewError&&<p role="alert">{previewError}</p>}
      {p.jobs.slice(0,3).map(j=><div className="video-job" key={j.id}><p role="status">{{queued:'等待合成',running:'正在合成',succeeded:output?.current&&output.id===j.id?'合成完成':'历史合成完成',failed:'合成失败',canceled:'已取消的合成'}[j.state]}{j.error?`：${j.error}`:''}</p>{(j.state==='queued'||j.state==='running')&&<button disabled={busy} onClick={()=>void onRun(async()=>{await writeApi(`${creatorBase}/projects/${p.id}/jobs/${j.id}/cancel`,'POST',{});})}>取消合成</button>}</div>)}
    </div><section className="video-settings-panel" aria-label="素材与合成设置">
      <h3>{speech?'制作这支短片':'素材与合成设置'}</h3>
      {speech?<>
        <section className="video-preparation"><h4><b>1</b>{p.method==='storyboard'?'采用图片':'实拍镜头'}<span>{p.method==='storyboard'?(p.assets.cover&&!reviewCover?'已就绪':'待采用'):p.assets.video?'已就绪':'待上传'}</span></h4>
          {p.method==='storyboard'?<><p>{p.assets.cover?.name||'先在修图中准备并采用商品图。'}</p><button disabled={blocked||!onNavigate} onClick={()=>onNavigate?.('cover')}>{reviewCover?'去修图采用图片':'查看采用图 ↗'}</button>
            <details className="video-extra-images"><summary>{cap?.storyboard_min_images===1?'补充镜头图片（可选）':'补充镜头图片'}</summary><p>{cap?.storyboard_min_images===1?'没有补充图片时，用采用图的平移与缩放完成短片。':'当前服务还需要特写图和场景图。'}</p>{material('detail')}{material('scene')}</details>
          </>:material('video')}
        </section>
        <section className="video-preparation"><h4><b>2</b>采用口播<span>{p.script&&!reviewScript?'已就绪':'待核对'}</span></h4><p className="video-script-excerpt">{p.script||'先在口播中起稿，再确认采用。'}</p><button disabled={blocked||!onNavigate} onClick={()=>onNavigate?.('script')}>{reviewScript?'去口播核对主稿':'查看口播主稿 ↗'}</button>{scriptIssue&&p.script&&<button disabled={blocked} onClick={()=>onSuggest('把本项目已采用的主稿整理为配音短句：总计不超过 320 字、12 句，每句不超过 36 字；保留已确认事实。先给候选稿，等我采用。','spoken-script')}>让 Chat 整理短句</button>}</section>
      </>:<div className="video-materials">{needed.map(material)}</div>}
      <section className="video-preparation video-render-settings"><h4>{speech&&<b>3</b>}{speech?'配音与成片':'成片设置'}</h4>
        <label>成片比例<select aria-label="视频比例" value={p.mode} disabled={blocked} onChange={e=>void onRun(async()=>{await saveCreator(p,{mode:e.target.value});})}><option value="portrait">竖版 9:16</option><option value="landscape">横版 16:9</option></select></label>
        {speech&&<label>配音声音<select aria-label="视频配音风格" value={p.speech_style||'standard'} disabled={blocked} onChange={e=>void onRun(async()=>{await saveCreator(p,{speech_style:e.target.value});})}><option value="standard">明亮女声 · Cherry</option><option value="warm">自然温柔 · Serena</option><option value="narrative">沉稳旁白 · Ethan</option></select></label>}
        {p.method==='narrated'&&p.assets.video?.audio&&<label className="video-audio"><input type="checkbox" disabled={blocked} checked={!!p.keep_source_audio} onChange={e=>void onRun(async()=>{await saveCreator(p,{keep_source_audio:e.target.checked});})}/>保留背景音，旁白时压低</label>}
        {speech&&<p className="companion-note">{p.method==="storyboard"?"短片使用图片平移与缩放运镜。":"配音与字幕叠加到实拍镜头。"}</p>}

      </section>
    </section></div>
  </section>;
}
