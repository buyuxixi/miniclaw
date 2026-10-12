// @vitest-environment jsdom
import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {afterEach,beforeEach,expect,test,vi} from 'vitest';
import type {ChatController} from './chat-controller';
import {readApi,writeApi} from './management-api';
import type {ImagePlan} from './ImagePlanPanel';
vi.mock('./use-chat',()=>({useChat:(c:ChatController)=>({...c.state,connection:c.connection})}));
vi.mock('./management-api',()=>({readApi:vi.fn(),writeApi:vi.fn()}));
vi.mock('./canvas-api',async()=>({...await vi.importActual('./canvas-api'),loadProject:vi.fn(async()=>({project:{id:'precision',revision:1,document:{layers:[]}},jobs:[]}))}));
history.replaceState(null,'','/?director=workspace-one&target=asset-one');
const {StudioDirector}=await import('./StudioDirector');
(globalThis as any).IS_REACT_ACT_ENVIRONMENT=true;
const plan:ImagePlan={id:'plan-one',project:'precision',revision:1,input_revision:1,layer_id:'layer-one',goal:'加小痣',preserve:'五官与肤色',state:'proposed',steps:[{action:'ai_edit',label:'自然地加痣',params:{prompt:'眼角添加一颗浅褐色小痣。',region:false}}]};
let host:HTMLDivElement,root:ReturnType<typeof createRoot>,controller:ChatController,frame:{postMessage:ReturnType<typeof vi.fn>};
const state={assets:[{id:'asset-one',name:'原图',file:'/original.png',imagePrompt:'旧提示词',imageModel:'selected-model'}],shots:[]};
beforeEach(()=>{
  vi.clearAllMocks();localStorage.clear();
  vi.mocked(readApi).mockImplementation(async path=>path.includes('session-capabilities')?{ready:true,images:true}:path.endsWith('/plans')?[plan]:{state});
  vi.mocked(writeApi).mockResolvedValue({project:'precision',revision:1,layer:'layer-one',object:'asset-one',source:'/original.png'});
  controller={state:{items:[{id:'u1',kind:'user',text:'加小痣'},{id:'tool',kind:'tool',name:'miniclaw_canvas_propose',text:'',result:JSON.stringify({success:true,id:'plan-one',project:'precision'})},{id:'a1',kind:'assistant',text:'原来的方案'},{id:'u2',kind:'user',text:'这个效果不好'},{id:'a2',kind:'assistant',text:'哪里需要调整？'}],info:{tools:{canvas:['miniclaw_canvas_propose']}},sessionId:'live',storedId:'owner',busy:false,running:false},connection:'open',client:{onAny:()=>()=>{},onState:()=>()=>{}},send:vi.fn(async()=>true)} as unknown as ChatController;
  frame={postMessage:vi.fn((m)=>{if(m.type==='miniclaw.director.adopt-image-prompt')window.dispatchEvent(new MessageEvent('message',{origin:location.origin,source:frame as any,data:{type:'miniclaw.director.prompt-result',workspace:'workspace-one',request:m.request,ok:true}}));})};
  vi.stubGlobal('parent',frame);host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();});
async function render(){await act(async()=>root.render(<StudioDirector controller={controller}/>));}
function action(){return [...host.querySelectorAll('button')].find(b=>b.textContent==='回填画布，选择模型')!;}
test('the plan stays under its original reply when a later discussion is restored',async()=>{
  await render();const messages=host.querySelectorAll('article.assistant');
  expect(messages[0].nextElementSibling?.className).toBe('image-plan-panel');
  expect(messages[1].nextElementSibling?.classList.contains('image-plan-panel')).not.toBe(true);
  expect(host.querySelectorAll('.image-plan-panel')).toHaveLength(1);
});
test('refill saves only the prompt then asks the parent to open the selected canvas editor',async()=>{
  await render();await act(async()=>action().click());
  expect(frame.postMessage).toHaveBeenCalledWith(expect.objectContaining({type:'miniclaw.director.adopt-image-prompt',target:'asset-one',before:'旧提示词',file:'/original.png',task:'image-edit',prompt:'眼角添加一颗浅褐色小痣。\n必须保留：五官与肤色'}),location.origin);
  expect(frame.postMessage).toHaveBeenCalledWith({type:'miniclaw.director.return',workspace:'workspace-one',target:'asset-one',task:'image-edit'},location.origin);
  expect(writeApi).not.toHaveBeenCalledWith(expect.stringContaining('/generate'),expect.anything(),expect.anything());
  expect(controller.send).not.toHaveBeenCalled();expect(state.assets[0].imageModel).toBe('selected-model');
});
test('a changed canvas prompt stops refill and keeps the proposal available',async()=>{
  await render();vi.mocked(readApi).mockImplementation(async path=>path.endsWith('/plans')?[plan]:{state:{...state,assets:[{...state.assets[0],imagePrompt:'刚编辑的新要求'}]}});
  await act(async()=>action().click());
  expect(host.textContent).toContain('图片或提示词已变化');
  expect(frame.postMessage.mock.calls.some(([m])=>m.type==='miniclaw.director.adopt-image-prompt')).toBe(false);
  expect(action()).toBeDefined();
});
test('clarification answers use the discussion contract with plan-only permissions',async()=>{
  controller.state.items=[{id:'a',kind:'assistant',text:'先确认问题。\n```studio-question\n{"questions":[{"title":"哪里不满意？","options":["位置不对","变化太明显"]}]}\n```'}];
  await render();await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='位置不对')!.click());
  await act(async()=>host.querySelector('.director-questions')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(controller.send).toHaveBeenCalledWith('哪里不满意？\n位置不对',undefined,[],{project_id:'precision',revision:1,layer_id:'layer-one',mode:'plan'});
});

