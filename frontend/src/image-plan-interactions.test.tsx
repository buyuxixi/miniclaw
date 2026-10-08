// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { ImagePlanPanel, type ImagePlan } from './ImagePlanPanel';
import { readApi, writeApi } from './management-api';
import { exportBlob, type Project } from './canvas-api';
vi.mock('./management-api', () => ({ readApi:vi.fn(), writeApi:vi.fn() }));
vi.mock('./canvas-api', async () => ({ ...(await vi.importActual('./canvas-api')), exportBlob:vi.fn() }));
let host: HTMLDivElement, root: Root;
const project: Project = { id:'fixture', name:'茶壶', revision:4,cursor:2,updated:1,archived:false,chat_id:'chat', document:{schema_version:1,width:80,height:60,background:'#ffffff',layers:[]} };
const plan: ImagePlan = { id:'plan',project:'fixture',revision:4,input_revision:4,layer_id:'image',goal:'把背景换为暖白',preserve:'壶身与细绳',state:'proposed', steps:[{action:'background',label:'调整底色',params:{color:'#f2efe7'}}] };
const send = vi.fn(), refresh = vi.fn();
function view(p = project, activeJob = false, busy = false) {
  return <ImagePlanPanel key={p.id} project={p} busy={busy} activeJob={activeJob} canPlan hasTarget onSend={send} onRun={async work => work()} onRefresh={refresh} />;
}
function button(text: string) { return [...host.querySelectorAll('button')].find(b => b.textContent === text)!; }
async function click(text: string) { await act(async () => button(text).click()); }
beforeEach(() => {
  vi.useFakeTimers(); vi.resetAllMocks(); vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,blob:async () => new Blob(['preview'])}));
  URL.createObjectURL=vi.fn(() => 'blob:image'); URL.revokeObjectURL=vi.fn();
  HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','');};
  vi.mocked(readApi).mockResolvedValue([plan]); vi.mocked(exportBlob).mockResolvedValue(new Blob(['original']));
  send.mockResolvedValue(undefined); refresh.mockResolvedValue(undefined);
  host=document.createElement('div'); document.body.append(host); root=createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.useRealTimers(); vi.unstubAllGlobals(); });

test('goal submission proposes without any document mutation or paid request', async () => {
  await act(async () => root.render(view()));
  const input=host.querySelector('textarea')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(input,'保留商品，背景暗一些');
    input.dispatchEvent(new Event('input',{bubbles:true}));
  });
  await click('让Chat制定修改方案');
  expect(send).toHaveBeenCalledWith('保留商品，背景暗一些');
  expect(writeApi).not.toHaveBeenCalled(); expect(fetch).not.toHaveBeenCalled();
});

test('local edits show frozen real preview and only apply after explicit click', async () => {
  await act(async () => root.render(view()));
  await click('预览本地修改');
  expect(host.querySelector('[aria-label="修改方案预览"]')).not.toBeNull();
  expect(writeApi).not.toHaveBeenCalled();
  expect(exportBlob).toHaveBeenCalledWith('fixture',2);
  await click('应用本地修改到画布');
  expect(writeApi).toHaveBeenCalledWith('/api/miniclaw/canvas/projects/fixture/plans/plan/apply','POST',{revision:4});
  expect(refresh).toHaveBeenCalled();
  expect(host.querySelector('dialog')).toBeNull();
});

test('version change expires proposal, closes preview and project change clears draft', async () => {
  await act(async () => root.render(view())); await click('预览本地修改');
  await act(async () => root.render(view({...project,revision:5})));
  expect(host.querySelector('dialog')).toBeNull();
  expect(button('预览本地修改').disabled).toBe(true);
  expect(host.textContent).toContain('本方案过期');
  await click('继续调整要求');
  expect(host.querySelector('textarea')!.value).toContain('把背景换为暖白');
  vi.mocked(readApi).mockResolvedValue([]);
  await act(async () => root.render(view({...project,id:'other'})));
  expect(host.querySelector('textarea')!.value).toBe('');
  expect(host.textContent).not.toContain('把背景换为暖白');
});

test('AI is explicit and cancel stays available while job is active', async () => {
  vi.mocked(readApi).mockResolvedValue([{...plan,state:'submitted',job_id:'job',steps:[{action:'ai_edit',label:'生成AI候选',params:{prompt:'暗背景',region:false}}]}]);
  await act(async () => root.render(view(project,true)));
  expect(button('取消方案').disabled).toBe(false);
  await click('取消方案');
  expect(writeApi).toHaveBeenCalledWith('/api/miniclaw/canvas/projects/fixture/plans/plan/cancel','POST',{});
  expect(fetch).not.toHaveBeenCalled();
});


test('solid background shortcut requires a subject selection and previews without applying', async () => {
  const props = { project, busy:false, canPlan:true, hasTarget:true, targetLayerId:'image', onSend:send, onRun:async (work:()=>Promise<void>)=>work(), onRefresh:refresh };
  await act(async () => root.render(<ImagePlanPanel {...props} />));
  expect(button('预览商品纯色背景').disabled).toBe(true);
  vi.mocked(writeApi).mockResolvedValue({...plan,steps:[{action:'replace_background',label:'保留主体换纯色背景',params:{color:'#f2efe7'}}]});
  await act(async () => root.render(<ImagePlanPanel {...props} hasSubjectSelection />));
  await click('预览商品纯色背景');
  expect(writeApi).toHaveBeenCalledTimes(1);
  expect(writeApi).toHaveBeenCalledWith('/api/miniclaw/canvas/projects/fixture/plans','POST',expect.objectContaining({revision:4,layer_id:'image',steps:[{action:'replace_background',params:{color:'#f2efe7'}}]}));
  expect(host.textContent).toContain('选区遗漏会被替换');
  await click('放大检查方案细节');
  expect(host.querySelector('[aria-label="商品细节对照"]')).not.toBeNull();
  expect(writeApi).toHaveBeenCalledTimes(1);
  await click('关闭细节查看');
  await click('应用本地修改到画布');
  expect(writeApi).toHaveBeenCalledTimes(2);
});
