// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { Composer } from './Composer';
import { SettingsDialog } from './SettingsDialog';
import { SkillEditor } from './SkillEditor';
import { MemoryEditor } from './MemoryEditor';
import { App } from './App';
import { attachmentBlob, uploadFile, cancelUpload, documentStatus, retryDocument, type Attachment } from './attachments';
import { readApi, writeApi } from './management-api';
import type { ChatController } from './chat-controller';
import type { ChatState } from './types';
import { exportBlob } from './canvas-api';

vi.mock('./management-api', () => ({ readApi: vi.fn(), writeApi: vi.fn() }));
vi.mock('./attachments', () => ({ uploadFile: vi.fn(), attachmentBlob: vi.fn(), cancelUpload:vi.fn().mockResolvedValue(undefined), documentStatus:vi.fn(),retryDocument:vi.fn() }));
vi.mock('./canvas-api', async () => ({...(await vi.importActual('./canvas-api')),exportBlob:vi.fn()}));
let host: HTMLDivElement;
let root: Root;
const BrowserURL=URL;
const fakeAttachment: Attachment = { id: 'fixture-image', name: 'fixture.png', kind: 'image', mime: 'image/png', bytes: 10 };
const chat = (owner = 'owner-a'): ChatState => ({ sessions: [], sessionId: 'live-' + owner, storedId: owner, items: [], info: {}, running: false, busy: false, status: '', error: '' });
function controller() {
  return { connection: 'open', send: vi.fn().mockResolvedValue(true), stop: vi.fn(), client: { request: vi.fn().mockResolvedValue({}) } } as unknown as ChatController;
}
const input = () => host.querySelector<HTMLTextAreaElement>('textarea[aria-label="消息"]')!;
const button = (label: string) => [...host.querySelectorAll<HTMLButtonElement>('button')].find(el => el.getAttribute('aria-label') === label || el.textContent === label)!;
async function click(label: string) { await act(async () => button(label).click()); }
async function files(eventName: 'paste' | 'drop', supplied: File[]) {
  const event = new Event(eventName, { bubbles: true, cancelable: true });
  Object.defineProperty(event, eventName === 'paste' ? 'clipboardData' : 'dataTransfer', { value: { files: supplied, types: ['Files'] } });
  await act(async () => (eventName === 'paste' ? input() : host.querySelector('form')!).dispatchEvent(event));
}

beforeEach(() => {
  Object.defineProperty(Element.prototype,'scrollTo',{configurable:true,value:vi.fn()});
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:fixture'), revokeObjectURL: vi.fn() });
  vi.resetAllMocks();
  vi.mocked(attachmentBlob).mockResolvedValue(new Blob(['fixture']));
  vi.mocked(cancelUpload).mockResolvedValue(undefined);
  vi.mocked(exportBlob).mockResolvedValue(new Blob(['working'],{type:'image/png'}));
  vi.mocked(readApi).mockResolvedValue({ ready: true, images: true });
  vi.mocked(writeApi).mockResolvedValue({});
  localStorage.clear();
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value: function(this: HTMLDialogElement) { this.setAttribute('open', ''); } });
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value: function(this: HTMLDialogElement) { this.removeAttribute('open'); } });
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); });

test('conversation restoration protects input until its owner and draft are ready',async()=>{
  const c=controller();
  await act(async()=>root.render(<Composer controller={c} chat={{...chat(),busy:true}} onManage={()=>{}}/>));
  expect(input().disabled).toBe(true);
  await act(async()=>root.render(<Composer controller={c} chat={chat()} onManage={()=>{}}/>));
  expect(input().disabled).toBe(false);
  await act(async()=>root.render(<Composer controller={c} chat={{...chat(),running:true}} onManage={()=>{}}/>));
  expect(input().disabled).toBe(false);
});

test('pending questions keep the composer visible and preserve its draft when task control is not accepted',async()=>{
  localStorage.setItem('miniclaw.draft.owner-a',JSON.stringify({text:'先取消这轮任务',attachments:[]}));
  const pending={id:'pending',task_id:'task',version:1,status:'pending' as const,deadline:2000000000,questions:[{id:'color',question:'选择颜色',choices:['红色','蓝色'],multi_select:false}]};
  const c={...controller(),connect:vi.fn(),dispose:vi.fn(),subscribe:()=>()=>{},state:{...chat(),clarifications:[pending]},cancelClarification:vi.fn().mockResolvedValue(undefined)} as unknown as ChatController;
  vi.mocked(c.send).mockResolvedValue(false);
  await act(async()=>root.render(<App controller={c}/>));
  expect(input().closest('[hidden]')).toBeNull();
  expect(input().disabled).toBe(false);
  expect(input().value).toBe('先取消这轮任务');
  await click('发送');
  expect(c.send).toHaveBeenCalledWith('先取消这轮任务',undefined,[]);
  expect(input().value).toBe('先取消这轮任务');
  expect(JSON.parse(localStorage.getItem('miniclaw.draft.owner-a')!).text).toBe('先取消这轮任务');
  await click('修改需求');
  expect(c.cancelClarification).toHaveBeenCalledWith(pending,true);
  expect(input().value).toBe('先取消这轮任务');
});

