import { afterEach, expect, test, vi } from 'vitest';
import { ChatController } from './chat-controller';

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

test('project turns submit only the reference and bind the reply to the server snapshot', async () => {
  const controller=new ChatController();controller.connection='open';
  controller.state={...controller.state,sessionId:'live',storedId:'owner'};
  const source={project_id:'project',node:'script' as const,revision:7,basis:'server-hash'};
  const request=vi.spyOn(controller.client,'request').mockResolvedValue({creator_context:source});
  expect(await controller.send('按最新风格改稿',undefined,[],undefined,{project_id:'project',node:'script'})).toBe(true);
  expect(request).toHaveBeenCalledWith('miniclaw.turn.submit',expect.objectContaining({creator_context:{project_id:'project',node:'script'}}));
  expect(controller.state.items[0].creator_context).toEqual(source);
});

test('replayed replies restore their source version from the persisted turn metadata', async () => {
  vi.stubGlobal('window',{__HERMES_SESSION_TOKEN__:'test'});
  vi.stubGlobal('localStorage',{setItem:vi.fn()});
  const source={project_id:'project',node:'script',revision:2,basis:'old-basis'};
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({'33':{text:'改稿',attachments:[],creator_context:source}})}));
  const controller=new ChatController();
  const messages=[{role:'user',text:'model-expanded-prompt',row_id:33},{role:'assistant',text:'候选稿',row_id:34}];
  const request=vi.spyOn(controller.client,'request').mockImplementation(async method=>method==='session.resume'?{session_id:'live',stored_session_id:'owner',info:{},messages}:method==='session.history'?{messages}:{sessions:[]});
  await controller.open('owner');
  expect(controller.state.items[1].creator_context).toEqual(source);
  expect(controller.state.items[0].text).toBe('改稿');
  expect(request.mock.calls.map(c=>c[0])).toEqual(['session.resume']);
});

for (const hasTool of [false, true]) test(hasTool ? 'replay still restores durable tool failure bodies' : 'an empty live session resumes without querying a missing database record', async () => {
  vi.stubGlobal('window', { __HERMES_SESSION_TOKEN__: 'test' });
  vi.stubGlobal('localStorage', { setItem: vi.fn() });
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ messages: [{ role: 'tool', tool_call_id: 'call', content: '{"error":"missing file"}' }] }) });
  vi.stubGlobal('fetch', fetchMock);
  const controller = new ChatController();
  const messages = hasTool ? [{ role: 'tool', name: 'read', tool_call_id: 'call' }] : [];
  vi.spyOn(controller.client, 'request').mockImplementation(async method => {
    if (method === 'session.resume') return { session_id: 'live', stored_session_id: 'new', info: {}, messages };
    if (method === 'session.history') return { messages };
    return { sessions: [] };
  });
  await controller.open('new');
  expect(controller.state.error).toBe('');
  expect(fetchMock).toHaveBeenCalledTimes(hasTool ? 1 : 0);
  if (hasTool) expect(controller.state.items[0]).toMatchObject({ kind: 'tool', status: 'error', result: '{"error":"missing file"}' });
  else expect(controller.state.items).toEqual([]);
});

test('reload resumes the durable selection even outside the recent list window', async () => {
  vi.stubGlobal('window', { __HERMES_SESSION_TOKEN__: 'test' });
  vi.stubGlobal('location', { href: 'http://localhost:9120/' });
  vi.stubGlobal('localStorage', { getItem: () => 'older-than-sidebar' });
  const controller = new ChatController();
  vi.spyOn(controller.client, 'connect').mockResolvedValue();
  vi.spyOn(controller.client, 'request').mockResolvedValue({ sessions: [] });
  const resume = vi.spyOn(controller, 'open').mockResolvedValue();
  const create = vi.spyOn(controller, 'newSession').mockResolvedValue();
  await controller.connect();
  expect(resume).toHaveBeenCalledWith('older-than-sidebar', true);
  expect(create).not.toHaveBeenCalled();
});

for(const linked of [undefined,'project-owner'])test(linked?'a project resumes its own conversation':'a new project never inherits the last unrelated global conversation',async()=>{
  vi.stubGlobal('window',{__HERMES_SESSION_TOKEN__:'test'});
  vi.stubGlobal('location',{href:'http://localhost:9120/'});
  vi.stubGlobal('localStorage',{getItem:()=> 'unrelated-tea-chat'});
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({chat_id:linked})}));
  const controller=new ChatController();controller.workspace={id:'project-fixture'};
  vi.spyOn(controller.client,'connect').mockResolvedValue();
  vi.spyOn(controller.client,'request').mockResolvedValue({sessions:[]});
  const open=vi.spyOn(controller,'open').mockResolvedValue();
  const create=vi.spyOn(controller,'newSession').mockResolvedValue();
  await controller.connect();
  expect(open).not.toHaveBeenCalledWith('unrelated-tea-chat',true);
  if(linked)expect(open).toHaveBeenCalledWith(linked,true);
  else expect(create).toHaveBeenCalledTimes(1);
});

