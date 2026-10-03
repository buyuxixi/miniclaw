import { useEffect, useRef, useState } from 'react';
import { ChatController } from './chat-controller';
import { useChat } from './use-chat';
import { Message } from './Message';
import { SidebarSessions } from './SidebarSessions';
import { SettingsDialog } from './SettingsDialog';
import { Composer } from './Composer';
import { Icon, type IconName } from './Icon';
import { ImageWorkspace } from './ImageWorkspace';
import type { Attachment } from './attachments';

const suggestions = [
  { icon: 'chat', title: '梳理一个想法', detail: '把目标拆成可以开始的步骤', prompt: '我想做一个面向抖音带货的智能助手，帮我梳理一个不依赖大量数据的切入点。' },
  { icon: 'file', title: '总结商品资料', detail: '提取事实，找出还缺少的信息', prompt: '列出教学目录，再读取 product-note.md，区分已知信息和缺少的证据。' },
  { icon: 'edit', title: '改写一段文案', detail: '让表达自然、清晰、更容易理解', prompt: '帮我把这句话改得更自然，不添加未经证实的功效：本工具将充分赋能业务实现高效协同。' },
];

export function App({ controller }: { controller: ChatController }) {
  const chat = useChat(controller);
  const [suggestion, setSuggestion] = useState<{ text: string; nonce: number; attachment?: Attachment }>();
  const [imageEditor, setImageEditor] = useState<{ initial?: Attachment }>();
  const [following, setFollowing] = useState(true);
  const conversation = useRef<HTMLDivElement>(null);
  const followRef = useRef(true);
  const [sidebar, setSidebar] = useState(false);
  const [settings, setSettings] = useState(false);
  const [settingsTab, setSettingsTab] = useState<'general' | 'skills' | 'tools'>('general');
  const bottom = useRef<HTMLDivElement>(null);
  const connected = chat.connection === 'open';
  const title = chat.info.title || chat.sessions.find(s => s.id === chat.storedId)?.title || '新对话';
  const tools = Object.values(chat.info.tools ?? {}).flat();
  const readOnly = tools.length > 0 && tools.every(name => ['miniclaw_list_files', 'miniclaw_read_file', 'skills_list', 'skill_view'].includes(name));
  useEffect(() => { if (followRef.current) bottom.current?.scrollIntoView({ behavior: 'instant' }); }, [chat.items.length, chat.items.at(-1)?.text, chat.running]);
  useEffect(() => { followRef.current = true; setFollowing(true); conversation.current?.scrollTo({ top: conversation.current.scrollHeight }); }, [chat.storedId]);
  function follow() { followRef.current = true; setFollowing(true); bottom.current?.scrollIntoView({ behavior: 'smooth' }); }

  return <div className="app-shell">
    <a className="skip-link" href="#message-input">跳到消息输入</a>
    {sidebar && <button className="sidebar-scrim" aria-label="关闭侧栏" onClick={() => setSidebar(false)} />}
    <aside className={`sidebar ${sidebar ? 'visible' : ''}`}>
      <div className="brand"><span className="brand-mark">m</span><strong>miniclaw</strong><span className="beta">预览</span></div>
      <button className="new-chat" disabled={chat.running || chat.busy || !connected} onClick={() => { void controller.newSession(); setSidebar(false); setSuggestion(undefined); }}><Icon name="plus" />新建对话</button>
      <SidebarSessions controller={controller} chat={chat} onSelect={() => { setSidebar(false); setSuggestion(undefined); }} />
      <div className="sidebar-bottom"><button className="settings-button" onClick={() => { setSettingsTab('general'); setSettings(true); }}><Icon name="settings" /><span>设置</span></button>
        <div className="workspace"><span className={`status-dot ${connected ? 'online' : ''}`} />个人工作区<span>本机</span></div>
      </div>
    </aside>
    <main className="main-panel">
      <header className="topbar"><button className="mobile-menu icon-button" onClick={() => setSidebar(true)} aria-label="打开侧栏"><Icon name="menu" /></button>
        <span className="topbar-title">{title}</span><span className="topbar-right"><button className="workspace-mode" disabled={!chat.storedId || chat.busy} onClick={() => setImageEditor({})}><Icon name="image" size={14} />修图</button>{readOnly && <button className="workspace-mode" title="本对话未加载写文件工具，可在设置中选择受限工具后新建对话" onClick={() => { setSettingsTab('tools'); setSettings(true); }}><Icon name="lock" size={14} />只读工作区</button>}<span className={`status-dot ${connected ? 'online' : ''}`} /><span className="connection-label">{connected ? '已连接' : chat.connection === 'connecting' ? '连接中' : '未连接'}</span></span>
      </header>
      <div className="conversation" ref={conversation} onScroll={event => { const el = event.currentTarget; const near = el.scrollHeight - el.clientHeight - el.scrollTop < 100; followRef.current = near; setFollowing(near); }}>
        {!chat.items.length ? <section className="welcome">
          <h1>今天想完成什么？</h1><p className="welcome-subtitle">聊想法、读资料，或者一起把文字写好。</p>
          <div className="suggestions">{suggestions.map(suggestion => <button key={suggestion.title} onClick={() => { setSuggestion({ text: suggestion.prompt, nonce: Date.now() }); }}>
            <span className="suggestion-icon"><Icon name={suggestion.icon as IconName} size={21} /></span><strong>{suggestion.title}</strong><p>{suggestion.detail}</p>
          </button>)}</div>
        </section> : <div className="transcript">{chat.items.map(item => <Message key={item.id} item={item} owner={chat.storedId} onReuse={text => setSuggestion({ text, nonce: Date.now() })} onEdit={initial => setImageEditor({ initial })} />)}
          {chat.running && <div className="run-status"><span className="loading-dot" />{chat.status || '正在执行'}</div>}
          {!chat.running && chat.status && <div className="run-status">{chat.status}</div>}
          <div ref={bottom} /></div>}
      </div>
      <div className="composer-area">
        {chat.error && <div className="error-banner" role="alert"><span>⚠ {chat.error}</span>{!connected && <button onClick={() => void controller.connect()} disabled={chat.busy || chat.connection === 'connecting'}>重新连接</button>}</div>}
        {!following && <button className="jump-latest" onClick={follow}>↓ 回到最新消息</button>}
        <Composer key={chat.storedId || 'pending'} controller={controller} chat={chat} suggestion={suggestion} onManage={() => { setSettingsTab('skills'); setSettings(true); }} />
      </div>
    </main>
    {settings && <SettingsDialog controller={controller} chat={chat} initialTab={settingsTab} onClose={() => setSettings(false)} />}
    {imageEditor && <ImageWorkspace key={chat.storedId} controller={controller} chat={chat} initial={imageEditor.initial} onClose={() => { setImageEditor(undefined); void controller.refresh(); }} onTools={() => { setImageEditor(undefined); setSettingsTab('tools'); setSettings(true); }} onUse={attachment => { setSuggestion({ text: '', attachment, nonce: Date.now() }); setImageEditor(undefined); void controller.refresh(); }} />}

  </div>;
}
