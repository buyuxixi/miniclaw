import { useEffect, useState } from 'react';
import { creatorBase, creatorBlob, getCreator, saveCreator, uploadCreator, creationNodes, type CreatorContext, type CreatorFile, type CreatorProject } from './creator-api';
import { readApi, writeApi } from './management-api';
import { Icon } from './Icon';

export interface CreatorSummary { id: string; name: string; updated: number; chat_id?: string; preview?: CreatorFile; script_preview?: string; progress?: Record<string, boolean> }

export function CreatorPreview({ project, file }: { project: string; file?: CreatorFile }) {
  const [url, setUrl] = useState('');
  useEffect(() => {
    const abort = new AbortController(); let link = '';
    setUrl('');
    if (file) void creatorBlob(project, file.id, abort.signal).then(blob => { if (!abort.signal.aborted) { link = URL.createObjectURL(blob); setUrl(link); } }).catch(() => {});
    return () => { abort.abort(); if (link) URL.revokeObjectURL(link); };
  }, [project, file?.id]);
  return url ? <img src={url} alt="项目图片预览" /> : <div className="home-preview-empty"><Icon name="image" size={32} /><span>{file ? '正在准备预览' : '等待第一张商品图'}</span></div>;
}

export default function CreatorHome({ active, onChat, onStart, onDetails }: {
  active: boolean; onChat: () => void | Promise<unknown>;
  onStart: (p: CreatorProject, node: CreatorContext['node']) => Promise<unknown>; onDetails: (p: CreatorProject) => void;
}) {
  const [rows, setRows] = useState<CreatorSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [file, setFile] = useState<File>();
  const [query, setQuery] = useState('');
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (!active) return;
    const abort = new AbortController(); setLoading(true); setError('');
    void readApi<CreatorSummary[]>(`${creatorBase}/projects`, abort.signal).then(setRows).catch(e => { if (!abort.signal.aborted) setError(String(e)); }).finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [active, revision]);
  async function run(work: () => Promise<unknown>) {
    if (busy) return; setBusy(true); setError('');
    try { await work(); } catch(e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  }
  const visible = rows.filter(p => `${p.name} ${p.script_preview || ''}`.toLowerCase().includes(query.toLowerCase()));
  return <main className="creation-home" aria-label="创作看板">
    <aside className="home-sidebar"><div className="brand"><span className="brand-mark">m</span><strong>miniclaw</strong></div>
      <nav aria-label="主导航"><button aria-current="page"><Icon name="file"/>创作看板</button><button disabled={busy} onClick={()=>void run(async()=>onChat())}><Icon name="chat"/>新建自由对话</button></nav>
      <div className="home-sidebar-foot">个人工作区<span>本机保存</span></div>
    </aside>
    <div className="home-main">
      <section className="home-intro"><h1>创作看板</h1><button className="primary-button" onClick={() => setCreating(v => !v)} aria-expanded={creating}><Icon name="plus"/>新建创作</button></section>
      {creating && <form className="home-new-form" onSubmit={e => { e.preventDefault(); void run(async () => {
        let p = await writeApi<CreatorProject>(`${creatorBase}/projects`, 'POST', {name:name.trim() || '新创作任务'});
        p = await saveCreator(p,{method:'storyboard'});
        setRows(r => [{id:p.id,name:p.name,updated:Date.now()/1000},...r]);
        if (file) p = await uploadCreator(p,'source',file);
        setCreating(false); setName(''); setFile(undefined); setRevision(v => v+1);
        await onStart(p,'brief');
      }); }}><label>作品名称<input aria-label="作品名称" maxLength={80} autoFocus value={name} onChange={e => setName(e.target.value)} placeholder="例如：深绿茶壶 · 秋日上新"/></label><label className="home-file">商品原图 <small>也可以进入项目后补充</small><input type="file" aria-label="新作品商品原图" accept="image/png,image/jpeg,image/webp" onChange={e => setFile(e.target.files?.[0])}/></label><div><button className="primary-button" disabled={busy}>创建并开始对话</button><button type="button" disabled={busy} onClick={() => setCreating(false)}>取消</button></div></form>}
      {error && <p role="alert" className="creator-error">{error}<button onClick={() => setRevision(v => v+1)}>重新加载</button></p>}
      <section className="home-work-list"><header><div><h2>最近的创作</h2><p>{rows.length} 件作品</p></div><label className="home-search"><Icon name="search"/><input aria-label="搜索创作" placeholder="搜索作品或稿件" value={query} onChange={e => setQuery(e.target.value)}/></label></header>
        {loading && !rows.length ? <p role="status">正在读取创作记录…</p> : !visible.length ? <div className="home-empty"><h3>{query ? '没有找到这件作品' : '把第一件作品放进来'}</h3><p>上传商品原图，或者先和 Agent 聊聊你的创作目标。</p><button onClick={() => setCreating(true)}>新建创作</button></div> : <div className="home-grid">{visible.map(p => {
          const next = p.progress?.video ? 'video' : !p.progress?.brief ? 'brief' : !p.progress.cover ? 'cover' : !p.progress.script ? 'script' : 'video';
          return <article className="home-project" key={p.id}><div className="home-project-preview"><CreatorPreview project={p.id} file={p.preview}/><span className="home-project-badge">{p.progress?.video ? '已有成片' : p.progress?.script ? '口播已采用' : p.progress?.cover ? '图片已采用' : '创作中'}</span></div><div className="home-project-copy"><div className="home-project-title"><h3><button className="home-title-link" disabled={busy} onClick={() => void run(async()=>onStart(await getCreator(p.id),next))}>{p.name}</button></h3><button aria-label={`项目资料 ${p.name}`} disabled={busy} onClick={() => void run(async()=>onDetails(await getCreator(p.id)))}>···</button></div><p className="home-project-date">{new Date(p.updated*1000).toLocaleDateString('zh-CN',{month:'long',day:'numeric'})} 更新</p><p className="home-script-preview">{p.script_preview || '还没有采用口播稿。先确定商品特点，再开始表达。'}</p>
            <nav className="home-stages" aria-label={`${p.name}的创作步骤`}>{creationNodes.map(([node,label]) => <button key={node} disabled={busy} className={p.progress?.[node] ? 'done' : ''} onClick={() => void run(async()=>onStart(await getCreator(p.id),node))}>{label}<small>{p.progress?.[node] ? node==='brief'?'已确认':node==='video'?'已完成':'已采用' : '待完善'}</small></button>)}</nav>
            <button className="home-continue" disabled={busy} onClick={() => void run(async()=>onStart(await getCreator(p.id),next))}>{p.progress?.video ? '查看成片' : `打开${creationNodes.find(n => n[0]===next)?.[1]}`}<span aria-hidden="true">→</span></button></div></article>;
        })}</div>}
      </section>
    </div>
  </main>;
}