test('pending text control bypasses cover preparation',async()=>{
  const pending={id:'pending',task_id:'task',version:1,status:'pending' as const,deadline:2000000000,questions:[{id:'color',question:'选择颜色',choices:['红色'],multi_select:false}]};
  const c=controller();const state={...chat(),clarifications:[pending]};
  vi.mocked(readApi).mockResolvedValue({ready:false,images:false});
  localStorage.setItem('miniclaw.draft.owner-a',JSON.stringify({text:'取消任务',skill:'canvas-editor',attachments:[]}));
  await act(async()=>root.render(<Composer controller={c} chat={state} creatorContext={{project_id:'product',node:'cover'}} onManage={()=>{}}/>));
  await click('发送');
  expect(c.send).toHaveBeenCalledWith('取消任务',undefined,[]);
  expect(exportBlob).not.toHaveBeenCalled();expect(uploadFile).not.toHaveBeenCalled();
});

test('pending attachment drafts remain intact until the user chooses how to change the task',async()=>{
  const c=controller();const state={...chat(),clarifications:[{id:'pending',task_id:'task',version:1,status:'pending' as const,deadline:2000000000,questions:[{id:'color',question:'选择颜色',choices:['红色'],multi_select:false}]}]};
  localStorage.setItem('miniclaw.draft.owner-a',JSON.stringify({text:'修改要求',attachments:[fakeAttachment]}));
  await act(async()=>root.render(<Composer controller={c} chat={state} onManage={()=>{}}/>));
  await click('发送');
  expect(c.send).not.toHaveBeenCalled();
  expect(host.textContent).toContain('附件草稿已保留');
  expect(input().value).toBe('修改要求');
  expect(JSON.parse(localStorage.getItem('miniclaw.draft.owner-a')!).attachments).toEqual([fakeAttachment]);
});

test('IME Enter and Shift+Enter cannot send; ordinary Enter sends the persisted draft', async () => {
  localStorage.setItem('miniclaw.draft.owner-a', JSON.stringify({ text: '你好', attachments: [] }));
  const c = controller();
  await act(async () => root.render(<Composer controller={c} chat={chat()} onManage={() => {}} />));
  for (const options of [{ isComposing: true }, { keyCode: 229 }, { shiftKey: true }]) {
    await act(async () => input().dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true, ...options })));
  }
  expect(c.send).not.toHaveBeenCalled();
  expect(input().value).toBe('你好');
  await act(async () => input().dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })));
  expect(c.send).toHaveBeenCalledWith('你好', undefined, []);
  expect(input().value).toBe('');
});

test('a chosen skill stays visible and is submitted on every turn until explicitly replaced or removed', async () => {
  vi.stubGlobal('requestAnimationFrame',(fn:()=>void)=>{fn();return 1;});
  vi.mocked(readApi).mockImplementation(async url=>url==='/api/miniclaw/skills' ?
    ['product-video-plan','product-prompt-optimize'].map(name=>({name,enabled:true,description:'',binding:{version:1,current:true,required_tools:[],content_hash:'fixture'}})) :
    {ready:true,images:true});
  const c=controller();
  vi.mocked(c.client.request).mockResolvedValue({skills:{'/product-video-plan':{},'/product-prompt-optimize':{}},categories:[]});
  localStorage.setItem('miniclaw.draft.owner-a',JSON.stringify({text:'策划第一镜',attachments:[fakeAttachment]}));
  const render=(text?:string,nonce=1)=>root.render(<Composer key="owner-a" controller={c} chat={chat()} onManage={()=>{}} suggestion={text?{text,nonce}:undefined}/>);
  const choose=async(title:string)=>{
    await act(async()=>[...host.querySelectorAll('article')].find(e=>e.querySelector('h3')?.textContent===title)!.querySelector('button')!.click());
  };
  await act(async()=>render());
  await click('选择技能'); await choose('产品短片策划');
  await click('发送');
  expect(c.send).toHaveBeenNthCalledWith(1,'策划第一镜','product-video-plan',[fakeAttachment]);
  expect(input().value).toBe('');
  expect(host.querySelector('.attachments')).toBeNull();
  expect(host.querySelector('.composer-skill')?.textContent).toContain('产品短片策划');
  expect(JSON.parse(localStorage.getItem('miniclaw.draft.owner-a')!).skill).toBe('product-video-plan');
  await act(async()=>render('继续调整第二镜',2));
  await click('发送');
  expect(c.send).toHaveBeenNthCalledWith(2,'继续调整第二镜','product-video-plan',[]);
  expect(button('当前技能：产品短片策划')).toBeDefined();
  await click('当前技能：产品短片策划'); await choose('产品宣传提示词优化');
  await act(async()=>render('只优化运动要求',3));
  await click('发送');
  expect(c.send).toHaveBeenNthCalledWith(3,'只优化运动要求','product-prompt-optimize',[]);
  await click('移除技能');
  await act(async()=>render('普通讨论',4));
  await click('发送');
  expect(c.send).toHaveBeenNthCalledWith(4,'普通讨论',undefined,[]);
  expect(host.querySelector('.composer-skill')).toBeNull();
  expect(JSON.parse(localStorage.getItem('miniclaw.draft.owner-a')!).skill).toBeUndefined();
});

