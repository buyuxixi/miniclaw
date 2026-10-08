// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, test, vi } from 'vitest';
import { CreatorAdoption } from './CreatorAdoption';
import { getCreator, saveCreator, type CreatorProject, type CreatorReturn } from './creator-api';
vi.mock('./creator-api',()=>({creatorBase:'/creator',getCreator:vi.fn(),saveCreator:vi.fn()}));
const incoming:CreatorReturn={project:'p',owner:'owner',revision:3,kind:'script',text:'保留的候选正文',item:'turn',nonce:1};
const project={id:'p',name:'作品',chat_id:'owner',revision:3} as CreatorProject;
test('adoption rechecks the revision and preserves the candidate when another edit has occurred',async()=>{
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
  vi.mocked(getCreator).mockResolvedValueOnce(project).mockResolvedValueOnce({...project,revision:4});
  vi.mocked(saveCreator).mockClear();
  const done=vi.fn(),host=document.createElement('div');document.body.append(host);const root=createRoot(host);
  try{
    await act(async()=>root.render(<CreatorAdoption incoming={incoming} owner="owner" onClose={()=>{}} onDone={done}/>));
    await act(async()=>Array.from(host.querySelectorAll('button')).find(b=>b.textContent==='确认采用')!.click());
    expect(saveCreator).not.toHaveBeenCalled();expect(done).not.toHaveBeenCalled();
    expect(host.querySelector('[role=alert]')?.textContent).toContain('旧候选不能覆盖');
    expect(host.querySelector('textarea')?.value).toBe('保留的候选正文');
  }finally{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();}
});
