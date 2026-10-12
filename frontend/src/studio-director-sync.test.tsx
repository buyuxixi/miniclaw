// @vitest-environment jsdom
import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {afterEach,beforeEach,expect,test,vi} from 'vitest';
import {GatewayEventHub, type ConnectionState, type GatewayEvent} from '../../hermes-agent/apps/shared/src/json-rpc-gateway';
import type {ChatController} from './chat-controller';

vi.mock('./use-chat',()=>({useChat:(controller:ChatController)=>({...controller.state,connection:controller.connection})}));
vi.mock('./management-api',()=>({readApi:vi.fn(async()=>({state:{shots:[{id:'shot-one',name:'产品镜头',prompt:'保持包装',mode:'first',first:'asset-one',refs:[]}],assets:[{id:'asset-one',name:'产品首帧',file:'/image.png'}]}})),writeApi:vi.fn()}));
vi.mock('./Message',()=>({Message:()=>null}));
history.replaceState(null,'','/?director=workspace-one&target=shot-one');
const {StudioDirector}=await import('./StudioDirector');
(globalThis as any).IS_REACT_ACT_ENVIRONMENT=true;
Element.prototype.scrollIntoView=vi.fn();

let host:HTMLDivElement,root:ReturnType<typeof createRoot>,controller:ChatController;
let events:GatewayEventHub,stateListeners:Set<(state:ConnectionState)=>void>;
let frameParent:{postMessage:ReturnType<typeof vi.fn>};
beforeEach(()=>{
  localStorage.clear();events=new GatewayEventHub();stateListeners=new Set();
  controller={state:{sessions:[],items:[],info:{},sessionId:'live',storedId:'owner',busy:false,running:false,status:'',error:''},connection:'open',
    client:{onAny:events.onAny.bind(events),onState:(listener:(state:ConnectionState)=>void)=>{stateListeners.add(listener);return()=>stateListeners.delete(listener);}}} as unknown as ChatController;
  frameParent={postMessage:vi.fn()};vi.stubGlobal('parent',frameParent);
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();vi.restoreAllMocks();});
async function render(){await act(async()=>root.render(<StudioDirector controller={controller}/>));}
function emit(type:GatewayEvent['type'],payload:Record<string,unknown>={},extra:Partial<GatewayEvent>={}){events.dispatch({type,session_id:'live',payload,...extra} as GatewayEvent);}
function changes(){return frameParent.postMessage.mock.calls.filter(([message])=>message.type==='miniclaw.director.changed');}

test('restoring history or mounting an active session does not announce a project change',async()=>{
  controller.state={...controller.state,running:true,items:[{id:'row-1',kind:'tool',text:'',status:'done',name:'miniclaw_studio_view'}]};
  await render();expect(changes()).toHaveLength(0);
  controller.state={...controller.state,running:false,items:[...controller.state.items,{id:'row-2',kind:'assistant',text:'历史回复',status:'done'}]};
  await render();expect(changes()).toHaveLength(0);
  emit('tool.complete',{}, {replayed:true});emit('message.complete',{}, {replayed:true});
  expect(changes()).toHaveLength(0);
});

test('fresh tool completion and turn completion request a revision check in the same-origin parent',async()=>{
  await render();emit('message.start');emit('tool.start');expect(changes()).toHaveLength(0);
  emit('tool.complete',{tool_id:'tool-one',result:{ok:true}});
  expect(changes()).toEqual([[{type:'miniclaw.director.changed',workspace:'workspace-one'},location.origin]]);
  emit('message.complete',{status:'done'});expect(changes()).toHaveLength(2);
});

test.each(['done','error','interrupted'])('a fresh %s turn completion still checks for work already applied',async status=>{
  await render();emit('message.complete',{status});expect(changes()).toHaveLength(1);
});

test('failed tools and execution errors check for partial changes without treating a connection error as work',async()=>{
  await render();emit('error',{message:'连接异常'});expect(changes()).toHaveLength(0);
  emit('tool.start');emit('tool.complete',{tool_id:'tool-one',result:{error:'后续步骤失败'}});expect(changes()).toHaveLength(1);
  emit('error',{message:'本轮执行失败'});expect(changes()).toHaveLength(2);
  emit('error',{message:'重复错误'});expect(changes()).toHaveLength(2);
});

test('other sessions and closed connections cannot announce changes, and unmount removes listeners',async()=>{
  await render();emit('message.complete',{}, {session_id:'other-session'});expect(changes()).toHaveLength(0);
  emit('message.start');controller.connection='closed';for(const listener of stateListeners)listener('closed');
  emit('tool.complete');emit('message.complete');expect(changes()).toHaveLength(0);
  controller.connection='open';emit('error',{message:'重新连接失败'});expect(changes()).toHaveLength(0);
  await act(async()=>root.unmount());root=createRoot(host);expect(stateListeners.size).toBe(0);
  emit('tool.complete');expect(changes()).toHaveLength(0);
});

test('the standalone director never sends the embedded change notification',async()=>{
  vi.stubGlobal('parent',window);vi.spyOn(window,'postMessage').mockImplementation(()=>{});
  await render();emit('tool.complete');emit('message.complete');
  expect(window.postMessage).not.toHaveBeenCalledWith(expect.objectContaining({type:'miniclaw.director.changed'}),location.origin);
});

test('streaming replies preserve a reader browsing history and resume only on request',async()=>{
  await render();const pane=host.querySelector('main')!;
  Object.defineProperties(pane,{scrollHeight:{configurable:true,value:1400},clientHeight:{configurable:true,value:400}});
  pane.scrollTop=200;
  await act(async()=>pane.dispatchEvent(new Event('scroll',{bubbles:true})));
  controller.state={...controller.state,items:[{id:'reply',kind:'assistant',status:'running',text:'新回复的第一段'}]};
  await render();expect(pane.scrollTop).toBe(200);
  const latest=[...host.querySelectorAll('button')].find(b=>b.textContent==='↓ 回到最新消息')!;
  expect(latest).toBeDefined();
  await act(async()=>latest.click());expect(pane.scrollTop).toBe(1400);
  pane.scrollTop=1000;
  Object.defineProperty(pane,'scrollHeight',{configurable:true,value:1600});
  controller.state={...controller.state,items:[{id:'reply',kind:'assistant',status:'running',text:'新回复的第一段和第二段'}]};
  await render();expect(pane.scrollTop).toBe(1600);
  expect(host.querySelector('.director-latest')).toBeNull();
});

test('following a reply scrolls the conversation without moving the embedded page',async()=>{
  await render();const pane=host.querySelector('main')!;
  Object.defineProperties(pane,{scrollHeight:{configurable:true,value:900},clientHeight:{configurable:true,value:400}});
  pane.scrollTop=480;
  await act(async()=>pane.dispatchEvent(new Event('scroll',{bubbles:true})));
  controller.state={...controller.state,items:[{id:'reply',kind:'assistant',status:'running',text:'继续输出'}]};
  await render();expect(pane.scrollTop).toBe(900);
  expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled();
});
