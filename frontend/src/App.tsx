import { useEffect, useRef, useState } from 'react';
import { ChatController } from './chat-controller';
import { useChat } from './use-chat';
import { Message } from './Message';

const suggestions = [
  { icon: '✦', title: '聊一个想法', detail: '梳理目标，一起把想法变具体', prompt: '我想做一个面向抖音带货的智能助手，帮我梳理一个不依赖大量数据的切入点。' },
  { icon: '▤', title: '了解教学素材', detail: '读取商品资料，区分事实与待验证信息', prompt: '列出教学目录，再读取 product-note.md，区分已知信息和缺少的证据。' },
  { icon: '⌘', title: '观察工具执行', detail: '通过一个文件请求看清执行过程', prompt: '请使用文件工具读取 product-note.md，并用三条要点概括内容。' },
];

export function App({ controller }: { controller: ChatController }) {
  const chat = useChat(controller);
  const [draft, setDraft] = useState('');
  const [sidebar, setSidebar] = useState(false);
  const [settings, setSettings] = useState(false);
  const [sending, setSending] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const connected = chat.connection === 'open';
  const blocked = !connected || chat.busy || chat.running || sending;
  const title = chat.info.title || chat.sessions.find(s => s.id === chat.storedId)?.title || '新对话';
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth' }); }, [chat.items.length, chat.items.at(-1)?.text, chat.running]);
  useEffect(() => { if (input.current) { input.current.style.height = 'auto'; input.current.style.height = `${Math.min(input.current.scrollHeight, 180)}px`; } }, [draft]);

  async function submit() {
    if (blocked || !draft.trim()) return;
    const text = draft;
    setSending(true);
    if (await controller.send(text)) setDraft(current => current === text ? '' : current);
    setSending(false);
    input.current?.focus();
  }

  return <div className="app-shell">
    {sidebar && <button className="sidebar-scrim" aria-label="关闭侧栏" onClick={() => setSidebar(false)} />}
    <aside className={`sidebar ${sidebar ? 'visible' : ''}`}>
      <div className="brand"><span className="brand-mark">m</span><strong>miniclaw</strong><span className="beta">预览</span></div>
      <button className="new-chat" disabled={chat.running || chat.busy || !connected} onClick={() => { void controller.newSession(); setSidebar(false); }}><span>＋</span>新建对话</button>
      <div className="section-label">对话</div>
      <nav className="session-list" aria-label="历史对话">{chat.sessions.length ? chat.sessions.map(session => <button
        key={session.id} className={`session ${session.id === chat.storedId ? 'selected' : ''}`}
        disabled={chat.running || chat.busy || !connected}
        onClick={() => { void controller.open(session.id); setSidebar(false); }} title={session.title || session.preview}
      ><span className="chat-icon">◻</span><span>{session.title || session.preview || '未命名对话'}</span></button>) : <p className="sessions-empty">第一条消息会保存为对话</p>}</nav>
      <div className="sidebar-bottom"><button className="settings-button" onClick={() => setSettings(value => !value)}>⚙<span>连接与设置</span></button>
        <div className="workspace"><span className={`status-dot ${connected ? 'online' : ''}`} />个人工作区<span>本机</span></div>
      </div>
    </aside>
    <main className="main-panel">
      <header className="topbar"><button className="mobile-menu" onClick={() => setSidebar(true)} aria-label="打开侧栏">☰</button>
        <span className="topbar-title">{title}</span><span className="topbar-right"><span className={`status-dot ${connected ? 'online' : ''}`} />{connected ? '已连接' : chat.connection === 'connecting' ? '连接中' : '未连接'}</span>
      </header>
      {settings && <section className="settings-panel"><strong>连接与设置</strong><p>模型：{chat.info.model || '读取配置中'}</p>
        <p>模型凭据由服务端环境配置管理。当前开放的文件工具仅能读取教学目录。</p>
        <button onClick={() => { void controller.connect(); }} disabled={chat.connection === 'connecting' || connected}>重新连接</button>
        <button onClick={() => setSettings(false)}>关闭</button></section>}
      <div className="conversation" aria-live="polite">
        {!chat.items.length ? <section className="welcome"><span className="welcome-symbol">✳</span><div className="eyebrow">你的 Agent 工作台</div>
          <h1>从一个想法开始。</h1><p className="welcome-subtitle">和 miniclaw 对话，一步步完成你的任务。</p>
          <div className="suggestions">{suggestions.map(suggestion => <button key={suggestion.title} onClick={() => { setDraft(suggestion.prompt); input.current?.focus(); }}>
            <span className="suggestion-icon">{suggestion.icon}</span><strong>{suggestion.title}</strong><p>{suggestion.detail}</p><span className="suggestion-arrow">↗</span>
          </button>)}</div>
        </section> : <div className="transcript">{chat.items.map(item => <Message key={item.id} item={item} />)}
          {chat.running && <div className="run-status"><span className="loading-dot" />{chat.status || '正在执行'}</div>}
          {!chat.running && chat.status && <div className="run-status">{chat.status}</div>}
          <div ref={bottom} /></div>}
      </div>
      <div className="composer-area">
        {chat.error && <div className="error-banner" role="alert"><span>⚠ {chat.error}</span>{!connected && <button onClick={() => void controller.connect()} disabled={chat.busy || chat.connection === 'connecting'}>重新连接</button>}</div>}
        <form className="composer" onSubmit={event => { event.preventDefault(); void submit(); }}>
          <textarea ref={input} aria-label="消息" placeholder="向 miniclaw 描述你的任务…" rows={2} value={draft} onChange={event => setDraft(event.target.value)}
            onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void submit(); } }} />
          <div className="composer-toolbar"><span className="model-badge"><span className="model-symbol">✧</span>{chat.info.model || 'DeepSeek'}<span className="model-caption">个人工作区</span></span>
            {chat.running ? <button type="button" className="send-button stop" aria-label="停止" title="停止本轮执行" onClick={() => void controller.stop()}>■</button>
              : <button type="submit" className="send-button" aria-label="发送" disabled={blocked || !draft.trim()}>↑</button>}
          </div>
        </form><div className="composer-hint">Enter 发送 · Shift + Enter 换行<span>重要信息请核对来源</span></div>
      </div>
    </main>
  </div>;
}
