// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, test, vi } from 'vitest';
import { CropReview, cropDocument, type CropCandidate } from './CropReview';
import { ImageDetailReview } from './ImageDetailReview';
import { ImageComparison } from './ImageJobCard';
import type { Attachment } from './attachments';
vi.mock('./image-api', async()=>({...await vi.importActual('./image-api'),useImageBlob: (_owner: string, image?: Attachment)=>({url:image ? `blob:${image.id}` : '',error:''})}));

async function mount(element: React.ReactNode) {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('ResizeObserver',class { observe() {} disconnect() {} });
  const host = document.createElement('div'); document.body.append(host); const root=createRoot(host);
  await act(async()=>root.render(element));
  return {host,root,close:async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();}};
}
function candidate(): CropCandidate {
  const original={schema_version:1 as const,width:100,height:300,background:'#fff',layers:[]};
  return {project:'fixture',revision:1,original,document:cropDocument(original,50,200),before:new Blob(),after:new Blob(),top:50,bottom:200};
}

test('drag and keyboard boundaries clamp without applying an outdated preview; blank precision input cannot preview',async()=>{
  Object.defineProperty(URL,'createObjectURL',{configurable:true,value:vi.fn(()=> 'blob:crop')});
  Object.defineProperty(URL,'revokeObjectURL',{configurable:true,value:vi.fn()});
  const preview=vi.fn(),apply=vi.fn(),c=candidate();
  const view=await mount(<CropReview candidate={c} busy={false} onPreview={preview} onApply={apply} onClose={()=>{}} />);
  try {
    const svg=view.host.querySelector('svg')!, top=view.host.querySelector<SVGGElement>('[aria-label="保留上沿"]')!;
    svg.getBoundingClientRect=()=>({top:10,height:300} as DOMRect);
    top.setPointerCapture=vi.fn();
    await act(async()=>{top.dispatchEvent(new MouseEvent('pointerdown',{bubbles:true}));svg.dispatchEvent(new MouseEvent('pointermove',{bubbles:true,clientY:309}));svg.dispatchEvent(new MouseEvent('pointerup',{bubbles:true}));});
    expect(view.host.querySelector<HTMLInputElement>('[aria-label="裁剪上边界"]')!.value).toBe('184');
    const button=(text:string)=>Array.from(view.host.querySelectorAll('button')).find(b=>b.textContent===text)!;
    expect(button('确认范围，应用裁剪').disabled).toBe(true); expect(apply).not.toHaveBeenCalled();
    await act(async()=>top.dispatchEvent(new KeyboardEvent('keydown',{bubbles:true,key:'Home'})));
    expect(top.getAttribute('aria-valuenow')).toBe('0');
    await act(async()=>top.dispatchEvent(new KeyboardEvent('keydown',{bubbles:true,key:'ArrowDown',shiftKey:true})));
    await act(async()=>button('更新裁剪预览').click());expect(preview).toHaveBeenCalledWith(10,200);
    const input=view.host.querySelector<HTMLInputElement>('[aria-label="裁剪上边界"]')!;
    await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,'');input.dispatchEvent(new Event('input',{bubbles:true}));});
    expect(button('更新裁剪预览').disabled).toBe(true); expect(button('确认范围，应用裁剪').disabled).toBe(true);
    expect(c.original.height).toBe(300);
  } finally { await view.close(); }
});

test('detail panes share zoom and normalized scroll without changing the image; reset and close are available',async()=>{
  const close=vi.fn(),view=await mount(<ImageDetailReview before="blob:source" after="blob:result" onClose={close} />);
  try {
    const zoom=view.host.querySelector<HTMLButtonElement>('[aria-label="放大对照"]')!;
    await act(async()=>zoom.click());
    expect(Array.from(view.host.querySelectorAll('img')).map(i=>i.style.width)).toEqual(['150%','150%']);
    const panes=Array.from(view.host.querySelectorAll<HTMLDivElement>('.image-detail-pane'));
    for(const [i,pane] of panes.entries()) Object.defineProperties(pane,{scrollHeight:{value:i ? 1200 : 600},clientHeight:{value:200},scrollWidth:{value:i ? 400 : 300},clientWidth:{value:100}});
    panes[0].scrollTop=200;panes[0].scrollLeft=100;
    await act(async()=>panes[0].dispatchEvent(new Event('scroll',{bubbles:true})));
    expect(panes[1].scrollTop).toBe(500);expect(panes[1].scrollLeft).toBe(150);
    const button=(name:string)=>Array.from(view.host.querySelectorAll('button')).find(b=>b.textContent===name)!;
    await act(async()=>button('恢复全图').click());
    expect(panes[1].scrollTop).toBe(0);expect(view.host.querySelector('img')!.getAttribute('src')).toBe('blob:source');
    await act(async()=>button('关闭细节查看').click());expect(close).toHaveBeenCalledOnce();
  } finally { await view.close(); }
});

test('Escape cannot discard a crop while its preview or application is pending',async()=>{
  const close=vi.fn(), view=await mount(<CropReview candidate={candidate()} busy={true} onPreview={()=>{}} onApply={()=>{}} onClose={close} />);
  try {
    const event=new Event('cancel',{bubbles:false,cancelable:true});
    await act(async()=>view.host.querySelector('dialog')!.dispatchEvent(event));
    expect(event.defaultPrevented).toBe(true); expect(close).not.toHaveBeenCalled();
    expect(view.host.querySelector('[aria-label="保留上沿"]')!.getAttribute('aria-disabled')).toBe('true');
  } finally { await view.close(); }
});

test('changing the comparison owner removes the old detail dialog',async()=>{
  const source={id:'source',name:'原图.png'} as Attachment, output={id:'result',name:'候选.png'} as Attachment;
  const view=await mount(<ImageComparison owner="one" source={source} output={output} />);
  try {
    await act(async()=>Array.from(view.host.querySelectorAll('button')).find(b=>b.textContent==='放大对照商品细节')!.click());
    expect(view.host.querySelector('dialog')).not.toBeNull();
    await act(async()=>view.root.render(<ImageComparison owner="two" source={source} output={output} />));
    expect(view.host.querySelector('dialog')).toBeNull();
  } finally { await view.close(); }
});
