// @vitest-environment jsdom
import {expect,test,vi} from 'vitest';
import {ChatController} from './chat-controller';
import {readApi,writeApi} from './management-api';
const rpc=vi.hoisted(()=>vi.fn());
vi.mock('./gateway',()=>({gatewayUrl:async()=>'/api/ws',JsonRpcGatewayClient:class{
  onAny(){} onState(){} async connect(){} request=rpc;
}}));
vi.mock('./management-api',()=>({readApi:vi.fn(),writeApi:vi.fn()}));

test('new project Chat links the captured workspace before exposing it to association lookup',async()=>{
  localStorage.clear();history.replaceState(null,'','/?workspace=project-fixture&target=shot-one');
  const controller=new ChatController();controller.workspace={id:'project-fixture',target:'shot-one'};
  rpc.mockImplementation(async method=>method==='session.list'?{sessions:[]}:{session_id:'live-new',stored_session_id:'stored-new',messages:[],info:{}});
  vi.mocked(readApi).mockResolvedValue({});vi.mocked(writeApi).mockResolvedValue({chat_id:'stored-new'});
  const pending:boolean[]=[];
  controller.subscribe(()=>{pending.push(!!controller.state.workspaceConnecting);if(controller.state.storedId)controller.workspace=undefined;});
  await controller.connect();
  expect(writeApi).toHaveBeenCalledWith('/api/workspaces/project-fixture/chat','POST',{session_id:'live-new'});
  expect(controller.state.error).toBe('');expect(controller.state.workspaceConnecting).toBe(false);
  expect(pending.slice(0,-1).every(Boolean)).toBe(true);
});

test('a mismatched project conversation cannot silently send without project context',async()=>{
  rpc.mockClear();vi.mocked(readApi).mockResolvedValue({chat_id:'other-chat'});
  const controller=new ChatController();controller.connection='open';controller.workspace={id:'project-one',target:'image-one'};
  controller.state={...controller.state,sessionId:'live',storedId:'chat-one'};
  expect(await controller.send('adjust this')).toBe(false);
  expect(controller.state.error).toContain('未关联');expect(rpc).not.toHaveBeenCalled();expect(controller.state.items).toHaveLength(0);
});

test('switching the selected target during asynchronous preparation preserves the draft and aborts',async()=>{
  rpc.mockClear();let resolve!:(value:unknown)=>void;
  vi.mocked(readApi).mockResolvedValueOnce({chat_id:'chat-one'}).mockImplementationOnce(()=>new Promise(r=>{resolve=r;}) as ReturnType<typeof readApi>);
  const controller=new ChatController();controller.connection='open';controller.workspace={id:'project-one',target:'image-one'};
  controller.state={...controller.state,sessionId:'live',storedId:'chat-one'};
  const sending=controller.send('rotate');await Promise.resolve();await Promise.resolve();
  controller.workspace={id:'project-two',target:'image-two'};resolve({revision:3});
  expect(await sending).toBe(false);expect(controller.state.error).toContain('已切换');expect(rpc).not.toHaveBeenCalled();
});
