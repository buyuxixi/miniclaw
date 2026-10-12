// @vitest-environment jsdom
import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {afterEach,beforeEach,expect,test,vi} from 'vitest';
import {readApi,writeApi} from './management-api';
const fixture=vi.hoisted(()=>({chat:{items:[] as any[],info:{tools:{}},connection:'open',sessionId:'live',storedId:'owner',busy:false,running:false,error:''}}));
vi.mock('./use-chat',()=>({useChat:()=>fixture.chat}));
vi.mock('./management-api',()=>({readApi:vi.fn(),writeApi:vi.fn()}));
vi.mock('./Message',()=>({Message:({item}:any)=><div>{item.text}</div>}));
history.replaceState(null,'','/?director=workspace-one&target=shot-one&label=泥膜镜头&intent=optimize');
const {StudioDirector}=await import('./StudioDirector');
(globalThis as any).IS_REACT_ACT_ENVIRONMENT=true;
Element.prototype.scrollIntoView=vi.fn();
let host:HTMLDivElement,root:ReturnType<typeof createRoot>;
const shot={id:'shot-one',name:'泥膜镜头',prompt:'原始提示词：泥膜静止',mode:'first',first:'asset-one',refs:[]};
let current={revision:4,state:{shots:[shot,{...shot,id:'shot-two',name:'第二镜头'}],assets:[{id:'asset-one',name:'产品首帧',file:'/image.png'}]}};
let controller:any;
beforeEach(()=>{vi.clearAllMocks();localStorage.clear();fixture.chat={...fixture.chat,items:[],busy:false,running:false,error:''};current={...current,state:{...current.state,assets:[{id:'asset-one',name:'产品首帧',file:'/image.png'}],shots:[{...shot},{...shot,id:'shot-two',name:'第二镜头'}]}};vi.mocked(readApi).mockImplementation(async path=>path.includes('session-capabilities')?{ready:true,images:true} as any:current as any);vi.mocked(writeApi).mockResolvedValue({});controller={workspace:undefined,state:fixture.chat,send:vi.fn().mockResolvedValue(true)};host=document.createElement('div');document.body.append(host);root=createRoot(host);vi.spyOn(window,'postMessage').mockImplementation(()=>{});});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();});
async function render(){await act(async()=>{root.render(<StudioDirector controller={controller}/>);});}
async function receive(data:object){await act(async()=>{window.dispatchEvent(new MessageEvent('message',{data:{type:'miniclaw.director.target',workspace:'workspace-one',...data},source:window,origin:location.origin}));});}
test('shot context shows source image and skips image-editing side effects',async()=>{
  await render();expect(host.querySelector('.director-context img')).not.toBeNull();expect(host.querySelector('.director-context')?.textContent).not.toContain('产品首帧');expect(host.textContent).toContain('原始提示词');expect(controller.workspace.target).toBe('shot-one');expect(writeApi).not.toHaveBeenCalled();
  await act(async()=>(host.querySelector('.director-context-toggle') as HTMLButtonElement).click());expect(host.querySelector('.director-context-details')?.textContent).toContain('产品首帧');
  await receive({target:'shot-two',label:'第二镜头',intent:'optimize',request:7,node:'video-result',result:'result'});expect(controller.workspace.target).toBe('shot-two');expect(host.querySelector('.director-context')?.textContent).toContain('视频结果');expect(window.postMessage).toHaveBeenCalledWith(expect.objectContaining({request:7,target:'shot-two',pending:false}),location.origin);
});

