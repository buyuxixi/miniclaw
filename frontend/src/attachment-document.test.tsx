// @vitest-environment jsdom
import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,test,vi} from 'vitest';
import {AttachmentCard} from './AttachmentCard';
import {attachmentBlob,documentStatus,retryDocument,type Attachment} from './attachments';
vi.mock('./attachments',()=>({attachmentBlob:vi.fn(),documentStatus:vi.fn(),retryDocument:vi.fn()}));
let root:Root,host:HTMLDivElement;
const file:Attachment={id:'doc',name:'长产品手册.pdf',kind:'document',mime:'application/pdf',bytes:50*1024*1024,parse_status:'queued'};
beforeEach(()=>{vi.resetAllMocks();vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);URL.createObjectURL=vi.fn(()=> 'blob:file');URL.revokeObjectURL=vi.fn();HTMLAnchorElement.prototype.click=vi.fn();Object.defineProperty(HTMLDialogElement.prototype,'showModal',{configurable:true,value:vi.fn(function(this:HTMLDialogElement){this.open=true;})});Object.defineProperty(HTMLDialogElement.prototype,'close',{configurable:true,value:vi.fn(function(this:HTMLDialogElement){this.open=false;})});host=document.createElement('div');document.body.append(host);root=createRoot(host);vi.mocked(documentStatus).mockResolvedValue({parse_status:'ready',chunks:20});vi.mocked(attachmentBlob).mockResolvedValue(new Blob(['pdf']));});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.useRealTimers();vi.unstubAllGlobals();});
test('large document cards read only parse metadata until the user downloads',async()=>{
  const update=vi.fn();await act(async()=>root.render(<AttachmentCard owner="owner" attachment={file} onStatus={update}/>));
  expect(attachmentBlob).not.toHaveBeenCalled();expect(host.textContent).toContain('50.0 MiB · 可使用');
  expect(update).toHaveBeenCalledWith(expect.objectContaining({id:'doc',parse_status:'ready',chunks:20}));
  await act(async()=>host.querySelector<HTMLButtonElement>('.attachment-text-action')!.click());
  expect(attachmentBlob).toHaveBeenCalledWith('owner',file);
});
test('parse failures offer a real retry and partial results show the coverage warning',async()=>{
  vi.mocked(documentStatus).mockResolvedValueOnce({parse_status:'failed',parse_error:'文件损坏'}).mockResolvedValue({parse_status:'partial',warnings:[{code:'limit',message:'只读取前100页',source:{page:101}}],coverage:{warning_count:120}});
  vi.mocked(retryDocument).mockResolvedValue({parse_status:'queued'});
  await act(async()=>root.render(<AttachmentCard owner="owner" attachment={file}/>));
  expect(host.textContent).toContain('文件损坏');
  const retry=[...host.querySelectorAll('button')].find(b=>b.textContent==='重试解析')!;await act(async()=>retry.click());
  expect(retryDocument).toHaveBeenCalledWith('owner','doc');expect(host.textContent).toContain('部分可读取');expect(host.textContent).toContain('第101页：只读取前100页');expect(host.textContent).toContain('120项');
});
test('new small text attachments refresh their queued parsing state while legacy text stays compatible',async()=>{
  const text:Attachment={id:'text',name:'说明.md',kind:'text',mime:'text/plain',bytes:30,parse_status:'queued'};
  const update=vi.fn();await act(async()=>root.render(<AttachmentCard owner="owner" attachment={text} onStatus={update}/>));
  expect(documentStatus).toHaveBeenCalledWith('owner','text',expect.any(AbortSignal));expect(host.textContent).toContain('可使用');expect(update).toHaveBeenCalledWith(expect.objectContaining({parse_status:'ready'}));
  vi.mocked(documentStatus).mockClear();await act(async()=>root.render(<AttachmentCard owner="owner" attachment={{...text,id:'legacy',parse_status:undefined}}/>));
  expect(documentStatus).not.toHaveBeenCalled();expect(host.textContent).not.toContain('等待解析');
});

