// @vitest-environment jsdom
import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,test,vi} from 'vitest';
import {StudioProjectDialog} from './StudioProjectDialog';
import {writeApi} from './management-api';
vi.mock('./management-api',()=>({writeApi:vi.fn()}));
let host:HTMLDivElement,root:Root;
beforeEach(()=>{
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
  Object.defineProperty(HTMLDialogElement.prototype,'showModal',{configurable:true,value:vi.fn()});
  Object.defineProperty(HTMLDialogElement.prototype,'close',{configurable:true,value:vi.fn()});
  vi.mocked(writeApi).mockReset().mockRejectedValue(new Error('fixture save failed'));
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();});
async function fillName(){
  const input=host.querySelector<HTMLInputElement>('#project-name')!;
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,'产品短片');input.dispatchEvent(new Event('input',{bubbles:true}));});
}
test('bringing a plan to the canvas includes uploaded materials by default and preserves choice on failure',async()=>{
  await act(async()=>root.render(<StudioProjectDialog owner="owner" sessionId="live" message="row-17" onClose={()=>{}}/>));
  const option=host.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
  expect(option.checked).toBe(true);await fillName();
  await act(async()=>host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(writeApi).toHaveBeenCalledWith('/api/workspaces','POST',expect.objectContaining({name:'产品短片',include_images:true,session_id:'live',message:17}));
  expect(option.checked).toBe(true);expect(host.querySelector<HTMLInputElement>('#project-name')?.value).toBe('产品短片');
  expect(host.querySelector('[role="alert"]')?.textContent).toContain('fixture save failed');
});
test('the user can choose to bring only the plan',async()=>{
  await act(async()=>root.render(<StudioProjectDialog owner="owner" sessionId="live" message="row-17" onClose={()=>{}}/>));
  await act(async()=>host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());await fillName();
  await act(async()=>host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(writeApi).toHaveBeenCalledWith('/api/workspaces','POST',expect.objectContaining({include_images:false}));
});
