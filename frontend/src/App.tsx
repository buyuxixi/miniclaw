import '../public/studio/project-name.js';
import './chat-workbench.css';
import './chat-trace-navigation.css';
import { useEffect, useMemo, useRef, useState } from "react";
import { ChatController } from "./chat-controller";
import { useChat } from "./use-chat";
import { Message } from "./Message";
import {saveStudioIdea} from './studio-api';
import {readApi} from './management-api';
import type {StudioProject} from './StudioHome';
import {StudioProjectDialog} from './StudioProjectDialog';
import { SidebarSessions } from "./SidebarSessions";
import { SettingsDialog } from "./SettingsDialog";
import { Composer } from "./Composer";
import { ClarificationCards } from './ClarificationCards';
import { Icon, type IconName } from "./Icon";
import { ImageWorkspace } from "./ImageWorkspace";
import type { Attachment } from "./attachments";
import type { CreatorTarget, CreatorTurn } from "./creator-api";
import type { BriefCandidate } from './creator-candidates';
import { ProjectCompanion, type WorkingImageContext, type ProjectImageReference, type ProjectMainScript } from './ProjectCompanion';
import { creationNodes } from './creator-api';
import { loadDraft } from './drafts';
import { taskItems } from './transcript';
import { ProjectConversationRecords } from './ProjectConversationRecords';
import { TraceView } from './TraceView';
import { useChatTrace } from './use-chat-trace';
import { withTraceHistory } from './trace-history';

