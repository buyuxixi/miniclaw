// @vitest-environment jsdom
import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {afterEach,beforeEach,expect,test,vi} from 'vitest';
import type {ChatController} from './chat-controller';
import {readApi,writeApi} from './management-api';
import {uploadFile,attachmentBlob} from './attachments';
import {useDirectorImages} from './use-director-images';
vi.mock('./use-chat',()=>({useChat:(c:ChatController)=>({...c.state,connection:c.connection})}));
vi.mock('./management-api',()=>({readApi:vi.fn(),writeApi:vi.fn()}));
vi.mock('./attachments',()=>({uploadFile:vi.fn(),attachmentBlob:vi.fn()}));
vi.mock('./canvas-api',async()=>({...await vi.importActual('./canvas-api'),loadProject:vi.fn(async()=>({project:{id:'precision',revision:1,document:{layers:[]}},jobs:[]}))}));
history.replaceState(null,'','/?director=workspace-one&target=asset-one');
const {StudioDirector}=await import('./StudioDirector');
(globalThis as any).IS_REACT_ACT_ENVIRONMENT=true;
const image={id:'uploaded-one',name:'效果对比.png',kind:'image' as const,mime:'image/png',bytes:400};
let host:HTMLDivElement,root:ReturnType<typeof createRoot>,controller:ChatController,frame:{postMessage:ReturnType<typeof vi.fn>};
beforeEach(()=>{
  vi.clearAllMocks();localStorage.clear();
  vi.mocked(readApi).mockImplementation(async path=>path.includes('session-capabilities')?{ready:true,images:true}:path.endsWith('/plans')?[]:{state:{assets:[{id:'asset-one',name:'原图',file:'/original.png'}],shots:[]}});
  vi.mocked(writeApi).mockResolvedValue({project:'precision',revision:1,layer:'layer-one',object:'asset-one',source:'/original.png'});
  vi.mocked(uploadFile).mockResolvedValue(image);vi.mocked(attachmentBlob).mockResolvedValue(new Blob(['image']));
  vi.stubGlobal('URL',Object.assign(URL,{createObjectURL:vi.fn(()=> 'blob:preview'),revokeObjectURL:vi.fn()}));
  controller={state:{items:[],info:{model:'vision-chat',tools:{canvas:['miniclaw_canvas_propose']}},sessionId:'live',storedId:'owner',busy:false,running:false},connection:'open',client:{onAny:()=>()=>{},onState:()=>()=>{}},send:vi.fn(async()=>true)} as unknown as ChatController;
  frame={postMessage:vi.fn()};vi.stubGlobal('parent',frame);
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();});
async function render(){await act(async()=>root.render(<StudioDirector controller={controller}/>));}
async function upload(){const input=host.querySelector('input[type=file]')!;Object.defineProperty(input,'files',{configurable:true,value:[new File(['png'],image.name,{type:'image/png'})]});await act(async()=>input.dispatchEvent(new Event('change',{bubbles:true})));}
async function submit(){await act(async()=>host.querySelector<HTMLButtonElement>('button[aria-label="发送修改要求"]')!.click());}
function transfer(type:'paste'|'drop',files:File[]){const e=new Event(type,{bubbles:true,cancelable:true});Object.defineProperty(e,type==='paste'?'clipboardData':'dataTransfer',{value:{files,types:['Files']}});return e;}
test('uploads an owned screenshot above the text and sends its bytes reference with an image-only turn',async()=>{
  await render();await upload();
  expect(uploadFile).toHaveBeenCalledWith('owner',expect.any(File));
  const tray=host.querySelector('.director-attachments')!;
  expect(tray.compareDocumentPosition(host.querySelector('textarea')!)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(tray.querySelector('img')?.src).toBe('blob:preview');
  await submit();expect(controller.send).toHaveBeenCalledWith('',undefined,[image],expect.objectContaining({mode:'plan'}));
  expect(host.querySelector('.director-attachments')).toBeNull();
});
test('paste and drop use the same upload path; removing a preview does not send or mutate the canvas',async()=>{
  await render();await act(async()=>host.querySelector('textarea')!.dispatchEvent(transfer('paste',[new File(['x'],'标记.png',{type:'image/png'})])));
  await act(async()=>host.querySelector<HTMLButtonElement>('button[aria-label="移除 效果对比.png"]')!.click());
  await act(async()=>host.querySelector('form')!.dispatchEvent(transfer('drop',[new File(['x'],'标记.png',{type:'image/png'})])));
  expect(uploadFile).toHaveBeenCalledTimes(2);expect(controller.send).not.toHaveBeenCalled();
  expect(vi.mocked(writeApi).mock.calls.some(([path])=>path.includes('generate')||path.includes('adopt'))).toBe(false);
});
test('failed sending retains the preview for an explicit retry',async()=>{
  vi.mocked(controller.send).mockResolvedValueOnce(false);await render();await upload();await submit();
  expect(host.textContent).toContain('图片也已保留');expect(host.querySelector('.director-attachments img')).not.toBeNull();
  await submit();expect(controller.send).toHaveBeenCalledTimes(2);expect(host.querySelector('.director-attachments')).toBeNull();
});
test('successful sending preserves any new text typed while the request is awaiting acceptance',async()=>{
  let finish!:(value:boolean)=>void;vi.mocked(controller.send).mockImplementation(()=>new Promise(resolve=>finish=resolve));
  await render();await upload();
  await act(async()=>host.querySelector<HTMLButtonElement>('button[aria-label="发送修改要求"]')!.click());
  const input=host.querySelector('textarea')!;
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(input,'还有一个细节');input.dispatchEvent(new Event('input',{bubbles:true}));});
  await act(async()=>finish(true));expect(input.value).toBe('还有一个细节');expect(host.querySelector('.director-attachments')).toBeNull();
});
test('a text-only model cannot silently discard screenshots and pretend to see them',async()=>{
  vi.mocked(readApi).mockImplementation(async path=>path.includes('session-capabilities')?{ready:true,images:false}:path.endsWith('/plans')?[]:{state:{assets:[],shots:[]}});
  await render();await upload();expect(host.textContent).toContain('当前聊天模型不能看图');
  expect(host.querySelector<HTMLButtonElement>('button[aria-label="发送修改要求"]')!.disabled).toBe(true);
  expect(controller.send).not.toHaveBeenCalled();expect(host.querySelector('.director-attachments img')).not.toBeNull();
});
test('a screenshot draft survives adding canvas references and a reload',async()=>{
  await render();await upload();
  await act(async()=>window.dispatchEvent(new MessageEvent('message',{origin:location.origin,source:frame as any,data:{type:'miniclaw.director.target',workspace:'workspace-one',target:'asset-two',label:'第二张',request:2}})));
  expect(frame.postMessage).toHaveBeenCalledWith(expect.objectContaining({pending:false,target:'asset-two'}),location.origin);
  await act(async()=>root.unmount());root=createRoot(host);await render();expect(host.querySelector('.director-attachments img')).not.toBeNull();
});