test('image prompt optimization uses the bounded text skill and never creates an editing target',async()=>{
  current.state.assets[0]={id:'asset-one',name:'洗面奶',file:'/image.png',imagePrompt:'倾斜30°，背景略暗'} as any;
  await render();await receive({target:'asset-one',label:'洗面奶',intent:'optimize-edit',request:7});
  expect(vi.mocked(writeApi).mock.calls.some(([path])=>path.endsWith('/editing-target'))).toBe(false);
  expect(host.querySelector('.director-context img')?.getAttribute('src')).toBe('/image.png');
  await act(async()=>host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(controller.send).toHaveBeenCalledExactlyOnceWith('优化当前提示词，检查相互冲突的要求，清楚描述需要变化的部分，保留产品包装与标识。','product-prompt-optimize',[],undefined,undefined,{task:'image-edit'});
  expect(writeApi).not.toHaveBeenCalled();
  const prompt='只调整产品倾斜与背景亮度，保留包装文字';
  fixture.chat.items=[{kind:'assistant',id:'row-2',text:'保留包装并限定调暗范围。\n```product-prompt\n'+JSON.stringify({task:'image-edit',prompt})+'\n```'}];await render();
  expect(host.querySelector('.prompt-compare-body')?.textContent).toBe(prompt);
  vi.mocked(window.postMessage).mockImplementation((data:any)=>{if(data.type==='miniclaw.director.adopt-image-prompt')queueMicrotask(()=>window.dispatchEvent(new MessageEvent('message',{source:window,origin:location.origin,data:{type:'miniclaw.director.prompt-result',workspace:data.workspace,request:data.request,ok:true}})));});
  await act(async()=>(host.querySelector('.director-adopt') as HTMLButtonElement).click());
  expect(window.postMessage).toHaveBeenCalledWith(expect.objectContaining({type:'miniclaw.director.adopt-image-prompt',target:'asset-one',before:'倾斜30°，背景略暗',prompt,file:'/image.png'}),location.origin);
  expect(window.postMessage).toHaveBeenCalledWith(expect.objectContaining({type:'miniclaw.director.return'}),location.origin);
});
test('a draft keeps its original target until the user explicitly moves it',async()=>{
  localStorage.setItem('studio-director-scoped-draft:workspace-one',JSON.stringify({target:'shot-one',text:'增加泥膜流动'}));await render();await receive({target:'shot-two',label:'第二镜头',intent:'optimize',request:8});expect(controller.workspace.target).toBe('shot-one');expect((host.querySelector('textarea') as HTMLTextAreaElement).value).toBe('增加泥膜流动');expect(host.textContent).toContain('草稿仍针对');expect(window.postMessage).toHaveBeenCalledWith(expect.objectContaining({request:8,target:'shot-one',pending:true}),location.origin);
  const button=[...host.querySelectorAll('button')].find(b=>b.textContent?.includes('将草稿改为'))!;await act(async()=>button.click());expect(controller.workspace.target).toBe('shot-two');expect((host.querySelector('textarea') as HTMLTextAreaElement).value).toBe('增加泥膜流动');
});
test('optimization previews only new replies for this target and rejects later manual prompt changes',async()=>{
  const text='```studio-plan\n'+JSON.stringify({shots:[{name:'泥膜镜头',duration:5,prompt:'产品固定，泥膜持续流动'}]})+'\n```';fixture.chat.items=[{kind:'assistant',id:'row-1',text}];await render();expect(host.querySelector('.prompt-comparison')).toBeNull();
  await act(async()=>host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));expect(controller.send).toHaveBeenCalledWith(expect.not.stringContaining('移除旧提示词'),'product-prompt-optimize',[],undefined,undefined,{task:'video'});
  expect(writeApi).not.toHaveBeenCalled();
  fixture.chat.items=[...fixture.chat.items,{kind:'assistant',id:'row-2',text}];await render();expect(host.querySelector('.prompt-comparison')?.textContent).toContain('产品固定，泥膜持续流动');expect(host.textContent).not.toContain('```studio-plan');expect(host.querySelector('#director-goal')).toBeNull();current.state.shots[0].prompt='刚手动修改过';await act(async()=>(host.querySelector('.director-adopt') as HTMLButtonElement).click());expect(host.textContent).toContain('提示词已修改');expect(vi.mocked(writeApi).mock.calls.some(([path])=>path.endsWith('/commands'))).toBe(false);expect((host.querySelector('.director-adopt') as HTMLButtonElement).disabled).toBe(true);
  await act(async()=>(host.querySelector('.director-error button') as HTMLButtonElement).click());expect((host.querySelector('.director-adopt') as HTMLButtonElement).disabled).toBe(true);expect(host.querySelector('.prompt-compare-body')?.textContent).toBe('产品固定，泥膜持续流动');
});

