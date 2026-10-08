import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { App } from "./App";
import type { ChatController } from "./chat-controller";
import { uploadFile, type Attachment } from "./attachments";
import {
  creatorBase,
  creatorBlob,
  getCreator,
  type CreatorContext,
  type CreatorTarget,
  type CreatorProject,
  type CreatorReturn,
} from "./creator-api";
import { readApi, writeApi } from "./management-api";
import { loadDraft } from "./drafts";
import { loadProject, type CanvasImport } from './canvas-api';
import { canvasOrigin, workingCanvas, rememberCanvas } from './creator-canvas';
import { CreatorAdoption } from './CreatorAdoption';
const CanvasApp = lazy(() => import("./CanvasApp"));
const CreatorWorkspace = lazy(() => import("./CreatorWorkspace"));
const StudioHome = lazy(() => import('./StudioHome'));

export function AppShell({ controller }: { controller: ChatController }) {
  const workspaceRoute = new URLSearchParams(location.search).has('workspace');
  const [module, setModule] = useState<"chat" | "canvas" | "creator" | "home">(() =>
    new URLSearchParams(location.search).has('projects') ? 'home' : new URLSearchParams(location.search).has('workspace') || new URLSearchParams(location.search).has('chat') ? 'chat' : localStorage.getItem("miniclaw.module") === "creator"
      ? "creator"
      : localStorage.getItem("miniclaw.module") === "canvas"
        ? "canvas"
        : localStorage.getItem('miniclaw.module') === 'chat' ? 'chat' : 'home',
  );
  const [canvasLoaded, setCanvasLoaded] = useState(module === "canvas");
  const [creatorLoaded, setCreatorLoaded] = useState(module === "creator");
  const [initialImport, setInitialImport] = useState<CanvasImport>();
  const [navigationError, setNavigationError] = useState('');
  const [suggestion, setSuggestion] = useState<{
    owner: string;
    attachment?: Attachment;
    text?: string;
    skill?: string;
    nonce: number;
  }>();
  const [settingsNonce, setSettingsNonce] = useState(0);
  const [target, setTarget] = useState<CreatorTarget>();
  const [incoming, setIncoming] = useState<CreatorReturn>();
  const [detailsProject, setDetailsProject] = useState<string>();
  const restoreSerial = useRef(0);
  const targets = useRef(new Map<string, CreatorTarget>());
  function selectTarget(p: CreatorProject, node: CreatorContext['node'], canvas = workingCanvas(p) || p.assets.cover?.source?.canvas_project_id) {
    ++restoreSerial.current;
    const next = { id: p.id, name: p.name, revision: p.revision, owner: controller.state.storedId, node, canvas, image: canvasOrigin(p)?.image };
    setTarget(next); targets.current.set(next.owner, next);
    localStorage.setItem('miniclaw.creator.active-owner', next.owner);
    localStorage.setItem(`miniclaw.creator.chat.${next.owner}`, JSON.stringify({id:p.id,node}));
    localStorage.setItem('miniclaw.creator.chat', JSON.stringify({ id: p.id, node }));
  }
  useEffect(() => {
    let stopped = false;
    let owner = '';
    function restore() {
      const currentOwner = controller.state.storedId;
      if (!currentOwner || currentOwner === owner) return;
      if (owner) localStorage.removeItem('miniclaw.creator.active-owner');
      owner = currentOwner;
      const ticket = ++restoreSerial.current;
      // A history selection is ordinary Chat. Project layout requires an
      // explicit project entry, never merely an association in the database.
      if (workspaceRoute || localStorage.getItem('miniclaw.creator.active-owner') !== currentOwner) {
        setTarget(undefined);
        return;
      }
      setTarget(targets.current.get(currentOwner));
      void (async () => {
        try {
          const saved = localStorage.getItem(`miniclaw.creator.chat.${currentOwner}`) || localStorage.getItem('miniclaw.creator.chat');
          let ref: {id?:string;node?:CreatorContext['node']} = {};
          try { if(saved) ref=JSON.parse(saved); } catch { /* fall back to the durable link */ }
          let p = typeof ref.id==='string' ? await getCreator(ref.id).catch(()=>undefined) : undefined;
          if (!p || p.chat_id!==currentOwner) {
            const linked = await readApi<{id:string}[]>(`${creatorBase}/projects?owner=${encodeURIComponent(currentOwner)}`);
            p = linked[0] ? await getCreator(linked[0].id) : undefined; ref={node:'brief'};
          }
          if (!p || p.chat_id!==currentOwner) return;
          const node = ['brief','cover','script','video'].includes(ref.node || '') ? ref.node! : 'brief';
          const candidate = workingCanvas(p) || p.assets.cover?.source?.canvas_project_id;
          let canvas: string | undefined;
          if (candidate) {
            const loaded = await loadProject(candidate).catch(() => undefined);
            if (loaded && !loaded.project.archived && loaded.project.chat_id === currentOwner) canvas = candidate;
          }
          if (!stopped && ticket===restoreSerial.current && controller.state.storedId === currentOwner) {
            const next={ id:p.id,name:p.name,revision:p.revision,owner:currentOwner,node,canvas,image:canvasOrigin(p)?.image };
            targets.current.set(currentOwner,next); setTarget(next);
            localStorage.setItem(`miniclaw.creator.chat.${currentOwner}`,JSON.stringify({id:p.id,node}));
          }
        } catch { /* Never send unverified project context when lookup fails. */ }
      })();
    }
    restore();
    const unsubscribe = controller.subscribe?.(restore);
    return () => { stopped = true; unsubscribe?.(); };
  }, [controller, workspaceRoute]);
  async function projectChat(p: CreatorProject) {
    if (
      controller.connection !== "open" ||
      controller.state.running ||
      controller.state.busy
    )
      throw new Error("请等待Chat连接和当前任务完成");
    if (p.chat_id) {
      if (controller.state.storedId !== p.chat_id)
        await controller.open(p.chat_id);
    } else {
      const previous = controller.state.sessionId;
      await controller.newSession();
      if (
        !controller.state.sessionId ||
        controller.state.sessionId === previous
      )
        throw new Error("项目新对话创建失败；未关联到旧对话");
    }
    if (
      !controller.state.storedId ||
      !controller.state.sessionId ||
      (p.chat_id && controller.state.storedId !== p.chat_id)
    )
      throw new Error("项目对话未准备，请在Chat检查连接");
    return p.chat_id
      ? p
      : await writeApi<CreatorProject>(
          `${creatorBase}/projects/${p.id}/link-chat`,
          "POST",
          { revision: p.revision, session_id: controller.state.sessionId },
        );
  }
  function show(value: "chat" | "canvas" | "creator" | "home") {
    setModule(value);
    localStorage.setItem("miniclaw.module", value);
    if (value === "canvas") setCanvasLoaded(true);
    if (value === "creator") setCreatorLoaded(true);
  }
  async function newFreeChat() {
    if (controller.connection !== 'open' || controller.state.running || controller.state.busy)
      throw new Error('请等待 Agent 连接和当前任务完成。');
    const previous = controller.state.storedId;
    await controller.newSession();
    if (!controller.state.storedId || controller.state.storedId === previous)
      throw new Error(controller.state.error || '自由对话创建失败，请重试。');
    const url=new URL(location.href);url.searchParams.delete('projects');url.searchParams.delete('workspace');url.searchParams.delete('target');url.searchParams.set('chat','1');url.searchParams.set('session',controller.state.storedId);history.replaceState(null,'',url);
    setSuggestion(undefined);
    show('chat');
  }
  async function startProject(p: CreatorProject, node: CreatorContext['node']) {
    checkTaskDraft(p,node);
    if(node==='cover') await continueCanvas(p,undefined,true);
    else { const linked=await projectChat(p); selectTarget(linked,node); show('chat'); }
  }
  function checkTaskDraft(p: CreatorProject, node: CreatorContext['node']) {
    if (p.chat_id !== controller.state.storedId || target?.id === p.id && target.node === node) return;
    const pending=loadDraft(controller.state.storedId);
    if (pending.text.trim() || pending.attachments.length) throw new Error('输入框有未发送内容，请发送或清空后再切换任务。草稿已保留。');
  }
  async function continueCanvas(p?: CreatorProject, design?: import('./photo-design').CanvasDesignRequest, inChat = false) {
    if (p) {
      checkTaskDraft(p,'cover');
      p = await projectChat(p);
      const owner = controller.state.storedId, session = controller.state.sessionId;
      const image = p.assets.cover || p.assets.source;
      const candidate = workingCanvas(p) || image?.source?.canvas_project_id;
      if (candidate) {
        const loaded = await loadProject(candidate);
        if (loaded.project.archived || loaded.project.chat_id !== p.chat_id)
          throw new Error('工作画布不属于当前项目对话或已归档，请在图片工作区核对；未采用任何图片');
      }
      if (controller.state.storedId !== owner || controller.state.sessionId !== session) throw new Error('当前对话已切换，请重新进入修图任务');
      if (image) {
        const attachment: Attachment = candidate
          ? { id: image.id, name: image.name, bytes: image.bytes, kind: 'image', mime: 'image/png', canvas_project_id: candidate }
          : await uploadFile(owner, new File([await creatorBlob(p.id, image.id)], image.name));
        if (controller.state.storedId !== owner || controller.state.sessionId !== session) throw new Error('当前对话已切换，请重新进入修图任务');
        setInitialImport({attachment, session, nonce: Date.now(), creator: canvasOrigin(p), design, precision: !inChat && !design});
      } else setInitialImport(undefined);
      selectTarget(p, 'cover', candidate);
    }
    setNavigationError('');
    setCanvasLoaded(true);
    show(inChat ? 'chat' : 'canvas');
    return p;
  }
  return (
    <>
      {navigationError && <p role="alert" className="creator-error">{navigationError}</p>}
      <div className="app-surface" hidden={module !== "chat"}>
        <App
          controller={controller}
          active={module==='chat'}
          onCreator={() => show("home")}
          onProjectDetails={()=>{if(target?.owner===controller.state.storedId){setDetailsProject(target.id);localStorage.setItem('miniclaw.creator',target.id);show('creator');}}}
          creatorContext={workspaceRoute ? undefined : target}
          onProjectTask={async node => {
            try {
              if (!target || target.owner !== controller.state.storedId) return;
              if (node !== target.node) { const pending=loadDraft(controller.state.storedId); if (pending.text.trim() || pending.attachments.length) throw new Error('输入框有未发送内容，请发送或清空后再切换任务。草稿已保留。'); }
              const p=await getCreator(target.id);
              if (p.chat_id!==controller.state.storedId) throw new Error('当前对话已切换，请重新选择创作任务');
              if (node==='cover') await continueCanvas(p,undefined,true);
              else { const linked=await projectChat(p); selectTarget(linked,node); }
              setNavigationError('');
            } catch(e) { setNavigationError(e instanceof Error ? e.message : String(e)); }
          }}
          onAdoptImage={async()=>{
            if (!target?.canvas || target.owner!==controller.state.storedId) throw new Error('请从商品总览重新进入修图任务');
            const p=await getCreator(target.id), canvas=await loadProject(target.canvas);
            if (p.chat_id!==target.owner || canvas.project.chat_id!==target.owner || canvas.project.archived || canvasOrigin(p)?.image!==target.image) throw new Error('商品或工作图关联已变化，未采用任何图片。请从总览重新进入。');
            const attachment=await writeApi<Attachment>(`/api/miniclaw/canvas/projects/${target.canvas}/send-chat`,'POST',{session_id:controller.state.sessionId});
            setIncoming({project:p.id,revision:p.revision,nonce:Date.now(),kind:'cover',owner:target.owner,attachment:attachment.id,name:attachment.name});
            show('chat');
          }}
          onContinueCanvas={() => {
            if (target?.owner !== controller.state.storedId) return;
            void getCreator(target.id).then(continueCanvas).catch(e => setNavigationError(e instanceof Error ? e.message : String(e)));
          }}
          onAdoptBrief={(fields, item, source) => {
            if (target && source.node === 'brief' && source.project_id === target.id && target.owner === controller.state.storedId) {
              setIncoming({project: target.id, revision: source.revision, nonce: Date.now(), kind: 'brief', fields, item, owner: controller.state.storedId});
              show('chat');
            }
          }}
          onAdopt={(text, item, source) => {
            if (target && source.node === 'script' && source.project_id === target.id && target.owner === controller.state.storedId) {
              setIncoming({
                project: target.id,
                revision: source.revision,
                nonce: Date.now(),
                kind: "script",
                text,
                item,
                owner: controller.state.storedId,
              });
              show("chat");
            }
          }}
          onCanvas={(attachment) => {
            if (attachment)
              setInitialImport({
                attachment,
                session: controller.state.sessionId,
                nonce: Date.now(),
              });
            show("canvas");
          }}
          externalSuggestion={suggestion}
          settingsNonce={settingsNonce}
        />
      </div>
      <div className="app-surface" hidden={module !== 'home'}><Suspense fallback={<p className="project-home-loading" role="status">正在读取项目…</p>}><StudioHome active={module==='home'} onChat={newFreeChat}/></Suspense></div>
      {creatorLoaded && (
        <div className="app-surface" hidden={module !== "creator"}>
          <Suspense
            fallback={<div style={{ padding: 40 }}>正在打开创作工作台…</div>}
          >
            <CreatorWorkspace
              active={module === "creator"}
              selectedProject={detailsProject}
              onBack={() => show('home')}
              incoming={undefined}
              onReturnDone={() => {
                setIncoming(undefined);
              }}
              onChat={async (p, node = 'brief') => {
                if (p) checkTaskDraft(p,node);
                if (p && node==='cover') return continueCanvas(p,undefined,true);
                if (p) {
                  p = await projectChat(p);
                  selectTarget(p, node);
                }
                show("chat");
                return p;
              }}
              onCanvas={continueCanvas}
              onDraft={async (text, p, node = 'script') => {
                let attachment: Attachment | undefined;
                if (p) {
                  p = await projectChat(p);
                  const pending = loadDraft(controller.state.storedId);
                  if (pending.text.trim() || pending.attachments.length)
                    throw new Error(
                      "项目对话已有待发草稿，请打开Chat处理后再带入，草稿已保留",
                    );
                  const image = node === 'brief' ? p.assets.source : p.assets.cover || p.assets.source;
                  if (image) {
                    const blob = await creatorBlob(p.id, image.id);
                    attachment = await uploadFile(
                      controller.state.storedId,
                      new File([blob], image.name),
                    );
                  }
                  selectTarget(p, node);
                }
                setSuggestion({
                  owner: controller.state.storedId,
                  text,
                  attachment,
                  skill: node === 'script' ? "spoken-script" : undefined,
                  nonce: Date.now(),
                });
                show("chat");
                return p;
              }}
            />
          </Suspense>
        </div>
      )}
      {canvasLoaded && (
        <div className="app-surface" hidden={module !== "canvas"}>
          <Suspense
            fallback={<div style={{ padding: 40 }}>正在打开图片工作区…</div>}
          >
            <CanvasApp
              controller={controller}
              active={module === "canvas"}
              initialImport={initialImport}
              onProjectReady={(origin, canvas) => {
                rememberCanvas(origin, canvas);
                setTarget(t => t?.id === origin.project && t.owner === origin.owner && t.image === origin.image ? {...t, canvas} : t);
              }}
              onChat={() => show("chat")}
              onBackToCreator={target ? () => show("creator") : undefined}
              creatorName={target?.name}
              creatorContext={target}
              onCreatorTurn={source => setTarget(t => t && t.id === source.project_id && t.owner === controller.state.storedId ? { ...t, revision: source.revision } : t)}
              onUseCreator={
                target
                  ? (attachment) => {
                      setIncoming({
                        project: target.id,
                        revision: target.revision,
                        nonce: Date.now(),
                        kind: "cover",
                        owner: controller.state.storedId,
                        attachment: attachment.id,
                        name: attachment.name,
                      });
                      show("chat");
                    }
                  : undefined
              }
              onUse={(attachment) => {
                setSuggestion({ attachment, nonce: Date.now(), owner: controller.state.storedId });
                show("chat");
              }}
              onSettings={() => {
                show("chat");
                setSettingsNonce(Date.now());
              }}
            />
          </Suspense>
        </div>
      )}
      {incoming && <CreatorAdoption key={incoming.nonce} incoming={incoming} owner={controller.state.storedId} onClose={()=>setIncoming(undefined)} onDone={p=>{if(p.chat_id===controller.state.storedId&&target?.id===p.id)selectTarget(p,target.node,target.canvas);setIncoming(undefined);}}/>}
    </>
  );
}
