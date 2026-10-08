// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { ProjectVideo, scriptVideoIssue } from './ProjectVideo';
import { saveCreator, type CreatorProject } from './creator-api';
import { readApi, writeApi } from './management-api';
vi.mock('./management-api',()=>({readApi:vi.fn(),writeApi:vi.fn()}));
vi.mock('./creator-api',async()=>({...await vi.importActual('./creator-api'),saveCreator:vi.fn()}));
let host:HTMLDivElement, root:Root;
const p:CreatorProject={id:'product',name:'茶壶',revision:8,facts:'深绿釉',script:'一把茶壶。\n慢慢看。',caption:'',provenance:'',mode:'portrait',method:'storyboard',assets:{cover:{id:'image',name:'cover.png',bytes:1}},outputs:[],packages:[],jobs:[],steps:{},flow:{brief:'ready',cover:'adopted',script:'adopted'}};
const cap={video:true,font:true,speech:{configured:true},storyboard_min_images:1};
const navigate=vi.fn(),suggest=vi.fn();
const render=(project=p)=>act(async()=>root.render(<ProjectVideo project={project} busy={false} onRun={async fn=>fn()} onSuggest={suggest} onNavigate={navigate}/>));
const button=(label:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent===label)!;
beforeEach(()=>{vi.resetAllMocks();vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.mocked(readApi).mockResolvedValue(cap);host=document.createElement('div');document.body.append(host);root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();});
test('one adopted image plus an adopted script is ready without any SRT/JSON or automatic billing',async()=>{
  await render();
  expect(button('生成配音字幕短片').disabled).toBe(false);
  expect(host.textContent).toContain('补充镜头图片（可选）');
  expect(host.querySelector('.video-input-summary')?.textContent).toContain('采用口播');
  expect(host.querySelector('.video-input-summary')?.textContent).toContain('竖版 9:16');
  expect(writeApi).not.toHaveBeenCalled();expect(saveCreator).not.toHaveBeenCalled();
  await act(async()=>button('生成配音字幕短片').click());
  expect(writeApi).toHaveBeenCalledWith('/api/miniclaw/creator/projects/product/render','POST',{revision:8});
});
test('missing or stale prerequisites provide navigation and cannot render',async()=>{
  await render({...p,flow:{...p.flow!,cover:'review',script:'review'}});
  expect(button('生成配音字幕短片').disabled).toBe(true);
  await act(async()=>button('去修图采用图片').click());expect(navigate).toHaveBeenCalledWith('cover');
  await act(async()=>button('去口播核对主稿').click());expect(navigate).toHaveBeenCalledWith('script');
  expect(writeApi).not.toHaveBeenCalled();
});
test('older services require their extra images',async()=>{
  vi.mocked(readApi).mockResolvedValue({...cap,storyboard_min_images:3});await render();
  expect(button('生成配音字幕短片').disabled).toBe(true);expect(host.textContent).toContain('还需准备：特写图、场景图');
});
test('missing voice configuration and nonreadable punctuation cannot start billing',async()=>{
  expect(scriptVideoIssue('。！？')).toContain('可朗读的句子');
  vi.mocked(readApi).mockResolvedValue({...cap,speech:{configured:false}});await render();
  expect(button('生成配音字幕短片').disabled).toBe(true);expect(host.textContent).toContain('后端配置百炼配音凭据');
  expect(writeApi).not.toHaveBeenCalled();
});
test('professional projects are not silently migrated; only choosing a basic path changes method',async()=>{
  await render({...p,method:'plan'});expect(saveCreator).not.toHaveBeenCalled();
  expect(host.querySelector<HTMLDetailsElement>('.video-advanced')!.open).toBe(true);
  await act(async()=>button('图片口播采用图 + 主稿，自动配音和字幕').click());
  expect(saveCreator).toHaveBeenCalledWith(expect.objectContaining({method:'plan'}),{method:'storyboard'});
});
test('long sentences can be sent to chat for refinement without overwriting the adopted script',async()=>{
  await render({...p,script:'茶'.repeat(37)+'。'});expect(button('生成配音字幕短片').disabled).toBe(true);
  expect(host.textContent).toContain('部分句子超过 36 字');
  await act(async()=>button('让 Chat 整理短句').click());expect(suggest).toHaveBeenCalledWith(expect.stringContaining('候选稿'),'spoken-script');expect(writeApi).not.toHaveBeenCalled();expect(saveCreator).not.toHaveBeenCalled();
});
