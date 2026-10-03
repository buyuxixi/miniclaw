// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import CanvasApp from "./CanvasApp";
import type { ChatController } from "./chat-controller";
import { readApi, writeApi } from "./management-api";
import { loadProject, type Project } from "./canvas-api";

vi.mock("./management-api", () => ({ readApi: vi.fn(), writeApi: vi.fn() }));
vi.mock("./CanvasStage", () => ({
  CanvasStage: () => <div>canvas fixture</div>,
}));
vi.mock("./canvas-api", async () => ({
  ...(await vi.importActual("./canvas-api")),
  loadProject: vi.fn(),
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
    jobs: [],
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