test('optimization hides unrelated history and keeps ordinary discussion available',async()=>{
  fixture.chat.items=[{kind:'assistant',id:'row-1',text:'很长的历史讨论，不是本次建议'}];await render();expect(host.textContent).not.toContain('很长的历史讨论');
  expect(host.querySelector('.director-modes')).toBeNull();await receive({target:'shot-one',label:'泥膜镜头',intent:'discuss',request:9});expect(host.textContent).toContain('很长的历史讨论');
});

test('one project chat sends ordinary shot questions without a rewriting skill or optimization context',async()=>{
  fixture.chat.items=[{kind:'assistant',id:'row-1',text:'共享的讨论记录'}];
  await render();await receive({target:'shot-one',label:'泥膜镜头',intent:'discuss',request:9});
  expect(host.querySelector('.director-modes')).toBeNull();expect(host.querySelector('#director-target')).toBeNull();
  const input=host.querySelector('textarea')!;
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(input,'这里为什么不自然？');input.dispatchEvent(new Event('input',{bubbles:true}));});
  await act(async()=>host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(controller.send).toHaveBeenCalledExactlyOnceWith('这里为什么不自然？',undefined,[],undefined);
  expect(controller.workspace).toEqual({id:'workspace-one',target:'shot-one',references:['shot-one']});
  expect(host.textContent).toContain('共享的讨论记录');
  expect(host.querySelector('.director-composer-references')?.textContent).toContain('泥膜镜头');
  expect(controller.state.sessionId).toBe('live');
});

test('switching between chat and inline optimization preserves separate drafts and rejects switching during a turn',async()=>{
  localStorage.setItem('studio-director-scoped-draft:workspace-one:shot-one:chat',JSON.stringify({target:'shot-one',text:'讨论草稿'}));
  await render();const input=host.querySelector('textarea')!;
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(input,'优化草稿');input.dispatchEvent(new Event('input',{bubbles:true}));});
  await receive({target:'shot-one',label:'泥膜镜头',intent:'discuss',request:10});expect(host.querySelector('textarea')!.value).toBe('讨论草稿');
  await receive({target:'shot-one',label:'泥膜镜头',intent:'optimize',request:11});expect(host.querySelector('textarea')!.value).toBe('优化草稿');
  fixture.chat.running=true;await render();await receive({target:'shot-one',label:'泥膜镜头',intent:'discuss',request:12});
  expect(host.querySelector('.director-optimization')).not.toBeNull();expect(host.textContent).toContain('当前任务完成后');
  expect(window.postMessage).toHaveBeenCalledWith(expect.objectContaining({request:12,pending:true,intent:'optimize'}),location.origin);
});

test('a view change cannot steal a request that is still awaiting acceptance',async()=>{
  let finish!:(ok:boolean)=>void;controller.send.mockImplementation(()=>new Promise(resolve=>finish=resolve));await render();
  await act(async()=>{host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));});
  await receive({target:'shot-one',label:'泥膜镜头',intent:'discuss',request:14});
  expect(window.postMessage).toHaveBeenCalledWith(expect.objectContaining({pending:true,intent:'optimize',request:14}),location.origin);
  expect(host.querySelector('.director-optimization')).not.toBeNull();await act(async()=>finish(true));
});

