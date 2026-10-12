import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { uploadFile, type Attachment } from './attachments';
const partSize=4*1024*1024;
const document:Attachment={id:'document-1',name:'资料.pdf',kind:'document',mime:'application/pdf',bytes:partSize+8,parse_status:'queued'};
const json=(value:unknown,status=200)=>({ok:status<400,status,json:async()=>value});
beforeEach(()=>{
  const storage=new Map<string,string>();
  vi.stubGlobal('window',{});vi.stubGlobal('localStorage',{getItem:(k:string)=>storage.get(k)??null,setItem:(k:string,v:string)=>storage.set(k,v)});
});
afterEach(()=>vi.unstubAllGlobals());
test('uploads bytes in bounded parts with verified hashes and reports real completed bytes',async()=>{
  const file=new File([new Uint8Array(partSize+8)],'资料.pdf',{lastModified:123});
  const calls:{path:string;init:RequestInit}[]=[];
  vi.stubGlobal('fetch',vi.fn(async(path:string,init:RequestInit)=>{calls.push({path,init});return json(path.endsWith('/complete')?document:path.includes('/parts/')?{ok:true}:{id:'upload-1',name:file.name,size:file.size,part_size:partSize,state:'uploading',parts:[]});}));
  const progress=vi.fn();expect(await uploadFile('owner',file,{onProgress:progress})).toEqual(document);
  const parts=calls.filter(c=>c.path.includes('/parts/'));
  expect(parts.map(c=>(c.init.body as Blob).size)).toEqual([partSize,8]);
  expect(parts[0].path).toContain('/parts/0?owner=owner');
  expect((parts[0].init.headers as Record<string,string>)['X-Part-SHA256']).toMatch(/^[0-9a-f]{64}$/);
  expect(progress).toHaveBeenLastCalledWith(file.size,file.size);
  expect(calls[0].init.body).not.toContain('data');
});
test('reselecting the original file verifies and skips successful parts after a network failure',async()=>{
  const file=new File([new Uint8Array(partSize+8)],'资料.pdf',{lastModified:123});let firstHash='';let failed=false;
  const fetcher=vi.fn(async(path:string,init:RequestInit)=>{
    if(init.method==='GET')return json({id:'upload-1',name:file.name,size:file.size,part_size:partSize,state:'uploading',parts:[{part_no:0,size:partSize,sha256:firstHash}]});
    if(path.includes('/parts/0')){firstHash=(init.headers as Record<string,string>)['X-Part-SHA256'];return json({ok:true});}
    if(path.includes('/parts/1')&&!failed){failed=true;throw new Error('网络中断');}
    return json(path.endsWith('/complete')?document:path.includes('/parts/')?{ok:true}:{id:'upload-1',name:file.name,size:file.size,part_size:partSize,state:'uploading',parts:[]});
  });vi.stubGlobal('fetch',fetcher);
  await expect(uploadFile('owner',file)).rejects.toThrow('网络中断');
  expect(await uploadFile('owner',file)).toEqual(document);
  expect(fetcher.mock.calls.filter(([path])=>path.includes('/parts/0'))).toHaveLength(1);
  expect(fetcher.mock.calls.filter(([path])=>path.includes('/parts/1'))).toHaveLength(2);
});
test('same-name same-size replacement never combines earlier parts with different bytes',async()=>{
  const file=new File(['old'], '资料.pdf',{lastModified:123});const replacement=new File(['new'],'资料.pdf',{lastModified:123});let oldHash='';let initNumber=0;let fail=true;
  const fetcher=vi.fn(async(path:string,init:RequestInit)=>{
    if(init.method==='GET')return json({id:'upload-old',name:file.name,size:3,part_size:partSize,state:'uploading',parts:[{part_no:0,size:3,sha256:oldHash}]});
    if(path.includes('/parts/')){oldHash=(init.headers as Record<string,string>)['X-Part-SHA256'];return json({ok:true});}
    if(path.endsWith('/complete')){if(fail){fail=false;throw new Error('回执中断');}return json({...document,bytes:3});}
    initNumber++;return json({id:initNumber===1?'upload-old':'upload-new',name:file.name,size:3,part_size:partSize,state:'uploading',parts:[]});
  });vi.stubGlobal('fetch',fetcher);
  await expect(uploadFile('owner',file)).rejects.toThrow('回执中断');await uploadFile('owner',replacement);
  expect(initNumber).toBe(2);
  expect(fetcher.mock.calls.some(([path])=>path.includes('upload-new/parts/0'))).toBe(true);
});
test('rejects unsupported and oversized inputs before a network request and accepts the 50 MiB boundary',async()=>{
  const fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);
  await expect(uploadFile('owner',new File(['x'],'old.doc'))).rejects.toThrow('DOCX');
  const big=new File(['x'],'large.xlsx');Object.defineProperty(big,'size',{value:50*1024*1024+1});
  await expect(uploadFile('owner',big)).rejects.toThrow('50 MiB');
  const image=new File(['x'],'large.png');Object.defineProperty(image,'size',{value:5*1024*1024+1});
  await expect(uploadFile('owner',image)).rejects.toThrow('图片最大5');expect(fetcher).not.toHaveBeenCalled();
});
