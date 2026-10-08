// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, test, vi } from 'vitest';
import CreatorHome from './CreatorHome';
import { readApi } from './management-api';
import { getCreator } from './creator-api';
vi.mock('./management-api',()=>({readApi:vi.fn(),writeApi:vi.fn()}));
vi.mock('./creator-api',async()=>({...await vi.importActual('./creator-api'),getCreator:vi.fn()}));

test('a project with an existing video opens that result even when older stages are incomplete',async()=>{
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
  const project={id:'complete',name:'已有成片的作品',updated:1,progress:{brief:true,cover:false,script:false,video:true}};
  vi.mocked(readApi).mockResolvedValue([project]);
  vi.mocked(getCreator).mockResolvedValue({...project,revision:3} as any);
  const start=vi.fn().mockResolvedValue(undefined),host=document.createElement('div'),root=createRoot(host);document.body.append(host);
  try {
    await act(async()=>root.render(<CreatorHome active onChat={()=>{}} onDetails={()=>{}} onStart={start}/>));
    expect(host.querySelector('.home-stages')?.textContent).toContain('修图待完善');
    expect(host.querySelector('.home-stages')?.textContent).toContain('视频已完成');
    await act(async()=>host.querySelector<HTMLButtonElement>('.home-continue')!.click());
    expect(start).toHaveBeenCalledWith(expect.objectContaining({id:'complete'}),'video');
    expect(host.querySelector('.home-continue')?.textContent).toContain('查看成片');
  } finally {await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();}
});
