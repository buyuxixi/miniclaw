// @vitest-environment jsdom
import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {test,expect,vi,beforeEach,afterEach} from 'vitest';
import {SettingsDialog} from './SettingsDialog';
import {SkillPicker} from './SkillPicker';
import {readApi,writeApi} from './management-api';
import type {ChatController} from './chat-controller';
import type {ChatState} from './types';
vi.mock('./management-api',()=>({readApi:vi.fn(),writeApi:vi.fn()}));
let host:HTMLDivElement;let root:ReturnType<typeof createRoot>;
const skills=[{name:'codex',description:'code',enabled:false},{name:'spoken-script',description:'speech',enabled:true,binding:{version:1,required_tools:[],content_hash:'ok',current:true}},{name:'product-video-plan',description:'video',enabled:true,binding:{version:1,required_tools:[],content_hash:'ok',current:true}}];
const chat={sessionId:'live',storedId:'owner',info:{tools:{}},running:false,busy:false} as ChatState;
const controller={connection:'open',client:{request:vi.fn().mockResolvedValue({skills:[]})}} as unknown as ChatController;
function button(text:string){return [...host.querySelectorAll('button')].find(b=>b.textContent?.includes(text))!;}
beforeEach(()=>{vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.mocked(readApi).mockResolvedValue(skills);vi.mocked(writeApi).mockResolvedValue({});Object.defineProperty(HTMLDialogElement.prototype,'showModal',{configurable:true,value:function(){this.setAttribute('open','')}});Object.defineProperty(HTMLDialogElement.prototype,'close',{configurable:true,value:function(){this.removeAttribute('open')}});host=document.createElement('div');document.body.append(host);root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();vi.clearAllMocks();});
test('settings default to promotional capabilities and retain archived skills in a separate recoverable group',async()=>{
 await act(async()=>root.render(<SettingsDialog chat={chat} controller={controller} initialTab="skills" onClose={()=>{}}/>));
 expect(host.querySelector('.skill-list')?.textContent).toContain('口播优化');expect(host.querySelector('.skill-list')?.textContent).not.toContain('Codex');
 await act(async()=>button('其他能力').click());expect(host.querySelector('.skill-list')?.textContent).toContain('Codex');
 await act(async()=>host.querySelector<HTMLButtonElement>('[aria-label="启用技能 codex"]')!.click());expect(writeApi).toHaveBeenCalledWith('/api/skills/toggle','PUT',{name:'codex',enabled:true});
});
test('failed skill configuration retains the previous state and shows a local error',async()=>{
 vi.mocked(writeApi).mockRejectedValueOnce(Error('保存失败'));
 await act(async()=>root.render(<SettingsDialog chat={chat} controller={controller} initialTab="skills" onClose={()=>{}}/>));
 await act(async()=>host.querySelector<HTMLButtonElement>('[aria-label="启用技能 spoken-script"]')!.click());
 expect(host.querySelector('[role="alert"]')?.textContent).toContain('保存失败');expect(host.querySelector('[aria-label="启用技能 spoken-script"]')?.getAttribute('aria-checked')).toBe('true');
});
test('picker does not offer unrelated installed skills as normal promotional choices',async()=>{
 await act(async()=>root.render(<SkillPicker chat={chat} controller={controller} onClose={()=>{}} onChoose={()=>{}} onManage={()=>{}}/>));
 await act(async()=>button('查看配置').click());expect(host.querySelector('.picker-list')?.textContent).toContain('口播优化');expect(host.querySelector('.picker-list')?.textContent).not.toContain('Codex');
 await act(async()=>button('其他能力').click());expect(host.querySelector('.picker-list')?.textContent).toContain('Codex');
});
test('picker exits a failed catalog check and retries in place without losing search',async()=>{
 const request=vi.mocked(controller.client.request);
 request.mockRejectedValueOnce(Error('RPC timeout'));
 await act(async()=>root.render(<SkillPicker chat={chat} controller={controller} onClose={()=>{}} onChoose={()=>{}} onManage={()=>{}}/>));
 expect(host.querySelector('[role="alert"]')?.textContent).toContain('检查连接后重试');
 expect(host.querySelector('.picker-list')?.getAttribute('aria-busy')).toBe('false');
 expect(request).toHaveBeenCalledWith('commands.catalog',{session_id:'live'},15000,expect.any(AbortSignal));
 await act(async()=>button('重试').click());
 expect(host.querySelector('[role="alert"]')).toBeNull();
 expect(request).toHaveBeenCalledTimes(2);
 expect(document.activeElement?.getAttribute('aria-label')).toBe('搜索技能');
});