export function App({
  controller,
  onCanvas,
  onCreator,
  onProjectDetails,
  creatorContext,
  onAdopt,
  onAdoptBrief,
  onContinueCanvas,
  onProjectTask,
  onAdoptImage,
  externalSuggestion,
  settingsNonce,
  active = true,
}: {
  controller: ChatController;
  onCanvas?: (attachment?: Attachment) => void;
  onCreator?: () => void;
  onProjectDetails?: () => void;
  creatorContext?: CreatorTarget;
  onAdopt?: (text: string, item: string, source: CreatorTurn) => void;
  onAdoptBrief?: (fields: BriefCandidate, item: string, source: CreatorTurn) => void;
  onContinueCanvas?: () => void;
  onProjectTask?: (node: CreatorTarget['node']) => Promise<void>;
  onAdoptImage?: () => Promise<void>;
  externalSuggestion?: {
    owner?: string;
    attachment?: Attachment;
    text?: string;
    skill?: string;
    nonce: number;
  };
  settingsNonce?: number;
  active?: boolean;
}) {
  const chat = useChat(controller);
  const [conversationView, setConversationView] = useState<'conversation' | 'trace'>(() =>
    new URLSearchParams(location.search).get('view') === 'trace' ? 'trace' : 'conversation');
  const trace = useChatTrace(chat.storedId, active && conversationView === 'trace' && !chat.workspaceConnecting && Boolean(chat.items.length || chat.running),
    chat.running, `${chat.items.length}:${chat.status}:${chat.error}`);
  const traceSteps = useMemo(() => withTraceHistory(chat.items, trace.steps), [chat.items, trace.steps]);
  const traceReturnScroll = useRef(0);
  const [linkedProject,setLinkedProject]=useState<StudioProject>();
  const [creatingProject,setCreatingProject]=useState<{owner:string;message?:string}>();
  const [associationError,setAssociationError]=useState('');
  const [associationLoading,setAssociationLoading]=useState(false);
  const contextLoading=chat.busy||chat.workspaceConnecting||associationLoading;
  const initialWelcome=useRef(!controller.resumeId&&!controller.workspace&&!localStorage.getItem('miniclaw.selected'));
  const workspaceId=linkedProject?.chat_id===chat.storedId?linkedProject.id:undefined;
  useEffect(()=>{
    let canceled=false;setLinkedProject(undefined);setAssociationError('');setAssociationLoading(false);
    if(!active||!chat.storedId||chat.workspaceConnecting)return;
    setAssociationLoading(true);
    const previousTarget=controller.workspace?.target;
    controller.workspace=undefined;
    if(chat.storedId)void readApi<StudioProject[]>(`/api/workspaces?owner=${encodeURIComponent(chat.storedId)}`).then(projects=>{
      if(canceled)return;
      const requested=new URLSearchParams(location.search).get('workspace');
      const selected=projects.find(p=>p.id===requested)||projects[0];
      setLinkedProject(selected);setAssociationLoading(false);controller.workspace=selected?{id:selected.id,...(selected.id===requested&&previousTarget?{target:previousTarget}:{})}:undefined;
      const url=new URL(studioChatHref(chat.storedId),location.origin);
      if(new URLSearchParams(location.search).get('view')==='trace')url.searchParams.set('view','trace');
      if(selected?.id===requested)for(const key of ['target','message']){const value=new URLSearchParams(location.search).get(key);if(value)url.searchParams.set(key,value);}
      if(selected)url.searchParams.set('workspace',selected.id);else {url.searchParams.delete('workspace');url.searchParams.delete('target');url.searchParams.delete('message');}
      history.replaceState(null,'',url);
    }).catch(e=>{if(!canceled){controller.workspace=undefined;setAssociationLoading(false);setAssociationError(e.message);}});
    return()=>{canceled=true;};
  },[chat.storedId,chat.workspaceConnecting,controller,active]);
  async function handoffIdea(item:string) {
    if(!workspaceId){setCreatingProject({owner:chat.storedId,message:item});return;}
    const result=await saveStudioIdea(workspaceId,chat.storedId,item);
    const object=result.events.at(-1)?.object;
    location.href=studioCanvasHref(workspaceId,object);
  }
  const [workingImage, setWorkingImage] = useState<WorkingImageContext>();
  const [projectImage, setProjectImage] = useState<ProjectImageReference>();
  const [mainScript, setMainScript] = useState<ProjectMainScript>();
  const [resultsOpen, setResultsOpen] = useState(false);
  const [switchingTask, setSwitchingTask] = useState(false);
  const [handoffError, setHandoffError] = useState('');
  const [conversationScope, setConversationScope] = useState<'task' | 'all'>('task');
  const [recordView, setRecordView] = useState(false);
  const recordScroll = useRef(0);
  const recordReturn = useRef(false);
  const pendingJump = useRef<string | undefined>(undefined);
  const projectActive = active && creatorContext?.owner === chat.storedId;
  const visibleItems = projectActive && conversationScope==='task' ? taskItems(chat.items,creatorContext!.id,creatorContext!.node) : chat.items;
  useEffect(()=>{setConversationScope('task');setHandoffError('');setRecordView(false);pendingJump.current=undefined;recordReturn.current=false;},[chat.storedId,creatorContext?.id,creatorContext?.node]);
  const [suggestion, setSuggestion] = useState<{
    owner: string;
    text: string;
    nonce: number;
    attachment?: Attachment;
    skill?: string;
  }>();
  const [imageEditor, setImageEditor] = useState<{ initial?: Attachment }>();
  const [following, setFollowing] = useState(true);
  const conversation = useRef<HTMLDivElement>(null);
  function switchConversationView(next: 'conversation' | 'trace') {
    if (next === conversationView) return;
    if (next === 'trace') traceReturnScroll.current = conversation.current?.scrollTop ?? 0;
    setConversationView(next);
    const url = new URL(location.href);
    if (next === 'trace') url.searchParams.set('view', 'trace'); else url.searchParams.delete('view');
    history.replaceState(null, '', url);
  }
  useEffect(() => {
    if (conversationView === 'conversation' && conversation.current) conversation.current.scrollTop = traceReturnScroll.current;
  }, [conversationView]);
  const followRef = useRef(true);
  const [sidebar, setSidebar] = useState(false);
  const [settings, setSettings] = useState(false);
  const [settingsTab, setSettingsTab] = useState<
    "general" | "skills" | "tools"
  >("general");
  const bottom = useRef<HTMLDivElement>(null);
  const sourceJumped = useRef(false);
  const sourceMessage = controller.workspace ? new URLSearchParams(location.search).get('message') : null;
  useEffect(() => {
    if (conversationView !== 'conversation' || sourceJumped.current || !sourceMessage || !/^row-\d+$/.test(sourceMessage)) return;
    const message = [...(conversation.current?.querySelectorAll<HTMLElement>('[data-project-message]') ?? [])].find(el => el.dataset.projectMessage === sourceMessage);
    if (message) {
      sourceJumped.current = true;
      followRef.current = false;
      setFollowing(false);
      message.scrollIntoView({block:'center',behavior:'instant'});
      message.setAttribute('tabindex','-1');
      message.focus({preventScroll:true});
      message.style.outline='2px solid var(--accent, #bba7f4)';
    }
  }, [chat.items,sourceMessage,conversationView]);
  const connected = chat.connection === "open";
  const title =
    chat.info.title ||
    chat.sessions.find((s) => s.id === chat.storedId)?.title ||
    "新对话";
  const tools = Object.values(chat.info.tools ?? {}).flat();
  const readOnly =
    tools.length > 0 &&
    tools.every((name) =>
      [
        "miniclaw_list_files",
        "miniclaw_read_file",
        "skills_list",
        "skill_view",
      ].includes(name),
    );
  useEffect(() => {
    if (externalSuggestion) setSuggestion({ text: "", ...externalSuggestion, owner: externalSuggestion.owner || chat.storedId });
  }, [externalSuggestion?.nonce]);
  useEffect(() => {
    if (settingsNonce) {
      setSettingsTab("tools");
      setSettings(true);
    }
  }, [settingsNonce]);
  useEffect(() => {
    if (conversationView === 'conversation' && followRef.current && !recordView && !recordReturn.current && !pendingJump.current)
      bottom.current?.scrollIntoView({ behavior: "instant" });
  }, [chat.items.length, chat.items.at(-1)?.text, chat.running, visibleItems.length, creatorContext?.id, creatorContext?.node, conversationScope,conversationView]);
  useEffect(() => {
    if (!active) return;
    followRef.current = true;
    setFollowing(true);
    if (conversationView === 'conversation') conversation.current?.scrollTo({ top: conversation.current.scrollHeight });
    traceReturnScroll.current = 0;
  }, [chat.storedId,active]);
  function follow() {
    followRef.current = true;
    setFollowing(true);
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }
  useEffect(() => {
    if (conversationView !== 'conversation' || recordView || !projectActive || !conversation.current) return;
    const panel = conversation.current;
    if (pendingJump.current) {
      const message = [...panel.querySelectorAll<HTMLElement>('[data-project-message]')].find(el => el.dataset.projectMessage === pendingJump.current);
      if (message) {
        panel.scrollTo({top:panel.scrollTop + message.getBoundingClientRect().top - panel.getBoundingClientRect().top - 16,behavior:'smooth'});
        pendingJump.current = undefined;
        recordReturn.current = false;
      }
    } else if (recordReturn.current) { panel.scrollTop = recordScroll.current; recordReturn.current = false; }
  }, [recordView,conversationScope,chat.storedId,conversationView]);

  return (
    <div className={`app-shell chat-workbench ${projectActive ? `project-studio ${resultsOpen ? 'studio-show-work' : 'studio-show-chat'}` : ''}`}>
      <a className="skip-link" href="#message-input">
        跳到消息输入
      </a>
      {projectActive && <>
        <header className="studio-global"><div className="brand"><span className="brand-mark">m</span><strong>miniclaw</strong></div><nav aria-label="主导航">{controller.workspace&&<a href={`/studio/index.html?workspace=${controller.workspace.id}`}>← 返回自由画布</a>}<button onClick={onCreator}>创作看板</button><button disabled={chat.running || chat.busy || !connected} onClick={()=>{void controller.newSession();setSuggestion(undefined);}}>新建自由对话</button></nav><div className="studio-global-right"><span className="studio-connection"><span className={`status-dot ${connected ? 'online' : ''}`}/>{connected ? 'Agent 已连接' : 'Agent 未连接'}</span><button className="studio-settings" aria-label="设置" onClick={()=>{setSettingsTab('general');setSettings(true);}}><Icon name="settings"/></button></div></header>
        <header className="studio-project"><div className="studio-project-title"><span>创作项目</span><h1 title={creatorContext!.name}>{creatorContext!.name}</h1></div><nav className="studio-tasknav" aria-label="当前创作任务">{creationNodes.filter(([node])=>node!=='brief').map(([node,label],index)=><button data-step={String(index+1).padStart(2,'0')} key={node} aria-pressed={creatorContext!.node===node} disabled={chat.running || chat.busy || switchingTask} onClick={async()=>{setSwitchingTask(true);try{await onProjectTask?.(node);}finally{setSwitchingTask(false);}}}>{label}</button>)}</nav><div className="studio-project-actions"><button className="studio-direction-button" aria-pressed={creatorContext!.node==='brief'} disabled={chat.running || chat.busy || switchingTask} onClick={async()=>{setSwitchingTask(true);try{await onProjectTask?.('brief');}finally{setSwitchingTask(false);}}}>商品方向</button><button onClick={onProjectDetails}>项目资料</button></div><nav className="studio-view-toggle" aria-label="工作区视图"><button aria-pressed={!resultsOpen} onClick={()=>setResultsOpen(false)}>对话</button><button aria-pressed={resultsOpen} onClick={()=>setResultsOpen(true)}>作品</button></nav></header>
      </>}
      {!projectActive && <>
      {sidebar && (
        <button
          className="sidebar-scrim"
          aria-label="关闭侧栏"
          onClick={() => setSidebar(false)}
        />
      )}
      <aside className={`sidebar ${sidebar ? "visible" : ""}`}>
        <div className="brand">
          <span className="brand-mark">m</span>
          <strong>miniclaw</strong>
          <span className="beta">预览</span>
        </div>
        <button
          className="new-chat"
          disabled={chat.running || chat.busy || !connected}
          onClick={() => {
            void controller.newSession();
            setSidebar(false);
            setSuggestion(undefined);
          }}
        >
          <Icon name="plus" />
          新建对话
        </button>
        {onCreator && <button className="sidebar-home" onClick={onCreator}><Icon name="folder"/>创作项目</button>}
        <SidebarSessions
          controller={controller}
          chat={chat}
          projectName={projectActive ? creatorContext!.name : undefined}
          onSelect={() => {
            setSidebar(false);
            setSuggestion(undefined);
          }}
        />
        <div className="sidebar-bottom">
          <button
            className="settings-button"
            onClick={() => {
              setSettingsTab("general");
              setSettings(true);
            }}
          >
            <Icon name="settings" />
            <span>设置</span>
          </button>
          <div className="workspace">
            <span className={`status-dot ${connected ? "online" : ""}`} />
            个人工作区<span>本机</span>
          </div>
        </div>
      </aside>
      </>}
      <div className={`chat-center ${projectActive ? 'has-project' : ''}`}>
      <main className={`main-panel${conversationView==='trace'?' is-trace':''}${initialWelcome.current&&contextLoading&&!visibleItems.length?' welcome-loading':''}`}>
        <header className="topbar">
          <button
            className="mobile-menu icon-button"
            onClick={() => setSidebar(true)}
            aria-label="打开侧栏"
          >
            <Icon name="menu" />
          </button>
          <span className="topbar-title">{projectActive ? creatorContext!.name : linkedProject ? shortStudioName(linkedProject.name) : title}</span>
          {projectActive && <button className="project-back-overview" onClick={onCreator}>看板</button>}
          {projectActive && onProjectDetails && <button className="project-back-overview" onClick={onProjectDetails}>资料</button>}
          <span className="topbar-right">
            {workspaceId&&!projectActive&&<a className="workspace-mode canvas-return" href={studioCanvasHref(workspaceId)} title={linkedProject?.name}><Icon name="image" size={15}/><span>打开画布</span></a>}
            {!projectActive && !workspaceId && <button
              className="workspace-mode"
              disabled={!chat.storedId || contextLoading}
              onClick={() => setCreatingProject({owner:chat.storedId})}
            >
              <Icon name="image" size={14} />
              建立创作项目
            </button>}
            {readOnly && (
              <button
                className="workspace-mode"
                title="本对话未加载写文件工具，可在设置中选择受限工具后新建对话"
                onClick={() => {
                  setSettingsTab("tools");
                  setSettings(true);
                }}
              >
                <Icon name="lock" size={14} />
                只读工作区
              </button>
            )}
            <span className={`status-dot ${connected ? "online" : ""}`} />
            <span className="connection-label">
              {contextLoading ? "正在读取" : connected
                ? "已连接"
                : chat.connection === "connecting"
                  ? "连接中"
                  : "未连接"}
            </span>
          </span>
        </header>
        <nav className="chat-view-tabs" role="tablist" aria-label="对话视图" onKeyDown={event => {
          if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
          event.preventDefault();
          const next = event.key === 'Home' ? 'conversation' : event.key === 'End' ? 'trace' : conversationView === 'trace' ? 'conversation' : 'trace';
          switchConversationView(next);
          event.currentTarget.querySelector<HTMLButtonElement>(`[data-view="${next}"]`)?.focus();
        }}>
          <button id="chat-conversation-tab" data-view="conversation" role="tab" aria-selected={conversationView==='conversation'} aria-controls="chat-conversation-panel" tabIndex={conversationView==='conversation'?0:-1} onClick={()=>switchConversationView('conversation')}>对话</button>
          <button id="chat-trace-tab" data-view="trace" role="tab" aria-selected={conversationView==='trace'} aria-controls="chat-trace-panel" tabIndex={conversationView==='trace'?0:-1} onClick={()=>switchConversationView('trace')}>轨迹</button>
        </nav>
        {conversationView==='trace' && <section id="chat-trace-panel" className="chat-trace-panel" role="tabpanel" aria-labelledby="chat-trace-tab">
          <TraceView key={chat.storedId} steps={traceSteps} running={chat.running} loading={trace.loading || chat.workspaceConnecting || (chat.busy && !chat.items.length) || controller.connection !== 'open'} error={trace.error} onRefresh={trace.refresh} hasMore={trace.hasMore} onLoadMore={trace.loadMore}/>
        </section>}
        {projectActive && <header className="studio-chat-heading"><span className="studio-agent-mark">✦</span><div><strong>创作对话</strong><span>Agent · {creationNodes.find(([node])=>node===creatorContext!.node)?.[1]}</span></div><button aria-label="对话记录" aria-expanded={recordView} onClick={()=>{if(!recordView){recordScroll.current=conversation.current?.scrollTop || 0;recordReturn.current=true;}setRecordView(v=>!v);}}>对话记录<Icon name="chat" size={16}/></button></header>}
        {projectActive && !recordView && <nav className="conversation-scope" aria-label="项目记录范围"><button aria-pressed={conversationScope==='task'} onClick={()=>setConversationScope('task')}>当前任务</button><button aria-pressed={conversationScope==='all'} onClick={()=>setConversationScope('all')}>全部讨论</button>{readOnly&&<button onClick={()=>{setSettingsTab('tools');setSettings(true);}}><Icon name="lock" size={14}/>只读工具</button>}</nav>}
        <div
          className="conversation"
          id="chat-conversation-panel"
          role="tabpanel"
          aria-labelledby="chat-conversation-tab"
          hidden={conversationView==='trace'}
          ref={conversation}
          onScroll={(event) => {
            if (recordView) return;
            const el = event.currentTarget;
            const near = el.scrollHeight - el.clientHeight - el.scrollTop < 100;
            followRef.current = near;
            setFollowing(near);
          }}
        >
          {!projectActive && contextLoading && !visibleItems.length ? <div className="conversation-loading" role="status">正在读取对话…</div> : projectActive && recordView ? <ProjectConversationRecords project={creatorContext!.id} items={chat.items} onClose={()=>setRecordView(false)} onSelect={id=>{pendingJump.current=id;followRef.current=false;setFollowing(false);setConversationScope('all');setRecordView(false);}}/> : !visibleItems.length && projectActive ? <section className="task-welcome"><span>{creationNodes.find(n=>n[0]===creatorContext!.node)?.[1]} + Chat</span><h1>{creatorContext!.node==='cover'?'这张图，你想怎样改？':creatorContext!.node==='script'?'一起打磨口播':creatorContext!.node==='video'?'一起确定镜头与节奏':'先把创作方向说清楚'}</h1><p>{creatorContext!.node==='cover'?'说清修改目标和保留项，先看方案，再应用。':creatorContext!.node==='script'?'用项目资料起稿，再逐句讨论与修改。':creatorContext!.node==='video'?'讨论分镜、字幕和素材，准备好后再合成。':'核对商品事实、受众与风格。'}</p><button onClick={()=>{setConversationScope('all');}}>查看之前的讨论</button></section> : !visibleItems.length ? (
            <section className="welcome">
              <h1>{workspaceId ? shortStudioName(linkedProject?.name) : '从这里开始创作'}</h1>
              <p className="welcome-subtitle">
                {workspaceId ? `${linkedProject?.pictures || 0} 张素材 · ${linkedProject?.shots || 0} 个镜头${linkedProject?.adopted ? ` · 已采用 ${linkedProject.adopted} 个片段` : ""}` : "提问、处理任务，或上传素材开始创作。"}
              </p>
              <div className="suggestions">
                {(workspaceId ? [
                  {title:'检查镜头',icon:'chat',prompt:'请读取当前项目，检查已有镜头和素材之间的关系，指出还需要补充什么。'},
                  {title:'调整画面',icon:'image',prompt:'我想调整当前项目的画面，先读取项目，和我确认要修改的素材和需要保留的内容。'},
                  {title:'打磨提示词',icon:'edit',prompt:'请读取当前项目的镜头提示词，帮我改进画面和运动描述，保留商品外观与包装文字。'},
                ] : []).map((suggestion) => (
                  <button
                    key={suggestion.title}
                    onClick={() => {
                      setSuggestion({
                        owner: chat.storedId,
                        text: suggestion.prompt,
                        nonce: Date.now(),
                      });
                    }}
                  >
                    <span className="suggestion-icon">
                      <Icon name={suggestion.icon as IconName} size={21} />
                    </span>
                    <strong>{suggestion.title}</strong>

                  </button>
                ))}
              </div>
            </section>
          ) : (
            <div className="transcript">
              {visibleItems.map((item) => (
                <div key={item.id} data-project-message={item.id}><Message
                  key={item.id}
                  item={item}
                  owner={chat.storedId}
                  canvasTarget={workspaceId && connected && !contextLoading && chat.sessionId ? {workspace:workspaceId,sessionId:chat.sessionId} : undefined}
                  onSaveIdea={!projectActive&&chat.storedId ? handoffIdea : undefined}
                  saveIdeaLabel={workspaceId?'带到项目画布':'以此方案建立项目'}
                  currentMain={mainScript?.owner===chat.storedId && mainScript.project===creatorContext?.id ? mainScript.text : undefined}
                  onReuse={(text) => setSuggestion({ text, nonce: Date.now(), owner: chat.storedId })}
                  onEdit={(initial) => setImageEditor({ initial })}
                  onAdopt={
                    creatorContext?.owner === chat.storedId && item.creator_context?.project_id === creatorContext.id && item.creator_context.node === 'script'
                      ? (text, id) => onAdopt?.(text, id, item.creator_context!)
                      : undefined
                  }
                  onAdoptBrief={creatorContext?.owner === chat.storedId && item.creator_context?.project_id === creatorContext.id && item.creator_context.node === 'brief'
                    ? (fields, id) => onAdoptBrief?.(fields, id, item.creator_context!) : undefined}
                /></div>
              ))}
              {chat.running && (
                <div className="run-status">
                  <span className="loading-dot" />
                  {chat.status || "正在执行"}
                </div>
              )}
              {!chat.running && chat.status && (
                <div className="run-status">{chat.status}</div>
              )}
              <div ref={bottom} />
            </div>
          )}
        </div>
        <div className="composer-area" hidden={projectActive && recordView && conversationView==='conversation'}>
          {chat.error && (
            <div className="error-banner" role="alert">
              <span>⚠ {chat.error}</span>
              {!connected && (
                <button
                  onClick={() => void controller.connect()}
                  disabled={chat.busy || chat.connection === "connecting"}
                >
                  重新连接
                </button>
              )}
            </div>
          )}
          {conversationView==='conversation' && !following && (
            <button className="jump-latest" onClick={follow}>
              ↓ 回到最新消息
            </button>
          )}
          {handoffError && <p role="alert" className="composer-error">{handoffError}<button onClick={()=>setHandoffError('')}>关闭</button></p>}
          <ClarificationCards controller={controller}/>
          <Composer
            key={chat.storedId || "pending"}
            controller={controller}
            chat={chat}
            creatorContext={creatorContext?.owner === chat.storedId ? { project_id: creatorContext.id, node: creatorContext.node } : undefined}
            canvasContext={projectActive && creatorContext!.node==='cover' && workingImage?.project_id===creatorContext!.canvas ? workingImage : undefined}
            projectImage={projectActive && projectImage?.project===creatorContext!.id ? projectImage : undefined}
            suggestion={suggestion?.owner === chat.storedId ? suggestion : undefined}
            onSuggestionUsed={() => setSuggestion(undefined)}
            onManage={(tab = 'skills') => {
              setSettingsTab(tab);
              setSettings(true);
            }}
          />
        </div>
      </main>
      {associationError&&<p className="error-banner" role="alert">项目关联读取失败：{associationError}</p>}
      {projectActive && <div className={`project-result-dock ${resultsOpen ? 'is-open' : ''}`}><button className="project-result-close" onClick={()=>setResultsOpen(false)} aria-label="关闭创作结果">×</button><ProjectCompanion key={`${creatorContext!.id}:${creatorContext!.node}`} target={creatorContext!} owner={chat.storedId} busy={chat.running || chat.busy || switchingTask} onContext={setWorkingImage} onReference={setProjectImage} onMainScript={setMainScript} onNavigate={async node=>{setSwitchingTask(true);try{await onProjectTask?.(node);}finally{setSwitchingTask(false);}}} onEdit={()=>{setResultsOpen(false);onContinueCanvas?.();}} onAdoptImage={onAdoptImage || (async()=>{})} onSuggest={(text,skill)=>{const draft=loadDraft(chat.storedId);if(draft.text.trim()||draft.attachments.length){setHandoffError('输入框已有未发送内容，请先发送或清空，再带入新的创作要求。草稿已保留。');setResultsOpen(false);return;}setHandoffError('');setSuggestion({owner:chat.storedId,text,skill,nonce:Date.now()});setResultsOpen(false);}}/></div>}
      </div>
      {settings && (
        <SettingsDialog
          controller={controller}
          chat={chat}
          initialTab={settingsTab}
          onClose={() => setSettings(false)}
        />
      )}
      {creatingProject&&creatingProject.owner===chat.storedId&&<StudioProjectDialog key={creatingProject.owner+creatingProject.message} owner={creatingProject.owner} sessionId={chat.sessionId} message={creatingProject.message} onClose={()=>setCreatingProject(undefined)}/>}
      {imageEditor && (
        <ImageWorkspace
          key={chat.storedId}
          controller={controller}
          chat={chat}
          initial={imageEditor.initial}
          onCanvas={
            onCanvas
              ? (attachment) => {
                  setImageEditor(undefined);
                  onCanvas(attachment);
                }
              : undefined
          }
          onClose={() => {
            setImageEditor(undefined);
            void controller.refresh();
          }}
          onTools={() => {
            setImageEditor(undefined);
            setSettingsTab("tools");
            setSettings(true);
          }}
          onUse={(attachment) => {
            setSuggestion({ text: "", attachment, nonce: Date.now(), owner: chat.storedId });
            setImageEditor(undefined);
            void controller.refresh();
          }}
        />
      )}
    </div>
  );
}
