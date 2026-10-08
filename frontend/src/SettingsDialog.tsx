import { useEffect, useRef, useState } from 'react';
import {capabilityGroups, skillGroup, type CapabilityGroup} from './capability-groups';
import { ActionMenu } from './ActionMenu';
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
  const [group,setGroup]=useState<CapabilityGroup|'business'>('business');
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
      <aside className="settings-nav"><div className="settings-brand">miniclaw <span>产品宣传工作台</span></div><nav>{tabs.map(item => <button key={item.id} className={tab === item.id ? 'active' : ''} aria-pressed={tab === item.id} disabled={busy} onClick={() => leave(() => { setTab(item.id); setEditor(undefined); setNotice(''); })}><Icon name={(({ general: "settings", skills: "skills", tools: "file", memory: "chat", developer: "edit" } as Record<Tab, IconName>)[item.id])} />{item.label}</button>)}</nav><p>个人工作区 · 本机</p></aside>
      <div className="settings-content"><header><div><span className="form-eyebrow">工作台设置</span><h2>{tabs.find(item => item.id === tab)?.label}</h2></div><button className="close-settings" aria-label="关闭设置" disabled={busy} onClick={() => leave(onClose)}><Icon name="close" /></button></header>
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
            <div className="settings-intro"><p className="settings-description">按宣传工作流程组织技能，执行条件与启用状态分别显示。</p><div className="settings-intro-actions"><button className="primary-button" disabled={blocked} onClick={() => setEditor({})}>添加技能</button><ActionMenu label="更多"><button disabled={blocked} onClick={() => void action(async () => { const result = await controller.client.request<{ result: { total: number } }>('skills.reload', { session_id: chat.sessionId }); setRevision(v => v + 1); setNotice(`已重新扫描 ${result.result.total} 个已安装技能。执行能力以当前对话工具为准。`); })}>重新扫描</button></ActionMenu></div></div>
            {editor ? <SkillEditor key={editor.name ?? 'new'} name={editor.name} controller={controller} sessionId={chat.sessionId} blocked={chat.running || chat.busy || controller.connection !== 'open'} onBack={() => leave(() => { setEditor(undefined); setRevision(v => v + 1); })} onSaved={() => setRevision(v => v + 1)} onDirty={setDirty} onBusy={setBusy} />
              : <>
                <label className="settings-search"><Icon name="search"/><input name="manage-skill-search" autoComplete="off" aria-label="搜索技能" placeholder="搜索用途，例如：产品短片、封面、口播" value={filter} onChange={e=>setFilter(e.target.value)}/></label>
                <div className="capability-filters" aria-label="技能分组"><button aria-pressed={group==='business'} onClick={()=>setGroup('business')}>宣传能力</button>{capabilityGroups.map(g=><button key={g.id} aria-pressed={group===g.id} onClick={()=>setGroup(g.id)}>{g.title}<span>{skills?.filter(s=>skillGroup(s)===g.id).length??0}</span></button>)}</div>
                <div className="list-caption">{group==='other'?'暂不用于产品宣传的能力，可按需重新启用。':`${skills?.filter(s=>skillGroup(s)!=='other'&&s.enabled).length??0} 个宣传技能已启用 · 工具配置在新对话中应用`}</div>
                <div className="skill-list">{capabilityGroups.filter(g=>group==='business'?g.id!=='other':g.id===group).map(g=>{
                  const rows=skills?.filter(s=>skillGroup(s)===g.id&&`${skillDetails(s).title} ${s.name} ${s.description}`.toLowerCase().includes(filter.toLowerCase()))??[];
                  return rows.length>0&&<section className="capability-section" key={g.id}><header><h3>{g.title}</h3><span>{g.description}</span></header>{rows.map(skill=>{
                    const state=skillReadiness(skill,Object.values(chat.info.tools??{}).flat());
                    return <article className="skill-card" key={skill.name}><div className="capability-mark"><Icon name={g.id==='image'?'image':g.id==='video'?'video':g.id==='planning'?'note':'file'}/></div><div className="skill-copy"><div className="managed-skill-title"><h3>{skillDetails(skill).title}</h3><span className={`readiness ${state.state}`}>{skill.name==='hermes-agent'?'系统保留':state.label}</span></div><p>{skillDetails(skill).description}</p><div className="skill-row-actions"><details className="skill-runtime"><summary>运行要求</summary><p className="skill-requirement">{state.reason}</p><code>{skill.name}</code></details><button className="text-button" disabled={blocked} onClick={()=>viewSkill(skill)}>查看与编辑</button></div></div><button role="switch" className="toggle" aria-checked={skill.enabled} aria-label={`启用技能 ${skill.name}`} disabled={blocked||skill.name==='hermes-agent'} onClick={()=>void toggleSkill(skill)}><span/></button></article>;
                  })}</section>;
                })}</div>
                {!loading&&skills&&!skills.some(s=>(group==='business'?skillGroup(s)!=='other':skillGroup(s)===group)&&`${skillDetails(s).title} ${s.name} ${s.description}`.toLowerCase().includes(filter.toLowerCase()))&&<div className="settings-empty"><Icon name="search"/><h3>没有匹配的技能</h3><p>调整关键词或切换分组。</p></div>}
              </>}

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
