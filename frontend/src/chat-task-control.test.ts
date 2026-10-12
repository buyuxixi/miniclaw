// @vitest-environment jsdom
import {afterEach,beforeEach,expect,test,vi} from 'vitest';
import {ChatController} from './chat-controller';
import {readApi} from './management-api';
import type {ClarificationRequest} from './types';

const rpc=vi.hoisted(()=>vi.fn());
vi.mock('./gateway',()=>({gatewayUrl:async()=>'/api/ws',JsonRpcGatewayClient:class {
  onAny() {} onState() {} close() {} request=rpc;
}}));
vi.mock('./management-api',()=>({readApi:vi.fn(async()=>({}))}));
const pending:ClarificationRequest={id:'question',task_id:'task',version:1,status:'pending',deadline:2000000000,questions:[{id:'color',question:'选择颜色',choices:['红色','蓝色'],multi_select:false}]};
let chat:ChatController;
beforeEach(()=>{
  vi.clearAllMocks();localStorage.clear();
  chat=new ChatController();chat.connection='open';chat.workspace={id:'project',target:'image'};
  chat.state={...chat.state,sessionId:'live',storedId:'owner',items:[{id:'old',kind:'assistant',text:'等待选择颜色'}],clarifications:[pending]};
});
afterEach(()=>chat.dispose());

test.each(['cancel','revise','new_topic'] as const)('a %s receipt without model work ends submission and restores authoritative history',async action=>{
  rpc.mockImplementation(async method=>method==='miniclaw.turn.submit'?{status:'completed',task_control:{action,status:'completed',message:'要求已处理',no_model:true}}:
    method==='session.history'?{messages:[{row_id:1,role:'user',text:'先取消这轮任务'},{row_id:2,role:'assistant',text:'要求已处理'}]}:
    method==='miniclaw.clarification.list'?{requests:[]}:{sessions:[]});
  expect(await chat.send('先取消这轮任务','canvas-editor',[],{project_id:'canvas',revision:1,layer_id:'layer'},undefined,{task:'image-edit'})).toBe(true);
  expect(rpc).toHaveBeenCalledWith('miniclaw.turn.submit',{session_id:'live',text:'先取消这轮任务',attachments:[]});
  expect(readApi).not.toHaveBeenCalledWith(expect.stringContaining('/workspaces/'));
  expect(chat.state.running).toBe(false);
  expect(chat.state.status).toBe('要求已处理');
  expect(chat.state.clarifications).toEqual([]);
  expect(chat.state.items.map(item=>item.id)).toEqual(['row-1','row-2']);
  expect(rpc.mock.calls.some(([method])=>method==='file.read'||method==='tool.execute')).toBe(false);
});

test('an unclear relationship keeps the input unaccepted and preserves the pending question',async()=>{
  const previous=chat.state.items;
  rpc.mockImplementation(async method=>method==='miniclaw.turn.submit'?{status:'awaiting_input',task_control:{action:'clarify',status:'awaiting_input',message:'请说明是回答问题、修改要求，还是开始新话题。',no_model:true}}:{requests:[pending]});
  expect(await chat.send('换一个吧','canvas-editor')).toBe(false);
  expect(chat.state.items).toBe(previous);
  expect(chat.state.running).toBe(false);
  expect(chat.state.error).toContain('请说明');
  expect(chat.state.clarifications).toEqual([pending]);
  expect(rpc.mock.calls.some(([method])=>method==='session.history')).toBe(false);
});

test('a revision accepted for model execution follows the existing streaming path',async()=>{
  rpc.mockResolvedValue({status:'streaming',task_control:{action:'revise',status:'running',message:'已更新要求',no_model:false}});
  expect(await chat.send('修改要求：背景改成白色')).toBe(true);
  expect(chat.state.running).toBe(true);
  expect(chat.state.items.at(-1)?.text).toBe('修改要求：背景改成白色');
  expect(rpc).toHaveBeenCalledTimes(1);
});

