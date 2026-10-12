// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import CanvasApp from "./CanvasApp";
import type { ChatController } from "./chat-controller";
import { readApi, writeApi } from "./management-api";
import { exportBlob, previewBlob, uploadCanvas, loadProject, type Project } from "./canvas-api";

vi.mock("./management-api", () => ({ readApi: vi.fn(), writeApi: vi.fn() }));
vi.mock("./CanvasStage", () => ({
  CanvasStage: ({ view, size, selectionColor }: { view: { x: number; y: number; scale: number }; size: { width: number; height: number }; selectionColor?: string }) =>
    <div data-stage-view={JSON.stringify(view)} data-stage-size={JSON.stringify(size)} data-selection-color={selectionColor}>canvas fixture</div>,
}));
vi.mock("./canvas-api", async () => ({
  ...(await vi.importActual("./canvas-api")),
  loadProject: vi.fn(),
  exportBlob: vi.fn(), previewBlob: vi.fn(), uploadCanvas: vi.fn(),
}));
let host: HTMLDivElement;
let root: Root;
const project: Project = {
  id: "fixture",
  name: "画布",
  revision: 1,
  cursor: 1,
  updated: 1,
  archived: false,
  chat_id: null,
  document: {
    schema_version: 1,
    width: 120,
    height: 80,
    background: "#ffffff00",
    layers: [
      {
        id: "a".repeat(32),
        kind: "shape",
        name: "矩形",
        x: 0,
        y: 0,
        width: 40,
        height: 30,
        scale_x: 1,
        scale_y: 1,
        rotation: 0,
        opacity: 1,
        visible: true,
        locked: false,
        fill: "#ff0000",
        shape: "rectangle",
      },
    ],
  },
};
const controller = {
  subscribe: () => () => {},
  state: {
    items: [],
    storedId: "chat",
    sessionId: "live",
    info: {},
    running: false,
    busy: false,
    error: "",
  },
} as unknown as ChatController;
function render(active: boolean) {
  return (
    <CanvasApp
      controller={controller}
      active={active}
      onChat={() => {}}
      onUse={() => {}}
      onSettings={() => {}}
    />
  );
}
beforeEach(() => {
  vi.useFakeTimers();
  vi.resetAllMocks();
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
  vi.mocked(loadProject).mockResolvedValue({
    project,
    assets: [],
    selection: null,
    history: [{ seq: 1, label: "当前", time: 1, current: true }],
    jobs: [], versions: [], versionTotal: 0,
  });
  vi.mocked(readApi).mockImplementation(async (path) =>
    path.endsWith("/capabilities")
      ? { sam: { state: "unprepared" }, cloud: { configured: false } }
      : [],
  );
  vi.mocked(writeApi).mockResolvedValue(project);
  localStorage.clear();
  localStorage.setItem("miniclaw.canvas.selected", "fixture");
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

test("hidden canvas cannot delete a layer through a Chat keyboard event", async () => {
  await act(async () => root.render(render(false)));
  expect(host.textContent).toContain("矩形");
  await act(async () =>
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Delete" })),
  );
  expect(writeApi).not.toHaveBeenCalled();
  await act(async () => root.render(render(true)));
  await act(async () =>
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Delete" })),
  );
  expect(writeApi).toHaveBeenCalledWith(
    "/api/miniclaw/canvas/projects/fixture/document",
    "PUT",
    expect.objectContaining({
      revision: 1,
      document: expect.objectContaining({ layers: [] }),
    }),
  );
});

test("polling does not erase a project-name draft", async () => {
  await act(async () => root.render(render(true)));
  const input = host.querySelector<HTMLInputElement>(
    'input[aria-label="项目名称"]',
  )!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, "正在输入的名字");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(input.value).toBe("正在输入的名字");
  await act(async () => vi.advanceTimersByTimeAsync(3000));
  expect(input.value).toBe("正在输入的名字");
});

test('precision is explicit and returning to simple editing resets a hidden crop tool', async () => {
  await act(async()=>root.render(render(true)));
  const byText = (text:string) => Array.from(host.querySelectorAll('button')).find(b=>b.textContent===text)!;
  expect(host.querySelector('.canvas-tools')?.hasAttribute('hidden')).toBe(true);
  expect(byText('图层').hidden).toBe(true);
  expect(host.querySelector('[aria-label="图片修改目标"]')).not.toBeNull();
  await act(async()=>byText('精调工具').click());
  expect(host.querySelector('.canvas-tools')?.hasAttribute('hidden')).toBe(false);
  expect(byText('图层').hidden).toBe(false);
  await act(async()=>(host.querySelector('.canvas-tools [aria-label="裁剪画布"]') as HTMLButtonElement).click());
  await act(async()=>byText('返回简洁编辑').click());
  expect(host.querySelector('.canvas-tools')?.hasAttribute('hidden')).toBe(true);
  expect(host.querySelector('.canvas-surface')?.className).toContain('tool-move');
  expect(writeApi).not.toHaveBeenCalled();
});

test('video-hosted fit leaves toolbar space and themes selection without changing the media document', async () => {
  const portrait = { ...project, document: { ...project.document, width: 400, height: 1200 } };
  vi.mocked(loadProject).mockResolvedValue({ project: portrait, assets: [], selection: null, history: [], jobs: [], versions: [], versionTotal: 0 });
  vi.stubGlobal('getComputedStyle', (element: Element) => {
    expect(element.classList.contains('canvas-surface')).toBe(true);
    return { getPropertyValue: (key: string) => key === '--ca-blue' ? 'rgb(196, 87, 46)' : '' };
  });
  await act(async () => root.render(render(true)));
  const stage = () => host.querySelector<HTMLElement>('[data-stage-view]')!;
  const fittedBottom = () => { const view = JSON.parse(stage().dataset.stageView!); return view.y + portrait.document.height * view.scale; };
  const toolbarTop = JSON.parse(stage().dataset.stageSize!).height - 56;
  expect(fittedBottom()).toBeGreaterThan(toolbarTop); // Preserve the standalone editor's existing fit.
  expect(stage().dataset.selectionColor).toBeUndefined();
  const originalDocument = JSON.stringify(portrait.document);
  await act(async () => root.render(<CanvasApp controller={controller} active onChat={() => {}} onUse={() => {}} onSettings={() => {}}
    workspaceHost={{ project: 'fixture', onClose() {}, onReview: async () => {} }} />));
  expect(fittedBottom()).toBeLessThan(toolbarTop);
  expect(stage().dataset.selectionColor).toBe('rgb(196, 87, 46)');
  expect(JSON.stringify(portrait.document)).toBe(originalDocument);
  expect(writeApi).not.toHaveBeenCalled();
});

test('fresh imports replace the previous reload selection and report the exact project binding', async () => {
  const created = {...project,id:'new-canvas',chat_id:'chat'};
  vi.mocked(writeApi).mockImplementation(async path => path.endsWith('/import-chat') ? {id:'asset',name:'source.png',width:1280,height:2778} as never : created as never);
  vi.mocked(loadProject).mockResolvedValue({project:created,assets:[],selection:null,history:[],jobs: [], versions: [], versionTotal: 0});
  const ready = vi.fn();
  const origin = {project:'creator',owner:'chat',image:'original'};
  await act(async () => root.render(<CanvasApp controller={controller} active onChat={()=>{}} onUse={()=>{}} onSettings={()=>{}} onProjectReady={ready} initialImport={{session:'live',nonce:1,creator:origin,attachment:{id:'upload',name:'source.png',kind:'image',mime:'image/png',bytes:12}}}/>));
  expect(localStorage.getItem('miniclaw.canvas.selected')).toBe('new-canvas');
  expect(ready).toHaveBeenCalledWith(origin,'new-canvas');
  expect(loadProject).not.toHaveBeenCalledWith('fixture');
});

test('a different canvas or conversation cannot adopt into the selected creative project', async () => {
  const adopt = vi.fn();
  const props = {controller,active:true,onChat:()=>{},onUse:()=>{},onSettings:()=>{},onUseCreator:adopt,creatorName:'商品',creatorContext:{id:'creator',name:'商品',revision:2,owner:'chat',node:'cover' as const,canvas:'expected'}};
  await act(async () => root.render(<CanvasApp {...props}/>));
  const button = () => Array.from(host.querySelectorAll('button')).find(b=>b.textContent?.includes('采用工作图'))!;
  expect(button().disabled).toBe(true);
  await act(async () => root.render(<CanvasApp {...props} creatorContext={{...props.creatorContext,canvas:'fixture'}}/>));
  expect(button().disabled).toBe(true); // fixture is linked to no Chat
  vi.mocked(loadProject).mockResolvedValue({project:{...project,revision:2,chat_id:'chat'},assets:[],selection:null,history:[],jobs: [], versions: [], versionTotal: 0});
  await act(async () => vi.advanceTimersByTimeAsync(3000));
  expect(button().disabled).toBe(false);
  expect(adopt).not.toHaveBeenCalled();
});

  test('linked manual editor returns to the same Chat and its tools cannot open a second assistant input', async () => {
    vi.mocked(loadProject).mockResolvedValue({project:{...project,chat_id:'chat'},assets:[],selection:null,history:[],jobs: [], versions: [], versionTotal: 0});
    const onChat=vi.fn();
    await act(async()=>root.render(<CanvasApp controller={controller} active onChat={onChat} onUse={()=>{}} onSettings={()=>{}} creatorContext={{id:'creator',name:'商品',revision:2,owner:'chat',node:'cover',canvas:'fixture'}}/>));
    const tools=Array.from(host.querySelectorAll('button')).find(b=>b.textContent==='图层与属性')!;
    await act(async()=>tools.click());
    expect(host.textContent).not.toContain('返回简洁编辑');
    expect(host.querySelector('.canvas-assistant textarea')).toBeNull();
    await act(async()=>Array.from(host.querySelectorAll('button')).find(b=>b.textContent?.includes('← 返回对话'))!.click());
    expect(onChat).toHaveBeenCalledOnce();
  });

  test('layout preparation previews without changing the canvas and applies the frozen revision only after confirmation', async () => {
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:preview') });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
  vi.mocked(exportBlob).mockResolvedValue(new Blob(['source'], {type:'image/png'}));
  vi.mocked(previewBlob).mockResolvedValue(new Blob(['preview'], {type:'image/png'}));
  vi.mocked(uploadCanvas).mockResolvedValue({id:'asset',name:'snapshot.png',kind:'image',mime:'image/png',bytes:6,width:160,height:120});
  await act(async () => root.render(render(true)));
  const click = async (name: string) => act(async () => Array.from(host.querySelectorAll('button')).find(b => b.textContent === name)!.click());
  await click('图片方案'); await click('预览构图 · 不改原图');
  expect(exportBlob).toHaveBeenCalledWith('fixture', 1);
  expect(previewBlob).toHaveBeenCalledWith('fixture', 1, expect.objectContaining({width:1080,height:1350}));
  expect(writeApi).not.toHaveBeenCalled();
  expect(host.querySelector('dialog[aria-label="构图预览"]')).not.toBeNull();
  await click('应用构图到画布');
  expect(writeApi).toHaveBeenCalledWith('/api/miniclaw/canvas/projects/fixture/document', 'PUT', expect.objectContaining({revision:1,label:'应用展示图构图'}));
  expect(host.querySelector('dialog[aria-label="构图预览"]')).toBeNull();
});

test('layout text drafts survive polling but do not leak into another product', async () => {
  await act(async () => root.render(render(true)));
  await act(async () => Array.from(host.querySelectorAll('button')).find(b => b.textContent === '图片方案')!.click());
  const input = () => host.querySelector<HTMLInputElement>('input[aria-label="展示图标题"]')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input(), '乳白 · 圆弧');
    input().dispatchEvent(new Event('input', {bubbles:true}));
  });
  await act(async () => vi.advanceTimersByTimeAsync(3000));
  expect(input().value).toBe('乳白 · 圆弧');
  vi.mocked(loadProject).mockResolvedValue({project:{...project,id:'green'},assets:[],selection:null,history:[],jobs: [], versions: [], versionTotal: 0});
  await act(async () => root.render(<CanvasApp controller={controller} active onChat={()=>{}} onUse={()=>{}} onSettings={()=>{}} initialImport={{session:'live',nonce:2,design:{mode:'layout',preset:'dark'},attachment:{id:'green-cover',canvas_project_id:'green',name:'green.png',kind:'image',mime:'image/png',bytes:12}}}/>));
  expect(input().value).toBe('留白之间');
});