test('partial UTF-8 surrogate failures have a readable message and manual retry polls until ready',async()=>{
  vi.useFakeTimers();
  const raw="UnicodeEncodeError: 'utf-8' codec can't encode character '\\ud83d' in position 99: surrogates not allowed";
  const partial={...file,parse_status:'partial' as const,parse_error:raw};
  vi.mocked(documentStatus).mockResolvedValueOnce({parse_status:'partial',parse_error:raw,warnings:[{code:'encoding',message:raw,source:{page:12}}]})
    .mockResolvedValueOnce({parse_status:'queued'}).mockResolvedValueOnce({parse_status:'parsing'}).mockResolvedValue({parse_status:'ready',chunks:200});
  vi.mocked(retryDocument).mockResolvedValue({parse_status:'queued'});
  const update=vi.fn();await act(async()=>root.render(<AttachmentCard owner="owner" attachment={partial} onStatus={update}/>));
  expect(host.querySelector('[role="alert"]')!.textContent).toBe('部分文字编码异常，已保留可读取内容，可重试解析。');
  expect(host.querySelector('.attachment-warnings')!.textContent).toContain('第12页：部分文字编码异常');
  expect(host.textContent).not.toContain('UnicodeEncodeError');expect(host.textContent).not.toContain('surrogates not allowed');
  expect(update).toHaveBeenCalledWith(expect.objectContaining({parse_error:raw}));
  expect(retryDocument).not.toHaveBeenCalled();expect(attachmentBlob).not.toHaveBeenCalled();
  const retry=[...host.querySelectorAll('button')].find(button=>button.textContent==='重试解析')!;
  await act(async()=>retry.click());
  expect(retryDocument).toHaveBeenCalledExactlyOnceWith('owner','doc');
  expect(host.textContent).toContain('等待解析');expect(host.querySelector('[role="alert"]')).toBeNull();
  await act(async()=>vi.advanceTimersByTimeAsync(2000));expect(host.textContent).toContain('正在解析');
  await act(async()=>vi.advanceTimersByTimeAsync(2000));expect(host.textContent).toContain('可使用');
  expect(documentStatus).toHaveBeenCalledTimes(4);
  await act(async()=>vi.advanceTimersByTimeAsync(10000));expect(documentStatus).toHaveBeenCalledTimes(4);
  expect([...host.querySelectorAll('button')].some(button=>button.textContent==='重试解析')).toBe(false);
  await act(async()=>[...host.querySelectorAll('button')].find(button=>button.textContent==='下载原文件')!.click());
  expect(attachmentBlob).toHaveBeenCalledExactlyOnceWith('owner',partial);
});

test('ordinary partial warnings remain visible and never cause an automatic retry',async()=>{
  vi.useFakeTimers();
  vi.mocked(documentStatus).mockResolvedValue({parse_status:'partial',warnings:[{code:'image',message:'该页图片没有可提取文字',source:{page:2}}],coverage:{warning_count:9}});
  await act(async()=>root.render(<AttachmentCard owner="owner" attachment={file}/>));
  expect(host.textContent).toContain('部分可读取');expect(host.textContent).toContain('第2页：该页图片没有可提取文字');expect(host.textContent).toContain('9项');
  expect([...host.querySelectorAll('button')].some(button=>button.textContent==='重试解析')).toBe(true);
  await act(async()=>vi.advanceTimersByTimeAsync(10000));
  expect(documentStatus).toHaveBeenCalledTimes(1);expect(retryDocument).not.toHaveBeenCalled();expect(attachmentBlob).not.toHaveBeenCalled();
});

test('unknown parsing errors remain visible and failed encoding errors do not claim readable content',async()=>{
  vi.mocked(documentStatus).mockResolvedValueOnce({parse_status:'failed',parse_error:'PDF目录结构损坏：xref offset 812 无效'});
  await act(async()=>root.render(<AttachmentCard owner="owner" attachment={file}/>));
  expect(host.querySelector('[role="alert"]')!.textContent).toBe('PDF目录结构损坏：xref offset 812 无效');
  vi.mocked(documentStatus).mockResolvedValueOnce({parse_status:'failed',parse_error:"'utf-8' codec can't encode character: surrogates not allowed"});
  await act(async()=>root.render(<AttachmentCard owner="owner" attachment={{...file,id:'failed-encoding'}}/>));
  expect(host.querySelector('[role="alert"]')!.textContent).toBe('文字编码异常，暂时无法完成解析，可重试解析。');
  expect(host.textContent).not.toContain('已保留可读取内容');
});