test('retained skills restore only in their own conversation and survive a refused send', async () => {
  const c=controller();
  localStorage.setItem('miniclaw.draft.owner-a',JSON.stringify({text:'继续策划',skill:'product-video-plan',attachments:[]}));
  const render=(owner:string)=>root.render(<Composer key={owner} controller={c} chat={chat(owner)} onManage={()=>{}}/>);
  await act(async()=>render('owner-a'));
  await click('发送');
  await act(async()=>render('owner-b'));
  expect(host.querySelector('.composer-skill')).toBeNull();
  expect(JSON.parse(localStorage.getItem('miniclaw.draft.owner-b')!).skill).toBeUndefined();
  await act(async()=>render('owner-a'));
  expect(host.querySelector('.composer-skill')?.textContent).toContain('产品短片策划');
  vi.mocked(c.send).mockResolvedValueOnce(false);
  await act(async()=>root.render(<Composer key="owner-a" controller={c} chat={chat()} onManage={()=>{}} suggestion={{text:'未发送要求',nonce:1}}/>));
  await click('发送');
  expect(input().value).toBe('未发送要求');
  expect(JSON.parse(localStorage.getItem('miniclaw.draft.owner-a')!).skill).toBe('product-video-plan');
  await click('移除技能');
  await act(async()=>render('owner-b'));
  await act(async()=>render('owner-a'));
  expect(host.querySelector('.composer-skill')).toBeNull();
  expect(input().value).toBe('未发送要求');
});

test('project reply adoption extracts only the spoken main and preserves the source revision', async () => {
  vi.stubGlobal('requestAnimationFrame',(fn:()=>void)=>{fn();return 1;});
  Object.defineProperty(Element.prototype, 'scrollIntoView', {configurable:true,value:vi.fn()});
  const source={project_id:'project',node:'script' as const,revision:2,basis:'old-basis'};
  const c={...controller(),connect:vi.fn(),dispose:vi.fn(),state:{...chat(),items:[{id:'reply',kind:'assistant' as const,text:'```spoken-script\n真实主稿。\n```\n## 开头备选\n备选。',creator_context:source}]},subscribe:()=>()=>{}} as unknown as ChatController;
  const adopt=vi.fn();
  await act(async()=>root.render(<App controller={c} creatorContext={{id:'project',name:'商品',revision:8,owner:'owner-a',node:'script'}} onAdopt={adopt}/>));
  await click('采用为项目口播');
  expect(adopt).toHaveBeenCalledWith('真实主稿。','reply',source);
});

test('the script task displays and sends its effective default skill',async()=>{
  localStorage.setItem('miniclaw.draft.owner-a',JSON.stringify({text:'缩短一半',attachments:[]}));
  const c=controller();
  await act(async()=>root.render(<Composer controller={c} chat={chat()} creatorContext={{project_id:'product',node:'script'}} onManage={()=>{}}/>));
  expect(button('当前技能：口播优化')).toBeDefined();
  expect(host.textContent).toContain('任务默认');
  await act(async()=>input().dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true})));
  expect(c.send).toHaveBeenCalledWith('缩短一半','spoken-script',[],undefined,{project_id:'product',node:'script'});
});

test('project records list real discussions and jump across tasks without sending or losing the draft', async () => {
  Object.defineProperty(Element.prototype,'scrollIntoView',{configurable:true,value:vi.fn()});
  localStorage.setItem('miniclaw.draft.owner-a', JSON.stringify({ text: '未发送的修改要求', attachments: [] }));
  const turn = { project_id:'project',node:'cover' as const,revision:2,basis:'basis' };
  const c={...controller(),connect:vi.fn(),dispose:vi.fn(),state:{...chat(),items:[
    {id:'image-request',kind:'user' as const,text:'把图片右侧留白增加160像素',creator_context:turn},
    {id:'other-project',kind:'user' as const,text:'另一个项目的机密内容',creator_context:{...turn,project_id:'other'}},
    {id:'script-request',kind:'user' as const,text:'缩短最后一句口播',creator_context:{...turn,node:'script' as const}},
    {id:'script-answer',kind:'assistant' as const,text:'这句更简洁。',creator_context:{...turn,node:'script' as const}},
  ]},subscribe:()=>()=>{}} as unknown as ChatController;
  await act(async()=>root.render(<App controller={c} creatorContext={{id:'project',name:'商品',revision:8,owner:'owner-a',node:'script'}}/>));
  const panel=host.querySelector<HTMLElement>('.conversation')!;
  panel.scrollTop=73;
  await click('对话记录');
  const records=host.querySelector('.studio-records')!;
  expect(records.textContent).toContain('2 次讨论');
  expect(records.textContent).not.toContain('机密内容');
  expect(records.querySelector('button strong')?.textContent).toBe('缩短最后一句口播');
  await click('返回对话');
  expect(host.querySelector<HTMLElement>('.conversation')!.scrollTop).toBe(73);
  await click('对话记录');
  await act(async()=>[...host.querySelectorAll<HTMLButtonElement>('.studio-record-list button')].find(b=>b.textContent?.includes('增加160像素'))!.click());
  expect(host.querySelector('.studio-records')).toBeNull();
  expect(host.querySelector('[data-project-message="image-request"]')).not.toBeNull();
  expect(button('全部讨论').getAttribute('aria-pressed')).toBe('true');
  expect(input().value).toBe('未发送的修改要求');
  expect(c.send).not.toHaveBeenCalled();
  expect(Element.prototype.scrollTo).toHaveBeenCalledWith(expect.objectContaining({behavior:'smooth'}));
});

