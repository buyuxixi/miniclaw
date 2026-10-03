import { useEffect, useRef, useState } from "react";
import type { ChatController } from "./chat-controller";
import { Message } from "./Message";
import { ImageComparison } from "./ImageJobCard";
import { readApi, writeApi } from "./management-api";
import type { Attachment } from "./attachments";
import { CanvasStage, type CanvasTool, type View } from "./CanvasStage";
import {
  copyDoc,
  downloadCanvas,
  exportBlob,
  loadProject,
  makeLayer,
  projectOwner,
  projectPath,
  uploadCanvas,
  type CanvasAsset,
  type CanvasCapabilities,
  type CanvasDocument,
  type CanvasJob,
  type CanvasLayer,
  type Project,
  type ProjectRow,
  type Selection,
  type Version,
} from "./canvas-api";
import "./canvas.css";

const tools: { id: CanvasTool; icon: string; label: string }[] = [
  { id: "move", icon: "↖", label: "选择与变换" },
  { id: "pan", icon: "✥", label: "平移画布" },
  { id: "rectangle", icon: "▧", label: "矩形选区" },
  { id: "lasso", icon: "◌", label: "套索选区" },
  { id: "brush", icon: "⌁", label: "笔刷选区" },
  { id: "sam", icon: "✦", label: "点选物体" },
  { id: "crop", icon: "⌗", label: "裁剪画布" },
];
const failures = (reason: unknown) =>
  reason instanceof Error ? reason.message : String(reason);

function ProjectCompare({
  project,
  seq,
  onClose,
}: {
  project: string;
  seq: number;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [urls, setUrls] = useState<string[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    dialog.current?.showModal();
    let alive = true;
    let links: string[] = [];
    void Promise.all([exportBlob(project, seq), exportBlob(project)])
      .then((blobs) => {
        links = blobs.map((b) => URL.createObjectURL(b));
        if (alive) setUrls(links);
        else links.forEach(URL.revokeObjectURL);
      })
      .catch((e) => {
        if (alive) setError(failures(e));
      });
    return () => {
      alive = false;
      links.forEach(URL.revokeObjectURL);
    };
  }, [project, seq]);
  return (
    <dialog className="canvas-compare" ref={dialog} onCancel={onClose}>
      <header>
        <strong>版本 {seq} 与当前画布</strong>
        <button onClick={onClose} aria-label="关闭对比">
          ×
        </button>
      </header>
      {error && <p role="alert">{error}</p>}
      <div>
        {urls.length ? (
          urls.map((url, i) => (
            <figure key={url}>
              <img src={url} alt={i === 0 ? `历史版本 ${seq}` : "当前画布"} />
              <figcaption>{i === 0 ? "历史版本" : "当前画布"}</figcaption>
            </figure>
          ))
        ) : (
          <p>正在合成画布…</p>
        )}
      </div>
    </dialog>
  );
}

