import { useEffect, useState } from 'react';
import { readApi, searchSessions, writeApi } from './management-api';
import type { ChatController } from './chat-controller';
import type { ChatState, SessionRow } from './types';
import { Icon } from './Icon';

export function SidebarSessions({ controller, chat, onSelect }: { controller: ChatController; chat: ChatState; onSelect: () => void }) {
  const [query, setQuery] = useState('');
  const [rows, setRows] = useState<SessionRow[]>([]);
  const [limit, setLimit] = useState(20);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [editing, setEditing] = useState('');
  const [name, setName] = useState('');
  const [saving, setSaving] = useState(false);
  const blocked = chat.running || chat.busy || saving || controller.connection !== 'open';
  useEffect(() => {
    const abort = new AbortController();
    if (controller.connection !== 'open') return;
    setLoading(true); setError('');
    const timer = setTimeout(() => {
      const task: Promise<{ sessions?: SessionRow[]; total?: number }> = query.trim()
        ? searchSessions(query.trim(), abort.signal).then(sessions => ({ sessions, total: sessions.length }))
        : (async () => {
          const sessions: SessionRow[] = []; let count = 0;
          for (let offset = 0; offset < limit; offset += 100) {
            const result = await readApi<{ sessions: SessionRow[]; total: number }>(`/api/sessions?limit=${Math.min(100, limit - offset)}&offset=${offset}&order=recent&exclude_sources=cron,delegate,kanban`, abort.signal);
            sessions.push(...result.sessions); count = result.total;
            if (sessions.length >= count || !result.sessions.length) break;
          }
          return { sessions, total: count };
        })();
      void task.then(result => { if (!abort.signal.aborted) { setRows(result.sessions ?? []); setTotal(result.total ?? 0); } })
        .catch(reason => { if (!abort.signal.aborted) setError(String(reason)); })
        .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    }, query ? 250 : 0);
    return () => { clearTimeout(timer); abort.abort(); };
  }, [query, limit, revision, chat.sessions, controller.connection]);
  async function rename(row: SessionRow) {
    if (blocked || !name.trim()) return;
    setSaving(true); setError('');
    try {
      if (row.id === chat.storedId) {
        if (!await controller.rename(name)) throw new Error(controller.state.error || '改名失败');
      } else {
        await writeApi(`/api/sessions/${encodeURIComponent(row.id)}`, 'PATCH', { title: name.trim() });
        await controller.refresh();
      }
      setEditing(''); setRevision(value => value + 1);
    } catch (reason) { setError(String(reason)); }
    finally { setSaving(false); }
  }
  return <>
    <label className="sidebar-search"><Icon name="search" size={17} /><input name="session-search" autoComplete="off" aria-label="搜索对话" value={query} placeholder="搜索对话" onChange={event => { setQuery(event.target.value); setEditing(''); }} />{query && <button aria-label="清除搜索" onClick={() => setQuery('')}><Icon name="close" size={14} /></button>}</label>
    <div className="section-label">{query ? '搜索结果' : '最近对话'}{loading && <span> · 查找中</span>}</div>
    <nav className="session-list" aria-label="历史对话">
      {error && <p className="sidebar-error" role="alert">{error}</p>}
      {rows.map(row => <div className={`session-row ${row.id === chat.storedId ? 'selected' : ''}`} key={row.id}>
        {editing === row.id ? <form className="rename-form" onSubmit={event => { event.preventDefault(); void rename(row); }}>
          <input name="session-title" autoComplete="off" aria-label="对话名称" autoFocus maxLength={200} value={name} onChange={event => setName(event.target.value)} onKeyDown={event => { if (event.key === 'Escape') setEditing(''); }} />
          <button aria-label="保存对话名称" disabled={blocked || !name.trim()}><Icon name="check" size={16} /></button><button type="button" aria-label="取消改名" onClick={() => setEditing('')}><Icon name="close" size={16} /></button>
        </form> : <><button className="session" title={row.title || row.preview} disabled={blocked} onClick={() => { void controller.open(row.id); onSelect(); }}><span>{row.title || row.preview || '未命名对话'}</span></button>
          <button className="session-action" title="重命名" aria-label={`重命名 ${row.title || '未命名对话'}`} disabled={blocked} onClick={() => { setEditing(row.id); setName(row.title || ''); }}><Icon name="edit" size={15} /></button></>}
      </div>)}
      {!loading && !rows.length && <p className="sessions-empty">{query ? '没有找到相关对话' : '开始聊天后，对话会保存在这里'}</p>}
      {!query && rows.length < total && <button className="load-sessions" disabled={loading} onClick={() => setLimit(value => value + 20)}>加载更早的对话</button>}
    </nav>
  </>;
}