test('matching adopted text is marked in Chat while a different candidate still retains its adoption action', async () => {
  const source={project_id:'project',node:'script' as const,revision:2,basis:'basis'};
  vi.mocked(readApi).mockResolvedValue({id:'project',chat_id:'owner-a',script:'当前采用稿。',flow:{script:'adopted'},assets:{},outputs:[],jobs:[]});
  const c={...controller(),connect:vi.fn(),dispose:vi.fn(),state:{...chat(),items:[
    {id:'same',kind:'assistant' as const,text:'```spoken-script\n当前采用稿。\n```',creator_context:source},
    {id:'new',kind:'assistant' as const,text:'```spoken-script\n新的候选稿。\n```',creator_context:source},
  ]},subscribe:()=>()=>{}} as unknown as ChatController;
  const adopt=vi.fn();
  await act(async()=>root.render(<App controller={c} creatorContext={{id:'project',name:'商品',revision:8,owner:'owner-a',node:'script'}} onAdopt={adopt}/>));
  expect(host.querySelector('[data-project-message="same"]')?.textContent).toContain('与主稿一致');
  expect(host.querySelector('[data-project-message="same"]')?.textContent).not.toContain('采用为项目口播');
  await click('采用为项目口播');
  expect(adopt).toHaveBeenCalledWith('新的候选稿。','new',source);
  vi.mocked(readApi).mockResolvedValue({id:'project',chat_id:'foreign',script:'当前采用稿。',assets:{}});
  await act(async()=>root.render(<App controller={c} creatorContext={{id:'another',name:'另一商品',revision:8,owner:'owner-a',node:'script'}} onAdopt={adopt}/>));
  expect(host.textContent).not.toContain('与主稿一致');
});

test('brief adoption is offered only for a complete candidate from the associated project', async () => {
  vi.stubGlobal('requestAnimationFrame',(fn:()=>void)=>{fn();return 1;});
  Object.defineProperty(Element.prototype, 'scrollIntoView', {configurable:true,value:vi.fn()});
  const source={project_id:'project',node:'brief' as const,revision:2,basis:'basis'};
  const fields={facts:'乳白壶',selling_points:'外观简洁',audience:'喜好浅色的人（建议）',style:'自然',constraints:'不编造材质'};
  const c={...controller(),connect:vi.fn(),dispose:vi.fn(),state:{...chat(),items:[{id:'reply',kind:'assistant' as const,text:'```json\n'+JSON.stringify(fields)+'\n```',creator_context:source}]},subscribe:()=>()=>{}} as unknown as ChatController;
  const adopt=vi.fn();
  await act(async()=>root.render(<App controller={c} creatorContext={{id:'project',name:'商品',revision:8,owner:'owner-a',node:'brief'}} onAdoptBrief={adopt}/>));
  expect(host.textContent).not.toContain('采用为项目口播');
  expect(host.querySelector('.message pre')).toBeNull();
  await click('采用为创作依据');
  expect(adopt).toHaveBeenCalledWith(fields,'reply',source);
  await act(async()=>root.render(<App controller={c} creatorContext={{id:'another',name:'别的商品',revision:8,owner:'owner-a',node:'brief'}} onAdoptBrief={adopt}/>));
  expect(host.textContent).not.toContain('采用为创作依据');
});

test('a consumed project suggestion cannot replay into another conversation or reappear after sending', async () => {
  Object.defineProperty(Element.prototype,'scrollIntoView',{configurable:true,value:vi.fn()});
  const c=controller();let notify=()=>{};
  Object.assign(c,{state:chat(),connect:vi.fn(),dispose:vi.fn(),subscribe:(fn:()=>void)=>{notify=fn;return()=>{};}});
  const suggestion={owner:'owner-a',text:'A项目口播要求',attachment:fakeAttachment,nonce:999};
  await act(async()=>root.render(<App controller={c} externalSuggestion={suggestion}/>));
  expect(input().value).toBe('A项目口播要求');
  await click('发送');
  expect(input().value).toBe('');
  (c as any).state=chat('owner-b');
  await act(async()=>notify());
  expect(input().value).toBe('');
  expect(host.querySelector('[aria-label="移除 fixture.png"]')).toBeNull();
  expect(JSON.parse(localStorage.getItem('miniclaw.draft.owner-b')!).attachments).toEqual([]);
  (c as any).state=chat('owner-a');
  await act(async()=>notify());
  expect(input().value).toBe('');
  expect(JSON.parse(localStorage.getItem('miniclaw.draft.owner-a')!).attachments).toEqual([]);
});

