// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { Message } from './Message';
import {attachmentBlob,documentStatus,type Attachment} from './attachments';
import {writeApi} from './management-api';

vi.mock('./attachments', () => ({ attachmentBlob:vi.fn(),documentStatus:vi.fn(),retryDocument:vi.fn() }));
vi.mock('./management-api',()=>({writeApi:vi.fn(),readApi:vi.fn()}));
let host:HTMLDivElement, root:Root;
const original='1.真实素材\n2.年轻化奢华\n3.真人\n4.10s，双镜\n5.保留包装\n\n还有一句补充。';
const image:Attachment={id:'one',name:'产品原图.png',kind:'image',mime:'image/png',bytes:100};
beforeEach(()=>{
  vi.resetAllMocks();
  vi.mocked(attachmentBlob).mockResolvedValue(new Blob(['fixture']));vi.mocked(documentStatus).mockResolvedValue({parse_status:'ready'});
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
  Object.defineProperty(URL,'createObjectURL',{configurable:true,value:vi.fn(()=>'blob:fixture')});
  Object.defineProperty(URL,'revokeObjectURL',{configurable:true,value:vi.fn()});
  Object.defineProperty(HTMLDialogElement.prototype,'showModal',{configurable:true,value:vi.fn(function(this:HTMLDialogElement){this.open=true;})});
  Object.defineProperty(HTMLDialogElement.prototype,'close',{configurable:true,value:vi.fn(function(this:HTMLDialogElement){this.open=false;})});
  HTMLAnchorElement.prototype.click=vi.fn();
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();});

