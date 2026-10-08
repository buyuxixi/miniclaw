import { useEffect, useState } from 'react';
import { readApi, writeApi } from './management-api';
import {capabilityGroups, toolGroup} from './capability-groups';
import {Icon} from './Icon';
interface Group { id: string; title: string; description: string; tools: string[]; enabled: boolean; required: boolean }
export function ToolPreferences({ loaded, blocked, onBusy }: { loaded: string[]; blocked: boolean; onBusy: (busy: boolean) => void }) {
  const [groups,setGroups]=useState<Group[]>();const [busy,setBusy]=useState(false);const [error,setError]=useState('');const [notice,setNotice]=useState('');const [other,setOther]=useState<string[]>([]);const [query,setQuery]=useState('');const [revision,setRevision]=useState(0);
  useEffect(()=>{const abort=new AbortController();setError('');void readApi<{groups:Group[];other_configured:string[]}>('/api/miniclaw/tools',abort.signal).then(r=>{if(!abort.signal.aborted){setGroups(r.groups);setOther(r.other_configured);}}).catch(e=>{if(!abort.signal.aborted)setError(String(e));});return()=>abort.abort();},[revision]);
  useEffect(()=>{onBusy(busy);},[busy,onBusy]);
  async function toggle(group:Group){if(blocked||busy)return;setBusy(true);setError('');try{const next=groups!.map(g=>g.id===group.id?{...g,enabled:!g.enabled}:g);await writeApi('/api/miniclaw/tools','PUT',{enabled:next.filter(g=>g.enabled).map(g=>g.id)});setGroups(next);setNotice('已保存。新建对话应用这次配置，当前对话的工具保持不变。');}catch(e){setError(String(e));}finally{setBusy(false);}}
  return <><p className="settings-description">技能决定工作流程，工具决定助手能执行的操作。</p>
    <label className="settings-search"><Icon name="search"/><input aria-label="搜索工具" placeholder="搜索图片编辑、动效或资料读取" value={query} onChange={e=>setQuery(e.target.value)}/></label>
    <div className="list-caption">{groups?`${groups.filter(g=>g.enabled).length} 组已启用 · ${loaded.length} 项工具已加载到当前对话`:'正在读取配置…'}</div>
    {error&&<div className="settings-error" role="alert">{error}<button onClick={()=>setRevision(v=>v+1)}>重试</button></div>}{notice&&<p className="settings-notice" role="status">{notice}</p>}
    {capabilityGroups.map(category=>{const rows=groups?.filter(g=>toolGroup(g.id)===category.id&&`${g.title} ${g.description} ${g.tools.join(' ')}`.toLowerCase().includes(query.toLowerCase()))??[];return rows.length>0&&<section className="capability-section" key={category.id}><header><h3>{category.title}</h3><span>{category.description}</span></header>{rows.map(g=><article className="skill-card" key={g.id}><div className="capability-mark"><Icon name={category.id==='image'?'image':category.id==='video'?'video':'file'}/></div><div className="skill-copy"><div className="managed-skill-title"><h3>{g.title}</h3><span className={`readiness ${g.enabled?'ready':'disabled'}`}>{g.required?'基础能力':g.enabled?'已启用':'未启用'}</span></div><p>{g.description}</p><details className="tool-detail"><summary>{g.tools.filter(t=>loaded.includes(t)).length} / {g.tools.length} 项已加载到本对话<span>查看工具明细</span></summary>{g.tools.map(t=><div className="tool-state" key={t}><code>{t}</code>{g.tools.some(t=>loaded.includes(t))&&<span className={loaded.includes(t)?'status-pill':'value-pill'}>{loaded.includes(t)?'已加载':'未加载'}</span>}</div>)}</details></div><button role="switch" className="toggle" aria-label={`启用${g.title}`} aria-checked={g.enabled} disabled={blocked||busy||g.required||!!other.length} onClick={()=>void toggle(g)}><span/></button></article>)}</section>;})}
    {groups&&!groups.some(g=>`${g.title} ${g.description} ${g.tools.join(' ')}`.toLowerCase().includes(query.toLowerCase()))&&<div className="settings-empty"><h3>没有匹配的工具</h3><p>调整搜索关键词。</p></div>}
    {!!other.length&&<p className="settings-note">其他后端配置：{other.join('、')}。请在后端维护这些配置。</p>}
    <p className="settings-note">工具变更在新对话中生效。开启收费模型后，生成结果仍需你确认采用。</p>
  </>;
}