test('paste and drop upload owned files; remove only cancels that reference and attachment-only send works', async () => {
  const text: Attachment = { id: 'fixture-text', name: 'note.md', kind: 'text', mime: 'text/plain', bytes: 4 };
  vi.mocked(uploadFile).mockResolvedValueOnce(fakeAttachment).mockResolvedValueOnce(text);
  const c = controller();
  await act(async () => root.render(<Composer controller={c} chat={chat()} onManage={() => {}} />));
  const imageFile = new File(['image'], 'fixture.png', { type: 'image/png' });
  const textFile = new File(['note'], 'note.md', { type: 'text/markdown' });
  await files('paste', [imageFile]); await files('drop', [textFile]);
  expect(uploadFile).toHaveBeenNthCalledWith(1, 'owner-a', imageFile, expect.objectContaining({signal:expect.any(AbortSignal)}));
  expect(uploadFile).toHaveBeenNthCalledWith(2, 'owner-a', textFile, expect.objectContaining({signal:expect.any(AbortSignal)}));
  expect(host.querySelector('button[aria-label="预览 fixture.png"]')).not.toBeNull();
  expect(host.querySelector('a[aria-label="预览 fixture.png"]')).toBeNull();
  expect(host.querySelector('a[download="note.md"]')).toBeNull();
  await click('查看附件 note.md');
  expect(document.querySelector('.attachment-details a[download="note.md"]')).not.toBeNull();
  await act(async()=>document.querySelector<HTMLButtonElement>('[aria-label="关闭附件详情"]')!.click());
  expect(document.querySelector('.attachment-details')).toBeNull();
  await click('移除 fixture.png');
  await click('发送');
  expect(c.send).toHaveBeenCalledWith('', undefined, [text]);
  expect(JSON.parse(localStorage.getItem('miniclaw.draft.owner-a')!).attachments).toEqual([]);
});

test('a completed upload cannot enter a different session after the Composer unmounts', async () => {
  let finish!: (attachment: Attachment) => void;
  vi.mocked(uploadFile).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const c = controller();
  await act(async () => root.render(<Composer key="a" controller={c} chat={chat()} onManage={() => {}} />));
  await files('paste', [new File(['image'], 'fixture.png', { type: 'image/png' })]);
  await act(async () => root.render(<Composer key="b" controller={c} chat={chat('owner-b')} onManage={() => {}} />));
  await act(async () => finish(fakeAttachment));
  expect(host.textContent).not.toContain('fixture.png');
  expect(JSON.parse(localStorage.getItem('miniclaw.draft.owner-b')!).attachments).toEqual([]);
  expect(JSON.parse(localStorage.getItem('miniclaw.draft.owner-a')!).attachments).toEqual([fakeAttachment]);
});

test('removing a document during pending parse retry keeps it removed after the old response',async()=>{
  const doc:Attachment={id:'old-doc',name:'旧手册.pdf',kind:'document',mime:'application/pdf',bytes:9000,parse_status:'partial'};
  localStorage.setItem('miniclaw.draft.owner-a',JSON.stringify({text:'保留这条要求',attachments:[doc]}));
  vi.mocked(documentStatus).mockResolvedValue({parse_status:'partial',warnings:[{code:'page',message:'部分内容无法读取',source:{page:2}}]});
  let finish!:(value:Partial<Attachment>)=>void;
  vi.mocked(retryDocument).mockImplementation(()=>new Promise(resolve=>{finish=resolve;}));
  const c=controller();await act(async()=>root.render(<Composer controller={c} chat={chat()} onManage={()=>{}}/>));
  await click('查看附件 旧手册.pdf');
  await act(async()=>[...document.querySelectorAll<HTMLButtonElement>('.attachment-details button')].find(b=>b.textContent==='重试解析')!.click());
  expect(retryDocument).toHaveBeenCalledExactlyOnceWith('owner-a','old-doc');
  await act(async()=>document.querySelector<HTMLButtonElement>('[aria-label="关闭附件详情"]')!.click());
  await click('移除 旧手册.pdf');
  expect(host.querySelector('.attachment-card')).toBeNull();
  await act(async()=>finish({parse_status:'ready',chunks:50}));
  expect(host.querySelector('.attachment-card')).toBeNull();expect(input().value).toBe('保留这条要求');
  expect(JSON.parse(localStorage.getItem('miniclaw.draft.owner-a')!).attachments).toEqual([]);
  expect(c.send).not.toHaveBeenCalled();
});