test('screenshot suggestion and adjusted previews never save until the exact range is confirmed', async () => {
  Object.defineProperty(URL,'createObjectURL',{configurable:true,value:vi.fn(()=> 'blob:crop')});
  Object.defineProperty(URL,'revokeObjectURL',{configurable:true,value:vi.fn()});
  vi.mocked(exportBlob).mockResolvedValue(new Blob(['source']));
  vi.mocked(previewBlob).mockResolvedValue(new Blob(['preview']));
  vi.mocked(writeApi).mockImplementation(async path => path.endsWith('/crop-suggestion') ? {y:10,height:40} as never : project as never);
  await act(async()=>root.render(render(true)));
  const click = async (name:string) => act(async()=>Array.from(host.querySelectorAll('button')).find(b=>b.textContent===name)!.click());
  await click('图片方案');
  await act(async()=>host.querySelector<HTMLDetailsElement>('.photo-preparation')!.open=true);
  await click('截图裁剪');
  expect(host.querySelector('[aria-label="截图裁剪预览"]')).not.toBeNull();
  expect(writeApi).not.toHaveBeenCalledWith(expect.stringContaining('/document'), 'PUT', expect.anything());
  expect(previewBlob).toHaveBeenCalledWith('fixture',1,expect.objectContaining({height:40,layers:[expect.objectContaining({y:-10})]}));
  const top=host.querySelector<HTMLInputElement>('[aria-label="裁剪上边界"]')!;
  await act(async()=>{
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(top,'12');
    top.dispatchEvent(new Event('input',{bubbles:true}));
  });
  expect(Array.from(host.querySelectorAll('button')).find(b=>b.textContent==='确认范围，应用裁剪')!.disabled).toBe(true);
  await click('更新裁剪预览'); await click('确认范围，应用裁剪');
  expect(writeApi).toHaveBeenCalledWith('/api/miniclaw/canvas/projects/fixture/document','PUT',expect.objectContaining({revision:1,document:expect.objectContaining({height:38,layers:[expect.objectContaining({y:-12})]})}));
});
