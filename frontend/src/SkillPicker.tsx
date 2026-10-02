import { useEffect, useRef, useState } from 'react';
import { Icon } from './Icon';
import { readApi } from './management-api';
import { skillCommandAvailable, type CommandCatalog } from './skill-prompt';
import { skillDetails, skillReadiness, type InstalledSkill } from './skill-readiness';
import type { ChatController } from './chat-controller';
import type { ChatState } from './types';

export function SkillPicker({ controller, chat, selected, onClose, onChoose, onManage }: {
  controller: ChatController; chat: ChatState; selected?: string; onClose: () => void;
  onChoose: (name: string) => void; onManage: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [skills, setSkills] = useState<InstalledSkill[]>([]);
  const [catalog, setCatalog] = useState<CommandCatalog>();
  const [query, setQuery] = useState('');
  const [scope, setScope] = useState<'ready' | 'all'>('ready');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const tools = Object.values(chat.info.tools ?? {}).flat();
  useEffect(() => { dialog.current?.showModal(); return () => dialog.current?.close(); }, []);
  useEffect(() => {
    const abort = new AbortController();
    setLoading(true); setError('');
    void Promise.all([readApi<InstalledSkill[]>('/api/skills', abort.signal), controller.client.request<CommandCatalog>('commands.catalog', { session_id: chat.sessionId })])
      .then(([installed, commands]) => { if (!abort.signal.aborted) { setSkills(installed); setCatalog(commands); } })
      .catch(reason => { if (!abort.signal.aborted) setError(String(reason)); })
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
  const ordered = [...skills].sort((left, right) => priority[availability(left).state] - priority[availability(right).state]);
  const visible = (scope === 'ready' ? ready : ordered).filter(skill => {
    const detail = skillDetails(skill);
    return `${detail.title} ${detail.description} ${skill.name}`.toLowerCase().includes(query.trim().toLowerCase());
  });
  return <dialog ref={dialog} className="skill-picker-dialog" aria-labelledby="skill-picker-heading" onCancel={onClose} onClick={event => { if (event.target === dialog.current) onClose(); }}>
    <header className="picker-header"><div><h2 id="skill-picker-heading">选择技能</h2><p>为这次任务选择一个合适的流程。</p></div><button className="icon-button" aria-label="关闭技能选择" onClick={onClose}><Icon name="close" /></button></header>
    <div className="picker-controls"><label className="picker-search"><Icon name="search" /><input aria-label="搜索技能" name="skill-search" autoComplete="off" placeholder="搜索用途或技能名称…" value={query} onChange={event => setQuery(event.target.value)} /></label>
      <div className="picker-scopes" aria-label="技能范围"><button aria-pressed={scope === 'ready'} onClick={() => setScope('ready')}>当前可用 <span>{loading ? '…' : ready.length}</span></button><button aria-pressed={scope === 'all'} onClick={() => setScope('all')}>全部技能 <span>{loading ? '…' : skills.length}</span></button></div>
    </div>
    <div className="picker-list" aria-busy={loading}>
      {loading ? <p className="picker-empty" role="status">正在检查技能与当前工具…</p> : error ? <div className="picker-empty" role="alert"><p>{error}</p><button className="secondary-action" onClick={() => setRevision(value => value + 1)}>重试</button></div> : <>
        {visible.map(skill => { const detail = skillDetails(skill); const state = availability(skill); const canUse = state.state === 'ready'; return <article className={`picker-skill ${canUse ? 'ready' : ''}`} key={skill.name}>
          <div className="picker-skill-copy"><div className="picker-skill-title"><h3>{detail.title}</h3><span className={`readiness ${state.state}`}>{state.label}</span></div><span className="skill-id" translate="no">{skill.name}</span><p>{detail.description}</p>{!canUse && <p className="skill-requirement">{state.reason}</p>}</div>
          <button className={canUse ? 'primary-action' : 'unavailable-action'} disabled={!canUse || chat.running || chat.busy} onClick={() => onChoose(skill.name)}>{canUse ? (selected === skill.name ? '已选择' : '选择') : '暂不可用'}{canUse && <Icon name="check" size={16} />}</button>
        </article>; })}
        {!visible.length && <div className="picker-empty"><Icon name="search" size={28} /><h3>{query ? '没有找到相关技能' : '当前没有已验证可用的技能'}</h3><p>{query ? '试试用途关键词，例如“文档”或“改写”。' : '查看全部技能，了解需要补齐哪些工具。'}</p>{!query && <button className="secondary-action" onClick={() => setScope('all')}>查看全部技能</button>}</div>}
      </>}
    </div>
    <footer className="picker-footer"><p>已安装的技能还需要对应的工具与运行环境。</p><button className="secondary-action" onClick={onManage}><Icon name="settings" size={16} />管理技能</button></footer>
  </dialog>;
}
