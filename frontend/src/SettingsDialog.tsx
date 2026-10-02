import { useEffect, useRef, useState } from 'react';
import { readApi, writeApi } from './management-api';
import { ContextPanel } from './ContextPanel';
import type { ChatController } from './chat-controller';
import type { ChatState } from './types';
import { Icon, type IconName } from './Icon';
import { SkillEditor } from './SkillEditor';
import { ToolPreferences } from './ToolPreferences';
import { MemoryEditor } from './MemoryEditor';
import { skillDetails, skillReadiness, type InstalledSkill } from './skill-readiness';

type Tab = 'general' | 'skills' | 'tools' | 'memory' | 'developer';
type Skill = InstalledSkill;
interface MemoryConfig { memory_enabled: boolean; user_profile_enabled: boolean }
const tabs: { id: Tab; label: string; icon: string }[] = [{ id: 'general', label: '通用', icon: '◈' }, { id: 'skills', label: '技能', icon: '✧' }, { id: 'tools', label: '工具', icon: '⌘' }, { id: 'memory', label: '记忆', icon: '◎' }, { id: 'developer', label: '开发者', icon: '‹›' }];

export function SettingsDialog({ controller, chat, onClose, initialTab = 'general' }: { controller: ChatController; chat: ChatState; onClose: () => void; initialTab?: Tab }) {
  const [tab, setTab] = useState<Tab>(initialTab);
  const [skills, setSkills] = useState<Skill[]>();
  const [filter, setFilter] = useState('');
  const [memory, setMemory] = useState<MemoryConfig>();
  const [memoryOriginal, setMemoryOriginal] = useState('');
  const memoryDirty = Boolean(memory) && JSON.stringify(memory) !== memoryOriginal;
  const [memoryBytes, setMemoryBytes] = useState({ memory: 0, user: 0 });
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [revision, setRevision] = useState(0);
  const [editor, setEditor] = useState<{ name?: string }>();
  const [dirty, setDirty] = useState(false);
  const [pendingLeave, setPendingLeave] = useState<() => void>();
  function leave(action: () => void) {
    if (busy) return;
    if (dirty || memoryDirty) { setPendingLeave(() => action); return; }
    action();
  }
  const [diagnostics, setDiagnostics] = useState(false);
  const root = useRef<HTMLDialogElement>(null);
  const blocked = chat.running || chat.busy || busy || loading || controller.connection !== 'open';
  useEffect(() => { root.current?.showModal(); return () => { root.current?.close(); }; }, []);
  useEffect(() => {
    const abort = new AbortController();
    setError('');
    if (tab !== 'skills' && tab !== 'memory') return;
    setLoading(true);
    const task = tab === 'skills' ? readApi<Skill[]>('/api/miniclaw/skills', abort.signal).then(result => { if (!abort.signal.aborted) setSkills(result); })
      : Promise.all([readApi<{ memory: MemoryConfig }>('/api/config', abort.signal), readApi<{ builtin_files: { memory: number; user: number } }>('/api/memory', abort.signal)])
        .then(([config, state]) => { if (!abort.signal.aborted) { setMemory(config.memory); setMemoryOriginal(JSON.stringify(config.memory)); setMemoryBytes(state.builtin_files); } });
    void task.catch(reason => { if (!abort.signal.aborted) setError(String(reason)); })
      .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [tab, revision, chat.sessionId, controller]);
  async function action(task: () => Promise<void>) {
    if (blocked) return;
    setBusy(true); setError(''); setNotice('');
    try { await task(); } catch (reason) { setError(String(reason)); }
    finally { setBusy(false); }
  }
  async function toggleSkill(skill: Skill) {
    await action(async () => {
      await writeApi('/api/skills/toggle', 'PUT', { name: skill.name, enabled: !skill.enabled });
      setSkills(current => current?.map(row => row.name === skill.name ? { ...row, enabled: !row.enabled } : row));
      setRevision(v => v + 1);
      setNotice('设置已保存。选择技能发送前会重新检查启用状态。');
    });
  }
  function viewSkill(skill: Skill) { setEditor({ name: skill.name }); }
  return <dialog ref={root} className="settings-dialog" aria-label="设置" onCancel={event => { event.preventDefault(); if (pendingLeave) setPendingLeave(undefined); else leave(onClose); }} onClick={event => { if (event.target === root.current && !pendingLeave) leave(onClose); }}>
    <div className="settings-layout" inert={Boolean(pendingLeave)}>
      <aside className="settings-nav"><div className="settings-brand">miniclaw <span>设置</span></div><nav>{tabs.map(item => <button key={item.id} className={tab === item.id ? 'active' : ''} aria-pressed={tab === item.id} disabled={busy} onClick={() => leave(() => { setTab(item.id); setEditor(undefined); setNotice(''); })}><Icon name={(({ general: "settings", skills: "skills", tools: "file", memory: "chat", developer: "edit" } as Record<Tab, IconName>)[item.id])} />{item.label}</button>)}</nav><p>个人工作区 · 本机</p></aside>
      <div className="settings-content"><header><h2>{tabs.find(item => item.id === tab)?.label}</h2><button className="close-settings" aria-label="关闭设置" disabled={busy} onClick={() => leave(onClose)}><Icon name="close" /></button></header>
        <div className="settings-scroll">
          {error && <div className="settings-error" role="alert">{error}</div>}{notice && <div className="settings-notice" role="status">{notice}</div>}
          {loading && <p className="muted">正在加载…</p>}
          {tab === 'general' && <>
            <p className="settings-description">你的聊天与 Agent 工作空间。</p>
            <div className="preference-row"><div><strong>当前模型</strong><p>{chat.info.provider || '本机配置'}</p></div><span className="value-pill">{chat.info.model || '未连接'}</span></div>
            <div className="preference-row"><div><strong>服务连接</strong><p>断线后可重新连接，继续已保存的对话。</p></div><button disabled={controller.connection === 'open' || controller.connection === 'connecting'} onClick={() => void controller.connect()}>重新连接</button></div>
            <div className="preference-row"><div><strong>聊天记录</strong><p>自动保存在本机。刷新或重启后可继续聊天。</p></div><span className="status-pill">自动保存</span></div>
            <div className="settings-note">模型和服务凭据在后端配置中管理。</div>
          </>}
          {tab === 'skills' && <>
            <div className="settings-intro"><p className="settings-description">在这里管理已安装的流程。使用时，从消息输入框旁的“选择技能”进入；是否能执行还取决于工具与运行环境。</p><div className="settings-intro-actions"><button className="primary-button" disabled={blocked} onClick={() => setEditor({})}>添加技能</button><button disabled={blocked} onClick={() => void action(async () => { const result = await controller.client.request<{ result: { total: number } }>('skills.reload', { session_id: chat.sessionId }); setRevision(v => v + 1); setNotice(`已重新扫描 ${result.result.total} 个可用技能。`); })}>重新扫描</button></div></div>
            {editor ? <SkillEditor key={editor.name ?? 'new'} name={editor.name} controller={controller} sessionId={chat.sessionId} blocked={chat.running || chat.busy || controller.connection !== 'open'} onBack={() => leave(() => { setEditor(undefined); setRevision(v => v + 1); })} onSaved={() => setRevision(v => v + 1)} onDirty={setDirty} onBusy={setBusy} />
              : <><label className="settings-search"><Icon name="search" /><input name="manage-skill-search" autoComplete="off" aria-label="搜索技能" placeholder="搜索技能名称或用途" value={filter} onChange={event => setFilter(event.target.value)} /></label><div className="list-caption">{skills ? `${skills.length} 个技能 · ${skills.filter(s => s.enabled).length} 个已开启` : ''}</div><div className="skill-list">{skills?.filter(skill => `${skillDetails(skill).title} ${skill.name} ${skill.description}`.toLowerCase().includes(filter.toLowerCase())).map(skill => <article className="skill-card" key={skill.name}><div className="skill-copy"><div className="managed-skill-title"><h3>{skillDetails(skill).title}</h3><span className={`readiness ${skillReadiness(skill, Object.values(chat.info.tools ?? {}).flat()).state}`}>{skillReadiness(skill, Object.values(chat.info.tools ?? {}).flat()).label}</span></div><span className="skill-id" translate="no">{skill.name}</span><p>{skillDetails(skill).description}</p><p className="skill-requirement">{skillReadiness(skill, Object.values(chat.info.tools ?? {}).flat()).reason}</p><button className="text-button" disabled={blocked} onClick={() => void viewSkill(skill)}>查看与编辑</button></div><button role="switch" className="toggle" aria-checked={skill.enabled} aria-label={`启用技能 ${skill.name}`} disabled={blocked} onClick={() => void toggleSkill(skill)}><span /></button></article>)}</div>{skills?.length === 0 && <div className="settings-empty"><span>✧</span><h3>还没有可用技能</h3><p>将技能安装到本机后，点击重新扫描。</p></div>}</>}
          </>}
          {tab === 'tools' && <ToolPreferences loaded={Object.values(chat.info.tools ?? {}).flat()} blocked={chat.running || chat.busy || controller.connection !== 'open'} onBusy={setBusy} />}
          {tab === 'memory' && <>
            <p className="settings-description">当前对话中的记忆与跨对话保留的信息分别管理。</p>
            <div className="preference-row"><div><strong>对话记忆</strong><p>使用当前会话的历史继续交流。新建对话从新的历史开始。</p></div><span className="status-pill">已启用</span></div>
            {memory && <><div className="preference-row"><div><strong>长期记忆</strong><p>把已保存的事实带入新对话。当前保存 {memoryBytes.memory} 字节。</p></div><button role="switch" className="toggle" aria-label="启用长期记忆" aria-checked={memory.memory_enabled} disabled={blocked} onClick={() => setMemory({ ...memory, memory_enabled: !memory.memory_enabled })}><span /></button></div>
              <div className="preference-row"><div><strong>个人偏好</strong><p>使用已保存的用户偏好。当前保存 {memoryBytes.user} 字节。</p></div><button role="switch" className="toggle" aria-label="启用个人偏好" aria-checked={memory.user_profile_enabled} disabled={blocked} onClick={() => setMemory({ ...memory, user_profile_enabled: !memory.user_profile_enabled })}><span /></button></div>
              <div className="settings-note">这些开关控制记忆加载。可以在下方手动维护内容；模型自动写入记忆尚未开放。</div>
              <div className="editor-footer"><span>保存后在新对话中应用</span><button className="primary-button" disabled={blocked || !memoryDirty} onClick={() => void action(async () => { await writeApi('/api/config', 'PUT', { config: { memory } }); setMemoryOriginal(JSON.stringify(memory)); setNotice('记忆设置已保存。新对话会按这些设置加载记忆。'); })}>保存设置</button></div>
            </>}
          </>}
          {tab === 'memory' && <MemoryEditor sessionId={chat.sessionId} blocked={chat.running || chat.busy || controller.connection !== 'open'} onBusy={setBusy} onDirty={setDirty} />}
          {tab === 'developer' && <><p className="settings-description">用于学习和排查 Agent 的上下文加载、工具调用及用量。不会出现在普通聊天中。</p><button aria-expanded={diagnostics} onClick={() => setDiagnostics(v => !v)}>上下文诊断</button>{diagnostics && <ContextPanel controller={controller} chat={chat} />}</>}
        </div>
      </div>
    </div>
    {pendingLeave && <div className="confirm-scrim"><section className="confirm-card" role="alertdialog" aria-modal="true" aria-labelledby="discard-title"><h3 id="discard-title">还有未保存的修改</h3><p>离开会丢弃这次编辑，已经保存的内容会保留。</p><div><button autoFocus onClick={() => setPendingLeave(undefined)}>继续编辑</button><button className="primary-button" onClick={() => { const action = pendingLeave; setPendingLeave(undefined); setDirty(false); setMemoryOriginal(JSON.stringify(memory)); action(); }}>放弃修改并离开</button></div></section></div>}
  </dialog>;
}
