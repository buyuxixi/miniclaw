// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import CreatorWorkspace from "./CreatorWorkspace";
import { readApi, writeApi } from "./management-api";
import {
  getCreator,
  creatorBlob,
  saveCreator,
  uploadCreator,
  type CreatorProject,
  type CreatorReturn,
} from "./creator-api";
vi.mock("./management-api", () => ({ readApi: vi.fn(), writeApi: vi.fn() }));
vi.mock("./creator-api", async () => ({
  ...(await vi.importActual("./creator-api")),
  getCreator: vi.fn(),
  saveCreator: vi.fn(),
  creatorBlob: vi.fn(),
}));
let root: Root, host: HTMLDivElement;
const fixture: CreatorProject = {
  id: "a".repeat(32),
  name: "验收任务",
  facts: "陶瓷杯",
  script: "每天一杯",
  caption: "我的作品",
  provenance: "自制",
  revision: 1,
  mode: "portrait",
  method: "plan",
  assets: {},
  outputs: [],
  packages: [],
  jobs: [],
  steps: {
    facts: true,
    script: true,
    cover: false,
    video: false,
    package: false,
  },
};
const draft = vi.fn();
const canvas = vi.fn();
const taskChat = vi.fn();
function render(active = true, incoming?: CreatorReturn) {
  return (
    <CreatorWorkspace
      active={active}
      incoming={incoming}
      onChat={taskChat}
      onCanvas={canvas}
      onDraft={draft}
    />
  );
}
function button(text: string) {
  return Array.from(host.querySelectorAll("button")).find(
    (b) => b.textContent === text,
  )!;
}
async function change(
  el: HTMLInputElement | HTMLTextAreaElement,
  value: string,
) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      el instanceof HTMLTextAreaElement
        ? HTMLTextAreaElement.prototype
        : HTMLInputElement.prototype,
      "value",
    )!.set!.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
