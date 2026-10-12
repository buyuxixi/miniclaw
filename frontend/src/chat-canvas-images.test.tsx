// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { App } from './App';
import { Message } from './Message';
import { attachmentBlob, type Attachment } from './attachments';
import { writeApi, readApi } from './management-api';
import type { ChatController } from './chat-controller';
import type { ChatState } from './types';

vi.mock('./management-api', () => ({ readApi:vi.fn(), writeApi:vi.fn() }));
vi.mock('./attachments', () => ({ attachmentBlob:vi.fn(), uploadFile:vi.fn() }));
let host:HTMLDivElement;let root:Root;
const image:Attachment={id:'chat-image',name:'商品.png',kind:'image',mime:'image/png',bytes:100};
const target={workspace:'current-workspace',sessionId:'live-session'};
const saved={workspace:target.workspace,revision:3,object:'saved-node',added:true};
beforeEach(()=>{
  vi.resetAllMocks();vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
  Object.defineProperty(URL,'createObjectURL',{configurable:true,value:vi.fn(()=>'blob:fixture')});
  Object.defineProperty(URL,'revokeObjectURL',{configurable:true,value:vi.fn()});
  Object.defineProperty(Element.prototype,'scrollIntoView',{configurable:true,value:vi.fn()});
  Object.defineProperty(Element.prototype,'scrollTo',{configurable:true,value:vi.fn()});
  vi.mocked(attachmentBlob).mockResolvedValue(new Blob(['fixture']));
  vi.mocked(writeApi).mockResolvedValue(saved);localStorage.clear();
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();});
const addButton=()=>host.querySelector<HTMLButtonElement>('button[aria-label="将 商品.png 加入画布"]');
test('image handoff remains in Chat and shows the persisted canvas node',async()=>{
  const reuse=vi.fn();
  await act(async()=>root.render(<Message item={{id:'row-1',kind:'user',text:'保留原图',attachments:[image]}} owner="owner-one" onReuse={reuse} canvasTarget={target}/>));
  await act(async()=>addButton()!.click());
  expect(writeApi).toHaveBeenCalledWith('/api/workspaces/current-workspace/assets/from-chat','POST',{
    request_id:expect.any(String),session_id:'live-session',attachment:'chat-image',
  });
  expect(host.textContent).toContain('已加入画布');expect(host.textContent).toContain('保留原图');
  expect(host.querySelector('a[href="/p/current-workspace?focus=saved-node"]')).not.toBeNull();
  expect(reuse).not.toHaveBeenCalled();expect(addButton()).toBeNull();
});
test('handoff failure keeps the Chat image and retries the same save without sending',async()=>{
  vi.mocked(writeApi).mockRejectedValueOnce(new Error('项目关联已失效'));
  await act(async()=>root.render(<Message item={{id:'row-2',kind:'user',text:'原对话仍保留',attachments:[image]}} owner="owner-one" onReuse={()=>{}} canvasTarget={target}/>));
  await act(async()=>addButton()!.click());
  expect(host.querySelector('[role="alert"]')?.textContent).toContain('项目关联已失效');
  expect(host.querySelector('button[aria-label="预览 商品.png"] img')).not.toBeNull();expect(host.textContent).toContain('原对话仍保留');
  const requestId=vi.mocked(writeApi).mock.calls[0][2];
  await act(async()=>addButton()!.click());
  expect(vi.mocked(writeApi).mock.calls[1][2]).toEqual(requestId);expect(host.textContent).toContain('已加入画布');
});
test('only images in a current workspace receive the handoff action',async()=>{
  const item={id:'row-1',kind:'user' as const,text:'资料',attachments:[image,{...image,id:'text',name:'资料.txt',kind:'text' as const}]};
  await act(async()=>root.render(<Message item={item} owner="owner-one" onReuse={()=>{}}/>));
  expect(addButton()).toBeNull();
  await act(async()=>root.render(<Message item={item} owner="owner-one" onReuse={()=>{}} canvasTarget={target}/>));
  expect(host.querySelectorAll('button[aria-label$="加入画布"]')).toHaveLength(1);
});
test('completed tool image outputs use the same handoff action and duplicate feedback',async()=>{
  vi.mocked(writeApi).mockResolvedValue({...saved,added:false});
  const result={id:'job-one',state:'succeeded',operation:'rotate',provider:'local',source:{...image,id:'original'},output:image};
  await act(async()=>root.render(<Message item={{id:'tool-result',kind:'tool',text:'',name:'miniclaw_image_status',status:'done',result}} owner="owner-one" onReuse={()=>{}} canvasTarget={target}/>));
  await act(async()=>addButton()!.click());
  expect(host.textContent).toContain('画布已有这张图片');
  expect(vi.mocked(writeApi).mock.calls[0][2]).toEqual(expect.objectContaining({attachment:'chat-image'}));
});
test('App supplies only the linked workspace and preserves an unsent draft',async()=>{
  vi.mocked(readApi).mockImplementation(async path=>path.startsWith('/api/workspaces?owner=')?[{id:target.workspace,chat_id:'owner-one',name:'商品项目'}]:{});
  localStorage.setItem('miniclaw.draft.owner-one',JSON.stringify({text:'还未发送的修改要求',attachments:[]}));
  const state:ChatState={sessions:[],sessionId:'live-session',storedId:'owner-one',items:[{id:'row-1',kind:'user',text:'商品原图',attachments:[image]}],info:{},running:false,busy:false,status:'',error:''};
  const send=vi.fn();const c={state,connection:'open',connect:vi.fn(),dispose:vi.fn(),subscribe:()=>()=>{},send,client:{request:vi.fn()}} as unknown as ChatController;
  await act(async()=>root.render(<App controller={c}/>));
  await act(async()=>addButton()!.click());
  expect(host.querySelector<HTMLTextAreaElement>('textarea[aria-label="消息"]')?.value).toBe('还未发送的修改要求');
  expect(send).not.toHaveBeenCalled();expect(host.textContent).toContain('已加入画布');
});
test('target or image changes isolate pending results and create a new save request',async()=>{
  const render=async(canvasTarget=target,attachment=image)=>act(async()=>root.render(<Message item={{id:'row-1',kind:'user',text:'商品原图',attachments:[attachment]}} owner="owner-one" onReuse={()=>{}} canvasTarget={canvasTarget}/>));
  let release!:(value:typeof saved)=>void;
  vi.mocked(writeApi).mockImplementationOnce(()=>new Promise(resolve=>{release=resolve as typeof release;}));
  await render();
  await act(async()=>addButton()!.click());
  const firstBody=vi.mocked(writeApi).mock.calls[0][2] as {request_id:string};
  await render({...target,sessionId:'reconnected-session'});
  await act(async()=>release(saved));
  expect(host.textContent).not.toContain('已加入画布');expect(addButton()).not.toBeNull();
  await act(async()=>addButton()!.click());
  const secondBody=vi.mocked(writeApi).mock.calls[1][2] as {request_id:string;session_id:string};
  expect(secondBody.request_id).not.toBe(firstBody.request_id);expect(secondBody.session_id).toBe('reconnected-session');
  await render({workspace:'another-workspace',sessionId:'reconnected-session'});
  expect(host.textContent).not.toContain('已加入画布');expect(addButton()).not.toBeNull();
  await render({workspace:'another-workspace',sessionId:'reconnected-session'},{...image,id:'another-image'});
  await act(async()=>addButton()!.click());
  expect(vi.mocked(writeApi).mock.calls[2][0]).toBe('/api/workspaces/another-workspace/assets/from-chat');
  expect(vi.mocked(writeApi).mock.calls[2][2]).toEqual(expect.objectContaining({attachment:'another-image'}));
});
