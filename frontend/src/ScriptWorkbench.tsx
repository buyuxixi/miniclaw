import { useState } from 'react';
import type { CreatorProject } from './creator-api';

export function ScriptWorkbench({project:p,image,busy,onSuggest}:{project:CreatorProject;image:string;busy:boolean;onSuggest:(text:string)=>void}) {
  const [copyState,setCopyState]=useState('');
  const [factsOpen,setFactsOpen]=useState(()=>window.innerWidth>650);
  const count=Array.from(p.script.replace(/\s/g,'')).length;
  const lines=p.script.split(/\n+/).filter(s=>s.trim());
  function refine(request:string) {onSuggest(`基于本项目最新资料和已采用主稿，${request}。保留已确认事实，不新增功效或未确认信息。先给候选主稿，等待我采用。`);}
  return <div className="studio-script-workgrid">
    <aside className="script-context" aria-label="口播参考"><h3>图文一起核对</h3>{image&&<img src={image} alt={p.assets.cover?'项目采用图':'商品参考图'}/>}
      <span>{p.assets.cover ? p.flow?.cover==='review'?'采用图待核对':'项目采用图' : '原图参考'}</span>
      {p.facts&&<details open={factsOpen} onToggle={event=>setFactsOpen(event.currentTarget.open)}><summary>商品事实</summary><p>{p.facts}</p></details>}{p.style&&<details><summary>表达风格</summary><p>{p.style}</p></details>}
      {p.constraints&&<details><summary>保留与避免</summary><p>{p.constraints}</p></details>}
    </aside>
    <div className="script-editorial"><div className="script-utilities"><span title="朗读时间为估计">{count ? `${count} 字 · 约 ${Math.max(1,Math.round(count/4))} 秒` : '等待第一版主稿'}</span>{count>0&&<div><button disabled={busy} onClick={()=>void navigator.clipboard.writeText(p.script).then(()=>setCopyState('已复制'),()=>setCopyState('复制失败，请选中文字复制'))}>{copyState || '复制主稿'}</button><a download={`${p.name}-口播.txt`} href={`data:text/plain;charset=utf-8,${encodeURIComponent(p.script)}`}>下载 TXT</a></div>}</div>
      <article className="studio-script-document"><div className="companion-script">{lines.length ? lines.map((text,index)=><div className="script-line" key={`${index}:${text}`}><p>{text}</p><button disabled={busy} aria-label={`打磨第${index+1}段`} onClick={()=>refine(`只打磨这一段：“${text}”，其他段落保持不变`)}>打磨这段 ↗</button></div>) : '先和 Agent 起一稿，再逐句打磨。'}</div></article>
      <section className="script-refine" aria-label="打磨主稿"><h3>{count ? '想从哪里改起？' : '开始口播创作'}</h3><div>{count ? <><button disabled={busy} onClick={()=>refine('让表达更自然口语，减少书面语')}>更口语</button><button disabled={busy} onClick={()=>refine('只优化开头，让第一句更直接')}>优化开头</button><button disabled={busy} onClick={()=>refine('把篇幅压缩约三分之一，保留核心事实')}>缩短篇幅</button><button className="primary-button" disabled={busy} onClick={()=>refine('帮我整体打磨，先给一版候选稿')}>继续打磨主稿</button></> : <button className="primary-button" disabled={busy} onClick={()=>refine('根据已确认的商品特点、受众和风格起一版自然口语的口播稿')}>让 Chat 起一稿</button>}</div><p>新稿确认后才替换主稿。</p></section>
    </div>
  </div>;
}
