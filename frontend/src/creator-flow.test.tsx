// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, test, vi } from 'vitest';
import { AppShell } from './AppShell';
import { creatorBlob, getCreator } from './creator-api';
import { uploadFile } from './attachments';
import type { ChatController } from './chat-controller';
import { loadProject } from './canvas-api';
import { rememberCanvas, workingCanvas } from './creator-canvas';
import { readApi, writeApi } from './management-api';
vi.mock('./management-api',()=>({writeApi:vi.fn(),readApi:vi.fn().mockResolvedValue([])}));
const p = {id:'project',name:'商品',revision:3,chat_id:'owner',assets:{source:{id:'raw',name:'product.png'}}};
const errors=vi.hoisted(()=>({text:''}));
vi.mock('./App',()=>({App:(props:any)=><div data-testid="chat">{props.externalSuggestion?.attachment?.id}<span>{props.creatorContext?.id}</span><span data-testid="node">{props.creatorContext?.node}</span><button onClick={()=>void props.onProjectTask?.('script')}>转口播</button><button onClick={()=>void props.onAdoptImage?.().catch((e:Error)=>{errors.text=e.message;})}>采用工作图</button><button onClick={props.onContinueCanvas}>继续修图</button></div>}));
vi.mock('./CreatorWorkspace',()=>({default:(props:any)=><><button onClick={()=>void props.onDraft('口播与修图要求',p).catch((e:Error)=>{errors.text=e.message;})}>带入</button><button onClick={()=>props.onCanvas(p)}>修图</button><button onClick={()=>props.onChat(p)}>项目聊天</button><button onClick={()=>void props.onChat(p,'cover').catch((e:Error)=>{errors.text=e.message;})}>节点图片</button></>}));
vi.mock('./StudioHome',()=>({default:(props:any)=> <div>创作看板<button data-testid="home-new-chat" onClick={()=>void props.onChat().catch((e:Error)=>{errors.text=e.message;})}>新建自由对话</button></div>}));
vi.mock('./CanvasApp',()=>({default:(props:any)=><div data-testid="canvas">{props.initialImport?.attachment?.id}<span>{props.creatorName}</span><span data-testid="canvas-id">{props.initialImport?.attachment?.canvas_project_id}</span><button onClick={()=>props.onProjectReady(props.initialImport.creator,'working')}>记住画布</button><button onClick={props.onBackToCreator}>返回创作</button></div>}));
vi.mock('./canvas-api',()=>({loadProject:vi.fn()}));
vi.mock('./creator-api',()=>({creatorBase:'/creator',creatorBlob:vi.fn(),getCreator:vi.fn()}));
vi.mock('./attachments',()=>({uploadFile:vi.fn(),attachmentBlob:vi.fn().mockResolvedValue(new Blob(['image']))}));
test('one project hands its source to Chat and Canvas without replacing pending drafts or creating another chat',async()=>{
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
  localStorage.clear();localStorage.setItem('miniclaw.module','creator');
  vi.mocked(creatorBlob).mockResolvedValue(new Blob(['raw']));
  vi.mocked(uploadFile).mockResolvedValue({id:'attached-raw',name:'product.png',kind:'image',mime:'image/png',bytes:3});
  const controller={connection:'open',state:{storedId:'owner',sessionId:'live',running:false,busy:false},newSession:vi.fn(),open:vi.fn()};
  const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
  try {
    await act(async()=>root.render(<AppShell controller={controller as unknown as ChatController}/>));
    const byText=(label:string)=>Array.from(host.querySelectorAll('button')).find(b=>b.textContent===label)!;
    const draft=byText('带入'),canvas=byText('修图'),chat=byText('项目聊天');
    localStorage.setItem('miniclaw.draft.owner',JSON.stringify({text:'已有草稿',attachments:[]}));
    await act(async()=>draft.click());
    expect(errors.text).toContain('已有待发草稿');
    expect(JSON.parse(localStorage.getItem('miniclaw.draft.owner')!).text).toBe('已有草稿');
    expect(uploadFile).not.toHaveBeenCalled();
    localStorage.removeItem('miniclaw.draft.owner');
    await act(async()=>draft.click());
    expect(creatorBlob).toHaveBeenCalledWith('project','raw');
    expect(uploadFile).toHaveBeenCalledWith('owner',expect.objectContaining({name:'product.png'}));
    expect(host.querySelector('[data-testid=chat]')?.textContent).toContain('attached-rawproject');
    await act(async()=>canvas.click());
    expect(host.querySelector('[data-testid=canvas]')?.textContent).toContain('attached-raw商品');
    expect(controller.newSession).not.toHaveBeenCalled();expect(controller.open).not.toHaveBeenCalled();
    controller.state.storedId='another';
    controller.open.mockImplementation(async(id:string)=>{controller.state.storedId=id;});
    await act(async()=>chat.click());
    expect(controller.open).toHaveBeenCalledWith('owner');
    expect(host.querySelector('[data-testid=chat]')?.textContent).toContain('project');
  } finally {await act(async()=>root.unmount());host.remove();localStorage.clear();vi.unstubAllGlobals();}
});