test('canvas clicks append deduplicated reading context without moving the draft or session',async()=>{
  await render();await receive({target:'shot-one',label:'泥膜镜头',intent:'discuss',request:20});
  const input=host.querySelector('textarea')!;
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(input,'参考这张的颜色，不改原镜头');input.dispatchEvent(new Event('input',{bubbles:true}));});
  for(const id of ['asset-one','shot-two','asset-one'])await receive({type:'miniclaw.director.reference',target:id});
  expect(input.value).toBe('参考这张的颜色，不改原镜头');expect(controller.workspace).toEqual({id:'workspace-one',target:'shot-one',references:['shot-one','asset-one','shot-two']});
  expect(host.querySelectorAll('.studio-reference')).toHaveLength(3);expect(host.querySelector('#director-target')).toBeNull();expect(host.querySelector('.director-context')).toBeNull();expect(host.textContent).not.toContain('草稿仍针对');
  expect(writeApi).not.toHaveBeenCalled();expect(controller.state.sessionId).toBe('live');
  await act(async()=>host.querySelector<HTMLButtonElement>('[aria-label="移除引用：产品首帧"]')!.click());
  expect(controller.workspace.references).toEqual(['shot-one','shot-two']);expect(input.value).toBe('参考这张的颜色，不改原镜头');
  await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='移除全部')!.click());
  expect(controller.workspace).toEqual({id:'workspace-one',target:'',references:[]});expect(input.value).toBe('参考这张的颜色，不改原镜头');
});

test('failed context sends retain the draft and citations; accepted sends retain removable context for followups',async()=>{
  await render();await receive({target:'shot-one',label:'泥膜镜头',intent:'discuss',request:21});
  const input=host.querySelector('textarea')!;
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(input,'比较一下');input.dispatchEvent(new Event('input',{bubbles:true}));});
  controller.send.mockResolvedValueOnce(false);
  await act(async()=>host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(input.value).toBe('比较一下');expect(controller.workspace.references).toEqual(['shot-one']);
  await act(async()=>host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(input.value).toBe('');expect(controller.workspace.references).toEqual(['shot-one']);
});

test('project discussion drafts do not push inline optimization back into the assistant',async()=>{
  await render();await receive({target:'shot-one',label:'泥膜镜头',intent:'discuss',request:22});
  const input=host.querySelector('textarea')!;
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(input,'还没写完的讨论');input.dispatchEvent(new Event('input',{bubbles:true}));});
  await receive({target:'shot-two',label:'第二镜头',intent:'optimize',request:23});
  expect(host.querySelector('.director-optimization')).not.toBeNull();expect(controller.workspace.target).toBe('shot-two');
  expect(window.postMessage).toHaveBeenCalledWith(expect.objectContaining({request:23,intent:'optimize',pending:false}),location.origin);
  await receive({target:'shot-two',label:'第二镜头',intent:'discuss',request:24});
  expect(host.querySelector('textarea')!.value).toBe('还没写完的讨论');expect(controller.workspace.references).toEqual(['shot-one','shot-two']);
});

test('ordinary image questions remain available when proposal tools are not loaded',async()=>{
  const project={id:'image-project',revision:4,document:{layers:[{id:'layer-one',kind:'image',asset_id:'current'}]}};
  vi.mocked(readApi).mockImplementation(async path=>path.includes('session-capabilities')?{ready:true,images:true} as any:path==='/api/miniclaw/canvas/projects/image-project'?project as any:path.includes('/canvas/')?[] as any:current as any);
  vi.mocked(writeApi).mockImplementation(async path=>path.endsWith('/editing-target')?{project:'image-project',layer:'layer-one',object:'asset-one',source:'/image.png'} as any:{});
  await render();await receive({target:'asset-one',label:'产品图片',intent:'discuss',request:15});
  const input=host.querySelector('textarea')!;
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(input,'这张图的构图好吗？');input.dispatchEvent(new Event('input',{bubbles:true}));});
  await act(async()=>host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(controller.send).toHaveBeenCalledExactlyOnceWith('这张图的构图好吗？',undefined,[],undefined);
  expect(host.textContent).not.toContain('未启用修图工具');
});

