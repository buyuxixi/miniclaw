// @vitest-environment jsdom
import {expect,test,vi} from 'vitest';
import {ChatController} from './chat-controller';
import {readApi,writeApi} from './management-api';
const rpc=vi.hoisted(()=>vi.fn());
vi.mock('./gateway',()=>({gatewayUrl:async()=>'/api/ws',JsonRpcGatewayClient:class{
  onAny(){} onState(){} async connect(){} request=rpc;
}}));
vi.mock('./management-api',()=>({readApi:vi.fn(),writeApi:vi.fn()}));

test('changing sessions updates the canonical URL before optional project metadata loads',async()=>{
  history.replaceState(null,'','/c/old-chat?workspace=project-one&target=shot-one&message=row-2');
  rpc.mockImplementation(async()=>({session_id:'live-new',stored_session_id:'new-chat',messages:[],info:{}}));
  const controller=new ChatController();controller.state={...controller.state,storedId:'old-chat'};
  await controller.newSession();
  expect(location.pathname).toBe('/c/new-chat');expect(location.search).not.toContain('target=');expect(location.search).not.toContain('message=');
  expect(controller.resumeId).toBe('new-chat');history.replaceState(null,'','/');
});

test('restoring a skill reply retains multiline display, skill identity and image ownership',async()=>{
  rpc.mockReset();vi.mocked(readApi).mockReset();
  const text='/product-video-plan\n1.真实素材\n2.清新方向';
  const image={id:'image-one',name:'原图.png',kind:'image',mime:'image/png',bytes:100};
  rpc.mockResolvedValue({session_id:'live-restored',stored_session_id:'chat-restored',messages:[{row_id:352,role:'user',text:'/product-video-plan 1.真实素材 2.清新方向'}],info:{}});
  vi.mocked(readApi).mockResolvedValue({'352':{text,skill:'product-video-plan',attachments:[image]}});
  const controller=new ChatController();await controller.open('chat-restored');
  expect(readApi).toHaveBeenCalledWith('/api/miniclaw/turns?owner=chat-restored');
  expect(controller.state.items[0]).toMatchObject({id:'row-352',text,skill:'product-video-plan',attachments:[image]});
});

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
  expect(await sending).toBe(false);expect(controller.state.error).toContain('引用已变化');expect(rpc).not.toHaveBeenCalled();
});

test('director submits the question separately and restores it without context scaffolding',async()=>{
  rpc.mockReset();vi.mocked(readApi).mockReset();
  const question='那怎么改？\n改提示词还是怎么改？';
  const skill={name:'product-prompt-optimize',enabled:true,binding:{current:true,required_tools:[]}};
  vi.mocked(readApi).mockImplementation(async path=>path==='/api/miniclaw/skills'?[skill]:path.endsWith('/chat')?{chat_id:'owner'}:path.includes('/turns')?{'42':{text:'/product-prompt-optimize\n'+question,attachments:[],skill:skill.name}}:{revision:4});
  rpc.mockImplementation(async method=>method==='commands.catalog'?{skills:{'/product-prompt-optimize':{}},categories:[]}:method==='miniclaw.turn.submit'?{status:'streaming'}:{sessions:[]});
  const controller=new ChatController();controller.connection='open';controller.workspace={id:'workspace',target:'shot'};
  controller.state={...controller.state,sessionId:'live',storedId:'owner'};
  expect(await controller.send(question,skill.name,[],undefined,undefined,{task:'video'})).toBe(true);
  expect(controller.state.items[0].text).toBe('/product-prompt-optimize\n'+question);
  expect(rpc).toHaveBeenCalledWith('miniclaw.turn.submit',{session_id:'live',text:question,skill:skill.name,attachments:[],studio_context:{workspace:'workspace',target:'shot',revision:4},director_context:{task:'video'}});
  rpc.mockResolvedValue({session_id:'live',stored_session_id:'owner',messages:[{row_id:42,role:'user',text:'MODEL CONTEXT'}],info:{}});
  await controller.open('owner',true);
  expect(controller.state.items[0].text).toBe('/product-prompt-optimize\n'+question);
});

test('shot references carry citations and never implicitly open their first frame as an edit target',async()=>{
  rpc.mockReset();vi.mocked(writeApi).mockClear();
  const refs=[{id:'shot',name:'开场',kind:'shot',text:'撩发',images:[{id:'image',name:'首帧',file:'/studio/media/objects/snapshot',image_index:1}]}];
  vi.mocked(readApi).mockImplementation(async path=>path.endsWith('/chat')?{chat_id:'owner'}:path.includes('/turns')?{'42':{text:'为什么动作僵硬？',attachments:[],studio_refs:refs}}:{revision:4,state:{assets:[{id:'image'}]}});
  rpc.mockResolvedValue({status:'streaming',studio_refs:refs});
  const controller=new ChatController();controller.connection='open';controller.workspace={id:'workspace',target:'shot',references:['shot']};
  controller.state={...controller.state,sessionId:'live',storedId:'owner',info:{tools:{canvas:['miniclaw_canvas_view']}}};
  expect(await controller.send('为什么动作僵硬？')).toBe(true);
  expect(writeApi).not.toHaveBeenCalled();expect(controller.state.items[0].studio_refs).toEqual(refs);
  expect(rpc).toHaveBeenCalledWith('miniclaw.turn.submit',expect.objectContaining({studio_context:{workspace:'workspace',target:'shot',references:['shot'],revision:4}}));
  rpc.mockResolvedValue({session_id:'live',stored_session_id:'owner',messages:[{row_id:42,role:'user',text:'model context'}],info:{}});
  await controller.open('owner',true);expect(controller.state.items[0].studio_refs).toEqual(refs);
});

test('changing the reference list during preparation aborts before submitting a mismatched turn',async()=>{
  rpc.mockClear();let finish!:(value:unknown)=>void;
  vi.mocked(readApi).mockResolvedValueOnce({chat_id:'owner'}).mockImplementationOnce(()=>new Promise(resolve=>finish=resolve) as ReturnType<typeof readApi>);
  const controller=new ChatController();controller.connection='open';controller.workspace={id:'workspace',references:['first']};controller.state={...controller.state,sessionId:'live',storedId:'owner'};
  const pending=controller.send('比较一下');await Promise.resolve();await Promise.resolve();
  controller.workspace.references!.push('second');finish({revision:3});
  expect(await pending).toBe(false);expect(rpc).not.toHaveBeenCalled();expect(controller.state.error).toContain('引用已变化');
});