test('a mixed batch continues after one failure and retries only that file',async()=>{
  let fail=true;vi.mocked(uploadFile).mockImplementation(async(_owner,file)=>{if(file.name==='bad.txt'&&fail)throw new Error('网络中断');return {id:file.name,name:file.name,kind:'text',mime:'text/plain',bytes:3};});
  const c=controller();await act(async()=>root.render(<Composer controller={c} chat={chat()} onManage={()=>{}}/>));
  await files('drop',['first.txt','bad.txt','last.txt'].map(name=>new File(['abc'],name)));
  expect(host.querySelectorAll('.composer-attachments .attachment-card')).toHaveLength(2);expect(host.textContent).toContain('网络中断');
  await click('发送');expect(c.send).not.toHaveBeenCalled();
  fail=false;await click('重试上传 bad.txt');
  expect(vi.mocked(uploadFile).mock.calls.map(([,f])=>f.name)).toEqual(['first.txt','bad.txt','last.txt','bad.txt']);
  expect(host.querySelectorAll('.composer-attachments .attachment-card')).toHaveLength(3);
  await click('发送');expect(c.send).toHaveBeenCalledWith('',undefined,expect.arrayContaining([expect.objectContaining({id:'last.txt'}),expect.objectContaining({id:'bad.txt'})]));
});

test('pending files reserve capacity immediately and two workers bound concurrent uploads',async()=>{
  vi.mocked(uploadFile).mockImplementation(()=>new Promise(()=>{}));
  const c=controller();await act(async()=>root.render(<Composer controller={c} chat={chat()} onManage={()=>{}}/>));
  const event=(names:string[])=>{const e=new Event('drop',{bubbles:true,cancelable:true});Object.defineProperty(e,'dataTransfer',{value:{files:names.map(name=>new File(['abc'],name)),types:['Files']}});return e;};
  await act(async()=>{host.querySelector('form')!.dispatchEvent(event(Array.from({length:6},(_,i)=>`${i}.txt`)));host.querySelector('form')!.dispatchEvent(event(Array.from({length:5},(_,i)=>`next${i}.txt`)));});
  expect(uploadFile).toHaveBeenCalledTimes(2);expect(host.querySelectorAll('.attachment-upload-row')).toHaveLength(6);expect(host.textContent).toContain('每轮最多10个附件');
});

test('canceling an active upload aborts its request and a late success cannot enter the draft',async()=>{
  let finish!:(attachment:Attachment)=>void;let signal!:AbortSignal;
  vi.mocked(uploadFile).mockImplementation((_owner,_file,options)=>{signal=options!.signal!;options!.onSession?.('upload-id');return new Promise(resolve=>finish=resolve);});
  const c=controller();await act(async()=>root.render(<Composer controller={c} chat={chat()} onManage={()=>{}}/>));
  await files('drop',[new File(['abc'],'pending.txt')]);await click('取消上传 pending.txt');
  expect(signal.aborted).toBe(true);expect(cancelUpload).toHaveBeenCalledWith('owner-a','upload-id');
  await act(async()=>finish(fakeAttachment));expect(JSON.parse(localStorage.getItem('miniclaw.draft.owner-a')!).attachments).toEqual([]);
});

test('refused sending preserves the text and attachments for correction', async () => {
  localStorage.setItem('miniclaw.draft.owner-a', JSON.stringify({ text: 'retain this', attachments: [fakeAttachment] }));
  const c = controller(); vi.mocked(c.send).mockResolvedValue(false);
  await act(async () => root.render(<Composer controller={c} chat={chat()} onManage={() => {}} />));
  await click('发送');
  expect(input().value).toBe('retain this');
  expect(host.textContent).toContain('fixture.png');
  expect(JSON.parse(localStorage.getItem('miniclaw.draft.owner-a')!).attachments).toHaveLength(1);
});

