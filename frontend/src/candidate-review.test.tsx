// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, test, vi } from 'vitest';
import { CandidateReview } from './CandidateReview';
import { cropDocument } from './CropReview';
import type { CanvasJob, CanvasDocument } from './canvas-api';

test('candidate adoption requires both recorded review and four current checks; rejection records the reason', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
  const host=document.createElement('div'); document.body.append(host); const root=createRoot(host), onReview=vi.fn();
  const job:CanvasJob={id:'candidate',revision:1,layer_id:'layer',source_id:'source',state:'succeeded',prompt:'精修'};
  const render=(j:CanvasJob)=> <CandidateReview job={j} busy={false} onReview={onReview}>{ready=><button disabled={!ready}>采用</button>}</CandidateReview>;
  try {
    await act(async()=>root.render(render(job)));
    const button=(name:string)=>Array.from(host.querySelectorAll('button')).find(b=>b.textContent===name)!;
    expect(button('采用').disabled).toBe(true);
    await act(async()=>host.querySelectorAll<HTMLInputElement>('input').forEach(input=>input.click()));
    expect(button('采用').disabled).toBe(true);
    await act(async()=>button('核对完成，允许采用').click());
    expect(onReview).toHaveBeenCalledWith('keep',['shape','color','parts','texture'],'');
    await act(async()=>root.render(render({...job,review:{decision:'keep',checks:['shape','color','parts','texture'],reason:'',time:1}})));
    expect(button('采用').disabled).toBe(false);
    await act(async()=>host.querySelector<HTMLInputElement>('input')!.click());
    expect(button('采用').disabled).toBe(true);
    const reason=host.querySelector<HTMLTextAreaElement>('textarea')!;
    await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(reason,'纹理磨平');reason.dispatchEvent(new Event('input',{bubbles:true}));});
    await act(async()=>button('细节有误，保留原图').click());
    expect(onReview).toHaveBeenLastCalledWith('reject',['color','parts','texture'],'纹理磨平');
  } finally { await act(async()=>root.unmount()); host.remove(); vi.unstubAllGlobals(); }
});

test('crop ranges cannot extend outside the source or mutate its layer geometry',()=>{
  const original:CanvasDocument={schema_version:1,width:100,height:300,background:'#ffffff',layers:[]};
  expect(cropDocument(original,50,180).height).toBe(130);
  expect(original.height).toBe(300);
  for(const [top,bottom] of [[-1,200],[0,301],[NaN,200],[2.5,200],[50,51]]) expect(()=>cropDocument(original,top,bottom)).toThrow();
});