test('user images precede the original multiline reply within one aligned group',async()=>{
  const reuse=vi.fn(),edit=vi.fn();
  await act(async()=>root.render(<Message item={{id:'row-1',kind:'user',text:original,attachments:[image,{...image,id:'two',name:'参考图.png'}]}} owner="owner" onReuse={reuse} onEdit={edit}/>));
  const body=host.querySelector('.message-body')!, gallery=host.querySelector('.attachments')!;
  expect(gallery.compareDocumentPosition(body)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(gallery.parentElement).toBe(body.parentElement);
  expect(gallery.querySelectorAll('.attachment-card-tile')).toHaveLength(2);expect(gallery.querySelector('.attachment-tile-remove')).toBeNull();
  expect(body.querySelector('p')?.textContent).toBe(original);
  await act(async()=>host.querySelector<HTMLButtonElement>('button[aria-label="编辑 产品原图.png"]')!.click());
  expect(edit).toHaveBeenCalledWith(image);
  await act(async()=>host.querySelector<HTMLButtonElement>('button[aria-label="复用这条消息"]')!.click());
  expect(reuse).toHaveBeenCalledWith(original);
});

test('ordinary slash text and decimal values remain verbatim',async()=>{
  const text='/素材/产品.png\n价格 1.5 元，10s 视频，9:16；第二版 2.3';
  await act(async()=>root.render(<Message item={{id:'row-2',kind:'user',text}} owner="owner" onReuse={()=>{}}/>));
  expect(host.querySelector('.message-body p')?.textContent).toBe(text);
  expect(host.querySelector('.message-skill')).toBeNull();
});

test('an explicitly selected skill is displayed separately from the original reply',async()=>{
  await act(async()=>root.render(<Message item={{id:'row-4',kind:'user',skill:'product-video-plan',text:'/product-video-plan\n'+original}} owner="owner" onReuse={()=>{}}/>));
  expect(host.querySelector('.message-skill')?.textContent).toBe('产品短片策划');
  expect(host.querySelector('.message-body p')?.textContent).toBe(original);
});

test('assistant attachments retain their existing position after the response',async()=>{
  await act(async()=>root.render(<Message item={{id:'row-3',kind:'assistant',text:'结果说明',attachments:[image]}} owner="owner" onReuse={()=>{}}/>));
  expect(host.querySelector('.message-body')!.compareDocumentPosition(host.querySelector('.attachments')!)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(host.querySelector('.attachment-card')).not.toBeNull();expect(host.querySelector('.attachment-card-tile')).toBeNull();
});

test('image-only user messages have no empty text bubble',async()=>{
  await act(async()=>root.render(<Message item={{id:'row-5',kind:'user',text:'',attachments:[image]}} owner="owner" onReuse={()=>{}}/>));
  expect(host.querySelector('.attachments')).not.toBeNull();
  expect(host.querySelector('.message-body')).toBeNull();
});

test('sent image and partial document use tiles while document details alone expose download and warnings',async()=>{
  const pdf:Attachment={id:'pdf',name:'产品说明.pdf',kind:'document',mime:'application/pdf',bytes:50*1024*1024,parse_status:'partial'};
  vi.mocked(documentStatus).mockResolvedValue({parse_status:'partial',chunks:140,warnings:[{code:'page_text',message:'该页部分内容无法读取',source:{page:12}}],coverage:{units_seen:131,units_done:120,total_units:131,warning_count:11}});
  await act(async()=>root.render(<Message item={{id:'sent',kind:'user',text:'分析这份资料',attachments:[image,pdf]}} owner="owner" onReuse={()=>{}}/>));
  expect(host.querySelectorAll('.user-attachments .attachment-card-tile')).toHaveLength(2);expect(host.querySelector('.attachment-tile-remove')).toBeNull();
  expect(host.querySelector('.attachment-tile-status.is-partial')!.textContent).toBe('部分可读取');
  expect(host.textContent).not.toContain('下载原文件');expect(host.textContent).not.toContain('该页部分内容无法读取');expect(host.querySelector('.attachment-warnings')).toBeNull();
  expect(attachmentBlob).toHaveBeenCalledTimes(1);
  await act(async()=>host.querySelector<HTMLButtonElement>('[aria-label="查看附件 产品说明.pdf"]')!.click());
  const details=document.querySelector<HTMLDialogElement>('.attachment-details')!;
  expect(details.textContent).toContain('第12页：该页部分内容无法读取');expect(details.textContent).toContain('读取范围说明（11项）');expect(details.textContent).toContain('显示服务返回的1项警告');
  expect(attachmentBlob).toHaveBeenCalledTimes(1);
  await act(async()=>[...details.querySelectorAll<HTMLButtonElement>('button')].find(button=>button.textContent==='下载原文件')!.click());
  expect(attachmentBlob).toHaveBeenLastCalledWith('owner',pdf);
});

test('sent image tiles preserve independent edit, canvas save and existing image preview actions',async()=>{
  const edit=vi.fn(),target={workspace:'workspace',sessionId:'live-session'},saved={workspace:'workspace',revision:3,object:'saved-node',added:true};
  vi.mocked(writeApi).mockResolvedValue(saved);
  await act(async()=>root.render(<Message item={{id:'sent-image',kind:'user',text:'保留原图',attachments:[image]}} owner="owner" onReuse={()=>{}} onEdit={edit} canvasTarget={target}/>));
  const tile=host.querySelector('.attachment-card-tile')!,preview=tile.querySelector<HTMLButtonElement>('[aria-label="预览 产品原图.png"]')!;
  expect(tile.querySelector('.attachment-tile-actions')).not.toBeNull();expect(preview.querySelector('button')).toBeNull();expect(tile.querySelector('.attachment-tile-remove')).toBeNull();
  await act(async()=>tile.querySelector<HTMLButtonElement>('[aria-label="编辑 产品原图.png"]')!.click());expect(edit).toHaveBeenCalledExactlyOnceWith(image);
  await act(async()=>tile.querySelector<HTMLButtonElement>('[aria-label="将 产品原图.png 加入画布"]')!.click());
  expect(writeApi).toHaveBeenCalledExactlyOnceWith('/api/workspaces/workspace/assets/from-chat','POST',{request_id:expect.any(String),session_id:'live-session',attachment:image.id});
  expect(tile.textContent).toContain('已加入画布');expect(tile.querySelector('a[href="/p/workspace?focus=saved-node"]')).not.toBeNull();expect(document.querySelector('.image-lightbox')).toBeNull();
  await act(async()=>preview.click());const modal=document.querySelector<HTMLDialogElement>('.image-lightbox')!;
  expect(modal.open).toBe(true);expect(modal.getAttribute('aria-label')).toBe('图片预览：产品原图.png');expect(modal.querySelector('img')!.getAttribute('src')).toBe('blob:fixture');
  expect(attachmentBlob).toHaveBeenCalledTimes(1);
});