test('pending questions keep the director input visible and send changes through server task control',async()=>{
  controller.state.clarifications=[{id:'pending',task_id:'task',version:1,status:'pending',deadline:2000000000,questions:[{id:'color',question:'选择颜色',choices:['红色','蓝色'],multi_select:false}]}];
  localStorage.setItem('studio-director-chat-draft:workspace-one',JSON.stringify({target:'asset-one',text:'水平翻转'}));
  vi.mocked(controller.send).mockResolvedValue(false);
  await render();
  const input=host.querySelector<HTMLTextAreaElement>('#director-goal')!;
  expect(input.closest('[hidden]')).toBeNull();
  expect(input.disabled).toBe(false);
  await act(async()=>input.closest('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(controller.send).toHaveBeenCalledWith('水平翻转',undefined,[]);
  expect(input.value).toBe('水平翻转');
  expect(JSON.parse(localStorage.getItem('studio-director-chat-draft:workspace-one')!).text).toBe('水平翻转');
  expect(writeApi).not.toHaveBeenCalledWith(expect.stringContaining('/document'),expect.anything(),expect.anything());
});

test('pending text control does not require the referenced image model to have vision',async()=>{
  controller.state.clarifications=[{id:'pending',task_id:'task',version:1,status:'pending',deadline:2000000000,questions:[{id:'color',question:'选择颜色',choices:['红色'],multi_select:false}]}];
  localStorage.setItem('studio-director-chat-draft:workspace-one',JSON.stringify({target:'asset-one',text:'取消任务'}));
  vi.mocked(readApi).mockImplementation(async path=>path.includes('session-capabilities')?{ready:true,images:false}:path.endsWith('/plans')?[plan]:{state});
  await render();
  const submit=host.querySelector<HTMLButtonElement>('button[aria-label="发送要求"]')!;
  expect(submit.disabled).toBe(false);
  await act(async()=>submit.click());
  expect(controller.send).toHaveBeenCalledWith('取消任务',undefined,[]);
});

test('changing the target while refill is reading cannot write into either image',async()=>{
  await render();let finish!:(value:unknown)=>void;
  vi.mocked(readApi).mockImplementationOnce(()=>new Promise(resolve=>finish=resolve));
  await act(async()=>action().click());
  await act(async()=>window.dispatchEvent(new MessageEvent('message',{origin:location.origin,source:frame as any,data:{type:'miniclaw.director.target',workspace:'workspace-one',target:'asset-two',label:'另一张图',intent:'optimize-edit',request:2}})));
  await act(async()=>finish({state}));
  expect(frame.postMessage.mock.calls.some(([m])=>m.type==='miniclaw.director.adopt-image-prompt')).toBe(false);
  expect(frame.postMessage.mock.calls.some(([m])=>m.type==='miniclaw.director.return')).toBe(false);
});

test.each([true,false])('a delayed proposal follows the latest reply only when the reader is at the bottom: %s',async following=>{
  let finish!:(value:any)=>void;
  vi.mocked(readApi).mockImplementation(async path=>path.endsWith('/plans')?new Promise(resolve=>finish=resolve):{state});
  await render();const pane=host.querySelector('main')!;
  Object.defineProperties(pane,{scrollHeight:{configurable:true,value:1000},clientHeight:{configurable:true,value:400}});
  pane.scrollTop=following?600:150;
  await act(async()=>pane.dispatchEvent(new Event('scroll',{bubbles:true})));
  Object.defineProperty(pane,'scrollHeight',{configurable:true,value:1800});
  await act(async()=>finish([plan]));
  expect(pane.scrollTop).toBe(following?1800:150);
});
