import { useEffect, useRef, useState } from 'react';
import {capabilityGroups,skillGroup,type CapabilityGroup} from './capability-groups';
import { Icon } from './Icon';
import { readApi } from './management-api';
import { skillCommandAvailable, type CommandCatalog } from './skill-prompt';
import { skillDetails, skillReadiness, type InstalledSkill } from './skill-readiness';
import type { ChatController } from './chat-controller';
import type { ChatState } from './types';

export function SkillPicker({ controller, chat, selected, requiredSkill, defaultSkill, onClose, onChoose, onManage }: {
  controller: ChatController; chat: ChatState; selected?: string; onClose: () => void;
  onChoose: (name: string) => void; onManage: (tab?: 'skills' | 'tools') => void;
  requiredSkill?: string;
  defaultSkill?: string;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [skills, setSkills] = useState<InstalledSkill[]>([]);
  const [catalog, setCatalog] = useState<CommandCatalog>();
  const [query, setQuery] = useState('');
  const [group,setGroup]=useState<CapabilityGroup|'business'>('business');
  const [scope, setScope] = useState<'ready' | 'all'>('ready');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const tools = Object.values(chat.info.tools ?? {}).flat();
  useEffect(() => { dialog.current?.showModal(); dialog.current?.querySelector('input')?.focus(); return () => dialog.current?.close(); }, []);
  useEffect(() => {
    const abort = new AbortController();
    setLoading(true); setError('');
    void Promise.all([readApi<InstalledSkill[]>('/api/miniclaw/skills', abort.signal), controller.client.request<CommandCatalog>('commands.catalog', { session_id: chat.sessionId },15_000,abort.signal)])
      .then(([installed, commands]) => { if (!abort.signal.aborted) { setSkills(installed); setCatalog(commands); } })
      .catch(() => { if (!abort.signal.aborted) setError('暂时无法读取技能，请检查连接后重试。'); })
      .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [controller, chat.sessionId, revision]);
  function availability(skill: InstalledSkill) {
    const result = skillReadiness(skill, tools);
    if (result.state === 'ready' && (!catalog || !skillCommandAvailable(catalog, skill.name))) return { state: 'unverified', label: '调用入口不可用', reason: '当前会话没有独立技能入口，请检查管理设置。' };
    return result;
  }
  const ready = skills.filter(skill => availability(skill).state === 'ready');
  const priority: Record<string, number> = { ready: 0, missing: 1, unverified: 2, disabled: 3 };
  const ordered = [...skills].sort((left, right) => Number(right.name === selected) - Number(left.name === selected) || priority[availability(left).state] - priority[availability(right).state]);
  const visible = (requiredSkill ? ordered.filter(s=>s.name===requiredSkill) : scope === 'ready' ? ordered.filter(s=>availability(s).state==='ready') : ordered).filter(skill => {
    const detail = skillDetails(skill);
    if(!requiredSkill&&(group==='business'?skillGroup(skill)==='other':skillGroup(skill)!==group))return false;
    return `${detail.title} ${detail.description} ${skill.name}`.toLowerCase().includes(query.trim().toLowerCase());
  });
  return <dialog ref={dialog} className="skill-picker-dialog" aria-labelledby="skill-picker-heading" onCancel={onClose} onClick={event => { if (event.target === dialog.current) onClose(); }}>
    <header className="picker-header"><div><h2 id="skill-picker-heading">{requiredSkill ? '当前任务技能' : '选择技能'}</h2><p>{requiredSkill ? '修图任务固定使用修图方案。其他技能可在自由对话中选择。' : '选中的技能会在当前对话中持续使用，可手动移除或切换。'}</p></div><button className="icon-button" aria-label="关闭技能选择" onClick={onClose}><Icon name="close" /></button></header>
    {!requiredSkill&&<div className="picker-controls"><label className="picker-search"><Icon name="search" /><input aria-label="搜索技能" name="skill-search" autoComplete="off" placeholder="搜索用途或技能名称…" value={query} onChange={event => setQuery(event.target.value)} /></label>
      <div className="picker-scopes" aria-label="技能范围"><button aria-pressed={scope === 'ready'} onClick={() => setScope('ready')}>当前可用 <span>{loading ? '…' : ready.length}</span></button><button aria-pressed={scope === 'all'} onClick={() => setScope('all')}>查看配置 <span>{loading ? '…' : skills.length}</span></button></div>
    <div className="capability-filters" aria-label="选择技能分组"><button aria-pressed={group==='business'} onClick={()=>setGroup('business')}>宣传能力</button>{capabilityGroups.map(g=><button key={g.id} aria-pressed={group===g.id} onClick={()=>{setGroup(g.id);if(g.id==='other')setScope('all');}}>{g.title}</button>)}</div></div>}
    <div className="picker-list" aria-busy={loading}>
      {loading ? <p className="picker-empty" role="status">正在检查技能与当前工具…</p> : error ? <div className="picker-empty" role="alert"><p>{error}</p><button className="secondary-action" onClick={() => setRevision(value => value + 1)}>重试</button></div> : <>
        {visible.map(skill => { const detail = skillDetails(skill); const state = availability(skill); const canUse = state.state === 'ready'; return <article className={`picker-skill ${canUse ? 'ready' : ''}`} key={skill.name}>
          <div className="picker-skill-copy"><div className="picker-skill-title"><h3>{detail.title}</h3>{selected===skill.name&&defaultSkill===skill.name&&<span className="readiness ready">任务默认</span>}{!canUse&&<span className={`readiness ${state.state}`}>{state.label}</span>}</div><span className="skill-id">{capabilityGroups.find(g=>g.id===skillGroup(skill))?.title}</span><p>{detail.description}</p>{!canUse && <p className="skill-requirement">{state.reason}</p>}</div>
          <button className={canUse && selected===skill.name ? 'primary-action' : canUse ? 'secondary-action' : 'unavailable-action'} disabled={chat.running || chat.busy} onClick={() => canUse ? onChoose(skill.name) : onManage(state.state==='missing' ? 'tools' : 'skills')}>{canUse ? (selected === skill.name ? '当前使用' : '选择') : state.state==='missing' ? '检查工具' : '查看配置'}{canUse && selected===skill.name && <Icon name="check" size={16} />}</button>
        </article>; })}
        {!visible.length && <div className="picker-empty"><Icon name="search" size={28} /><h3>{requiredSkill ? '修图方案技能尚未安装' : query ? '没有找到相关技能' : '当前没有已验证可用的技能'}</h3><p>{requiredSkill ? '请在管理技能中安装 canvas-editor，再继续修图任务。' : query ? '试试“产品短片”“口播”或切换分组。' : '切换到查看配置，检查当前分组的运行条件。'}</p>{!query && <button className="secondary-action" onClick={() => requiredSkill ? onManage('skills') : setScope('all')}>{requiredSkill ? '管理技能' : '查看全部技能'}</button>}</div>}
      </>}
    </div>
    <footer className="picker-footer"><button className="secondary-action" onClick={()=>onManage()}><Icon name="settings" size={16} />管理技能</button></footer>
  </dialog>;
}
