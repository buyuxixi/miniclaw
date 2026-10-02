import { useEffect, useState } from 'react';
import { readApi, writeApi } from './management-api';
interface Group { id: string; title: string; description: string; tools: string[]; enabled: boolean; required: boolean }
export function ToolPreferences({ loaded, blocked, onBusy }: { loaded: string[]; blocked: boolean; onBusy: (busy: boolean) => void }) {
  const [groups, setGroups] = useState<Group[]>(); const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [notice, setNotice] = useState(''); const [other, setOther] = useState<string[]>([]);
  useEffect(() => { const abort = new AbortController(); void readApi<{ groups: Group[]; other_configured: string[] }>('/api/miniclaw/tools', abort.signal).then(r => { setGroups(r.groups); setOther(r.other_configured); }).catch(e => { if (!abort.signal.aborted) setError(String(e)); }); return () => abort.abort(); }, []);
  useEffect(() => { onBusy(busy); }, [busy, onBusy]);
  async function toggle(group: Group) { if (blocked || busy) return; setBusy(true); setError(''); try { const next = groups!.map(g => g.id === group.id ? { ...g, enabled: !g.enabled } : g); await writeApi('/api/miniclaw/tools', 'PUT', { enabled: next.filter(g => g.enabled).map(g => g.id) }); setGroups(next); setNotice('配置已保存。新建对话后应用；当前对话仍使用已加载的工具。'); } catch (e) { setError(String(e)); } finally { setBusy(false); } }
  return <><p className="settings-description">控制 Agent 能实际执行的操作。技能依赖与工具权限分别设置。</p>{error && <p className="settings-error" role="alert">{error}</p>}{notice && <p className="settings-notice" role="status">{notice}</p>}
    {!groups && !error && <p role="status">加载工具配置…</p>}
    {groups?.map(g => <article className="skill-card" key={g.id}><div className="skill-copy"><h3>{g.title}</h3><p>{g.description}</p>{g.tools.map(t => <div className="tool-state" key={t}><code>{t}</code><span className={loaded.includes(t) ? 'status-pill' : 'value-pill'}>{loaded.includes(t) ? '本对话已加载' : '本对话未加载'}</span></div>)}</div><button role="switch" className="toggle" aria-label={`启用${g.title}`} aria-checked={g.enabled} disabled={blocked || busy || g.required || !!other.length} onClick={() => void toggle(g)}><span /></button></article>)}
    {!!other.length && <p className="settings-note">检测到其他后端工具配置：{other.join('、')}。页面不覆盖这些配置。</p>}
    <p className="settings-note">工具设置在新对话中生效。这里只开放本项目注册的受限工具；自定义工具/MCP适配器可通过版本化绑定契约扩展。</p></>;
}