test('an unfinished canvas resumes from Chat without reuploading and rejects a foreign canvas', async()=>{
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
  vi.clearAllMocks();localStorage.clear();localStorage.setItem('miniclaw.module','creator');
  vi.mocked(creatorBlob).mockResolvedValue(new Blob(['raw']));
  vi.mocked(uploadFile).mockResolvedValue({id:'attached-raw',name:'product.png',kind:'image',mime:'image/png',bytes:3});
  vi.mocked(getCreator).mockResolvedValue(p as any);
  vi.mocked(loadProject).mockResolvedValue({project:{id:'working',chat_id:'owner',archived:false}} as any);
  const controller={connection:'open',state:{storedId:'owner',sessionId:'live',running:false,busy:false}};
  const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
  const click=(label:string)=>Array.from(host.querySelectorAll('button')).find(b=>b.textContent===label)!.click();
  try {
    await act(async()=>root.render(<AppShell controller={controller as unknown as ChatController}/>));
    await act(async()=>click('修图'));
    await act(async()=>click('记住画布'));
    expect(workingCanvas(p as any)).toBe('working');
    await act(async()=>click('返回创作'));
    expect(Array.from(host.querySelectorAll('button')).find(b=>b.textContent==='修图')?.closest('.app-surface')?.hasAttribute('hidden')).toBe(false);
    const uploads=vi.mocked(uploadFile).mock.calls.length;
    await act(async()=>click('项目聊天'));
    await act(async()=>click('继续修图'));
    expect(host.querySelector('[data-testid="canvas-id"]')?.textContent).toBe('working');
    expect(uploadFile).toHaveBeenCalledTimes(uploads);
    vi.mocked(loadProject).mockResolvedValue({project:{id:'working',chat_id:'another',archived:false}} as any);
    await act(async()=>click('继续修图'));
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('不属于当前项目');
    expect(uploadFile).toHaveBeenCalledTimes(uploads);
  } finally {await act(async()=>root.unmount());host.remove();localStorage.clear();vi.unstubAllGlobals();}
});

test('navigation hints stop matching when the chosen image or conversation changes',()=>{
  localStorage.clear();rememberCanvas({project:'project',owner:'owner',image:'raw'},'working');
  expect(workingCanvas(p as any)).toBe('working');
  expect(workingCanvas({...p,chat_id:'another'} as any)).toBeUndefined();
  expect(workingCanvas({...p,assets:{source:{id:'new'}}} as any)).toBeUndefined();
  expect(workingCanvas({...p,assets:{...p.assets,cover:{id:'adopted'}}} as any)).toBeUndefined();
  localStorage.clear();
});

test('reload restores an explicitly entered project only for its own conversation',async()=>{
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
  localStorage.clear();localStorage.setItem('miniclaw.creator.chat',JSON.stringify({id:'project',node:'script'}));
  localStorage.setItem('miniclaw.creator.active-owner','owner');
  const controller={connection:'open',subscribe:()=>()=>{},state:{storedId:'owner',sessionId:'live',running:false,busy:false}};
  const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
  try {
    vi.mocked(getCreator).mockResolvedValue(p as any);
    await act(async()=>root.render(<AppShell controller={controller as unknown as ChatController}/>));
    expect(host.querySelector('[data-testid=chat]')?.textContent).toContain('project');
    await act(async()=>root.unmount());
    const otherRoot=createRoot(host);vi.mocked(getCreator).mockResolvedValue({...p,chat_id:'another'} as any);
    try {
      await act(async()=>otherRoot.render(<AppShell controller={controller as unknown as ChatController}/>));
      expect(host.querySelector('[data-testid=chat]')?.textContent).not.toContain('project');
    } finally {await act(async()=>otherRoot.unmount());}
  } finally {host.remove();localStorage.clear();vi.unstubAllGlobals();}
});


