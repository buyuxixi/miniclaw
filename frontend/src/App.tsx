import { useEffect, useRef, useState } from 'react';
import { ChatController } from './chat-controller';
import { useChat } from './use-chat';
import { Message } from './Message';
import { SidebarSessions } from './SidebarSessions';
import { SettingsDialog } from './SettingsDialog';
import { SkillPicker } from './SkillPicker';
import { Icon, type IconName } from './Icon';
import { skillDetails } from './skill-readiness';

const suggestions = [
  { icon: 'chat', title: '梳理一个想法', detail: '把目标拆成可以开始的步骤', prompt: '我想做一个面向抖音带货的智能助手，帮我梳理一个不依赖大量数据的切入点。' },
  { icon: 'file', title: '总结商品资料', detail: '提取事实，找出还缺少的信息', prompt: '列出教学目录，再读取 product-note.md，区分已知信息和缺少的证据。' },
  { icon: 'edit', title: '改写一段文案', detail: '让表达自然、清晰、更容易理解', prompt: '帮我把这句话改得更自然，不添加未经证实的功效：本工具将充分赋能业务实现高效协同。' },
];

export function App({ controller }: { controller: ChatController }) {
  const chat = useChat(controller);
  const [draft, setDraft] = useState('');
  const [sidebar, setSidebar] = useState(false);
  const [settings, setSettings] = useState(false);
  const [settingsTab, setSettingsTab] = useState<'general' | 'skills' | 'tools'>('general');
  const [pickingSkill, setPickingSkill] = useState(false);
  const [skill, setSkill] = useState<string>();
  const [sending, setSending] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const connected = chat.connection === 'open';
  const blocked = !connected || chat.busy || chat.running || sending;
  const title = chat.info.title || chat.sessions.find(s => s.id === chat.storedId)?.title || '新对话';
  const tools = Object.values(chat.info.tools ?? {}).flat();
  const readOnly = tools.length > 0 && tools.every(name => ['miniclaw_list_files', 'miniclaw_read_file'].includes(name));
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth' }); }, [chat.items.length, chat.items.at(-1)?.text, chat.running]);
  useEffect(() => { if (input.current) { input.current.style.height = 'auto'; input.current.style.height = `${Math.min(input.current.scrollHeight, 180)}px`; } }, [draft]);
  useEffect(() => { setSkill(undefined); }, [chat.sessionId]);
  useEffect(() => { if (!pickingSkill && !settings && skill) input.current?.focus(); }, [pickingSkill, settings, skill]);

  async function submit() {
    if (blocked || !draft.trim()) return;
    const text = draft;
    setSending(true);
    if (await controller.send(text, skill)) { setDraft(current => current === text ? '' : current); setSkill(undefined); }
    setSending(false);
    input.current?.focus();
  }

  return <div className="app-shell">
    <a className="skip-link" href="#message-input">跳到消息输入</a>
    {sidebar && <button className="sidebar-scrim" aria-label="关闭侧栏" onClick={() => setSidebar(false)} />}
    <aside className={`sidebar ${sidebar ? 'visible' : ''}`}>
      <div className="brand"><span className="brand-mark">m</span><strong>miniclaw</strong><span className="beta">预览</span></div>
      <button className="new-chat" disabled={chat.running || chat.busy || !connected} onClick={() => { void controller.newSession(); setSidebar(false); }}><Icon name="plus" />新建对话</button>
      <SidebarSessions controller={controller} chat={chat} onSelect={() => setSidebar(false)} />
      <div className="sidebar-bottom"><button className="settings-button" onClick={() => { setSettingsTab('general'); setSettings(true); }}><Icon name="settings" /><span>设置</span></button>
        <div className="workspace"><span className={`status-dot ${connected ? 'online' : ''}`} />个人工作区<span>本机</span></div>
      </div>
    </aside>
    <main className="main-panel">
      <header className="topbar"><button className="mobile-menu icon-button" onClick={() => setSidebar(true)} aria-label="打开侧栏"><Icon name="menu" /></button>
        <span className="topbar-title">{title}</span><span className="topbar-right">{readOnly && <button className="workspace-mode" title="当前可读资料，生成文件的执行工具尚未接入" onClick={() => { setSettingsTab('tools'); setSettings(true); }}><Icon name="lock" size={14} />只读工作区</button>}<span className={`status-dot ${connected ? 'online' : ''}`} /><span className="connection-label">{connected ? '已连接' : chat.connection === 'connecting' ? '连接中' : '未连接'}</span></span>
      </header>
      <div className="conversation" aria-live="polite">
        {!chat.items.length ? <section className="welcome">
          <h1>今天想完成什么？</h1><p className="welcome-subtitle">聊想法、读资料，或者一起把文字写好。</p>
          <div className="suggestions">{suggestions.map(suggestion => <button key={suggestion.title} onClick={() => { setDraft(suggestion.prompt); input.current?.focus(); }}>
            <span className="suggestion-icon"><Icon name={suggestion.icon as IconName} size={21} /></span><strong>{suggestion.title}</strong><p>{suggestion.detail}</p>
          </button>)}</div>
        </section> : <div className="transcript">{chat.items.map(item => <Message key={item.id} item={item} />)}
          {chat.running && <div className="run-status"><span className="loading-dot" />{chat.status || '正在执行'}</div>}
          {!chat.running && chat.status && <div className="run-status">{chat.status}</div>}
          <div ref={bottom} /></div>}
      </div>
      <div className="composer-area">
        {chat.error && <div className="error-banner" role="alert"><span>⚠ {chat.error}</span>{!connected && <button onClick={() => void controller.connect()} disabled={chat.busy || chat.connection === 'connecting'}>重新连接</button>}</div>}
        <form className="composer" onSubmit={event => { event.preventDefault(); void submit(); }}>
          {skill && <div className="composer-skill"><Icon name="skills" size={16} /><span>{skillDetails({ name: skill, description: '' }).title}</span><small>本次任务</small><button type="button" className="icon-button" aria-label="移除技能" disabled={blocked} onClick={() => setSkill(undefined)}><Icon name="close" size={14} /></button></div>}
          <textarea id="message-input" name="message" autoComplete="off" ref={input} aria-label="消息" placeholder="描述任务，或从下方选择技能…" rows={2} value={draft} onChange={event => setDraft(event.target.value)}
            onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void submit(); } }} />
          <div className="composer-toolbar"><div className="composer-options"><span className="model-badge" translate="no"><span className="model-dot" />{chat.info.model || 'DeepSeek'}</span><button className="skill-picker" type="button" disabled={blocked} onClick={() => setPickingSkill(true)}><Icon name="skills" size={16} />选择技能<Icon name="chevron" size={14} /></button></div>
            {chat.running ? <button type="button" className="send-button stop" aria-label="停止" title="停止本轮执行" onClick={() => void controller.stop()}><Icon name="stop" size={15} /></button>
              : <button type="submit" className="send-button" aria-label="发送" disabled={blocked || !draft.trim()}><Icon name="arrow" size={20} /></button>}
          </div>
        </form><div className="composer-hint">Enter 发送 · Shift + Enter 换行<span>重要信息请核对来源</span></div>
      </div>
    </main>
    {settings && <SettingsDialog controller={controller} chat={chat} initialTab={settingsTab} onClose={() => setSettings(false)} />}
    {pickingSkill && <SkillPicker controller={controller} chat={chat} selected={skill} onClose={() => setPickingSkill(false)} onChoose={name => { setSkill(name); setPickingSkill(false); input.current?.focus(); }} onManage={() => { setPickingSkill(false); setSettingsTab('skills'); setSettings(true); }} />}
  </div>;
}