const details=()=>document.querySelector<HTMLDialogElement>('.attachment-details');
const openTile=()=>host.querySelector<HTMLButtonElement>('.attachment-tile-open')!;

test('ready tiles show only filename and type, and document details defer original download',async()=>{
  await act(async()=>root.render(<AttachmentCard owner="owner" attachment={file} variant="tile"/>));
  expect(host.querySelector('.attachment-card-tile')).not.toBeNull();
  expect(host.querySelector('.attachment-tile-name')!.textContent).toBe(file.name);
  expect(host.querySelector('.attachment-tile-type')!.textContent).toBe('PDF');
  expect(host.querySelector('.attachment-tile-status')).toBeNull();
  expect(host.querySelector('.attachment-tile-actions')).toBeNull();
  expect(host.textContent).not.toContain('50.0 MiB');expect(host.textContent).not.toContain('可使用');expect(host.textContent).not.toContain('下载');
  expect(attachmentBlob).not.toHaveBeenCalled();
  await act(async()=>openTile().click());
  expect(details()!.open).toBe(true);
  expect(document.getElementById(details()!.getAttribute('aria-labelledby')!)!.textContent).toBe(file.name);
  expect(details()!.textContent).toContain('50.0 MiB');expect(details()!.textContent).toContain('可使用');expect(details()!.textContent).toContain('文本块20');
  expect(attachmentBlob).not.toHaveBeenCalled();
  await act(async()=>[...details()!.querySelectorAll('button')].find(button=>button.textContent==='下载原文件')!.click());
  expect(attachmentBlob).toHaveBeenCalledExactlyOnceWith('owner',file);
});

test('partial tiles keep the badge compact and details distinguish processed pages from warning pages',async()=>{
  const warnings=Array.from({length:11},(_,index)=>({code:'page_text',message:'该页部分内容无法读取',source:{page:121+index}}));
  vi.mocked(documentStatus).mockResolvedValue({parse_status:'partial',chunks:140,warnings,coverage:{units_seen:131,units_done:120,total_units:131,warning_count:11,complete:false}});
  await act(async()=>root.render(<AttachmentCard owner="owner" attachment={file} variant="tile"/>));
  expect(host.querySelector('.attachment-tile-status.is-partial')!.textContent).toBe('部分可读取');
  expect(document.getElementById(openTile().getAttribute('aria-describedby')!)!.textContent).toBe('部分可读取');
  expect(host.textContent).not.toContain('该页部分内容无法读取');expect(host.querySelector('.attachment-warnings')).toBeNull();
  await act(async()=>openTile().click());
  expect(details()!.querySelector('.attachment-details-coverage')!.textContent).toBe('已处理131/131页；11页有读取警告');
  expect(details()!.textContent).toContain('第121页：该页部分内容无法读取');expect(details()!.textContent).toContain('读取范围说明（11项）');
  expect(details()!.querySelectorAll('.attachment-details-warnings p')).toHaveLength(11);
  expect(retryDocument).not.toHaveBeenCalled();expect(attachmentBlob).not.toHaveBeenCalled();
});

test('details report stopped parsing and the exact warning total without inventing omitted warnings',async()=>{
  vi.mocked(documentStatus).mockResolvedValue({parse_status:'partial',warnings:[{code:'page',message:'页内读取失败',source:{page:2}},{code:'limit',message:'达到解析预算'}],coverage:{units_seen:10,units_done:9,total_units:131,stopped_early:true,warning_count:120}});
  await act(async()=>root.render(<AttachmentCard owner="owner" attachment={file} variant="tile"/>));
  await act(async()=>openTile().click());
  const text=details()!.textContent!;
  expect(text).toContain('已处理10/131页');expect(text).toContain('解析提前停止，后续内容尚未处理');
  expect(text).toContain('读取范围说明（120项）');expect(text).toContain('当前显示服务返回的2项警告，完整警告共120项。');
  expect(details()!.querySelectorAll('.attachment-details-warnings p')).toHaveLength(3);
  expect(text).not.toContain('120页有读取警告');expect(text).not.toContain('已处理9/131页');
});