test('project sends fetch the current revision and freeze the selected target',async()=>{
  vi.stubGlobal('window',{__HERMES_SESSION_TOKEN__:'test'});
  vi.stubGlobal('fetch',vi.fn().mockImplementation(async url=>({ok:true,json:async()=>String(url).endsWith('/chat')?{chat_id:'owner'}:{revision:9}})));
  const controller=new ChatController();controller.workspace={id:'workspace-fixture',target:'shot-two'};
  controller.connection='open';controller.state={...controller.state,sessionId:'live',storedId:'owner'};
  const request=vi.spyOn(controller.client,'request').mockResolvedValue({});
  expect(await controller.send('核对当前采用结果')).toBe(true);
  expect(request).toHaveBeenCalledWith('miniclaw.turn.submit',expect.objectContaining({studio_context:{workspace:'workspace-fixture',target:'shot-two',revision:9}}));
});

test('refreshing an explicitly selected history resumes it without rebinding or replacing the project chat',async()=>{
  vi.stubGlobal('window',{__HERMES_SESSION_TOKEN__:'test'});
  vi.stubGlobal('location',{href:'http://localhost:9120/?workspace=project-fixture&session=older-history'});
  vi.stubGlobal('localStorage',{getItem:()=> 'unrelated-last-chat'});
  const fetchMock=vi.fn().mockResolvedValue({ok:true,json:async()=>({chat_id:'project-owner'})});vi.stubGlobal('fetch',fetchMock);
  const controller=new ChatController();controller.workspace={id:'project-fixture'};controller.resumeId='older-history';
  vi.spyOn(controller.client,'connect').mockResolvedValue();vi.spyOn(controller.client,'request').mockResolvedValue({sessions:[]});
  const open=vi.spyOn(controller,'open').mockResolvedValue();
  await controller.connect();
  expect(open.mock.calls).toEqual([['older-history',true]]);
  expect(fetchMock.mock.calls.some(call=>call[1]?.method==='POST')).toBe(false);
});

test('a multi-reference shot can be discussed without sending an undefined image context',async()=>{
  vi.stubGlobal('window',{__HERMES_SESSION_TOKEN__:'test'});
  vi.stubGlobal('fetch',vi.fn().mockImplementation(async url=>({ok:true,json:async()=>String(url).endsWith('/chat')?{chat_id:'owner'}:String(url).endsWith('/editing-target')?{selection_required:true,assets:[{id:'source'},{id:'macro'}]}:{revision:2}})));
  const controller=new ChatController();controller.workspace={id:'workspace-fixture',target:'shot-two'};
  controller.connection='open';controller.state={...controller.state,sessionId:'live',storedId:'owner',info:{tools:{canvas:['miniclaw_canvas_view']}}};
  const request=vi.spyOn(controller.client,'request').mockResolvedValue({});
  expect(await controller.send('讨论镜头节奏')).toBe(true);
  const submitted=request.mock.calls.find(call=>call[0]==='miniclaw.turn.submit')![1];
  expect(submitted).not.toHaveProperty('canvas_context');
  expect(submitted).toHaveProperty('studio_context.target','shot-two');
});

test('free project Chat keeps normal tools and binds image proposals without executing them',async()=>{
  vi.stubGlobal('window',{__HERMES_SESSION_TOKEN__:'test'});
  const fetchMock=vi.fn().mockImplementation(async url=>({ok:true,json:async()=>String(url).endsWith('/chat')?{chat_id:'owner'}:String(url).endsWith('/editing-target')?{project:'pixels',revision:3,layer:'bottle'}:{revision:9}}));
  vi.stubGlobal('fetch',fetchMock);
  const controller=new ChatController();controller.workspace={id:'workspace-fixture',target:'shot-two'};
  controller.connection='open';controller.state={...controller.state,sessionId:'live',storedId:'owner',info:{tools:{canvas:['miniclaw_canvas_view'],files:['miniclaw_read_file']}}};
  const request=vi.spyOn(controller.client,'request').mockResolvedValue({});
  expect(await controller.send('继续修改这张图，先给方案')).toBe(true);
  expect(request).toHaveBeenCalledWith('miniclaw.turn.submit',expect.objectContaining({canvas_context:{project_id:'pixels',revision:3,layer_id:'bottle',mode:'context'}}));
  expect(controller.state.info.tools?.files).toEqual(['miniclaw_read_file']);
});

test('an orphan draft is copied before the replacement session is rendered, without transferring attachment ownership', async () => {
  const values = new Map<string, string>();
  vi.stubGlobal('localStorage', { getItem: (key: string) => values.get(key), setItem: (key: string, value: string) => values.set(key, value) });
  const controller = new ChatController();
  vi.spyOn(controller.client, 'request').mockResolvedValue({ session_id: 'live', stored_session_id: 'replacement', info: {}, messages: [] });
  let draftAtRender = '';
  controller.subscribe(() => { if (controller.state.storedId === 'replacement') draftAtRender = values.get('miniclaw.draft.replacement') ?? ''; });
  await controller.newSession(JSON.stringify({ text: 'unfinished', skill: 'lesson', attachments: [{ id: 'belongs-to-old' }] }));
  expect(JSON.parse(draftAtRender)).toEqual({ text: 'unfinished', skill: 'lesson', attachments: [] });
});