test('the image flow enters the same Chat with its canvas hidden, and switching refuses pending drafts', async()=>{
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.clearAllMocks();localStorage.clear();localStorage.setItem('miniclaw.module','creator');
  rememberCanvas({project:p.id,owner:'owner',image:'raw'},'working');
  vi.mocked(getCreator).mockResolvedValue(p as any);
  vi.mocked(loadProject).mockResolvedValue({project:{id:'working',chat_id:'owner',archived:false}} as any);
  const controller={connection:'open',state:{storedId:'owner',sessionId:'live',running:false,busy:false},send:vi.fn()};
  const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
  const click=(text:string)=>Array.from(host.querySelectorAll('button')).find(b=>b.textContent===text)!.click();
  try {
    await act(async()=>root.render(<AppShell controller={controller as unknown as ChatController}/>));
    await act(async()=>click('节点图片'));
    expect(host.querySelector('[data-testid="node"]')?.textContent).toBe('cover');
    expect(host.querySelector('[data-testid="chat"]')?.closest('.app-surface')?.hasAttribute('hidden')).toBe(false);
    expect(host.querySelector('[data-testid="canvas"]')?.closest('.app-surface')?.hasAttribute('hidden')).toBe(true);
    expect(uploadFile).not.toHaveBeenCalled();
    vi.mocked(writeApi).mockResolvedValue({id:'exported',name:'canvas.png'});
    await act(async()=>click('采用工作图'));
    expect(writeApi).toHaveBeenLastCalledWith('/api/miniclaw/canvas/projects/working/send-chat','POST',{session_id:'live'});
    expect(host.querySelector('dialog[open]')?.textContent).toContain('确认采用工作图');
    expect(host.querySelector('[data-testid="chat"]')?.closest('.app-surface')?.hasAttribute('hidden')).toBe(false);
    await act(async()=>click('暂不采用'));
    localStorage.setItem('miniclaw.draft.owner',JSON.stringify({text:'未发送的修改要求',attachments:[]}));
    await act(async()=>click('转口播'));
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('未发送内容');
    expect(host.querySelector('[data-testid="node"]')?.textContent).toBe('cover');
    localStorage.removeItem('miniclaw.draft.owner');
    await act(async()=>click('转口播'));
    expect(host.querySelector('[data-testid="node"]')?.textContent).toBe('script');
    expect(controller.send).not.toHaveBeenCalled();
  } finally {await act(async()=>root.unmount());host.remove();localStorage.clear();vi.unstubAllGlobals();}
});


test('history selection stays in free Chat even for linked projects and rejects a late project response',async()=>{
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.clearAllMocks();localStorage.clear();localStorage.setItem('miniclaw.module','chat');
  localStorage.setItem('miniclaw.creator.chat.owner-a',JSON.stringify({id:'a',node:'script'}));
  localStorage.setItem('miniclaw.creator.chat.owner-b',JSON.stringify({id:'b',node:'video'}));
  localStorage.setItem('miniclaw.creator.active-owner','owner-a');
  let notify=()=>{};let finishA:(p:any)=>void=()=>{};
  const slowA=new Promise<any>(resolve=>{finishA=resolve;});
  vi.mocked(getCreator).mockImplementation(async id=>id==='a'?slowA:({...p,id:'b',chat_id:'owner-b',assets:{}} as any));
  const controller={connection:'open',subscribe:(f:()=>void)=>{notify=f;return()=>{};},state:{storedId:'owner-a',sessionId:'live-a',running:false,busy:false}};
  const host=document.createElement('div'),root=createRoot(host);document.body.append(host);
  try{
    await act(async()=>root.render(<AppShell controller={controller as unknown as ChatController}/>));
    await act(async()=>{controller.state.storedId='owner-b';notify();});
    expect(host.querySelector('[data-testid=node]')?.textContent).toBe('');
    await act(async()=>finishA({...p,id:'a',chat_id:'owner-a',assets:{}}));
    expect(host.querySelector('[data-testid=node]')?.textContent).toBe('');
    await act(async()=>{controller.state.storedId='owner-a';notify();});
    expect(host.querySelector('[data-testid=node]')?.textContent).toBe('');
  }finally{await act(async()=>root.unmount());host.remove();localStorage.clear();vi.unstubAllGlobals();}
});