test('manual retry inside tile details updates parsing state, clears errors and preserves the open dialog',async()=>{
  vi.useFakeTimers();
  const raw="'utf-8' codec can't encode characters: surrogates not allowed";
  const partial={...file,parse_status:'partial' as const,parse_error:raw};
  vi.mocked(documentStatus).mockResolvedValueOnce({parse_status:'partial',parse_error:raw})
    .mockResolvedValueOnce({parse_status:'queued'}).mockResolvedValueOnce({parse_status:'parsing'}).mockResolvedValue({parse_status:'ready',chunks:22});
  vi.mocked(retryDocument).mockResolvedValue({parse_status:'queued'});
  const update=vi.fn();await act(async()=>root.render(<AttachmentCard owner="owner" attachment={partial} variant="tile" onStatus={update}/>));
  await act(async()=>openTile().click());const modal=details()!;
  expect(modal.querySelector('[role="alert"]')!.textContent).toContain('部分文字编码异常');
  await act(async()=>[...modal.querySelectorAll('button')].find(button=>button.textContent==='重试解析')!.click());
  expect(retryDocument).toHaveBeenCalledExactlyOnceWith('owner','doc');expect(details()).toBe(modal);expect(modal.querySelector('[role="alert"]')).toBeNull();
  expect(host.querySelector('.attachment-tile-status.is-queued')!.textContent).toBe('等待解析');
  await act(async()=>vi.advanceTimersByTimeAsync(2000));expect(host.querySelector('.attachment-tile-status.is-parsing')!.textContent).toBe('正在解析');
  await act(async()=>vi.advanceTimersByTimeAsync(2000));expect(host.querySelector('.attachment-tile-status')).toBeNull();expect(modal.textContent).toContain('可使用');
  expect(update).toHaveBeenLastCalledWith(expect.objectContaining({parse_status:'ready',parse_error:'',chunks:22}));
  await act(async()=>vi.advanceTimersByTimeAsync(10000));expect(documentStatus).toHaveBeenCalledTimes(4);
});

test('tile details close on Escape or backdrop and restore focus to the opener',async()=>{
  await act(async()=>root.render(<AttachmentCard owner="owner" attachment={file} variant="tile"/>));
  const opener=openTile();opener.focus();await act(async()=>opener.click());
  expect(document.activeElement).toBe(details()!.querySelector('[aria-label="关闭附件详情"]'));
  await act(async()=>details()!.querySelector('h2')!.click());expect(details()).not.toBeNull();
  const cancel=new Event('cancel',{bubbles:true,cancelable:true});await act(async()=>details()!.dispatchEvent(cancel));
  expect(cancel.defaultPrevented).toBe(true);expect(details()).toBeNull();expect(document.activeElement).toBe(opener);
  await act(async()=>opener.click());await act(async()=>details()!.click());
  expect(details()).toBeNull();expect(document.activeElement).toBe(opener);
});

test('tile removal is a separate button and never opens the document dialog',async()=>{
  const remove=vi.fn();await act(async()=>root.render(<AttachmentCard owner="owner" attachment={file} variant="tile" onRemove={remove}/>));
  expect(openTile().querySelector('button')).toBeNull();
  await act(async()=>host.querySelector<HTMLButtonElement>(`[aria-label="移除 ${file.name}"]`)!.click());
  expect(remove).toHaveBeenCalledOnce();expect(details()).toBeNull();expect(attachmentBlob).not.toHaveBeenCalled();
});

test('default row remains compatible and tile images retain the existing preview without duplicate name announcements',async()=>{
  await act(async()=>root.render(<AttachmentCard owner="owner" attachment={file}/>));
  expect(host.querySelector('.attachment-card-tile')).toBeNull();expect(host.textContent).toContain('50.0 MiB · 可使用');expect(host.querySelector('.attachment-text-action')).not.toBeNull();
  const image:Attachment={id:'image',name:'产品图.png',kind:'image',mime:'image/png',bytes:100};
  await act(async()=>root.render(<AttachmentCard owner="owner" attachment={image} variant="tile"/>));
  expect(openTile().getAttribute('aria-label')).toBe('预览 产品图.png');expect(openTile().querySelector('img')!.getAttribute('alt')).toBe('');
  await act(async()=>openTile().click());
  const preview=document.querySelector<HTMLDialogElement>('.image-lightbox')!;
  expect(preview.open).toBe(true);expect(preview.getAttribute('aria-label')).toBe('图片预览：产品图.png');
  expect(preview.querySelector('img')!.getAttribute('src')).toBe('blob:file');expect(preview.querySelector('a[download]')!.getAttribute('download')).toBe(image.name);
  expect(details()).toBeNull();expect(attachmentBlob).toHaveBeenCalledTimes(1);
  expect(host.querySelector('.attachment-tile-actions')).toBeNull();
  await act(async()=>preview.querySelector<HTMLButtonElement>('[aria-label="关闭图片预览"]')!.click());expect(document.querySelector('.image-lightbox')).toBeNull();
});

