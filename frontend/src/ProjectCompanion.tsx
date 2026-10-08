import { useEffect, useRef, useState } from 'react';
import { creatorBlob, getCreator, saveCreator, type CreatorProject, type CreatorTarget, type CreatorFile } from './creator-api';
import { exportBlob, loadProject, projectOwner, projectPath, type Project } from './canvas-api';
import { writeApi } from './management-api';
import { ImagePlanPanel } from './ImagePlanPanel';
import { CandidateReview } from './CandidateReview';
import { ImageComparison } from './ImageJobCard';
import { canvasOrigin } from './creator-canvas';
import { ProjectVideo } from './ProjectVideo';
import { ScriptWorkbench } from './ScriptWorkbench';

export type WorkingImageContext = { project_id: string; revision: number; layer_id: string; mode: 'plan' };
export type ProjectImageReference = { project: string; file: CreatorFile };
export type ProjectMainScript = { project: string; owner: string; text: string };

export function ProjectCompanion({ target, owner, busy, onContext, onEdit, onAdoptImage, onReference, onSuggest, onMainScript, onNavigate }: {
  target: CreatorTarget; owner: string; busy: boolean;
  onContext: (context?: WorkingImageContext) => void; onEdit: () => void; onAdoptImage: () => Promise<void>;
  onReference: (reference?: ProjectImageReference) => void;
  onMainScript?: (script?: ProjectMainScript) => void;
  onSuggest: (text: string, skill?: string) => void;
  onNavigate?: (node: CreatorTarget['node']) => void;
}) {
  const [project, setProject] = useState<CreatorProject>();
  const [working, setWorking] = useState<Awaited<ReturnType<typeof loadProject>>>();
  const [url, setUrl] = useState('');
  const [sourceUrl, setSourceUrl] = useState('');
  const [sourceError, setSourceError] = useState('');
  const [imageView, setImageView] = useState<'work' | 'source'>('work');
  const [error, setError] = useState('');
  const [readError, setReadError] = useState('');
  const [saving, setSaving] = useState(false);
  const serial = useRef(0);
  const source = useRef(target); source.current = target;
  async function reload() {
    const ticket = ++serial.current;
    try {
      const p = await getCreator(target.id);
      if (p.chat_id !== owner) throw new Error('这个商品不属于当前对话，请从总览重新进入。');
      const canvas = target.node === 'cover' && target.canvas ? await loadProject(target.canvas) : undefined;
      if (canvas && (canvas.project.archived || canvas.project.chat_id !== owner)) throw new Error('工作图关联已变化，请从商品总览重新进入。');
      if (canvas && canvasOrigin(p)?.image !== target.image) throw new Error('商品图片已更新，请从总览重新进入修图。');
      if (ticket !== serial.current) return;
      setProject(p); setWorking(canvas); setReadError('');
    } catch (e) { if (ticket === serial.current) { setReadError(e instanceof Error ? e.message : String(e)); setProject(undefined); setWorking(undefined); } }
  }
  useEffect(() => {
    setProject(undefined); setWorking(undefined); onContext(undefined);
    void reload();
    const timer = setInterval(() => void reload(), 2500);
    return () => { clearInterval(timer); ++serial.current; };
  }, [target.id, target.canvas, target.node, target.revision, owner]);
  useEffect(() => {
    const p = working?.project;
    const image = p?.document.layers.find(l => l.kind === 'image' && l.visible && !l.locked);
    onContext(p && image ? {project_id:p.id,revision:p.revision,layer_id:image.id,mode:'plan'} : undefined);
    return () => onContext(undefined);
  }, [working?.project.id, working?.project.revision, target.node]);
  const file = target.node === 'brief' ? project?.assets.source : project?.assets.cover || project?.assets.source;
  useEffect(() => {
    onReference(project && file ? {project:project.id,file} : undefined);
    return () => onReference(undefined);
  }, [project?.id,file?.id,target.node]);
  useEffect(() => {
    onMainScript?.(project?.script && project.chat_id===owner && project.flow?.script!=='review' && project.flow?.script!=='empty'
      ? {project:project.id,owner,text:project.script} : undefined);
    return () => onMainScript?.(undefined);
  }, [project?.id,project?.script,project?.flow?.script,owner,onMainScript]);
  useEffect(() => {
    let alive = true, link = '';
    setUrl('');
    const blob = target.node === 'cover' && working ? exportBlob(working.project.id, working.project.cursor) : project && file ? creatorBlob(project.id,file.id) : undefined;
    if (blob) void blob.then(value => { if (alive) { link = URL.createObjectURL(value); setUrl(link); } }).catch(() => { if (alive) setReadError('图片暂时无法读取，请稍后重试。'); });
    return () => { alive = false; if (link) URL.revokeObjectURL(link); };
  }, [project?.id,file?.id,target.node,working?.project.id,working?.project.revision]);
  useEffect(() => {
    const abort = new AbortController(); let link = '';
    setSourceUrl(''); setSourceError(''); setImageView('work');
    if (target.node === 'cover' && project?.assets.source) void creatorBlob(project.id,project.assets.source.id,abort.signal).then(blob=>{
      if(!abort.signal.aborted){link=URL.createObjectURL(blob);setSourceUrl(link);}
    }).catch(()=>{if(!abort.signal.aborted)setSourceError('原图参考暂时无法读取。');});
    return ()=>{abort.abort();if(link)URL.revokeObjectURL(link);};
  }, [project?.id,project?.assets.source?.id,target.node]);
  async function run(work: () => Promise<void>) {
    if (saving || busy) return;
    const before = source.current;
    setSaving(true); setError('');
    try { await work(); if (source.current.id === before.id && source.current.node === before.node) await reload(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setSaving(false); }
  }
  const canvas = working?.project;
  const jobs = working?.jobs || [];
  return <aside className={`project-companion ${target.node==='cover'?'studio-image-workbench':''}`} aria-label="当前创作结果">
    <div className="companion-heading"><div><strong>{target.node === 'video' ? '视频工作台' : target.node === 'script' ? '口播主稿' : target.node === 'brief' ? '商品与方向' : '图片工作台'}</strong><span>{target.node === 'cover' && canvas ? `工作版本 ${canvas.cursor}` : target.node==='script' ? project?.script ? project.flow?.script==='review' ? '待重新核对' : '已采用主稿' : '等待起稿' : ''}</span>{target.node==='cover'&&project&&<span className="studio-adopt-state">{project.flow?.cover==='review'?'采用图待复核':project.assets.cover?'采用图已保存':'尚无采用图'}</span>}</div></div>
    {(error || readError) && <p role="alert" className="companion-error">{error || readError}</p>}
    {!project && !readError && <p role="status">正在读取项目…</p>}
    {project && target.node === 'video' ? <ProjectVideo project={project} image={url} busy={busy || saving} onRun={run} onSuggest={onSuggest} onNavigate={onNavigate}/> : project && target.node === 'script' ? <>
      <ScriptWorkbench project={project} image={url} busy={busy} onSuggest={onSuggest}/>
      {project.flow?.script==='review'&&<div className="companion-adopted"><strong>项目资料已变化，主稿待重新核对</strong><p>检查商品事实、风格和采用图，继续打磨或确认现有主稿仍适用。</p><button disabled={busy||saving} onClick={()=>void run(async()=>{await saveCreator(project,{confirm:'script'});})}>确认主稿仍适用</button></div>}
    </> : project ? <>
      {target.node==='cover' && project?.assets.source && <nav className="studio-image-view" aria-label="图片预览版本"><button aria-pressed={imageView==='work'} onClick={()=>setImageView('work')}>当前工作图</button><button aria-pressed={imageView==='source'} onClick={()=>setImageView('source')}>原图参考</button>{imageView==='source'&&<span>参考原图 · 修改仍作用于工作图</span>}</nav>}
      <div className="studio-image-stage">{(imageView==='source' ? sourceUrl : url) ? <img className="companion-image" src={imageView==='source' ? sourceUrl : url} alt={target.node === 'cover' && imageView==='work' ? '当前工作图' : '商品原图'} /> : project && <div className="companion-placeholder">{imageView==='source' ? sourceError || '正在读取原图…' : file ? '正在准备图片…' : '先到项目资料放入原图'}</div>}</div>
      {target.node==='cover' && <div className="companion-image-actions"><button disabled={busy || saving || !canvas} onClick={onEdit}>打开画布精调 ↗</button><button className="primary-button" disabled={busy || saving || !canvas} onClick={()=>void run(onAdoptImage)}>采用工作图</button></div>}
      {target.node === 'brief' && project && <div className="companion-brief"><h3>已确认信息</h3><p>{project.facts || '尚未确定。和Chat核对可见特点与未知项，再采用创作方向。'}</p>{project.style && <p><b>风格</b> {project.style}</p>}</div>}
      {target.node === 'cover' && <>
        <div className="companion-adopted"><strong>{project?.assets.cover ? `项目采用图：${project.assets.cover.name}` : '项目还没有采用图片'}</strong><p>{project?.flow?.cover==='review'?'创作方向已变化，请重新核对采用图。':'后续视频使用项目采用图。工作预览修改后，点击“采用工作图”才会保存为采用图。'}</p></div>
        {canvas ? <ImagePlanPanel compact project={canvas} busy={busy || saving} activeJob={jobs.some(j=>j.state==='running'||j.state==='queued')} hasTarget={!!canvas.document.layers.find(l=>l.kind==='image' && l.visible && !l.locked)} canPlan
          onSend={async text=>{onSuggest(text);}} onRun={run} onRefresh={reload} /> : project && <div className="companion-note"><p>{file?'工作图尚未准备，请准备后开始修图。':'还没有商品原图，请从顶部“资料”上传。'}</p>{file&&<button disabled={busy||saving} onClick={onEdit}>准备工作图并打开画布</button>}</div>}
        {jobs.map(j => <details className="companion-candidate" key={j.id} open={j.revision===canvas?.revision && j.state==='succeeded' && !j.review}>
          <summary>{j.state==='running'||j.state==='queued' ? '正在生成候选…' : j.state==='succeeded' ? j.review?.decision==='reject' ? '历史候选 · 未采用' : '图片候选 · 待核对' : j.state==='failed' ? '候选生成失败' : '已取消的候选'}</summary>
          {j.error && <p role="status">{j.error}</p>}
          {j.output && canvas && working.assets.find(a=>a.id===j.source_id) && <>
            <ImageComparison owner={projectOwner(canvas.id)} source={working.assets.find(a=>a.id===j.source_id)!} output={j.output}/>
            <CandidateReview job={j} busy={busy || saving} onReview={(decision,checks,reason)=>void run(async()=>{await writeApi(`${projectPath(canvas.id)}/jobs/${j.id}/review`,'POST',{revision:canvas.revision,decision,checks,reason});})}>
              {ready=><button disabled={busy || saving || !ready || j.revision!==canvas.revision} onClick={()=>void run(async()=>{await writeApi(`${projectPath(canvas.id)}/jobs/${j.id}/adopt`,'POST',{revision:canvas.revision});})}>应用候选到工作图</button>}
            </CandidateReview>
            {j.revision!==canvas.revision && <p className="companion-note">这份候选基于旧版本，不能覆盖当前工作图。</p>}
          </>}
        </details>)}
      </>}
    </> : null}
  </aside>;
}