test('pending attachment drafts are refused without silently dropping files or making calls',async()=>{
  expect(await chat.send('取消任务',undefined,[{id:'image',name:'image.png',kind:'image',mime:'image/png',bytes:10}])).toBe(false);
  expect(chat.state.error).toContain('附件草稿已保留');
  expect(chat.state.items).toHaveLength(1);
  expect(chat.state.running).toBe(false);
  expect(rpc).not.toHaveBeenCalled();
});

test('execution still blocks new input and a delayed receipt cannot replace another session',async()=>{
  chat.state.running=true;
  expect(await chat.send('修改要求')).toBe(false);
  expect(rpc).not.toHaveBeenCalled();
  chat.state.running=false;
  let finish!:(value:unknown)=>void;
  rpc.mockImplementation(()=>new Promise(resolve=>finish=resolve));
  const submitted=chat.send('取消任务');
  chat.state={...chat.state,sessionId:'another-live',storedId:'another-owner',running:false,status:'另一个会话',items:[],clarifications:[]};
  finish({task_control:{action:'cancel',status:'completed',message:'旧任务已取消',no_model:true}});
  expect(await submitted).toBe(false);
  expect(chat.state.status).toBe('另一个会话');
  expect(chat.state.items).toEqual([]);
  expect(rpc).toHaveBeenCalledTimes(1);
});

test('reattaching the same live session also retires a delayed control receipt',async()=>{
  let finish!:(value:unknown)=>void;
  rpc.mockImplementation(async method=>method==='miniclaw.turn.submit'?new Promise(resolve=>finish=resolve):
    method==='session.resume'?{session_id:'live',stored_session_id:'owner',running:false,info:{},messages:[]}:{requests:[]});
  const submitted=chat.send('取消任务');
  await chat.open('owner',true);
  finish({task_control:{action:'cancel',status:'completed',message:'旧提交取消回执',no_model:true}});
  expect(await submitted).toBe(false);
  expect(chat.state.status).toBe('');
  expect(chat.state.items).toEqual([]);
  expect(rpc.mock.calls.some(([method])=>method==='session.history')).toBe(false);
});

test('a completed control preserves a warning when its history receipt could not be saved',async()=>{
  rpc.mockImplementation(async method=>method==='miniclaw.turn.submit'?{warning:'任务已取消，但控制回执未能写入历史，请核对。',task_control:{action:'cancel',status:'completed',message:'旧任务已取消',no_model:true}}:
    method==='session.history'?{messages:[]}:
    method==='miniclaw.clarification.list'?{requests:[]}:{sessions:[]});
  expect(await chat.send('取消任务')).toBe(true);
  expect(chat.state.running).toBe(false);
  expect(chat.state.status).toBe('旧任务已取消');
  expect(chat.state.error).toContain('控制回执未能写入历史');
});

test.each(['session.history','miniclaw.clarification.list'])('switching sessions while %s is pending cannot return success for an old control',async deferredMethod=>{
  let finish!:(value:unknown)=>void,started!:()=>void;
  const startedRead=new Promise<void>(resolve=>started=resolve);
  rpc.mockImplementation(async (method,params)=>method==='miniclaw.turn.submit'?{task_control:{action:'cancel',status:'completed',message:'旧任务已取消',no_model:true}}:
    method===deferredMethod&&params?.session_id==='live'?new Promise(resolve=>{finish=resolve;started();}):
    method==='session.resume'?{session_id:'other-live',stored_session_id:'other-owner',running:false,info:{},messages:[]}:
    method==='session.history'?{messages:[]}:
    method==='miniclaw.clarification.list'?{requests:[]}:{sessions:[]});
  const submitted=chat.send('取消任务');
  await startedRead;
  await chat.open('other-owner',true);
  finish(deferredMethod==='session.history'?{messages:[{row_id:1,role:'assistant',text:'旧任务回执'}]}:{requests:[]});
  expect(await submitted).toBe(false);
  expect(chat.state.sessionId).toBe('other-live');
  expect(chat.state.items).toEqual([]);
  expect(chat.state.status).toBe('');
});