export default function CanvasApp({
  controller,
  onChat,
  onUse,
  initialImport,
  onSettings,
  active,
}: {
  controller: ChatController;
  onChat: () => void;
  onUse: (attachment: Attachment) => void;
  onSettings: () => void;
  initialImport?: { attachment: Attachment; session: string; nonce: number };
  active: boolean;
}) {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [archived, setArchived] = useState(false);
  const [search, setSearch] = useState("");
  const [project, setProject] = useState<Project>();
  const [assets, setAssets] = useState<CanvasAsset[]>([]);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [history, setHistory] = useState<Version[]>([]);
  const [jobs, setJobs] = useState<CanvasJob[]>([]);
  const [capabilities, setCapabilities] = useState<CanvasCapabilities>();
  const [selected, setSelected] = useState("");
  const [tool, setTool] = useState<CanvasTool>("move");
  const [view, setView] = useState<View>({ x: 30, y: 30, scale: 0.5 });
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [name, setName] = useState("");
  const [panel, setPanel] = useState<"layers" | "history" | "assistant">(
    "layers",
  );
  const [drawer, setDrawer] = useState(false);
  const [combine, setCombine] = useState("replace");
  const [radius, setRadius] = useState(20);
  const [brightness, setBrightness] = useState(0.15);
  const [prompt, setPrompt] = useState("");
  const [region, setRegion] = useState(true);
  const [feather, setFeather] = useState(0);
  const [assistant, setAssistant] = useState("");
  const [cropRatio, setCropRatio] = useState("free");
  const [compare, setCompare] = useState<number>();
  const [size, setSize] = useState({ width: 800, height: 600 });
  const host = useRef<HTMLDivElement>(null);
  const upload = useRef<HTMLInputElement>(null);
  const importNonce = useRef<number | undefined>(undefined);
  const activeId = useRef("");
  const lastName = useRef("");
  const [, renderChat] = useState(0);
  useEffect(
    () => controller.subscribe(() => renderChat((n) => n + 1)),
    [controller],
  );
  useEffect(() => {
    busyRef.current = busy;
  }, [busy]);
  const target = project?.document.layers.find((l) => l.id === selected);
  const chat = controller.state;
  const canAssist = Object.values(chat.info.tools ?? {})
    .flat()
    .includes("miniclaw_canvas_view");
  const activeJob = jobs.find(
    (j) => j.state === "running" || j.state === "queued",
  );
  async function list(archive = archived) {
    setProjects(
      await readApi<ProjectRow[]>(
        `/api/miniclaw/canvas/projects?archived=${archive}`,
      ),
    );
  }
  async function refresh(id: string) {
    const state = await loadProject(id);
    if (activeId.current !== id) return;
    if (state.project.archived) {
      activeId.current = "";
      setProject(undefined);
      localStorage.removeItem("miniclaw.canvas.selected");
      setArchived(true);
      setNotice("项目已归档，可以在项目列表恢复。");
      return;
    }
    setProject((before) =>
      before?.id === state.project.id &&
      before.revision === state.project.revision
        ? before
        : state.project,
    );
    if (lastName.current !== state.project.id + state.project.name) {
      lastName.current = state.project.id + state.project.name;
      setName(state.project.name);
    }
    setAssets(state.assets);
    setSelection(state.selection);
    setHistory(state.history);
    setJobs(state.jobs);
    setSelected((before) =>
      state.project.document.layers.some((l) => l.id === before)
        ? before
        : (state.project.document.layers.at(-1)?.id ?? ""),
    );
  }
  function fit(doc = project?.document) {
    if (!doc) return;
    const scale = Math.max(
      0.04,
      Math.min(
        1,
        (size.width - 80) / doc.width,
        (size.height - 80) / doc.height,
      ),
    );
    setView({
      scale,
      x: (size.width - doc.width * scale) / 2,
      y: (size.height - doc.height * scale) / 2,
    });
  }
  async function run(work: () => Promise<void>) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await work();
    } catch (e) {
      setError(failures(e));
      if (activeId.current) await refresh(activeId.current).catch(() => {});
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }
  async function open(id: string) {
    await run(async () => {
      activeId.current = id;
      await refresh(id);
      localStorage.setItem("miniclaw.canvas.selected", id);
      setTool("move");
    });
  }
  useEffect(() => {
    void list().catch((e) => setError(failures(e)));
  }, [archived]);
  useEffect(() => {
    const saved = localStorage.getItem("miniclaw.canvas.selected");
    if (saved && !initialImport) void open(saved);
  }, []);
  useEffect(() => {
    if (!initialImport || importNonce.current === initialImport.nonce) return;
    importNonce.current = initialImport.nonce;
    void run(async () => {
      if (initialImport.attachment.canvas_project_id) {
        const id = initialImport.attachment.canvas_project_id;
        activeId.current = id;
        await refresh(id);
        localStorage.setItem("miniclaw.canvas.selected", id);
        return;
      }
      const created = await writeApi<Project>(
        "/api/miniclaw/canvas/projects",
        "POST",
        { name: initialImport.attachment.name.replace(/\.[^.]+$/, "") },
      );
      activeId.current = created.id;
      const asset = await writeApi<CanvasAsset>(
        `${projectPath(created.id)}/import-chat`,
        "POST",
        {
          session_id: initialImport.session,
          asset_id: initialImport.attachment.id,
        },
      );
      const doc = copyDoc(created.document);
      doc.width = Math.max(16, asset.width);
      doc.height = Math.max(16, asset.height);
      doc.layers.push(
        makeLayer("image", asset.name, asset.width, asset.height, {
          asset_id: asset.id,
        }),
      );
      const saved = await writeApi<Project>(
        `${projectPath(created.id)}/document`,
        "PUT",
        { revision: created.revision, document: doc, label: "导入聊天图片" },
      );
      await writeApi(`${projectPath(created.id)}`, "PATCH", {
        revision: saved.revision,
        session_id: initialImport.session,
      });
      await refresh(created.id);
      await list();
      fit(doc);
    });
  }, [initialImport?.nonce]);
  useEffect(() => {
    if (!host.current) return;
    const observer = new ResizeObserver((entries) => {
      const box = entries[0].contentRect;
      if (box.width > 0 && box.height > 0)
        setSize({
          width: Math.round(box.width),
          height: Math.round(box.height),
        });
    });
    observer.observe(host.current);
    return () => observer.disconnect();
  }, [project?.id]);
  useEffect(() => {
    if (project) fit(project.document);
  }, [project?.id, size.width, size.height]);
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const caps = await readApi<CanvasCapabilities>(
          "/api/miniclaw/canvas/capabilities",
        );
        if (alive) setCapabilities(caps);
        const id = activeId.current;
        if (id && !busyRef.current) await refresh(id);
      } catch (e) {
        if (alive) setError(failures(e));
      }
      if (alive) timer = setTimeout(poll, 3000);
    }
    void poll();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, []);
  async function save(doc: CanvasDocument, label: string) {
    if (!project) return;
    await writeApi<Project>(`${projectPath(project.id)}/document`, "PUT", {
      revision: project.revision,
      document: doc,
      label,
    });
    await refresh(project.id);
  }
  function editLayer(
    id: string,
    patch: Partial<CanvasLayer>,
    label = "调整图层",
  ) {
    void run(async () => {
      if (!project) return;
      const doc = copyDoc(project.document);
      const layer = doc.layers.find((l) => l.id === id);
      if (!layer) return;
      Object.assign(layer, patch);
      await save(doc, label);
    });
  }
  function addLayer(
    kind: "text" | "shape",
    shape: "rectangle" | "ellipse" = "rectangle",
  ) {
    void run(async () => {
      if (!project) return;
      const doc = copyDoc(project.document);
      const layer =
        kind === "text"
          ? makeLayer("text", "文字", 400, 120, {
              x: 60,
              y: 60,
              text: "在这里写文字",
              font_size: 36,
              fill: "#253147",
            })
          : makeLayer(
              "shape",
              shape === "ellipse" ? "椭圆" : "矩形",
              240,
              160,
              { x: 60, y: 60, shape, fill: "#5478e8" },
            );
      doc.layers.push(layer);
      await save(doc, "添加图层");
      setSelected(layer.id);
    });
  }
  async function addImage(file: File) {
    await run(async () => {
      if (!project) return;
      const asset = await uploadCanvas(project.id, file);
      const doc = copyDoc(project.document);
      const layer = makeLayer("image", asset.name, asset.width, asset.height, {
        asset_id: asset.id,
      });
      if (!doc.layers.length) {
        doc.width = Math.max(16, asset.width);
        doc.height = Math.max(16, asset.height);
      } else {
        const scale = Math.min(
          1,
          doc.width / asset.width,
          doc.height / asset.height,
        );
        layer.scale_x = scale;
        layer.scale_y = scale;
      }
      doc.layers.push(layer);
      await save(doc, "添加图片");
      setSelected(layer.id);
      fit(doc);
    });
  }
  function modify(action: "duplicate" | "remove" | "up" | "down") {
    void run(async () => {
      if (!project || !target || target.locked) return;
      const doc = copyDoc(project.document);
      const index = doc.layers.findIndex((l) => l.id === selected);
      if (action === "duplicate")
        doc.layers.splice(index + 1, 0, {
          ...doc.layers[index],
          id: crypto.randomUUID().replaceAll("-", ""),
          name: target.name + " 副本",
          x: target.x + 20,
          y: target.y + 20,
        });
      if (action === "remove") doc.layers.splice(index, 1);
      if (action === "up" && index < doc.layers.length - 1)
        [doc.layers[index], doc.layers[index + 1]] = [
          doc.layers[index + 1],
          doc.layers[index],
        ];
      if (action === "down" && index > 0)
        [doc.layers[index], doc.layers[index - 1]] = [
          doc.layers[index - 1],
          doc.layers[index],
        ];
      await save(doc, "调整图层");
    });
  }
  function select(points: number[][], mode = tool) {
    void run(async () => {
      if (!project || !target) return;
      const body = {
        revision: project.revision,
        layer_id: target.id,
        points,
        mode,
        radius,
        combine,
      };
      const result = await writeApi<Selection | null>(
        `${projectPath(project.id)}/${mode === "sam" ? "segment" : "selection"}`,
        "POST",
        mode === "sam" ? { ...body, point: points[0] } : body,
      );
      setSelection(result);
    });
  }
  function selectionAction(mode: "clear" | "invert") {
    select([], mode as CanvasTool);
  }
  function masked(operation: string) {
    void run(async () => {
      if (!project || !target) return;
      await writeApi(`${projectPath(project.id)}/masked`, "POST", {
        revision: project.revision,
        layer_id: target.id,
        selection_id: selection?.id,
        operation,
        params: operation === "adjust" ? { brightness } : {},
      });
      await refresh(project.id);
    });
  }
  function local(operation: string, params: object) {
    void run(async () => {
      if (!project || !target) return;
      await writeApi(`${projectPath(project.id)}/local`, "POST", {
        revision: project.revision,
        layer_id: target.id,
        operation,
        params,
      });
      await refresh(project.id);
    });
  }
  function crop(points: number[][]) {
    void run(async () => {
      if (!project) return;
      const doc = copyDoc(project.document);
      let x = Math.max(0, Math.round(Math.min(points[0][0], points[1][0]))),
        y = Math.max(0, Math.round(Math.min(points[0][1], points[1][1])));
      let width = Math.round(Math.abs(points[0][0] - points[1][0])),
        height = Math.round(Math.abs(points[0][1] - points[1][1]));
      if (cropRatio !== "free") {
        const [w, h] = cropRatio.split(":").map(Number);
        height = Math.round((width * h) / w);
      }
      width = Math.min(width, doc.width - x);
      height = Math.min(height, doc.height - y);
      if (width < 16 || height < 16) throw new Error("裁剪区域最小16×16像素");
      doc.width = width;
      doc.height = height;
      doc.layers.forEach((l) => {
        l.x -= x;
        l.y -= y;
      });
      await save(doc, "裁剪画布");
      setTool("move");
      fit(doc);
    });
  }
  function restore(seq: number) {
    void run(async () => {
      if (!project) return;
      await writeApi(`${projectPath(project.id)}/restore`, "POST", {
        revision: project.revision,
        seq,
      });
      await refresh(project.id);
    });
  }
  useEffect(() => {
    function key(event: KeyboardEvent) {
      if (
        !active ||
        !project ||
        busy ||
        (event.target instanceof HTMLElement &&
          /INPUT|TEXTAREA|SELECT/.test(event.target.tagName))
      )
        return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        const seq = project.cursor + (event.shiftKey ? 1 : -1);
        if (history.some((h) => h.seq === seq)) restore(seq);
      }
      if (event.key === "Delete") modify("remove");
      if (event.key === "Escape") setTool("move");
    }
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [project, busy, history, selected, active]);
  async function link() {
    if (!project || !chat.sessionId)
      throw new Error("请先在聊天页连接一个对话");
    await writeApi(projectPath(project.id), "PATCH", {
      revision: project.revision,
      session_id: chat.sessionId,
    });
    await refresh(project.id);
  }
  async function useInChat() {
    if (!project) return;
    if (project.chat_id !== chat.storedId) await link();
    const attachment = await writeApi<Attachment>(
      `${projectPath(project.id)}/send-chat`,
      "POST",
      { session_id: chat.sessionId },
    );
    onUse(attachment);
  }
  async function prepareAssistant() {
    if (!project || controller.connection !== "open")
      throw new Error("请先连接聊天服务");
    const configured = await readApi<{
      groups: { id: string; enabled: boolean }[];
    }>("/api/miniclaw/tools");
    const enabled = configured.groups.filter((g) => g.enabled).map((g) => g.id);
    await writeApi("/api/miniclaw/tools", "PUT", {
      enabled: [...new Set([...enabled, "miniclaw-files", "miniclaw-canvas"])],
    });
    const before = controller.state.sessionId;
    await controller.newSession();
    if (controller.state.sessionId === before)
      throw new Error(
        controller.state.error || "新建修图聊天失败，请回聊天页检查连接",
      );
    await writeApi(projectPath(project.id), "PATCH", {
      revision: project.revision,
      session_id: controller.state.sessionId,
    });
    await refresh(project.id);
  }
  const property = (
    label: string,
    key:
      | "x"
      | "y"
      | "rotation"
      | "scale_x"
      | "scale_y"
      | "opacity"
      | "font_size",
    min: number,
    max: number,
    step = 1,
  ) =>
    target && (
      <label className="canvas-field">
        {label}
        <input
          key={`${target.id}-${key}-${target[key]}`}
          type="number"
          defaultValue={target[key]}
          min={min}
          max={max}
          step={step}
          disabled={busy || target.locked}
          onBlur={(event) => {
            const value = Number(event.target.value);
            if (Number.isFinite(value) && value !== target[key])
              editLayer(target.id, { [key]: value });
          }}
        />
      </label>
    );
  return (
    <section className="canvas-app" aria-label="图片工作区">
      <header className="canvas-header">
        <button
          className="canvas-wordmark"
          onClick={() => {
            activeId.current = "";
            setProject(undefined);
            localStorage.removeItem("miniclaw.canvas.selected");
            void list();
          }}
          disabled={busy}
        >
          miniclaw <span>/ 图片</span>
        </button>
        {project && (
          <input
            aria-label="项目名称"
            className="canvas-title"
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={busy}
            onBlur={() => {
              if (name !== project.name)
                void run(async () => {
                  await writeApi(projectPath(project.id), "PATCH", {
                    revision: project.revision,
                    name,
                  });
                  await refresh(project.id);
                });
            }}
          />
        )}
        <span className="canvas-saved">
          {busy ? "正在保存…" : project ? "已保存" : "独立图片项目"}
        </span>
        <button onClick={onChat}>聊天</button>
        {project && (
          <>
            <button
              onClick={() =>
                void run(async () => {
                  await downloadCanvas(project.id);
                })
              }
              disabled={busy}
            >
              导出 PNG
            </button>
            <button
              className="canvas-primary"
              onClick={() => void run(useInChat)}
              disabled={busy || !chat.sessionId}
            >
              用于聊天
            </button>
          </>
        )}
      </header>
      {(error || notice) && (
        <div
          className={`canvas-banner ${error ? "is-error" : ""}`}
          role={error ? "alert" : "status"}
        >
          <span>{error || notice}</span>
          <button
            onClick={() => {
              setError("");
              setNotice("");
            }}
            aria-label="关闭提示"
          >
            ×
          </button>
        </div>
      )}
      {!project ? (
        <div className="canvas-projects">
          <div className="canvas-projects-title">
            <div>
              <p>图片工作区</p>
              <h1>把一张图，做成你想要的样子。</h1>
              <span>独立画布 · 图层编辑 · 局部修图</span>
            </div>
            <button
              className="canvas-primary"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  const p = await writeApi<Project>(
                    "/api/miniclaw/canvas/projects",
                    "POST",
                    { name: "未命名图片项目" },
                  );
                  activeId.current = p.id;
                  await refresh(p.id);
                  localStorage.setItem("miniclaw.canvas.selected", p.id);
                })
              }
            >
              ＋ 新建图片项目
            </button>
          </div>
          <div className="canvas-project-filter">
            <input
              aria-label="搜索图片项目"
              placeholder="搜索项目"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <button
              aria-pressed={archived}
              onClick={() => setArchived(!archived)}
            >
              {archived ? "返回项目" : "已归档"}
            </button>
          </div>
          <div className="canvas-project-grid">
            {projects
              .filter((p) =>
                p.name.toLowerCase().includes(search.toLowerCase()),
              )
              .map((p) => (
                <article key={p.id}>
                  <button
                    className="canvas-project-open"
                    onClick={() => void open(p.id)}
                    disabled={busy || p.archived}
                  >
                    <div className="canvas-project-art">▧</div>
                    <strong>{p.name}</strong>
                    <span>
                      {new Date(p.updated * 1000).toLocaleString("zh-CN")}
                      {p.chat_id ? " · 已关联聊天" : ""}
                    </span>
                  </button>
                  <button
                    className="canvas-project-archive"
                    disabled={busy}
                    onClick={() =>
                      void run(async () => {
                        await writeApi(projectPath(p.id), "PATCH", {
                          revision: p.revision,
                          archived: !p.archived,
                        });
                        await list();
                      })
                    }
                  >
                    {p.archived ? "恢复" : "归档"}
                  </button>
                </article>
              ))}
          </div>
          {!projects.length && (
            <p className="canvas-empty">
              {archived
                ? "没有归档项目"
                : "从空白画布开始，或者从聊天图片进入这里。"}
            </p>
          )}
        </div>
      ) : (
        <>
          <div className="canvas-commandbar">
            <button disabled={busy} onClick={() => upload.current?.click()}>
              ＋ 图片
            </button>
            <button disabled={busy} onClick={() => addLayer("text")}>
              文字
            </button>
            <button disabled={busy} onClick={() => addLayer("shape")}>
              矩形
            </button>
            <button
              disabled={busy}
              onClick={() => addLayer("shape", "ellipse")}
            >
              椭圆
            </button>
            <span className="canvas-command-divider" />
            <button
              aria-label="撤销"
              disabled={
                busy || !history.some((h) => h.seq === project.cursor - 1)
              }
              onClick={() => restore(project.cursor - 1)}
            >
              ↶
            </button>
            <button
              aria-label="重做"
              disabled={
                busy || !history.some((h) => h.seq === project.cursor + 1)
              }
              onClick={() => restore(project.cursor + 1)}
            >
              ↷
            </button>
            <button
              className="canvas-panel-toggle"
              onClick={() => setDrawer(!drawer)}
            >
              图层与操作
            </button>
            <input
              ref={upload}
              hidden
              type="file"
              accept="image/png,image/jpeg,image/webp"
              aria-label="添加画布图片"
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (file) void addImage(file);
              }}
            />
          </div>
          <div className="canvas-editor">
            <nav className="canvas-tools" aria-label="画布工具">
              {tools.map((t) => (
                <button
                  key={t.id}
                  aria-label={t.label}
                  title={t.label}
                  aria-pressed={tool === t.id}
                  disabled={
                    busy ||
                    (t.id === "sam" && capabilities?.sam.state !== "ready")
                  }
                  onClick={() => setTool(t.id)}
                >
                  <span>{t.icon}</span>
                  <small>{t.label.slice(0, 2)}</small>
                </button>
              ))}
            </nav>
            <div className={`canvas-surface tool-${tool}`} ref={host}>
              <CanvasStage
                project={project.id}
                document={project.document}
                assets={assets}
                selection={selection}
                selected={selected}
                tool={tool}
                busy={busy}
                view={view}
                setView={setView}
                onSelect={setSelected}
                onChange={editLayer}
                onPath={select}
                onCrop={crop}
                size={size}
              />
              {!project.document.layers.length && (
                <div className="canvas-start">
                  <strong>你的画布已准备好</strong>
                  <span>添加图片，或写下第一行文字</span>
                  <button
                    className="canvas-primary"
                    onClick={() => upload.current?.click()}
                  >
                    添加图片
                  </button>
                </div>
              )}
              <div className="canvas-viewbar">
                <button
                  onClick={() =>
                    setView({
                      ...view,
                      scale: Math.max(0.04, view.scale * 0.8),
                    })
                  }
                  aria-label="缩小画布"
                >
                  −
                </button>
                <span>{Math.round(view.scale * 100)}%</span>
                <button
                  onClick={() =>
                    setView({ ...view, scale: Math.min(8, view.scale * 1.25) })
                  }
                  aria-label="放大画布"
                >
                  ＋
                </button>
                <button onClick={() => fit()}>适应</button>
                <button onClick={() => setView({ scale: 1, x: 30, y: 30 })}>
                  1:1
                </button>
              </div>
            </div>
            <aside className={`canvas-inspector ${drawer ? "is-open" : ""}`}>
              <div className="canvas-tabs">
                {(["layers", "history", "assistant"] as const).map((tab) => (
                  <button
                    key={tab}
                    aria-pressed={panel === tab}
                    onClick={() => setPanel(tab)}
                  >
                    {tab === "layers"
                      ? "图层"
                      : tab === "history"
                        ? "历史"
                        : "助手"}
                  </button>
                ))}
                <button
                  className="canvas-drawer-close"
                  onClick={() => setDrawer(false)}
                  aria-label="关闭操作面板"
                >
                  ×
                </button>
              </div>
              {panel === "layers" && (
                <div className="canvas-panel-content">
                  <div className="canvas-section-heading">
                    <strong>图层</strong>
                    <span>{project.document.layers.length} / 40</span>
                  </div>
                  <div className="canvas-layer-list">
                    {[...project.document.layers].reverse().map((l) => (
                      <div
                        key={l.id}
                        className={`canvas-layer-row ${selected === l.id ? "selected" : ""}`}
                      >
                        <button
                          className="canvas-layer-select"
                          onClick={() => setSelected(l.id)}
                        >
                          <span>
                            {l.kind === "image"
                              ? "▧"
                              : l.kind === "text"
                                ? "T"
                                : "◇"}
                          </span>
                          <span>{l.name}</span>
                        </button>
                        <button
                          title={l.visible ? "隐藏图层" : "显示图层"}
                          disabled={busy || l.locked}
                          onClick={() =>
                            editLayer(l.id, { visible: !l.visible })
                          }
                        >
                          {l.visible ? "◉" : "○"}
                        </button>
                        <button
                          title={l.locked ? "解锁图层" : "锁定图层"}
                          disabled={busy}
                          onClick={() => editLayer(l.id, { locked: !l.locked })}
                        >
                          {l.locked ? "▣" : "▫"}
                        </button>
                      </div>
                    ))}
                  </div>
                  {target && (
                    <>
                      <div className="canvas-section-heading">
                        <strong>属性</strong>
                        <span>{target.locked ? "已锁定" : ""}</span>
                      </div>
                      <label className="canvas-field">
                        名称
                        <input
                          key={target.id + target.name}
                          defaultValue={target.name}
                          disabled={busy || target.locked}
                          onBlur={(e) => {
                            if (e.target.value !== target.name)
                              editLayer(target.id, { name: e.target.value });
                          }}
                        />
                      </label>
                      <div className="canvas-fields-grid">
                        {property("X", "x", -8192, 8192)}
                        {property("Y", "y", -8192, 8192)}
                        {property("横向缩放", "scale_x", 0.02, 20, 0.05)}
                        {property("纵向缩放", "scale_y", 0.02, 20, 0.05)}
                        {property("旋转°", "rotation", -36000, 36000)}
                        {property("透明度", "opacity", 0, 1, 0.05)}
                      </div>
                      {target.kind === "text" && (
                        <>
                          <label className="canvas-field">
                            文字
                            <textarea
                              key={target.id + target.text}
                              defaultValue={target.text}
                              disabled={busy || target.locked}
                              onBlur={(e) => {
                                if (e.target.value !== target.text)
                                  editLayer(target.id, {
                                    text: e.target.value,
                                  });
                              }}
                            />
                          </label>
                          {property("字号", "font_size", 8, 256)}
                        </>
                      )}
                      {target.kind !== "image" && (
                        <label className="canvas-field">
                          颜色
                          <input
                            type="color"
                            value={target.fill?.slice(0, 7)}
                            disabled={busy || target.locked}
                            onChange={(e) =>
                              editLayer(target.id, { fill: e.target.value })
                            }
                          />
                        </label>
                      )}
                      <div className="canvas-button-grid">
                        <button
                          disabled={busy || target.locked}
                          onClick={() => modify("up")}
                        >
                          上移
                        </button>
                        <button
                          disabled={busy || target.locked}
                          onClick={() => modify("down")}
                        >
                          下移
                        </button>
                        <button
                          disabled={busy || target.locked}
                          onClick={() => modify("duplicate")}
                        >
                          复制
                        </button>
                        <button
                          disabled={busy || target.locked}
                          onClick={() => modify("remove")}
                        >
                          删除
                        </button>
                      </div>
                      {target.kind === "image" && (
                        <div className="canvas-button-grid">
                          <button
                            disabled={busy || target.locked}
                            onClick={() =>
                              local("flip", { direction: "horizontal" })
                            }
                          >
                            水平翻转
                          </button>
                          <button
                            disabled={busy || target.locked}
                            onClick={() =>
                              local("flip", { direction: "vertical" })
                            }
                          >
                            垂直翻转
                          </button>
                          <button
                            disabled={busy || target.locked}
                            onClick={() => local("rotate", { angle: 90 })}
                          >
                            旋转90°
                          </button>
                          <button
                            disabled={busy || target.locked}
                            onClick={() => local("adjust", { brightness })}
                          >
                            整层调色
                          </button>
                        </div>
                      )}
                    </>
                  )}
                  <div className="canvas-section-heading">
                    <strong>{tool === "crop" ? "裁剪" : "选区"}</strong>
                    <span>
                      {selection?.layer_id === selected ? "已选择" : "未选择"}
                    </span>
                  </div>
                  {tool === "crop" ? (
                    <>
                      <label className="canvas-field">
                        比例
                        <select
                          value={cropRatio}
                          onChange={(e) => setCropRatio(e.target.value)}
                        >
                          {["free", "1:1", "4:5", "9:16", "16:9"].map((r) => (
                            <option key={r} value={r}>
                              {r === "free" ? "自由裁剪" : r}
                            </option>
                          ))}
                        </select>
                      </label>
                      <p className="canvas-hint">
                        拖出裁剪区域后保存。锁定的图层需先解锁。
                      </p>
                    </>
                  ) : (
                    <>
                      <label className="canvas-field">
                        组合
                        <select
                          value={combine}
                          onChange={(e) => setCombine(e.target.value)}
                        >
                          <option value="replace">新选区</option>
                          <option value="add">增加选区</option>
                          <option value="subtract">擦除选区</option>
                        </select>
                      </label>
                      <label className="canvas-field">
                        笔刷半径
                        <input
                          type="range"
                          min={1}
                          max={128}
                          value={radius}
                          onChange={(e) => setRadius(Number(e.target.value))}
                        />
                        <span>{radius}px</span>
                      </label>
                      <div className="canvas-button-grid">
                        <button
                          disabled={busy || !selection}
                          onClick={() => selectionAction("clear")}
                        >
                          清除
                        </button>
                        <button
                          disabled={busy || !selection}
                          onClick={() => selectionAction("invert")}
                        >
                          反选
                        </button>
                      </div>
                      {target?.kind === "image" && !target.locked ? (
                        <>
                          <p className="canvas-hint">
                            选区仅作用于「{target.name}
                            」。框选、套索或笔刷都可用。
                          </p>
                          <label className="canvas-field">
                            亮度
                            <input
                              type="range"
                              min={-1}
                              max={1}
                              step={0.05}
                              value={brightness}
                              onChange={(e) =>
                                setBrightness(Number(e.target.value))
                              }
                            />
                            <span>{Math.round(brightness * 100)}%</span>
                          </label>
                          <div className="canvas-button-grid">
                            <button
                              disabled={
                                busy || selection?.layer_id !== selected
                              }
                              onClick={() => masked("adjust")}
                            >
                              选区调色
                            </button>
                            <button
                              disabled={
                                busy || selection?.layer_id !== selected
                              }
                              onClick={() => masked("erase")}
                            >
                              擦除为透明
                            </button>
                            <button
                              disabled={
                                busy || selection?.layer_id !== selected
                              }
                              onClick={() => masked("extract")}
                            >
                              提取图层
                            </button>
                          </div>
                        </>
                      ) : (
                        <p className="canvas-hint">
                          选择一个未锁定的图片图层后，再编辑选区。
                        </p>
                      )}
                      <button
                        className="canvas-sam-prepare"
                        disabled={
                          busy ||
                          capabilities?.sam.state === "preparing" ||
                          capabilities?.sam.state === "ready"
                        }
                        onClick={() =>
                          void run(async () => {
                            await writeApi(
                              "/api/miniclaw/canvas/sam/prepare",
                              "POST",
                              {},
                            );
                            setNotice(
                              "正在准备SAM本地模型，首次需要下载权重。",
                            );
                          })
                        }
                      >
                        {capabilities?.sam.state === "ready"
                          ? "SAM 点选已就绪"
                          : capabilities?.sam.state === "preparing"
                            ? "SAM 模型准备中…"
                            : "准备 SAM 点选模型"}
                      </button>
                      {capabilities?.sam.error && (
                        <p className="canvas-hint">{capabilities.sam.error}</p>
                      )}
                    </>
                  )}
                  <div className="canvas-section-heading">
                    <strong>画布</strong>
                    <span>
                      {project.document.width} × {project.document.height}
                    </span>
                  </div>
                  <div className="canvas-fields-grid">
                    {(["width", "height"] as const).map((k) => (
                      <label className="canvas-field" key={k}>
                        {k === "width" ? "宽度" : "高度"}
                        <input
                          key={k + project.document[k]}
                          type="number"
                          min={16}
                          max={4096}
                          defaultValue={project.document[k]}
                          disabled={busy}
                          onBlur={(e) => {
                            const n = Number(e.target.value);
                            if (n !== project.document[k])
                              void run(() =>
                                save(
                                  { ...copyDoc(project.document), [k]: n },
                                  "调整画布尺寸",
                                ),
                              );
                          }}
                        />
                      </label>
                    ))}
                  </div>
                  <label className="canvas-field">
                    背景
                    <input
                      type="color"
                      value={project.document.background.slice(0, 7)}
                      disabled={busy}
                      onChange={(e) =>
                        void run(() =>
                          save(
                            {
                              ...copyDoc(project.document),
                              background: e.target.value,
                            },
                            "调整画布背景",
                          ),
                        )
                      }
                    />
                    <button
                      disabled={busy}
                      onClick={() =>
                        void run(() =>
                          save(
                            {
                              ...copyDoc(project.document),
                              background: "#ffffff00",
                            },
                            "透明背景",
                          ),
                        )
                      }
                    >
                      透明
                    </button>
                  </label>
                </div>
              )}
              {panel === "history" && (
                <div className="canvas-panel-content">
                  <p className="canvas-hint">
                    保存操作形成版本，最多保留最近101个。撤销后继续编辑会建立新分支。
                  </p>
                  {history.map((v) => (
                    <div
                      className={`canvas-version ${v.current ? "current" : ""}`}
                      key={v.seq}
                    >
                      <strong>{v.label}</strong>
                      <span>
                        版本 {v.seq} ·{" "}
                        {new Date(v.time * 1000).toLocaleTimeString()}
                      </span>
                      <div>
                        <button
                          disabled={busy || v.current}
                          onClick={() => restore(v.seq)}
                        >
                          {v.current ? "当前" : "恢复"}
                        </button>
                        <button onClick={() => setCompare(v.seq)}>对比</button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {panel === "assistant" && (
                <div className="canvas-panel-content">
                  <div className="canvas-section-heading">
                    <strong>AI 修图</strong>
                    <span>百炼</span>
                  </div>
                  <p className="canvas-hint">
                    {target ? `目标：${target.name}` : "先选择图片图层"}
                    。结果先生成候选，再比较、采用。
                  </p>
                  <label className="canvas-field">
                    处理范围
                    <select
                      value={region ? "region" : "layer"}
                      onChange={(e) => setRegion(e.target.value === "region")}
                    >
                      <option value="region">当前选区</option>
                      <option value="layer">整张图片图层</option>
                    </select>
                  </label>
                  <label className="canvas-field">
                    修图要求
                    <textarea
                      value={prompt}
                      maxLength={2000}
                      placeholder="例如：把选中的污点自然去掉，保留背景纹理"
                      onChange={(e) => setPrompt(e.target.value)}
                    />
                  </label>
                  <label className="canvas-field">
                    向内羽化
                    <input
                      type="range"
                      min={0}
                      max={20}
                      value={feather}
                      onChange={(e) => setFeather(Number(e.target.value))}
                    />
                    <span>{feather}px</span>
                  </label>
                  <button
                    className="canvas-primary"
                    disabled={
                      busy ||
                      !!activeJob ||
                      !prompt.trim() ||
                      target?.kind !== "image" ||
                      target.locked ||
                      !capabilities?.cloud.configured ||
                      (region && selection?.layer_id !== selected)
                    }
                    onClick={() =>
                      void run(async () => {
                        await writeApi(
                          `${projectPath(project.id)}/jobs`,
                          "POST",
                          {
                            revision: project.revision,
                            layer_id: selected,
                            prompt,
                            request_id: crypto.randomUUID(),
                            region,
                            feather,
                            selection_id: region ? selection?.id : undefined,
                          },
                        );
                        await refresh(project.id);
                      })
                    }
                  >
                    生成候选 · 可能计费
                  </button>
                  {jobs.map((j) => (
                    <div className="canvas-job" key={j.id}>
                      <strong>
                        {j.state === "succeeded"
                          ? "候选已生成"
                          : j.state === "running"
                            ? "正在修图"
                            : j.state === "queued"
                              ? "等待处理"
                              : j.state === "canceled"
                                ? "已取消"
                                : "处理失败"}
                      </strong>
                      <p>{j.prompt}</p>
                      {j.error && <p role="status">{j.error}</p>}
                      {j.output && (
                        <>
                          <ImageComparison
                            owner={projectOwner(project.id)}
                            source={assets.find((a) => a.id === j.source_id)!}
                            output={j.output}
                          />
                          <div className="canvas-button-grid">
                            <button
                              disabled={busy || project.revision !== j.revision}
                              onClick={() =>
                                void run(async () => {
                                  await writeApi(
                                    `${projectPath(project.id)}/jobs/${j.id}/adopt`,
                                    "POST",
                                    { revision: project.revision },
                                  );
                                  await refresh(project.id);
                                })
                              }
                            >
                              采用到原层
                            </button>
                            <button
                              disabled={busy}
                              onClick={() =>
                                void run(async () => {
                                  const doc = copyDoc(project.document);
                                  doc.layers.push(
                                    makeLayer(
                                      "image",
                                      "AI 候选",
                                      j.output!.width,
                                      j.output!.height,
                                      { asset_id: j.output!.id },
                                    ),
                                  );
                                  await save(doc, "添加AI候选图层");
                                })
                              }
                            >
                              另加图层
                            </button>
                          </div>
                          {project.revision !== j.revision && (
                            <p className="canvas-hint">
                              画布已更新，候选可作为新图层添加。
                            </p>
                          )}
                        </>
                      )}
                      {["running", "queued"].includes(j.state) && (
                        <button
                          disabled={busy}
                          onClick={() =>
                            void run(async () => {
                              await writeApi(
                                `${projectPath(project.id)}/jobs/${j.id}/cancel`,
                                "POST",
                                {},
                              );
                              await refresh(project.id);
                            })
                          }
                        >
                          取消接收
                        </button>
                      )}
                    </div>
                  ))}
                  <div className="canvas-section-heading">
                    <strong>修图助手</strong>
                    <span>Hermes</span>
                  </div>
                  <p className="canvas-hint">
                    {project.chat_id === chat.storedId
                      ? "已关联当前聊天"
                      : "可关联一个聊天，由同一个Agent继续操作。"}
                  </p>
                  <button
                    disabled={busy || chat.running || !chat.sessionId}
                    onClick={() => void run(link)}
                  >
                    关联当前聊天
                  </button>
                  {project.chat_id && project.chat_id !== chat.storedId && (
                    <button
                      disabled={busy || chat.running || chat.busy}
                      onClick={() => void controller.open(project.chat_id!)}
                    >
                      打开关联聊天
                    </button>
                  )}
                  {!canAssist && (
                    <div>
                      <p className="canvas-hint">
                        当前聊天未加载画布工具，新聊天才能使用新增能力。
                      </p>
                      <button
                        disabled={
                          busy ||
                          chat.running ||
                          chat.busy ||
                          controller.connection !== "open"
                        }
                        onClick={() => void run(prepareAssistant)}
                      >
                        启用画布工具并新建聊天
                      </button>
                      <button onClick={onSettings}>设置工具</button>
                    </div>
                  )}
                  <textarea
                    aria-label="给修图助手的消息"
                    placeholder="例如：把当前选区提取成独立图层"
                    value={assistant}
                    onChange={(e) => setAssistant(e.target.value)}
                  />
                  <button
                    disabled={
                      busy ||
                      chat.running ||
                      chat.busy ||
                      !canAssist ||
                      !assistant.trim() ||
                      !target ||
                      project.chat_id !== chat.storedId
                    }
                    onClick={() => {
                      void controller
                        .send(assistant, "canvas-editor", [], {
                          project_id: project.id,
                          revision: project.revision,
                          layer_id: selected,
                        })
                        .then((ok) => {
                          if (ok) setAssistant("");
                        });
                    }}
                  >
                    发送给助手
                  </button>
                  {chat.error && <p role="alert">{chat.error}</p>}
                  {chat.running && (
                    <p className="canvas-hint">
                      {chat.status || "助手正在处理…"}
                    </p>
                  )}
                  <div className="canvas-assistant-messages">
                    {project.chat_id === chat.storedId &&
                      chat.items
                        .slice(-6)
                        .map((item) => (
                          <Message
                            key={item.id}
                            item={item}
                            owner={chat.storedId}
                            onReuse={setAssistant}
                          />
                        ))}
                  </div>
                </div>
              )}
              <div className="canvas-mobile-use">
                <button
                  className="canvas-primary"
                  disabled={busy || !chat.sessionId}
                  onClick={() => void run(useInChat)}
                >
                  把画布放入聊天草稿
                </button>
              </div>
            </aside>
          </div>
          <footer className="canvas-statusbar">
            <span>
              {tools.find((t) => t.id === tool)?.label}{" "}
              {target ? `· ${target.name}` : ""}
            </span>
            <span>
              画布 {project.document.width} × {project.document.height} · 版本{" "}
              {project.cursor}
            </span>
          </footer>
        </>
      )}
      {project && compare !== undefined && (
        <ProjectCompare
          project={project.id}
          seq={compare}
          onClose={() => setCompare(undefined)}
        />
      )}
    </section>
  );
}