test('image editing is sent from the Chat composer with the exact working context and automatic image', async () => {
  const c=controller(), state={...chat(),info:{tools:{canvas:['miniclaw_canvas_propose']}}};
  const creator={project_id:'product',node:'cover' as const};
  const canvas={project_id:'working',revision:7,layer_id:'subject',mode:'plan' as const};
  localStorage.setItem('miniclaw.draft.owner-a',JSON.stringify({text:'让背景柔和一点',attachments:[]}));
  vi.mocked(uploadFile).mockResolvedValue(fakeAttachment);
  await act(async()=>root.render(<Composer controller={c} chat={state} creatorContext={creator} canvasContext={canvas} onManage={()=>{}}/>));
  await click('发送');
  expect(exportBlob).toHaveBeenCalledWith('working');
  expect(uploadFile).toHaveBeenCalledWith('owner-a',expect.objectContaining({name:'当前商品工作图.png'}));
  expect(c.send).toHaveBeenCalledExactlyOnceWith('让背景柔和一点','canvas-editor',[fakeAttachment],canvas,creator);
});

  test('ten existing attachments cannot silently become eleven when preparing the working image', async () => {
    const c=controller(), state={...chat(),info:{tools:{canvas:['miniclaw_canvas_propose']}}};
    const attachments=Array.from({length:10},(_,i)=>({...fakeAttachment,id:'text-'+i,kind:'text',mime:'text/plain'}));
    localStorage.setItem('miniclaw.draft.owner-a',JSON.stringify({text:'修改背景',attachments}));
    await act(async()=>root.render(<Composer controller={c} chat={state} creatorContext={{project_id:'p',node:'cover'}} canvasContext={{project_id:'w',revision:1,layer_id:'l',mode:'plan'}} onManage={()=>{}}/>));
    await click('发送');
    expect(c.send).not.toHaveBeenCalled();
    expect(exportBlob).not.toHaveBeenCalled();
    expect(input().value).toBe('修改背景');
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('先移除一个附件');
  });

  test('switching tasks during automatic image preparation refuses the stale send and keeps the draft', async () => {
  const c=controller(), state={...chat(),info:{tools:{canvas:['miniclaw_canvas_propose']}}};
  let finish!:(blob:Blob)=>void;
  vi.mocked(exportBlob).mockReturnValue(new Promise(resolve=>{finish=resolve;}));
  localStorage.setItem('miniclaw.draft.owner-a',JSON.stringify({text:'尚未发送的修图要求',attachments:[]}));
  await act(async()=>root.render(<Composer controller={c} chat={state} creatorContext={{project_id:'p',node:'cover'}} canvasContext={{project_id:'w',revision:1,layer_id:'l',mode:'plan'}} onManage={()=>{}}/>));
  await click('发送');
  await act(async()=>root.render(<Composer controller={c} chat={state} creatorContext={{project_id:'p',node:'script'}} onManage={()=>{}}/>));
  await act(async()=>finish(new Blob(['old'])));
  expect(c.send).not.toHaveBeenCalled();
  expect(uploadFile).not.toHaveBeenCalled();
  expect(input().value).toBe('尚未发送的修图要求');
  expect(host.querySelector('[role="alert"]')?.textContent).toContain('任务已切换');
});

test('Chat exposes the creation dashboard beside the primary conversation navigation', async () => {
  const c=controller();
  Object.assign(c,{state:chat(),subscribe:()=>()=>{},refresh:vi.fn(),connect:vi.fn(),dispose:vi.fn()});
  await act(async()=>root.render(<App controller={c} onCreator={()=>{}} onCanvas={()=>{}}/>));
  expect(host.querySelector('.app-module-switch')).toBeNull();
  expect(host.querySelector('.sidebar .new-chat')).not.toBeNull();
  expect(host.querySelector('.sidebar .sidebar-home')?.textContent).toBe('创作项目');
  expect(host.querySelectorAll('.sidebar-home')).toHaveLength(1);
});

test('untouched new template leaves directly; real changes use the in-page keep/discard protection', async () => {
  vi.mocked(readApi).mockImplementation(async path => path.endsWith('/tools') ? { groups: [] } : []);
  const c = controller(); const close = vi.fn();
  await act(async () => root.render(<SettingsDialog controller={c} chat={chat()} initialTab="skills" onClose={close} />));
  await click('添加技能');
  await click('关闭设置');
  expect(close).toHaveBeenCalledOnce();
  expect(host.querySelector('[role="alertdialog"]')).toBeNull();
  close.mockClear();
  await act(async () => host.querySelector<HTMLInputElement>('.binding-confirm input')!.click());
  await click('关闭设置');
  expect(close).not.toHaveBeenCalled();
  expect(host.querySelector('.settings-layout')!.hasAttribute('inert')).toBe(true);
  expect(host.querySelector('[role="alertdialog"]')).not.toBeNull();
  await click('继续编辑');
  expect(host.querySelector('.settings-layout')!.hasAttribute('inert')).toBe(false);
  await click('关闭设置'); await click('放弃修改并离开');
  expect(close).toHaveBeenCalledOnce();
});

test('imported Skill is created, declared against server hash, then reloaded without frontend dispatch', async () => {
  const content = '---\nname: import-demo\ndescription: Summarize supplied text.\n---\n\nSummarize only the supplied text.';
  vi.mocked(readApi).mockImplementation(async path => path.endsWith('/tools') ? { groups: [] } : { content_hash: 'server-hash', content });
  const c = controller(); const saved = vi.fn();
  await act(async () => root.render(<SkillEditor controller={c} sessionId="live" blocked={false} onBack={() => {}} onSaved={saved} onDirty={() => {}} onBusy={() => {}} />));
  const file = { name: 'SKILL.md', size: content.length, arrayBuffer: async () => new TextEncoder().encode(content).buffer } as File;
  const upload = host.querySelector<HTMLInputElement>('input[type="file"]')!;
  Object.defineProperty(upload, 'files', { configurable: true, value: [file] });
  await act(async () => upload.dispatchEvent(new Event('change', { bubbles: true })));
  expect(host.querySelector<HTMLInputElement>('input[aria-label="技能标识"]')!.value).toBe('import-demo');
  await act(async () => host.querySelector<HTMLInputElement>('.binding-confirm input')!.click());
  await click('保存技能与依赖');
  expect(writeApi).toHaveBeenNthCalledWith(1, '/api/miniclaw/skills', 'POST', { name: 'import-demo', content });
  expect(writeApi).toHaveBeenNthCalledWith(2, '/api/miniclaw/skills/binding', 'PUT', { name: 'import-demo', required_tools: [], content_hash: 'server-hash' });
  expect(c.client.request).toHaveBeenCalledWith('skills.reload', { session_id: 'live' });
  expect(saved).toHaveBeenCalledOnce();
});