beforeEach(async () => {
  vi.resetAllMocks();
  vi.useFakeTimers();
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  localStorage.clear();
  localStorage.setItem("miniclaw.creator", fixture.id);
  vi.mocked(readApi).mockImplementation(async (path) =>
    path.endsWith("/capabilities")
      ? { video: true, font: true }
      : ([{ id: fixture.id, name: fixture.name }] as never),
  );
  vi.mocked(getCreator).mockResolvedValue(structuredClone(fixture));
  vi.mocked(creatorBlob).mockImplementation((await vi.importActual<typeof import('./creator-api')>('./creator-api')).creatorBlob);
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:preview') });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
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

test('a source-only project can start guided Chat without filling manual fact fields', async () => {
  const p = { ...fixture, facts: '', script: '', assets: { source: { id: 'source', name: 'original.png', bytes: 1 } } };
  vi.mocked(getCreator).mockResolvedValue(p);
  await act(async () => root.render(render()));
  expect(host.querySelector('.creator-manual-brief')?.hasAttribute('open')).toBe(false);
  await act(async () => button('和Chat确定创作方向').click());
  expect(draft).toHaveBeenCalledWith(expect.stringContaining('先区分已知事实'), p, 'brief');
  expect(saveCreator).not.toHaveBeenCalled();
});

test('direction on a completed project shows the original and sends the current goal as a brief', async () => {
  vi.mocked(creatorBlob).mockResolvedValue(new Blob(['image']));
  const p = {...fixture, assets: {source:{id:'raw',name:'raw.png',bytes:1},cover:{id:'adopted',name:'cover.png',bytes:1}}, outputs:[{id:'film',name:'film.mp4',bytes:1,current:true}]};
  vi.mocked(getCreator).mockResolvedValue(p);
  await act(async()=>root.render(render()));
  await act(async()=>Array.from(host.querySelectorAll('.creator-progress button')).find(b=>b.querySelector('strong')?.textContent==='方向')!.dispatchEvent(new MouseEvent('click',{bubbles:true})));
  expect(host.querySelector('.creator-preview img')?.getAttribute('alt')).toContain('原图');
  expect(host.querySelector('.creator-preview video')).toBeNull();
  expect(host.querySelector('.creator-guide')).toBeNull();
  await change(host.querySelector('[aria-label="创作目标"]') as HTMLTextAreaElement,'制作柔光商品图');
  await act(async()=>button('和Chat确定创作方向').click());
  expect(draft).toHaveBeenCalledWith(expect.stringContaining('制作柔光商品图'),p,'brief');
  expect(saveCreator).not.toHaveBeenCalled();
});

test('image step resumes the project and keeps extra tools folded until requested', async () => {
  vi.mocked(creatorBlob).mockResolvedValue(new Blob(['image']));
  const p = {...fixture,assets:{source:{id:'raw',name:'raw.png',bytes:1},cover:{id:'adopted',name:'cover.png',bytes:1}}};
  vi.mocked(getCreator).mockResolvedValue(p);
  await act(async()=>root.render(render()));
  await act(async()=>Array.from(host.querySelectorAll('.creator-progress button')).find(b=>b.querySelector('strong')?.textContent==='图片')!.dispatchEvent(new MouseEvent('click',{bubbles:true})));
  expect(host.querySelector('.creator-preview img')?.getAttribute('alt')).toContain('采用图');
  expect(Array.from(host.querySelectorAll('details.creator-options')).every(d=>!d.hasAttribute('open'))).toBe(true);
  await act(async()=>button('继续修改图片').click());
  expect(canvas).toHaveBeenCalledExactlyOnceWith(p);
  expect(saveCreator).not.toHaveBeenCalled();
});

test('folding video steps returns to a visible core step', async () => {
  vi.mocked(getCreator).mockResolvedValue({...fixture,outputs:[{id:'film',name:'film.mp4',bytes:1,current:true}]});
  await act(async()=>root.render(render()));
  expect(host.querySelector('.creator-progress [aria-current] strong')?.textContent).toBe('视频');
  await act(async()=>(host.querySelector('.creator-advanced-toggle') as HTMLButtonElement).click());
  expect(host.querySelector('.creator-progress [aria-current] strong')?.textContent).toBe('方向');
  expect(host.querySelector('.creator-advanced-toggle')?.getAttribute('aria-expanded')).toBe('false');
});

test('the default product view is a flow overview and nodes continue in Chat', async () => {
  const p={...fixture,assets:{source:{id:'raw',name:'raw.png',bytes:1}}};
  vi.mocked(getCreator).mockResolvedValue(p);
  await act(async()=>root.render(render()));
  expect(host.querySelector('.creator-manual-area')?.hasAttribute('hidden')).toBe(true);
  expect(host.querySelectorAll('.flow-node')).toHaveLength(3);
  expect(host.querySelectorAll('.flow-overview .creator-primary')).toHaveLength(1);
  await act(async()=>(host.querySelectorAll('.flow-node')[1] as HTMLButtonElement).click());
  expect(taskChat).toHaveBeenCalledExactlyOnceWith(p,'cover');
  expect(canvas).not.toHaveBeenCalled();
  expect(draft).not.toHaveBeenCalled();
  await act(async()=>button('项目设置').click());
  expect(host.querySelector('.creator-manual-area')?.hasAttribute('hidden')).toBe(false);
  await change(host.querySelector('[aria-label="商品事实"]') as HTMLTextAreaElement,'正在编辑的信息');
  expect(button('返回总览').disabled).toBe(true);
});

test("editing prevents render/upload and task switching until saved; Chat handoff does not send", async () => {
  await act(async () => root.render(render()));
  const script = host.querySelector('textarea[aria-label="口播稿"]') as HTMLTextAreaElement;
  await change(script, "改好的稿件");
  expect(button("合成视频").disabled).toBe(true);
  expect(
    (host.querySelector("input[type=file]") as HTMLInputElement).disabled,
  ).toBe(true);
  await act(async () => button("带入 Chat 草稿").click());
  expect(draft).not.toHaveBeenCalled();
  expect(writeApi).not.toHaveBeenCalled();
  vi.mocked(saveCreator).mockResolvedValue({
    ...fixture,
    script: "改好的稿件",
    revision: 2,
  });
  await act(async () => button("保存任务内容").click());
  expect(saveCreator).toHaveBeenCalledWith(
    expect.objectContaining({ revision: 1 }),
    expect.objectContaining({ script: "改好的稿件" }),
  );
  expect(button("合成视频").disabled).toBe(false);
  await act(async () => button("带入 Chat 草稿").click());
  expect(draft).toHaveBeenCalledWith(
    expect.stringContaining("改好的稿件"),
    expect.objectContaining({ id: fixture.id, revision: 2 }),
  );
});

test("render polling preserves unsaved script and stops in hidden module", async () => {
  vi.mocked(getCreator).mockResolvedValue({
    ...fixture,
    jobs: [{ id: "job", state: "running" }],
  });
  await act(async () => root.render(render()));
  await change(host.querySelector('textarea[aria-label="口播稿"]') as HTMLTextAreaElement, "未保存的新稿");
  vi.mocked(getCreator).mockResolvedValue({
    ...fixture,
    revision: 2,
    jobs: [{ id: "job", state: "running" }],
  });
  await act(async () => vi.advanceTimersByTimeAsync(1600));
  expect((host.querySelector('textarea[aria-label="口播稿"]') as HTMLTextAreaElement).value).toBe("未保存的新稿");
  const count = vi.mocked(getCreator).mock.calls.length;
  await act(async () => root.render(render(false)));
  await act(async () => vi.advanceTimersByTimeAsync(4000));
  expect(getCreator).toHaveBeenCalledTimes(count);
});

test("an old output never enables packaging for changed media", async () => {
  vi.mocked(getCreator).mockResolvedValue({
    ...fixture,
    outputs: [{ id: "old", name: "old.mp4", bytes: 100, current: false }],
  });
  await act(async () => root.render(render()));
  expect(host.textContent).toContain("已有成片属于旧版本");
  expect(button("生成发布包").disabled).toBe(true);
  expect(host.querySelector("video")).toBeNull();
});

test("oversized binary upload is refused before fetch", async () => {
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  const file = new File(["x"], "demo.mp4");
  Object.defineProperty(file, "size", { value: 256 * 1024 * 1024 + 1 });
  await expect(uploadCreator(fixture, "video", file)).rejects.toThrow(
    "256 MiB",
  );
  expect(fetcher).not.toHaveBeenCalled();
});

test("old versions can be downloaded explicitly without making them current", async () => {
  vi.mocked(getCreator).mockResolvedValue({
    ...fixture,
    outputs: [{ id: "old", name: "video.mp4", bytes: 100, current: false }],
  });
  const fetcher = vi.fn().mockResolvedValue({
    ok: true,
    blob: async () => new Blob(["fixture-video"]),
  });
  vi.stubGlobal("fetch", fetcher);
  vi.stubGlobal("URL", {
    createObjectURL: () => "blob:old-video",
    revokeObjectURL: vi.fn(),
  });
  await act(async () => root.render(render()));
  const selector = host.querySelector("details select") as HTMLSelectElement;
  await act(async () => {
    selector.value = "old";
    selector.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(host.querySelector("video")?.getAttribute("src")).toBe(
    "blob:old-video",
  );
  expect(button("生成发布包").disabled).toBe(true);
  expect(fetcher).toHaveBeenCalledWith(
    expect.stringContaining("/files/old"),
    expect.objectContaining({
      headers: expect.objectContaining({
        "X-Hermes-Session-Token": expect.any(String),
      }),
    }),
  );
});

test("Chat return requires review and uses frozen revision; secondary directions are editable", async () => {
  const incoming: CreatorReturn = {
    kind: "script",
    project: fixture.id,
    revision: 1,
    nonce: 101,
    text: "主稿。\n两个开头。",
    owner: "chat-owner",
    item: "reply-1",
  };
  await act(async () => root.render(render(true, incoming)));
  expect(host.querySelector('[role="dialog"]')).not.toBeNull();
  expect(saveCreator).not.toHaveBeenCalled();
  const input = host.querySelector(
    '[role="dialog"] textarea',
  ) as HTMLTextAreaElement;
  await change(input, "只保留主稿。");
  vi.mocked(saveCreator).mockResolvedValue({
    ...fixture,
    revision: 2,
    script: "只保留主稿。",
  });
  await act(async () => button("确认采用").click());
  expect(saveCreator).toHaveBeenCalledWith(
    expect.objectContaining({ id: fixture.id, revision: 1 }),
    { script: "只保留主稿。" },
  );
  expect(host.querySelector('[role="dialog"]')).toBeNull();
  expect((host.querySelector('textarea[aria-label="口播稿"]') as HTMLTextAreaElement).value).toBe("只保留主稿。");
});

test("dirty drafts and mismatched project returns are preserved instead of adopted", async () => {
  await act(async () => root.render(render()));
  await change(host.querySelector('textarea[aria-label="口播稿"]') as HTMLTextAreaElement, "保留的未保存主稿");
  await act(async () =>
    root.render(
      render(true, {
        kind: "script",
        project: fixture.id,
        revision: 1,
        nonce: 102,
        text: "旧回复",
        owner: "chat",
        item: "reply",
      }),
    ),
  );
  expect(host.querySelector('[role="dialog"]')).toBeNull();
  expect((host.querySelector('textarea[aria-label="口播稿"]') as HTMLTextAreaElement).value).toBe("保留的未保存主稿");
  expect(saveCreator).not.toHaveBeenCalled();
  expect(host.querySelector('[role="alert"]')?.textContent).toContain("未覆盖");
});

test("storyboard rendering waits for speech capability instead of silently substituting local speech", async () => {
  vi.mocked(getCreator).mockResolvedValue({ ...fixture, method: "storyboard" });
  await act(async () => root.render(render()));
  expect(button("合成视频").disabled).toBe(true);
  expect(host.textContent).toContain("百炼语音未配置");
  expect(writeApi).not.toHaveBeenCalled();
});

test("shared brief is edited in the existing workspace and the flow recommends images before speech", async () => {
  await act(async () => root.render(render()));
  expect(Array.from(host.querySelectorAll('[aria-label="创作步骤"] strong')).map(el=>el.textContent)).toEqual(['方向','图片','口播']);
  await act(async () => (host.querySelector('.creator-advanced-toggle') as HTMLButtonElement).click());
  expect(Array.from(host.querySelectorAll('[aria-label="创作步骤"] strong')).map(el=>el.textContent)).toEqual(['方向','图片','口播','视频','导出']);
  await change(host.querySelector('textarea[aria-label="统一风格"]') as HTMLTextAreaElement, '米白柔光');
  await change(host.querySelector('textarea[aria-label="已确认卖点"]') as HTMLTextAreaElement, '杯身哑光');
  expect(button('下一步 · 图片 →').disabled).toBe(true);
  vi.mocked(saveCreator).mockResolvedValue({...fixture,revision:2,style:'米白柔光',selling_points:'杯身哑光'});
  await act(async()=>button('保存任务内容').click());
  expect(saveCreator).toHaveBeenCalledWith(expect.objectContaining({revision:1}),expect.objectContaining({style:'米白柔光',selling_points:'杯身哑光'}));
  expect(button('下一步 · 图片 →').disabled).toBe(false);
  vi.mocked(getCreator).mockResolvedValue({...fixture,revision:2,style:'米白柔光',selling_points:'杯身哑光'});
  await act(async()=>root.render(render(false)));
  await act(async()=>root.render(render()));
  expect((host.querySelector('textarea[aria-label="统一风格"]') as HTMLTextAreaElement).value).toBe('米白柔光');
});

test("a late reply cannot be adopted into a newer saved project", async () => {
  vi.mocked(getCreator).mockResolvedValue({...fixture,revision:4,script:'新版已保存'});
  await act(async()=>root.render(render(true,{kind:'script',project:fixture.id,revision:1,nonce:110,text:'迟到旧稿',owner:'chat',item:'row'})));
  expect(host.querySelector('[role="dialog"]')).toBeNull();
  expect((host.querySelector('textarea[aria-label="口播稿"]') as HTMLTextAreaElement).value).toBe('新版已保存');
  expect(saveCreator).not.toHaveBeenCalled();
});

test("narrated footage blocks missing speech and exposes explicit style and background choices", async () => {
  vi.mocked(getCreator).mockResolvedValue({
    ...fixture,
    method: "narrated",
    speech_style: "warm",
  });
  await act(async () => root.render(render()));
  expect(button("合成视频").disabled).toBe(true);
  const style = Array.from(host.querySelectorAll("select")).find((s) =>
    s.parentElement?.textContent?.includes("配音风格"),
  )!;
  expect(style.value).toBe("warm");
  expect(host.textContent).toContain("Serena");
  const background = host.querySelector(
    ".creator-audio-choice input",
  ) as HTMLInputElement;
  expect(background.checked).toBe(false);
  expect(background.disabled).toBe(true);
  expect(host.textContent).toContain("上传已剪好的镜头片");
  expect(writeApi).not.toHaveBeenCalled();
});

test('Chat brief remains editable and requires confirmation; the frozen revision is used', async () => {
  const fields = {facts:'杯身哑光，容量未知',selling_points:'哑光外观；购买偏好待验证',audience:'喜欢简洁茶具的人（建议）',style:'米白柔光',constraints:'不编造功能'};
  const incoming: CreatorReturn = {kind:'brief',project:fixture.id,revision:1,nonce:301,owner:'chat',item:'reply',fields};
  await act(async()=>root.render(render(true,incoming)));
  expect(host.querySelector('[role="dialog"]')?.textContent).toContain('确认创作依据');
  expect(saveCreator).not.toHaveBeenCalled();
  await change(host.querySelector('[aria-label="待采用商品事实"]') as HTMLTextAreaElement,'杯身哑光，容量未验证（用户核对）');
  vi.mocked(saveCreator).mockResolvedValue({...fixture,...fields,revision:2});
  await act(async()=>button('确认采用').click());
  expect(saveCreator).toHaveBeenCalledWith(expect.objectContaining({revision:1}),{...fields,facts:'杯身哑光，容量未验证（用户核对）'});
  expect(host.querySelector('[role="dialog"]')).toBeNull();
});

test('an old brief cannot overwrite the current product facts', async () => {
  await act(async()=>root.render(render(true,{kind:'brief',project:fixture.id,revision:0,nonce:302,owner:'chat',item:'reply',fields:{facts:'旧事实',selling_points:'',audience:'',style:'',constraints:''}})));
  expect(host.querySelector('[role="dialog"]')).toBeNull();
  expect(saveCreator).not.toHaveBeenCalled();
  expect((host.querySelector('[aria-label="商品事实"]') as HTMLTextAreaElement).value).toBe(fixture.facts);
});

test('a returned brief from another conversation is rejected even at the same project revision', async () => {
  vi.mocked(getCreator).mockResolvedValue({...fixture,chat_id:'current-chat'});
  await act(async()=>root.render(render(true,{kind:'brief',project:fixture.id,revision:1,nonce:303,owner:'foreign-chat',item:'reply',fields:{facts:'外来事实',selling_points:'',audience:'',style:'',constraints:''}})));
  expect(host.querySelector('[role="dialog"]')).toBeNull();
  expect(saveCreator).not.toHaveBeenCalled();
});