test('missing local selection is recovered from the durable project chat link',async()=>{
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.clearAllMocks();localStorage.clear();localStorage.setItem('miniclaw.module','chat');
  localStorage.setItem('miniclaw.creator.active-owner','owner');
  vi.mocked(readApi).mockResolvedValue([{id:'project'}]);vi.mocked(getCreator).mockResolvedValue({...p,assets:{}} as any);
  const controller={connection:'open',subscribe:()=>()=>{},state:{storedId:'owner',sessionId:'live',running:false,busy:false}};
  const host=document.createElement('div'),root=createRoot(host);document.body.append(host);
  try{
    await act(async()=>root.render(<AppShell controller={controller as unknown as ChatController}/>));
    expect(readApi).toHaveBeenCalledWith('/creator/projects?owner=owner');
    expect(host.querySelector('[data-testid=chat]')?.textContent).toContain('project');
    expect(JSON.parse(localStorage.getItem('miniclaw.creator.chat.owner')!).id).toBe('project');
  }finally{await act(async()=>root.unmount());host.remove();localStorage.clear();vi.unstubAllGlobals();}
});

test('dashboard free Chat creates an unlinked conversation while preserving the project selection and draft',async()=>{
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.clearAllMocks();localStorage.clear();
  localStorage.setItem('miniclaw.creator.chat.owner',JSON.stringify({id:'project',node:'script'}));
  localStorage.setItem('miniclaw.draft.owner',JSON.stringify({text:'项目待发草稿',attachments:[]}));
  vi.mocked(readApi).mockResolvedValue([]);vi.mocked(getCreator).mockResolvedValue({...p,assets:{}} as any);
  let notify=()=>{};
  const controller={connection:'open',subscribe:(fn:()=>void)=>{notify=fn;return()=>{};},state:{storedId:'owner',sessionId:'live',running:true,busy:false,error:''},newSession:vi.fn()};
  controller.newSession.mockImplementation(async()=>{controller.state.storedId='free';controller.state.sessionId='live-free';notify();});
  const host=document.createElement('div'),root=createRoot(host);document.body.append(host);
  try{
    await act(async()=>root.render(<AppShell controller={controller as unknown as ChatController}/>));
    const click=()=>host.querySelector<HTMLButtonElement>('[data-testid=home-new-chat]')!.click();
    await act(async()=>click());
    expect(controller.newSession).not.toHaveBeenCalled();
    expect(errors.text).toContain('当前任务完成');
    await act(async()=>{controller.state.running=false;click();});
    expect(controller.newSession).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem('miniclaw.module')).toBe('chat');
    expect(host.querySelector('[data-testid=chat]')?.textContent).not.toContain('project');
    expect(JSON.parse(localStorage.getItem('miniclaw.creator.chat.owner')!).id).toBe('project');
    expect(JSON.parse(localStorage.getItem('miniclaw.draft.owner')!).text).toBe('项目待发草稿');
    expect(writeApi).not.toHaveBeenCalled();
  }finally{await act(async()=>root.unmount());host.remove();localStorage.clear();vi.unstubAllGlobals();}
});

test('canvas free Chat ignores legacy project layout even when the session has an explicit legacy selection',async()=>{
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('location',{search:'?workspace=canvas-fixture'});vi.clearAllMocks();localStorage.clear();
  localStorage.setItem('miniclaw.creator.active-owner','owner');localStorage.setItem('miniclaw.creator.chat.owner',JSON.stringify({id:'project',node:'cover'}));
  const controller={connection:'open',subscribe:()=>()=>{},state:{storedId:'owner',sessionId:'live',running:false,busy:false}};
  const host=document.createElement('div'),root=createRoot(host);document.body.append(host);
  try{
    await act(async()=>root.render(<AppShell controller={controller as unknown as ChatController}/>));
    expect(host.querySelector('[data-testid=node]')?.textContent).toBe('');
    expect(getCreator).not.toHaveBeenCalled();
    expect(host.querySelector('[data-testid=chat]')?.closest('.app-surface')?.hasAttribute('hidden')).toBe(false);
  }finally{await act(async()=>root.unmount());host.remove();localStorage.clear();vi.unstubAllGlobals();}
});