async function newSuggestion(){
  await render();await act(async()=>host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  fixture.chat.items=[{kind:'assistant',id:'row-3',text:'泥膜由静止改为流动。\n```studio-plan\n'+JSON.stringify({shots:[{name:'泥膜镜头',duration:5,prompt:'产品固定，泥膜持续流动'}]})+'\n```'}];await render();
}

test('a completed optimization restores after reopening and remains pinned to its saved reply',async()=>{
  await newSuggestion();expect(controller.send).toHaveBeenCalledTimes(1);
  await act(async()=>root.unmount());root=createRoot(host);
  fixture.chat.items.push({kind:'assistant',id:'row-99',text:'```studio-plan\n'+JSON.stringify({shots:[{name:'别的镜头',duration:5,prompt:'无关建议'}]})+'\n```'});
  await render();expect(host.querySelector('.prompt-compare-body')?.textContent).toBe('产品固定，泥膜持续流动');expect(controller.send).toHaveBeenCalledTimes(1);
});

test('adoption returns to generation only after the parent confirms the write',async()=>{
  await newSuggestion();vi.mocked(window.postMessage).mockImplementation((data:any)=>{if(data.type==='miniclaw.director.adopt-prompt')queueMicrotask(()=>window.dispatchEvent(new MessageEvent('message',{source:window,origin:location.origin,data:{type:'miniclaw.director.prompt-result',workspace:data.workspace,request:data.request,ok:true}})));});
  await act(async()=>(host.querySelector('.director-adopt') as HTMLButtonElement).click());expect(window.postMessage).toHaveBeenCalledWith(expect.objectContaining({type:'miniclaw.director.return',workspace:'workspace-one'}),location.origin);
});

test('failed adoption leaves the suggestion and comparison available',async()=>{
  await newSuggestion();vi.mocked(window.postMessage).mockImplementation((data:any)=>{if(data.type==='miniclaw.director.adopt-prompt')queueMicrotask(()=>window.dispatchEvent(new MessageEvent('message',{source:window,origin:location.origin,data:{type:'miniclaw.director.prompt-result',workspace:data.workspace,request:data.request,ok:false,error:'保存失败'}})));});
  await act(async()=>(host.querySelector('.director-adopt') as HTMLButtonElement).click());expect(host.textContent).toContain('保存失败');expect(host.querySelector('.director-adopt')?.textContent).toBe('重试采用建议');expect(host.querySelector('.director-error button')).toBeNull();expect(host.querySelector('.prompt-comparison')?.textContent).toContain('产品固定，泥膜持续流动');expect(window.postMessage).not.toHaveBeenCalledWith(expect.objectContaining({type:'miniclaw.director.return'}),location.origin);
});

test('comparison shows the change and switches text without hiding the adoption action',async()=>{
  await newSuggestion();expect(host.querySelector('.prompt-change-summary')?.textContent).toBe('泥膜由静止改为流动。');
  const original=[...host.querySelectorAll<HTMLButtonElement>('.prompt-compare-tabs button')].find(b=>b.textContent==='原提示词')!;
  await act(async()=>original.click());expect(host.querySelector('.prompt-compare-body')?.textContent).toBe(shot.prompt);expect(original.getAttribute('aria-pressed')).toBe('true');expect(host.querySelector('.director-adopt')).not.toBeNull();
});

test('further adjustment retains the previous goal and refines the candidate',async()=>{
  await newSuggestion();const previousRequest=controller.send.mock.calls[0][0];const button=[...host.querySelectorAll('button')].find(b=>b.textContent==='继续调整')!;await act(async()=>button.click());expect(host.textContent).toContain('进一步调整');expect(host.querySelector('.director-previous-goal')?.textContent).toContain('当前目标');
  const setValue=Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!;
  await act(async()=>{const input=host.querySelector('#director-goal')!;setValue.call(input,'流动幅度更大');input.dispatchEvent(new Event('input',{bubbles:true}));});
  await act(async()=>host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(controller.send.mock.calls[1][0]).toBe('流动幅度更大');expect(controller.send.mock.calls[1][5]).toEqual({task:'video',prompt:'产品固定，泥膜持续流动',previous_goal:previousRequest});expect(previousRequest).not.toContain(shot.prompt);
});

test('failed sending preserves the entered goal and leaves adoption unavailable',async()=>{
  localStorage.setItem('studio-director-scoped-draft:workspace-one',JSON.stringify({target:'shot-one',text:'让泥膜持续流动'}));controller.send.mockResolvedValue(false);await render();await act(async()=>host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect((host.querySelector('#director-goal') as HTMLTextAreaElement).value).toBe('让泥膜持续流动');expect(host.querySelector('.director-adopt')).toBeNull();expect(host.textContent).toContain('修改要求已保留');
});

test('failed further adjustment preserves the previous candidate and new draft',async()=>{
  await newSuggestion();await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='继续调整')!.click());
  const setValue=Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!;
  await act(async()=>{const input=host.querySelector('#director-goal')!;setValue.call(input,'流动更明显');input.dispatchEvent(new Event('input',{bubbles:true}));});controller.send.mockResolvedValue(false);
  await act(async()=>host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(host.querySelector('.prompt-compare-body')?.textContent).toBe('产品固定，泥膜持续流动');expect((host.querySelector('#director-goal') as HTMLTextAreaElement).value).toBe('流动更明显');expect(host.textContent).toContain('返回建议');
});


test('historical image results remain comparable against the latest work without generating again',async()=>{
  const project={id:'image-project',revision:14,document:{layers:[{id:'layer-one',kind:'image',asset_id:'current-local-edit'}]}};
  const jobs=[{id:'retained-job',revision:2,layer_id:'layer-one',state:'succeeded',output:{id:'retained-output'}}];
  vi.mocked(readApi).mockImplementation(async(path)=>{
    if(path.includes('session-capabilities'))return {ready:true,images:true} as any;
    if(path.endsWith('/jobs'))return jobs as any;
    if(path.endsWith('/versions'))return {items:[],total:0} as any;
    if(path==='/api/miniclaw/canvas/projects/image-project')return project as any;
    if(path.includes('/canvas/'))return [] as any;
    return current as any;
  });
  const candidate={project:'image-project',revision:14,output:'/after.png',output_id:'snapshot',before_output:'/before.png',comparison:{id:'snapshot',job:'retained-job'}};
  vi.mocked(writeApi).mockImplementation(async(path)=>path.endsWith('/editing-target')?{project:'image-project',layer:'layer-one',object:'asset-one',source:'/image.png'} as any:candidate as any);
  await render();await receive({target:'asset-one',label:'产品图片'});
  expect(host.querySelector('.director-job-history')).toBeNull();
  await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='修改记录')!.click());
  await act(async()=>host.querySelector<HTMLDetailsElement>('.director-job-history')!.querySelector('summary')!.click());
  const compare=[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent==='与当前工作图比较')!;
  expect(compare).toBeDefined();expect(compare.disabled).toBe(false);
  await act(async()=>compare.click());
  expect(writeApi).toHaveBeenCalledWith('/api/precision/full/image-project/compare-job','POST',{revision:14,job:'retained-job'});
  expect(window.postMessage).toHaveBeenCalledWith(expect.objectContaining({type:'miniclaw.director.compare',candidate}),location.origin);
  expect(controller.send).not.toHaveBeenCalled();
  vi.mocked(writeApi).mockImplementation(async(path)=>{
    if(path.endsWith('/editing-target'))return {project:'image-project',layer:'layer-one',object:'asset-one',source:'/image.png'} as any;
    throw Error('Method Not Allowed');
  });
  await act(async()=>compare.click());
  expect(window.postMessage).toHaveBeenCalledWith(expect.objectContaining({type:'miniclaw.director.compare-retained',candidate:expect.objectContaining({job:expect.objectContaining({id:'retained-job'})})}),location.origin);
  expect(controller.send).not.toHaveBeenCalled();
});
