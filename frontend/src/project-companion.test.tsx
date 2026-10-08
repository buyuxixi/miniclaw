// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, test, vi } from 'vitest';
import { ProjectCompanion } from './ProjectCompanion';
import { getCreator, creatorBlob } from './creator-api';
import { loadProject, exportBlob } from './canvas-api';
vi.mock('./creator-api',()=>({getCreator:vi.fn(),creatorBlob:vi.fn()}));
vi.mock('./canvas-api',async()=>({...await vi.importActual('./canvas-api'),loadProject:vi.fn(),exportBlob:vi.fn()}));
vi.mock('./management-api',()=>({readApi:vi.fn(async()=>[]),writeApi:vi.fn()}));
const target={id:'product',name:'商品',revision:11,owner:'owner',node:'cover' as const,canvas:'working',image:'adopted'};
const project={id:'product',name:'商品',revision:11,chat_id:'owner',assets:{source:{id:'raw',name:'original.png',bytes:1},cover:{id:'adopted',name:'cover.png',bytes:1,source:{kind:'canvas',canvas_project_id:'working'}}}};
const canvas={project:{id:'working',revision:7,cursor:4,chat_id:'owner',archived:false,document:{layers:[{id:'text',kind:'text',visible:true,locked:false},{id:'main',kind:'image',visible:true,locked:false}]}},assets:[],jobs:[]};

test('the result rail binds the main image and follows work revisions without sending a model request',async()=>{
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.useFakeTimers();vi.clearAllMocks();
  vi.stubGlobal('URL',{createObjectURL:vi.fn(()=> 'blob:working'),revokeObjectURL:vi.fn()});
  vi.mocked(getCreator).mockResolvedValue(project as any);vi.mocked(loadProject).mockResolvedValue(canvas as any);vi.mocked(exportBlob).mockResolvedValue(new Blob(['work']));vi.mocked(creatorBlob).mockResolvedValue(new Blob(['adopted']));
  const context=vi.fn(), adopt=vi.fn(), reference=vi.fn();
  const host=document.createElement('div'),root=createRoot(host);document.body.append(host);
  try {
    await act(async()=>root.render(<ProjectCompanion target={target} owner="owner" busy={false} onContext={context} onReference={reference} onSuggest={()=>{}} onEdit={()=>{}} onAdoptImage={adopt}/>));
    expect(context).toHaveBeenLastCalledWith({project_id:'working',revision:7,layer_id:'main',mode:'plan'});
    expect(exportBlob).toHaveBeenCalledWith('working',4);
    expect(host.querySelector('.companion-image')?.getAttribute('alt')).toBe('当前工作图');
    expect(host.querySelector('textarea[aria-label="图片修改目标"]')).toBeNull();
    await act(async()=>Array.from(host.querySelectorAll('button')).find(b=>b.textContent==='原图参考')!.click());
    expect(host.querySelector('.companion-image')?.getAttribute('alt')).toBe('商品原图');
    expect(creatorBlob).toHaveBeenCalledWith('product','raw',expect.any(AbortSignal));
    expect(context).toHaveBeenLastCalledWith({project_id:'working',revision:7,layer_id:'main',mode:'plan'});
    expect(reference).toHaveBeenLastCalledWith({project:'product',file:project.assets.cover});
    await act(async()=>Array.from(host.querySelectorAll('button')).find(b=>b.textContent==='当前工作图')!.click());
    expect(host.querySelector('.companion-image')?.getAttribute('alt')).toBe('当前工作图');
    vi.mocked(loadProject).mockResolvedValue({...canvas,project:{...canvas.project,revision:8,cursor:5}} as any);
    await act(async()=>vi.advanceTimersByTimeAsync(2500));
    expect(context).toHaveBeenLastCalledWith({project_id:'working',revision:8,layer_id:'main',mode:'plan'});
    expect(adopt).not.toHaveBeenCalled();
    adopt.mockRejectedValueOnce(new Error('回传失败，请重试'));
    await act(async()=>Array.from(host.querySelectorAll('button')).find(b=>b.textContent==='采用工作图')!.click());
    await act(async()=>vi.advanceTimersByTimeAsync(2500));
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('回传失败');
  } finally {await act(async()=>root.unmount());host.remove();vi.useRealTimers();vi.unstubAllGlobals();}
});

test('a foreign canvas cannot appear as the product result or become a sending context',async()=>{
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.clearAllMocks();
  vi.mocked(getCreator).mockResolvedValue(project as any);vi.mocked(loadProject).mockResolvedValue({...canvas,project:{...canvas.project,chat_id:'foreign'}} as any);
  const context=vi.fn(),host=document.createElement('div'),root=createRoot(host);document.body.append(host);
  try {
    await act(async()=>root.render(<ProjectCompanion target={target} owner="owner" busy={false} onContext={context} onReference={()=>{}} onSuggest={()=>{}} onEdit={()=>{}} onAdoptImage={async()=>{}}/>));
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('关联已变化');
    expect(context).not.toHaveBeenCalledWith(expect.objectContaining({project_id:'working'}));
    expect(exportBlob).not.toHaveBeenCalled();
  } finally {await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();}
});