test('tile image editing stays outside the preview button and absent actions keep upload tiles compact',async()=>{
  const image:Attachment={id:'image-edit',name:'产品图.png',kind:'image',mime:'image/png',bytes:100},edit=vi.fn();
  await act(async()=>root.render(<AttachmentCard owner="owner" attachment={image} variant="tile" onEdit={edit}/>));
  expect(host.querySelector('.attachment-card-tile.has-actions')).not.toBeNull();
  const action=host.querySelector<HTMLButtonElement>('[aria-label="编辑 产品图.png"]')!;
  expect(action.closest('.attachment-tile-actions')).not.toBeNull();expect(openTile().querySelector('button')).toBeNull();
  await act(async()=>action.click());expect(edit).toHaveBeenCalledOnce();expect(document.querySelector('.image-lightbox')).toBeNull();expect(details()).toBeNull();
  await act(async()=>root.render(<AttachmentCard owner="owner" attachment={image} variant="tile"/>));
  expect(host.querySelector('.attachment-tile-actions')).toBeNull();expect(host.querySelector('.has-actions')).toBeNull();
});

const deferred=<T,>()=>{let resolve!:(value:T)=>void,reject!:(error:Error)=>void;const promise=new Promise<T>((done,fail)=>{resolve=done;reject=fail;});return{promise,resolve,reject};};
const detailButton=(label:string)=>[...details()!.querySelectorAll<HTMLButtonElement>('button')].find(button=>button.textContent===label)!;

test.each(['resolve','reject'] as const)('a %s retry receipt after closing and removing the card cannot restore its reference',async outcome=>{
  const pending=deferred<Partial<Attachment>>(),update=vi.fn();
  vi.mocked(documentStatus).mockResolvedValue({parse_status:'partial'});vi.mocked(retryDocument).mockReturnValue(pending.promise);
  await act(async()=>root.render(<AttachmentCard owner="owner" attachment={file} variant="tile" onStatus={update}/>));
  await act(async()=>openTile().click());await act(async()=>detailButton('重试解析').click());
  expect(detailButton('正在重试…').disabled).toBe(true);
  await act(async()=>details()!.querySelector<HTMLButtonElement>('[aria-label="关闭附件详情"]')!.click());
  await act(async()=>root.render(null));update.mockClear();vi.mocked(documentStatus).mockClear();
  await act(async()=>{if(outcome==='resolve')pending.resolve({parse_status:'queued'});else pending.reject(new Error('旧附件重试失败'));});
  expect(update).not.toHaveBeenCalled();expect(documentStatus).not.toHaveBeenCalled();expect(host.querySelector('.attachment-card')).toBeNull();expect(details()).toBeNull();
  expect(retryDocument).toHaveBeenCalledExactlyOnceWith('owner','doc');
});