test('memory UI describes the actual session snapshot separately from saved file content', async () => {
  vi.mocked(readApi).mockImplementation(async path => path.includes('/session-capabilities') ? { ready: true, memory: { memory: { enabled: true, loaded: true }, user: { enabled: false, loaded: false } } } : { memory: { text: 'saved fact', hash: 'm', limit: 2200 }, user: { text: 'saved preference', hash: 'u', limit: 1375 } });
  await act(async () => root.render(<MemoryEditor sessionId="live" blocked={false} onBusy={() => {}} onDirty={() => {}} />));
  expect(host.textContent).toContain('本对话已加载启动时的记忆快照');
  await click('个人偏好');
  expect(host.textContent).toContain('本对话未开启此项加载');
  expect(host.querySelector<HTMLTextAreaElement>('textarea')!.value).toBe('saved preference');
});

test('reading older messages suspends forced scrolling until the user returns to the latest message', async () => {
  const scroll = vi.fn();
  Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: scroll });
  Object.defineProperty(Element.prototype, 'scrollTo', { configurable: true, value: vi.fn() });
  vi.mocked(readApi).mockImplementation(async path => path.includes('/api/sessions?') ? { sessions: [], total: 0 } : { ready: true, images: true });
  const c = controller(); let notify = () => {};
  Object.assign(c, { state: { ...chat(), items: [{ id: 'reply', kind: 'assistant', text: 'first segment' }] }, connect: vi.fn().mockResolvedValue(undefined), dispose: vi.fn(), subscribe: (listener: () => void) => { notify = listener; return () => {}; } });
  await act(async () => root.render(<App controller={c} />));
  const conversation = host.querySelector<HTMLDivElement>('.conversation')!;
  Object.defineProperties(conversation, { scrollHeight: { configurable: true, value: 2000 }, clientHeight: { configurable: true, value: 400 }, scrollTop: { configurable: true, writable: true, value: 100 } });
  scroll.mockClear();
  await act(async () => conversation.dispatchEvent(new Event('scroll', { bubbles: true })));
  c.state = { ...c.state, items: [{ id: 'reply', kind: 'assistant', text: 'a later streamed segment' }] };
  await act(async () => notify());
  expect(scroll).not.toHaveBeenCalled();
  await click('↓ 回到最新消息');
  expect(scroll).toHaveBeenCalledWith({ behavior: 'smooth' });
  scroll.mockClear();
  c.state = { ...c.state, items: [{ id: 'reply', kind: 'assistant', text: 'final streamed segment' }] };
  await act(async () => notify());
  expect(scroll).toHaveBeenCalledWith({ behavior: 'instant' });
});


test('workspace association waits until the new Chat is durably linked',async()=>{
  vi.stubGlobal('URL',BrowserURL);
  history.replaceState(null,'','/?workspace=fixture-workspace&target=shot-one');
  const c={...controller(),connect:vi.fn(),dispose:vi.fn(),state:{...chat(),workspaceConnecting:true},workspace:{id:'fixture-workspace',target:'shot-one'},subscribe:()=>()=>{}} as unknown as ChatController;
  vi.mocked(readApi).mockImplementation(async path=>path.startsWith('/api/workspaces?')?[{id:'fixture-workspace',chat_id:'owner-a',name:'测试项目'}]:path.startsWith('/api/sessions?')?{sessions:[],total:0}:{ready:true,images:true});
  await act(async()=>root.render(<App controller={c}/>));
  expect(vi.mocked(readApi).mock.calls.some(([path])=>path.startsWith('/api/workspaces?'))).toBe(false);expect(c.workspace?.id).toBe('fixture-workspace');
  expect(host.querySelector('.conversation-loading')?.textContent).toBe('正在读取对话…');expect(host.querySelector('.welcome')).toBeNull();
  c.state={...c.state,workspaceConnecting:false};await act(async()=>root.render(<App controller={c}/>));
  expect(readApi).toHaveBeenCalledWith('/api/workspaces?owner=owner-a');expect(c.workspace).toEqual({id:'fixture-workspace',target:'shot-one'});
  expect(host.querySelector('.canvas-return')?.textContent).toBe('打开画布');expect(host.querySelector('.canvas-return')?.getAttribute('href')).toBe('/p/fixture-workspace');expect(host.querySelector('.canvas-return')?.getAttribute('title')).toBe('测试项目');expect(host.querySelector('.topbar-title')?.textContent).toBe('测试项目');expect(host.querySelector('.welcome h1')?.textContent).toBe('测试项目');
});
