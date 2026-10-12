// @vitest-environment jsdom
import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {expect,test,vi} from 'vitest';
import StudioHome from './StudioHome';
import {readApi,writeApi} from './management-api';
vi.mock('./management-api',()=>({readApi:vi.fn(),writeApi:vi.fn()}));
const projects=Array.from({length:14},(_,i)=>({id:'project-'+i,name:i===13?'最后的项目':'项目 '+i,chat_id:'chat '+i,cover:'',plan:'项目内容',notes:1,pictures:2,shots:1,adopted:0,updated_at:1}));
const projectPage=async (path:string)=>{const query=new URL(path,'http://local').searchParams;const filtered=projects.filter(p=>p.name.includes(query.get('q')||''));const page=Math.min(Number(query.get('page')||1),Math.max(1,Math.ceil(filtered.length/6)));return {items:filtered.slice((page-1)*6,page*6),total:filtered.length,page,page_size:6};};
test('projects paginate, preserve page on reload, reset on search and keep discussion links',async()=>{
 vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);history.replaceState(null,'','/?projects=1');vi.mocked(readApi).mockImplementation(projectPage as typeof readApi);
 const host=document.createElement('div');document.body.append(host);let root=createRoot(host);const onChat=vi.fn().mockResolvedValue(undefined);
 try{
  await act(async()=>root.render(<StudioHome active onChat={onChat}/>));expect(host.querySelectorAll('article')).toHaveLength(6);expect(host.querySelector('[aria-label="上一页"]')?.hasAttribute('disabled')).toBe(true);
  await act(async()=>host.querySelector<HTMLButtonElement>('[aria-label="下一页"]')!.click());expect(host.querySelector('h2')?.textContent).toBe('项目 6');expect(location.search).toContain('page=2');
  await act(async()=>root.unmount());root=createRoot(host);await act(async()=>root.render(<StudioHome active onChat={onChat}/>));expect(host.querySelector('h2')?.textContent).toBe('项目 6');
  const input=host.querySelector<HTMLInputElement>('input')!;await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,'最后');input.dispatchEvent(new Event('input',{bubbles:true}));});
  expect(host.querySelectorAll('article')).toHaveLength(1);expect(host.querySelector('h2')?.textContent).toBe('最后的项目');expect(location.search).not.toContain('page=');expect(host.querySelector('.project-discuss')?.getAttribute('href')).toBe('/c/chat%2013?workspace=project-13');
  await act(async()=>host.querySelector<HTMLButtonElement>('.home-assistant')!.click());expect(onChat).toHaveBeenCalledOnce();
 }finally{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();history.replaceState(null,'','/');}
});
test('invalid page clamps and failed refresh retains projects and current page',async()=>{
 vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);history.replaceState(null,'','/?projects=1&page=99');vi.mocked(readApi).mockImplementationOnce(projectPage as typeof readApi).mockRejectedValueOnce(Error('读取失败'));
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 try{await act(async()=>root.render(<StudioHome active onChat={async()=>{}}/>));expect(host.querySelectorAll('article')).toHaveLength(2);expect(location.search).toContain('page=3');await act(async()=>host.querySelector<HTMLButtonElement>('.home-refresh')!.click());expect(host.querySelector('[role="alert"]')?.textContent).toContain('读取失败');expect(host.querySelectorAll('article')).toHaveLength(2);}
 finally{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();history.replaceState(null,'','/');}
});

test('archiving collects pictures into the library and the library view lists them',async()=>{
 vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);history.replaceState(null,'','/');
 const item={id:'a'.repeat(64),name:'绿泥 主图',kind:'image',url:'/studio/media/objects/'+'a'.repeat(64),created_at:1};
 vi.mocked(readApi).mockImplementation((async (path:string)=>path.startsWith('/api/workspaces/library')?[item]:projectPage(path)) as typeof readApi);
 vi.mocked(writeApi).mockResolvedValue({archived:true,collected:3});
 const host=document.createElement('div'),root=createRoot(host);document.body.append(host);
 try{
  await act(async()=>root.render(<StudioHome active onChat={async()=>{}}/>));
  await act(async()=>host.querySelector<HTMLButtonElement>('.project-archive')!.click());
  expect(writeApi).toHaveBeenCalledWith('/api/workspaces/project-0/archive','POST',{archived:true,collect:true});
  expect(host.querySelector('.home-notice')?.textContent).toContain('3 张素材收进素材库');
  await act(async()=>[...host.querySelectorAll<HTMLButtonElement>('.studio-home-views button')].find(b=>b.textContent==='素材库')!.click());
  expect(location.search).toContain('view=library');
  expect(host.querySelector('.studio-library img')?.getAttribute('alt')).toBe('绿泥 主图');
  expect(host.querySelectorAll('article')).toHaveLength(0);
 }finally{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();history.replaceState(null,'','/');}
});

test('returning to Chat keeps the existing conversation instead of creating a new one',async()=>{
 vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.mocked(readApi).mockImplementation(projectPage as typeof readApi);
 const host=document.createElement('div'),root=createRoot(host);const onBack=vi.fn(),onChat=vi.fn();document.body.append(host);
 try{await act(async()=>root.render(<StudioHome active onChat={onChat} onBack={onBack}/>));await act(async()=>host.querySelector<HTMLButtonElement>('.home-assistant')!.click());expect(onBack).toHaveBeenCalledOnce();expect(onChat).not.toHaveBeenCalled();}
 finally{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();history.replaceState(null,'','/');}
});