test.each([
  {owner:'other-owner',id:'doc',outcome:'resolve'},
  {owner:'owner',id:'next-doc',outcome:'resolve'},
  {owner:'other-owner',id:'doc',outcome:'reject'},
  {owner:'owner',id:'next-doc',outcome:'reject'},
] as const)('changing to $owner/$id ignores old retry $outcome without clearing a new pending retry',async scope=>{
  const old=deferred<Partial<Attachment>>(),next=deferred<Partial<Attachment>>(),oldUpdate=vi.fn(),nextUpdate=vi.fn();
  vi.mocked(documentStatus).mockResolvedValueOnce({parse_status:'partial'}).mockResolvedValue({parse_status:'failed',parse_error:'新资料待重试'});
  vi.mocked(retryDocument).mockReturnValueOnce(old.promise).mockReturnValueOnce(next.promise);
  await act(async()=>root.render(<AttachmentCard owner="owner" attachment={file} variant="tile" onStatus={oldUpdate}/>));
  await act(async()=>openTile().click());await act(async()=>detailButton('重试解析').click());
  const replacement={...file,id:scope.id,name:'新资料.pdf'};
  await act(async()=>root.render(<AttachmentCard owner={scope.owner} attachment={replacement} variant="tile" onStatus={nextUpdate}/>));
  expect(details()).toBeNull();await act(async()=>openTile().click());
  expect(detailButton('重试解析').disabled).toBe(false);
  await act(async()=>detailButton('重试解析').click());oldUpdate.mockClear();nextUpdate.mockClear();
  await act(async()=>{if(scope.outcome==='resolve')old.resolve({parse_status:'queued'});else old.reject(new Error('旧资料迟到错误'));});
  expect(oldUpdate).not.toHaveBeenCalled();expect(nextUpdate).not.toHaveBeenCalled();
  expect(detailButton('正在重试…').disabled).toBe(true);expect(details()!.textContent).toContain('新资料.pdf');expect(details()!.textContent).toContain('新资料待重试');expect(details()!.textContent).not.toContain('旧资料迟到错误');
  expect(retryDocument).toHaveBeenNthCalledWith(1,'owner','doc');expect(retryDocument).toHaveBeenNthCalledWith(2,scope.owner,scope.id);
  vi.mocked(documentStatus).mockResolvedValue({parse_status:'ready',chunks:45});await act(async()=>next.resolve({parse_status:'ready',chunks:45}));
  expect(details()!.textContent).toContain('可使用');expect(details()!.textContent).not.toContain('正在重试');
  expect(nextUpdate).toHaveBeenLastCalledWith(expect.objectContaining({id:scope.id,name:'新资料.pdf',parse_status:'ready'}));
});

test('a download receipt after removal cannot create a blob URL or trigger an automatic download',async()=>{
  const pending=deferred<Blob>();vi.mocked(attachmentBlob).mockReturnValue(pending.promise);
  await act(async()=>root.render(<AttachmentCard owner="owner" attachment={file} variant="tile"/>));
  await act(async()=>openTile().click());await act(async()=>detailButton('下载原文件').click());
  expect(detailButton('正在下载…').disabled).toBe(true);expect(attachmentBlob).toHaveBeenCalledExactlyOnceWith('owner',file);
  await act(async()=>root.render(null));await act(async()=>pending.resolve(new Blob(['late-original'])));
  expect(URL.createObjectURL).not.toHaveBeenCalled();expect(HTMLAnchorElement.prototype.click).not.toHaveBeenCalled();expect(details()).toBeNull();
});

test('a stale download rejection cannot alter the new file or clear its pending download state',async()=>{
  const old=deferred<Blob>(),next=deferred<Blob>();vi.mocked(attachmentBlob).mockReturnValueOnce(old.promise).mockReturnValueOnce(next.promise);
  await act(async()=>root.render(<AttachmentCard owner="owner" attachment={file} variant="tile"/>));
  await act(async()=>openTile().click());await act(async()=>detailButton('下载原文件').click());
  const replacement={...file,id:'next-doc',name:'新原件.pdf'};
  await act(async()=>root.render(<AttachmentCard owner="other-owner" attachment={replacement} variant="tile"/>));
  await act(async()=>openTile().click());expect(detailButton('下载原文件').disabled).toBe(false);
  await act(async()=>detailButton('下载原文件').click());await act(async()=>old.reject(new Error('旧原件迟到失败')));
  expect(detailButton('正在下载…').disabled).toBe(true);expect(details()!.textContent).not.toContain('旧原件迟到失败');expect(URL.createObjectURL).not.toHaveBeenCalled();expect(HTMLAnchorElement.prototype.click).not.toHaveBeenCalled();
  expect(attachmentBlob).toHaveBeenNthCalledWith(2,'other-owner',replacement);
  await act(async()=>next.resolve(new Blob(['current-original'])));
  expect(URL.createObjectURL).toHaveBeenCalledOnce();expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledOnce();expect(detailButton('下载原文件').disabled).toBe(false);
});