test('adding a reference image retains the original edit scope and its plans',async()=>{
  vi.mocked(readApi).mockImplementation(async path=>path.includes('session-capabilities')?{ready:true,images:true}:path.endsWith('/plans')?[]:{state:{assets:[{id:'asset-one',name:'原图',file:'/original.png'},{id:'asset-two',name:'色调参考',file:'/reference.png'}],shots:[]}});
  await render();await upload();
  await act(async()=>window.dispatchEvent(new MessageEvent('message',{origin:location.origin,source:frame as any,data:{type:'miniclaw.director.reference',workspace:'workspace-one',target:'asset-two'}})));
  expect(controller.workspace).toEqual({id:'workspace-one',target:'asset-one',references:['asset-one','asset-two']});
  expect(host.textContent).toContain('当前图片');expect(host.textContent).toContain('色调参考');
  await submit();expect(controller.send).toHaveBeenCalledWith('',undefined,[image],expect.objectContaining({project_id:'precision',layer_id:'layer-one',mode:'plan'}));
  expect(vi.mocked(writeApi).mock.calls.filter(([path])=>path.endsWith('/editing-target')).every(([, ,data])=>(data as any).target==='asset-one')).toBe(true);
});
test('rejects too many images and retains earlier successes if a later upload fails',async()=>{
  await render();const file=new File(['x'],'mark.png',{type:'image/png'});
  await act(async()=>host.querySelector('form')!.dispatchEvent(transfer('drop',Array(5).fill(file))));
  expect(uploadFile).not.toHaveBeenCalled();expect(host.textContent).toContain('最多上传4张');
  vi.mocked(uploadFile).mockResolvedValueOnce(image).mockRejectedValueOnce(new Error('网络中断'));
  await act(async()=>host.querySelector('form')!.dispatchEvent(transfer('drop',[file,file])));
  expect(host.textContent).toContain('网络中断');expect(host.querySelector('.director-attachments img')).not.toBeNull();
});
test('non-image files and oversized screenshots never reach the upload endpoint',async()=>{
  await render();const large=new File(['x'],'large.png',{type:'image/png'});Object.defineProperty(large,'size',{value:5*1024*1024+1});
  for(const f of [new File(['x'],'notes.txt',{type:'text/plain'}),large])await act(async()=>host.querySelector('form')!.dispatchEvent(transfer('drop',[f])));
  expect(uploadFile).not.toHaveBeenCalled();expect(host.textContent).toContain('每张最大5 MiB');
});
test('a late upload cannot attach to another owner or node; it is recovered on the original node',async()=>{
  let finish!:(value:typeof image)=>void;vi.mocked(uploadFile).mockImplementation(()=>new Promise(resolve=>finish=resolve));
  let hook!:ReturnType<typeof useDirectorImages>;
  function Probe({owner,target}:{owner:string;target:string}){hook=useDirectorImages(owner,'work',target,'live','vision',false);return <div>{hook.items.map(i=>i.name).join()}</div>;}
  await act(async()=>root.render(<Probe owner="one" target="node-a"/>));
  let pending!:Promise<void>;await act(async()=>{pending=hook.addFiles([new File(['x'],'mark.png',{type:'image/png'})]);});
  await act(async()=>root.render(<Probe owner="two" target="node-b"/>));
  await act(async()=>{finish(image);await pending;});expect(hook.items).toHaveLength(0);
  await act(async()=>root.render(<Probe owner="one" target="node-a"/>));expect(hook.items).toEqual([image]);
});
