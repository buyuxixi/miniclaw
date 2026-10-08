import { useEffect, useRef, useState } from "react";
import { readApi, writeApi } from "./management-api";
import {
  creatorBase,
  creatorBlob,
  getCreator,
  saveCreator,
  uploadCreator,
  type CreatorFile,
  type CreatorContext,
  type CreatorProject,
  type CreatorReturn,
} from "./creator-api";
import { attachmentBlob } from "./attachments";
import { briefFields, briefPrompt, type BriefCandidate } from './creator-candidates';
import { nextCreation } from './creator-guide';
import { photographyPrompt, photoPresets, type CanvasDesignRequest } from './photo-design';
import "./creator.css";
const stages = [
  ["facts", "方向", "确定商品与创作方向"],
  ["cover", "图片", "在画布里打磨图片"],
  ["script", "口播", "在Chat里打磨主稿"],
  ["video", "视频", "配音、字幕与合成"],
  ["package", "导出", "文案与发布包"],
];
const slotNames: Record<string, string> = {
  source: "商品原图",
  video: "原视频",
  srt: "同版字幕 SRT",
  plan: "动效编排 JSON",
  overlay: "透明动效 MOV",
  cover: "封面图片",
  detail: "材质特写",
  scene: "场景图片",
};
const accepts: Record<string, string> = {
  source: ".png,.jpg,.jpeg,.webp",
  video: ".mp4,.mov,.webm",
  srt: ".srt",
  plan: ".json",
  overlay: ".mov",
  cover: ".png,.jpg,.jpeg,.webp",
  detail: ".png,.jpg,.jpeg,.webp",
  scene: ".png,.jpg,.jpeg,.webp",
};
const jobNames = {
  queued: "排队中",
  running: "合成中",
  succeeded: "合成完成",
  failed: "合成失败",
  canceled: "已取消",
};
type Draft = Pick<
  CreatorProject,
  | "name"
  | "facts"
  | "selling_points"
  | "audience"
  | "style"
  | "constraints"
  | "script"
  | "caption"
  | "provenance"
  | "mode"
  | "method"
  | "speech_style"
  | "keep_source_audio"
>;
function draftOf(p: CreatorProject): Draft {
  return {
    name: p.name,
    facts: p.facts,
    selling_points: p.selling_points || "",
    audience: p.audience || "",
    style: p.style || "",
    constraints: p.constraints || "",
    script: p.script,
    caption: p.caption,
    provenance: p.provenance,
    mode: p.mode,
    method: p.method,
    speech_style: p.speech_style || "standard",
    keep_source_audio: p.keep_source_audio || false,
  };
}
function ResultFile({
  project,
  file,
  preview = false,
  image = false,
  imageLabel = "封面",
  poster,
}: {
  project: string;
  file: CreatorFile;
  preview?: boolean;
  image?: boolean;
  imageLabel?: string;
  poster?: CreatorFile;
}) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const [posterUrl, setPosterUrl] = useState("");
  useEffect(() => {
    let objectUrl = "";
    const abort = new AbortController();
    setPosterUrl("");
    if (preview && poster)
      void creatorBlob(project, poster.id, abort.signal)
        .then((blob) => {
          if (!abort.signal.aborted) {
            objectUrl = URL.createObjectURL(blob);
            setPosterUrl(objectUrl);
          }
        })
        .catch(() => {});
    return () => {
      abort.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [project, preview, poster?.id]);
  useEffect(() => {
    let objectUrl = "";
    const abort = new AbortController();
    setUrl("");
    setError("");
    void creatorBlob(project, file.id, abort.signal)
      .then((blob) => {
        if (!abort.signal.aborted) {
          objectUrl = URL.createObjectURL(blob);
          setUrl(objectUrl);
        }
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(String(e));
      });
    return () => {
      abort.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [project, file.id]);
  return (
    <div className="creator-result">
      {preview && url && (
        <video
          controls
          playsInline
          preload="metadata"
          src={url}
          poster={posterUrl || undefined}
          aria-label="成片预览"
        />
      )}
      {image && url && <img src={url} alt={`当前项目${imageLabel}`} />}
      <p>
        {file.width ? `${file.width} × ${file.height} · ` : ""}
        {file.duration ? `${file.duration.toFixed(1)} 秒 · ` : ""}
        {(file.bytes / 1024 / 1024).toFixed(1)} MiB
      </p>
      {url ? (
        <a href={url} download={file.name}>
          ↓ 下载{preview ? "成片" : image ? imageLabel : "发布包"}
        </a>
      ) : (
        <span role="status">{error || "正在准备文件…"}</span>
      )}
    </div>
  );
}
function CoverReturn({
  incoming,
}: {
  incoming: Extract<CreatorReturn, { kind: "cover" }>;
}) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let objectUrl = "";
    const abort = new AbortController();
    void attachmentBlob(
      incoming.owner,
      {
        id: incoming.attachment,
        name: incoming.name,
        kind: "image",
        mime: "image/png",
        bytes: 0,
      },
      abort.signal,
    )
      .then((blob) => {
        if (!abort.signal.aborted) {
          objectUrl = URL.createObjectURL(blob);
          setUrl(objectUrl);
        }
      })
      .catch(() => {
        if (!abort.signal.aborted) setError("图片读取失败，请重新导出");
      });
    return () => {
      abort.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [incoming.nonce]);
  return url ? (
    <img className="creator-return-image" src={url} alt="待采用的修图结果" />
  ) : (
    <p role="status">{error || "正在读取修图结果…"}</p>
  );
}
export default function CreatorWorkspace({
  active,
  onChat,
  onCanvas,
  onDraft,
  incoming,
  onReturnDone,
  onBack,
  selectedProject,
}: {
  active: boolean;
  selectedProject?: string;
  onChat: (p?: CreatorProject, node?: CreatorContext['node']) => void | CreatorProject | Promise<void | CreatorProject>;
  onCanvas: (
    p?: CreatorProject,
    design?: CanvasDesignRequest,
  ) => void | CreatorProject | Promise<void | CreatorProject>;
  onDraft: (
    text: string,
    p?: CreatorProject,
    node?: CreatorContext['node'],
  ) => void | CreatorProject | Promise<void | CreatorProject>;
  incoming?: CreatorReturn;
  onReturnDone?: () => void;
  onBack?: () => void;
}) {
  const [rows, setRows] = useState<{ id: string; name: string }[]>([]);
  const [project, setProject] = useState<CreatorProject>();
  const [draft, setDraft] = useState<Draft>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [stage, setStage] = useState("facts");
  const [advanced, setAdvanced] = useState(false);
  const [goal, setGoal] = useState('');
  const [manual, setManual] = useState(false);
  const sourceInput = useRef<HTMLInputElement>(null);
  const [review, setReview] = useState<CreatorReturn>();
  const [reviewText, setReviewText] = useState("");
  const [reviewBrief, setReviewBrief] = useState<BriefCandidate>();
  const [cap, setCap] = useState<{
    video: boolean;
    font: boolean;
    speech?: { configured: boolean; model: string; voice: string };
  }>();
  const current = useRef(project);
  current.current = project;
  const dirty =
    !!project &&
    !!draft &&
    JSON.stringify(draft) !== JSON.stringify(draftOf(project));
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  const handled = useRef<number | undefined>(undefined);
  const reviewDialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (review && reviewDialog.current) {
      if (typeof reviewDialog.current.showModal === "function")
        reviewDialog.current.showModal();
      else reviewDialog.current.setAttribute("open", "");
    }
  }, [review?.nonce]);
  async function load(id: string) {
    const p = await getCreator(id);
    setProject(p);
    setDraft(draftOf(p));
    localStorage.setItem("miniclaw.creator", id);
    const video = p.outputs.some((o) => o.current);
    setStage(video ? 'video' : nextCreation(p).stage);
    setAdvanced(video);
    setGoal('');
    setManual(false);
  }
  async function task(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  async function handOff(
    fn: () => void | CreatorProject | Promise<void | CreatorProject>,
  ) {
    await task(async () => {
      const p = await fn();
      if (p) {
        setProject(p);
        setDraft(draftOf(p));
      }
    });
  }
  useEffect(() => {
    if (!active) return;
    void task(async () => {
      const list = await readApi<{ id: string; name: string }[]>(
        `${creatorBase}/projects`,
      );
      setRows(list);
      setCap(await readApi(`${creatorBase}/capabilities`));
      const wanted = incoming?.project || selectedProject;
      if (wanted && current.current?.id !== wanted && !dirtyRef.current) {
        await load(wanted);
      } else if (!current.current) {
        const id = localStorage.getItem("miniclaw.creator");
        if (id && list.some((p) => p.id === id)) await load(id);
      } else if (!dirtyRef.current) {
        const p = await getCreator(current.current.id);
        if (current.current?.id === p.id && !dirtyRef.current) {
          setProject(p);
          setDraft(draftOf(p));
        }
      }
    });
  }, [active, selectedProject, incoming?.nonce]);
  useEffect(() => {
    if (!active || !incoming || handled.current === incoming.nonce || !project)
      return;
    if (project.id !== incoming.project && !dirty) return;
    handled.current = incoming.nonce;
    if (
      project.id !== incoming.project ||
      project.revision !== incoming.revision ||
      (project.chat_id && project.chat_id !== incoming.owner) ||
      dirty
    ) {
      setError(
        "回传目标或版本已变化，未覆盖现有内容。请保存后，从当前项目重新进入Chat或修图。",
      );
      return;
    }
    setReview(incoming);
    setReviewText(incoming.kind === "script" ? incoming.text : "");
    setReviewBrief(incoming.kind === 'brief' ? incoming.fields : undefined);
    setStage(incoming.kind === "brief" ? "facts" : incoming.kind === "script" ? "script" : "cover");
  }, [active, incoming?.nonce, project?.id, project?.revision, dirty]);
  const rendering = project?.jobs.some(
    (j) => j.state === "queued" || j.state === "running",
  );
  useEffect(() => {
    if (!active || !rendering || !project) return;
    let stopped = false;
    const id = project.id;
    const timer = setInterval(() => {
      void getCreator(id)
        .then((p) => {
          if (
            !stopped &&
            current.current?.id === id &&
            p.revision >= current.current.revision
          )
            setProject(p);
        })
        .catch((e) => {
          if (!stopped) setError(String(e));
        });
    }, 1500);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [active, project?.id, rendering]);
  const output = project?.outputs.filter((o) => o.current).at(-1);
  const pack = project?.packages.filter((p) => p.current).at(-1);
  async function save() {
    if (!project || !draft) return;
    const p = await saveCreator(project, draft);
    setProject(p);
    setDraft(draftOf(p));
    setRows((r) =>
      r.map((v) => (v.id === p.id ? { id: p.id, name: p.name } : v)),
    );
  }
  async function guidedDraft(node: 'brief' | 'script' = 'brief') {
    if (!project || !draft) return;
    await task(async () => {
      const p = dirty ? await saveCreator(project, draft) : project;
      setProject(p); setDraft(draftOf(p));
      const script = node === 'script';
      const prompt = script
        ? `请按本项目事实、卖点、受众和采用图片，写一段自然口播。四句、70到110字：面向目标人群的开头，两句有图片证据的具体特点，一个自然的比较或了解建议。未知材质、工艺、性能、价格不编造，不读背景衣服。只把要读出的正文放在主稿，备选和核对事项分开。\n现有主稿：${p.script}`
        : briefPrompt;
      const linked = await onDraft(`${prompt}${goal.trim() ? '\n我的创作目标：' + goal.trim() : ''}`, p, script ? 'script' : 'brief');
      if (linked) { setProject(linked); setDraft(draftOf(linked)); }
    });
  }
  async function choose(id: string) {
    if (dirty) {
      setError("请先保存任务内容，再切换任务");
      return;
    }
    if (review) {
      setError("请先采用或放弃回传结果，再切换项目");
      return;
    }
    await load(id);
  }
  function edit(field: keyof Draft, value: string | boolean) {
    setDraft((d) => (d ? { ...d, [field]: value } : d));
  }
  async function adopt() {
    if (!project || !review) return;
    if (
      project.id !== review.project ||
      dirty ||
      (project.chat_id && project.chat_id !== review.owner) ||
      project.revision !== review.revision
    )
      throw new Error("项目已变化，请重新回传；现有内容保留");
    const p =
      review.kind === "script"
        ? await saveCreator(project, { script: reviewText })
        : review.kind === 'brief'
        ? await saveCreator(project, reviewBrief!)
        : await writeApi<CreatorProject>(
            `${creatorBase}/projects/${project.id}/adopt-cover`,
            "POST",
            {
              revision: review.revision,
              owner: review.owner,
              attachment: review.attachment,
            },
          );
    setProject(p);
    setDraft(draftOf(p));
    setReview(undefined);
    onReturnDone?.();
  }
  function uploadSlot(slot: string) {
    return (
      project && (
        <div className="creator-asset" key={slot}>
          <div>
            <strong>{slotNames[slot]}</strong>
            <span>{project.assets[slot]?.name || "选择文件加入当前项目"}</span>
          </div>
          <label className="creator-upload">
            {project.assets[slot] ? "替换" : "＋ 添加"}
            <input
              ref={slot === 'source' ? sourceInput : undefined}
              aria-label={`上传${slotNames[slot]}`}
              type="file"
              accept={accepts[slot]}
              disabled={busy || dirty}
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (file)
                  void task(async () => {
                    setProject(await uploadCreator(project, slot, file));
                  });
              }}
            />
          </label>
          {project.assets[slot] && (
            <button
              className="creator-remove"
              aria-label={`移除${slotNames[slot]}`}
              disabled={busy || dirty}
              onClick={() =>
                void task(async () => {
                  setProject(await saveCreator(project, { remove: slot }));
                })
              }
            >
              ×
            </button>
          )}
        </div>
      )
    );
  }
  const selected = stages.find((s) => s[0] === stage)!;
  return (
    <main className="creator-workspace" aria-label="创作工作台">
      <header className="creator-header">
        <div className="creator-brand">
          <span>m</span>
          <div>
            <strong>miniclaw</strong>
            <small>商品创作</small>
          </div>
        </div>
        <nav>{project&&<button disabled={busy||dirty||!!review} onClick={()=>void task(async()=>{const mapped=await writeApi<{id:string}>(`/api/workspaces/import-creator/${project.id}`,'POST',{revision:project.revision});location.href=`/studio/index.html?workspace=${mapped.id}`;})}>在自由画布继续</button>}<button disabled={busy || dirty || !!review} onClick={() => onBack ? onBack() : void handOff(() => onChat(project))}>{onBack ? '返回看板' : '返回对话'}</button></nav>
      </header>
      <div className="creator-layout">
        <aside className="creator-projects">
          <div className="creator-sidebar-title">
            作品库 <small>{rows.length}</small>
          </div>
          <button
            className="creator-new"
            disabled={busy || dirty || !!review}
            onClick={() =>
              void task(async () => {
                const p = await writeApi<CreatorProject>(
                  `${creatorBase}/projects`,
                  "POST",
                  { name: "新创作任务" },
                );
                setProject(p);
                setDraft(draftOf(p));
                setStage("facts");
                localStorage.setItem("miniclaw.creator", p.id);
                setRows((r) => [{ id: p.id, name: p.name }, ...r]);
              })
            }
          >
            ＋ 新建创作任务
          </button>
          <details className="creator-library">
          <summary>作品库 · {rows.length}件</summary>
          <div className="creator-project-list">
            {rows.map((p, i) => (
              <button
                key={p.id}
                aria-current={project?.id === p.id ? "page" : undefined}
                disabled={busy}
                onClick={() => void task(() => choose(p.id))}
              >
                <small>{String(rows.length - i).padStart(2, "0")}</small>
                <span>{p.name}</span>
                <b>↗</b>
              </button>
            ))}
          </div>
          </details>
          <p className="creator-sidebar-note">
            从一个主题开始。
            <br />
            把每一步留下来。
          </p>
        </aside>
        <div className="creator-content">
          {error && (
            <p role="alert" className="creator-error">
              {error}
            </p>
          )}
          {!project || !draft ? (
            <section className="creator-empty">
              <h1>
                从一件商品，
                <br />
                开始一次创作。
              </h1>
              <p>先确定卖点和风格，打磨图片与口播，再制作短片。</p>
              <p>新建项目，或继续已有作品。</p>
            </section>
          ) : (
            <>
              {!manual && <section className="flow-overview" aria-label="商品创作总览">
                <header className="flow-heading"><div><span>商品创作总览</span><h1>{project.name}</h1><p>同一个商品，同一个对话。方向、图片与口播共享已确认的信息。</p></div><button className="flow-settings" disabled={busy || !!review} onClick={()=>setManual(true)}>项目设置</button></header>
                <div className="flow-body">
                  <section className="flow-product"><div className="flow-product-label"><strong>{project.assets.cover ? '已采用图片' : '商品原图'}</strong><span>v{project.revision} · 已保存</span></div>
                    {project.assets.cover || project.assets.source ? <ResultFile project={project.id} file={project.assets.cover || project.assets.source} image imageLabel={project.assets.cover ? '采用图片' : '商品原图'}/> : <div className="flow-upload"><span>从一张商品图开始</span><p>放入原图，再和Chat确定要怎么呈现。</p><button className="creator-primary" disabled={busy} onClick={()=>sourceInput.current?.click()}>上传商品原图</button></div>}
                    <p className="flow-note">{project.assets.cover ? '这是当前采用结果。新的修改确认后才会替换。' : '原图始终保留，修改先预览，再决定是否采用。'}</p>
                  </section>
                  <section className="flow-route" aria-label="商品创作流程">
                    <div className="flow-route-heading"><span>创作流程</span><small>调整都在Chat中完成</small></div>
                    {([['brief','创作方向','核对商品特点，确定受众与风格'],['cover','商品图片','提出修改要求，比较后采用'],['script','口播主稿','围绕同一商品打磨表达']] as const).map(([node,label,note],i)=>{
                      const ready = node==='brief' ? !!project.facts.trim() : node==='cover' ? !!project.assets.cover : !!project.script.trim();
                      const check = node!=='brief' && project.flow?.[node]==='review';
                      const next = nextCreation(project).stage; const currentNode = next==='facts' ? 'brief' : next==='cover' ? 'cover' : 'script';
                      return <button key={node} className={`flow-node ${currentNode===node ? 'is-next' : ''}`} disabled={busy || !!review || !project.assets.source} onClick={()=>void handOff(()=>onChat(project,node))}><span className="flow-node-number">{i+1}</span><span className="flow-node-copy"><strong>{label}</strong><small>{node==='script' && ready ? project.script.slice(0,46)+'…' : note}</small></span><span className="flow-node-state">{check ? '待核对' : ready ? '已采用' : '待开始'}</span><span aria-hidden="true">→</span></button>;
                    })}
                    {project.assets.source && <div className="flow-next"><small>下一步</small><h2>{nextCreation(project).title}</h2><p>进入项目对话，直接说出要求。结果在对话旁查看和确认。</p><button className="creator-primary" disabled={busy || !!review} onClick={()=>{ const next=nextCreation(project).stage; void handOff(()=>onChat(project,next==='facts' ? 'brief' : next==='cover' ? 'cover' : 'script')); }}>在Chat中继续 →</button></div>}
                  </section>
                </div>
              </section>}
              <div className="creator-manual-area" hidden={!manual}>
                <div className="creator-manual-heading"><strong>项目设置与手动调整</strong><button disabled={busy || dirty || !!review} onClick={()=>setManual(false)}>返回总览</button></div>
              <div className="creator-heading">
                <div>
                  <small>
                    当前商品
                  </small>
                  <h1>{project.name}</h1>
                </div>
                <span className={dirty ? "creator-dirty" : "creator-saved"}>
                  {dirty
                    ? "● 有未保存的修改"
                    : `✓ 已保存 · v${project.revision}`}
                </span>
              </div>
              <nav className="creator-progress" aria-label="创作步骤">
                {stages.filter(([id]) => advanced || !['video', 'package'].includes(id)).map(([id, name], i) => (
                  <button
                    key={id}
                    aria-current={stage === id ? "step" : undefined}
                    onClick={() => setStage(id)}
                  >
                    <small>
                      {(id === 'cover' || id === 'script') && project.flow?.[id] === 'review' ? "↻" : project.steps[id] ? "✓" : String(i + 1).padStart(2, "0")}
                    </small>
                    <strong>{name}</strong>
                  </button>
                ))}
              </nav>
              <button className="creator-advanced-toggle" aria-expanded={advanced} onClick={() => { setAdvanced(!advanced); if (advanced && ['video','package'].includes(stage)) { const next = nextCreation(project).stage; setStage(['video','package'].includes(next) ? 'script' : next); } }}>更多：视频与导出 {advanced ? '−' : '＋'}</button>
              <div className="creator-studio">
                <section className="creator-editor">
                  <div className="creator-section-heading">
                    <small>
                      STEP{" "}
                      {String(
                        stages.findIndex((s) => s[0] === stage) + 1,
                      ).padStart(2, "0")}
                    </small>
                    <h2>{selected[2]}</h2>
                  </div>
                  <div hidden={stage !== "facts"}>
                    {uploadSlot("source")}

                    <label>这次想做什么？<textarea aria-label="创作目标" value={goal} maxLength={1000} onChange={e => setGoal(e.target.value)} placeholder="例如：做一张安静、有质感的商品展示图，再写一段自然介绍。也可以留空，让Chat先给方向。" /></label>
                    <p className="creator-hint">上传原图，说说用途。让Chat整理方向，核对后再采用；不需要先填写完整资料。</p>
                    <details className="creator-manual-brief"><summary>核对或手动补充商品资料</summary>
                    <label>
                      任务名称
                      <input
                        value={draft.name}
                        maxLength={80}
                        onChange={(e) => edit("name", e.target.value)}
                      />
                    </label>
                    <label>
                      商品事实
                      <textarea
                        aria-label="商品事实"
                        value={draft.facts}
                        maxLength={8000}
                        placeholder="先写你知道的商品信息和来源；材质、容量等未知项写未验证，也可以先让Chat帮你整理。"
                        onChange={(e) => edit("facts", e.target.value)}
                      />
                    </label>
                    {([
                      ['selling_points', '已确认卖点', 4000, '特征→卖点→谁可能因此愿意买→依据。审美偏好与购买理由标为建议，未知功效不写成事实。'],
                      ['audience', '目标受众', 1000, '内容主要给谁看？'],
                      ['style', '统一风格', 2000, '例如米白背景、柔和光线、简洁自然的表达。'],
                      ['constraints', '必须保留与避免', 2000, '例如保留瓶型、标签文字；避免夸大功效。'],
                    ] as const).map(([field, label, limit, placeholder]) => (
                      <label key={field}>{label}<textarea aria-label={label} value={draft[field]} maxLength={limit} placeholder={placeholder} onChange={e => edit(field, e.target.value)} /></label>
                    ))}
                    <p className="creator-hint">
                      保存后的依据由图片与口播共用；Chat每轮读取最新保存内容。原图独立保留。
                    </p>
                    </details>
                    <button className="creator-primary" disabled={busy || !!review || !project.assets.source} onClick={() => void guidedDraft('brief')}>和Chat确定创作方向</button>
                    <p className="creator-hint">带入已保存资料与原图，Chat给出建议。点击回复下的“采用为创作依据”，核对事实与购买理由后确认。</p>
                    <button disabled={busy || dirty || !!review} onClick={() => setStage("cover")}>
                      下一步 · 图片 →
                    </button>
                  </div>
                  <div hidden={stage !== "script"}>
                    <label>
                      口播稿
                      <textarea
                        aria-label="口播稿"
                        className="creator-script"
                        value={draft.script}
                        maxLength={12000}
                        placeholder="只保存要读出的主稿；方案和分镜留在Chat里。"
                        onChange={(e) => edit("script", e.target.value)}
                      />
                    </label>
                    <div className="creator-word-count">
                      {draft.script.length} 字
                    </div>
                    <button
                      className="creator-primary"
                      disabled={busy || dirty || !!review}
                      onClick={() =>
                        void handOff(() =>
                          onDraft(
                            `创作项目：${draft.name}\n请使用口播优化的方法，依据本项目最新商品事实、卖点、受众、风格和限制改稿。优先一个有依据的特征和对应的购买理由；仅有外观资料时做审美选择介绍，不假造功能、体验、销量或价格。开头给受众一个值得看的理由，正文用可核对细节支持，结尾给一个自然的选择或了解建议。不要把人物衣服、背景等无关内容读成商品介绍。主稿按句换行，每句不超过36字，总长不超过320字。主稿与备选开头、核对事项分开，采用时只保留要读出的文字。看不到附件就说明，只使用已有事实，不编造看到的细节。图片沿用同一视觉方向；本轮只打磨文字，不生成视频。\n\n现有口播：\n${draft.script}`,
                            project,
                          ),
                        )
                      }
                    >
                      带入 Chat 草稿
                    </button>
                    <p className="creator-hint">
                      在Chat完成改稿后，点击回复下的“采用为项目口播”。预览并保留主稿，即可回传。
                    </p>
                    {project.flow?.script === 'review' && <><p className="creator-hint" role="status">创作依据或图片已变化，或旧稿尚未记录依据。请核对口播；不会自动改写。</p><button disabled={busy || dirty || !!review} onClick={() => void handOff(() => saveCreator(project, { confirm: 'script' }))}>已核对，保留当前口播</button></>}
                    {project.steps.script && (
                      <button disabled={busy || dirty || !!review} onClick={() => { setAdvanced(true); setStage("video"); }}>
                        下一步 · 视频 →
                      </button>
                    )}
                  </div>
                  <div hidden={stage !== "cover"}>
                    <p className="creator-description">
                      先把当前商品图做满意，再用同一张图打磨介绍。
                    </p>
                    <button className="creator-primary" disabled={busy || dirty || !!review || !project.assets.source && !project.assets.cover} onClick={() => void handOff(() => onCanvas(project))}>继续修改图片</button>
                    <p className="creator-hint">说出想改的地方，先看方案，再比较和采用。原图保留。</p>
                    {project.assets.source && !project.assets.cover && (project.assets.source.height || 0) > (project.assets.source.width || Infinity) * 1.8 && <p className="creator-hint">这是长截图。进入图片编辑后，在“图片方案”中预览截图裁剪，先核对商品是否完整。</p>}
                    <details className="creator-options"><summary>构图模板与摄影方案</summary>
                    <div className="creator-style-grid">
                      {photoPresets.map(p => <button key={p.id} disabled={busy || dirty || !!review || !project.assets.source && !project.assets.cover} onClick={() => void handOff(() => onCanvas(project, { mode: 'layout', preset: p.id }))}>
                        <span className="creator-style-sample" style={{ background: p.color, color: p.ink }}><i /><b>{p.name}</b><i /></span>
                        <strong>{p.name}</strong><small>{p.note}</small><em>本机构图 · 可预览与撤销</em>
                      </button>)}
                      <button disabled={busy || dirty || !!review || !project.assets.source && !project.assets.cover} onClick={() => void handOff(() => onCanvas(project, { mode: 'photo', brief: `${photographyPrompt}\n本项目风格：${project.style || '自然克制'}\n必须保留与避免：${project.constraints || '保留商品真实结构与颜色'}`.slice(0, 2000) }))}>
                        <span className="creator-style-sample creator-photo-sample"><b>柔光 · 层次 · 质感</b></span><strong>AI摄影精修</strong><small>打磨灯光、高光与背景，生成候选后核对商品细节。</small><em>百炼修图 · 可能计费</em>
                      </button>
                    </div>
                    <p className="creator-hint">构图方案改善留白与信息层级；摄影精修改变图像呈现，需要核对商品是否被改错。截图先在画布裁去购物界面，再制作候选。</p>
                    </details>
                    <details className="creator-options"><summary>上传其他图片或替换采用图</summary><div className="creator-assets">
                      {["cover", "detail", "scene"].map(uploadSlot)}
                    </div></details>
                    {project.flow?.cover === 'review' && <><p className="creator-hint" role="status">创作依据或原图已变化，或旧图片尚未记录依据。请核对图片；不会自动修图。</p><button disabled={busy || dirty || !!review} onClick={() => void handOff(() => saveCreator(project, { confirm: 'cover' }))}>已核对，保留当前图片</button></>}
                    <button disabled={busy || dirty || !!review} onClick={() => setStage("script")}>下一步 · 口播 →</button>
                    {project.assets.cover?.source && (
                      <p className="creator-source">
                        封面来自
                        {project.assets.cover.source.kind === "canvas"
                          ? "画布导出"
                          : "Chat修图"}{" "}

                      </p>
                    )}
                  </div>
                  <div hidden={stage !== "video"}>
                    <label>
                      制作方式
                      <select
                        value={draft.method}
                        onChange={(e) => edit("method", e.target.value)}
                      >
                        <option value="storyboard">
                          图片口播短片 · 配音＋镜头＋字幕
                        </option>
                        <option value="narrated">
                          镜头片口播 · 配音＋字幕
                        </option>
                        <option value="plan">已有视频 · 加文字动效</option>
                        <option value="overlay">已有视频 · 叠加透明动效</option>
                      </select>
                    </label>
                    <label>
                      成片比例
                      <select
                        value={draft.mode}
                        onChange={(e) => edit("mode", e.target.value)}
                      >
                        <option value="portrait">竖版 9:16</option>
                        <option value="landscape">横版 16:9</option>
                      </select>
                    </label>
                    {(draft.method === "storyboard" ||
                      draft.method === "narrated") && (
                      <label>
                        配音风格
                        <select
                          value={draft.speech_style || "standard"}
                          onChange={(e) => edit("speech_style", e.target.value)}
                        >
                          <option value="standard">明亮女声 · Cherry</option>
                          <option value="warm">
                            自然温柔 · Serena · 指令配音
                          </option>
                          <option value="narrative">
                            沉稳旁白 · Ethan · 指令配音
                          </option>
                        </select>
                      </label>
                    )}
                    {draft.method === "storyboard" ||
                    draft.method === "narrated" ? (
                      <div className="creator-recipe">
                        <strong>
                          {draft.method === "narrated"
                            ? "保留镜头节奏，让旁白与画面一起表达"
                            : "封面 → 特写 → 场景 → 收尾"}
                        </strong>
                        <p>
                          {draft.method === "narrated"
                            ? "上传已剪好的镜头片，使用本项目主稿配音并生成同步字幕。默认替换原音轨，可保留背景音并在旁白时压低。保留完整画面与片尾；镜头片过短会提示修改。输出1080p。"
                            : "读取本项目主稿和3张图片，生成百炼配音、镜头缓慢推进和同步字幕。图片短片输出1080p。"}
                        </p>
                        <small>
                          {cap?.speech?.configured
                            ? `百炼语音已配置 · ${draft.speech_style === "warm" ? "Serena · 自然温柔" : draft.speech_style === "narrative" ? "Ethan · 沉稳旁白" : "Cherry"}`
                            : "百炼语音未配置"}
                        </small>
                        <p>
                          点击合成会发送主稿到百炼并消耗额度。最多320字、12句，每句36字；不自动重试。
                        </p>
                        {draft.method === "narrated" && uploadSlot("video")}
                        {draft.method === "narrated" && (
                          <label className="creator-audio-choice">
                            <input
                              type="checkbox"
                              checked={!!draft.keep_source_audio}
                              disabled={
                                !project.assets.video?.audio &&
                                !draft.keep_source_audio
                              }
                              onChange={(e) =>
                                edit("keep_source_audio", e.target.checked)
                              }
                            />
                            保留背景音，旁白时自动压低
                          </label>
                        )}
                      </div>
                    ) : (
                      <div className="creator-assets">
                        {[
                          "video",
                          ...(draft.method === "plan"
                            ? ["srt", "plan"]
                            : ["overlay"]),
                        ].map(uploadSlot)}
                      </div>
                    )}
                    {!cap?.video && <p>本机视频工具未准备，请参考视频文档。</p>}
                    <div className="creator-actions">
                      <button
                        className="creator-primary"
                        disabled={
                          busy ||
                          dirty ||
                          rendering ||
                          !cap?.video ||
                          (draft.method !== "overlay" && !cap.font) ||
                          ((draft.method === "storyboard" ||
                            draft.method === "narrated") &&
                            !cap.speech?.configured)
                        }
                        onClick={() =>
                          void task(async () => {
                            await writeApi(
                              `${creatorBase}/projects/${project.id}/render`,
                              "POST",
                              { revision: project.revision },
                            );
                            setProject(await getCreator(project.id));
                          })
                        }
                      >
                        合成视频
                      </button>
                      {project.jobs
                        .filter(
                          (j) => j.state === "queued" || j.state === "running",
                        )
                        .map((j) => (
                          <button
                            key={j.id}
                            disabled={busy}
                            onClick={() =>
                              void task(async () => {
                                await writeApi(
                                  `${creatorBase}/projects/${project.id}/jobs/${j.id}/cancel`,
                                  "POST",
                                  {},
                                );
                                setProject(await getCreator(project.id));
                              })
                            }
                          >
                            取消合成
                          </button>
                        ))}
                    </div>
                    {project.jobs.slice(0, 1).map((j) => (
                      <p key={j.id} role="status" className="creator-job">
                        {jobNames[j.state]}
                        {j.error ? `：${j.error}` : ""}
                      </p>
                    ))}
                    {project.jobs.length > 1 && (
                      <details className="creator-history">
                        <summary>
                          合成任务记录 · {project.jobs.length}次
                        </summary>
                        {project.jobs.map((j) => (
                          <p key={j.id}>
                            {j.id.slice(0, 8)} · {jobNames[j.state]}
                            {j.error ? `：${j.error}` : ""}
                          </p>
                        ))}
                      </details>
                    )}
                    {!output && project.outputs.length > 0 && (
                      <p className="creator-hint">
                        素材或比例已变化，已有成片属于旧版本，请重新合成。
                      </p>
                    )}
                  </div>
                  <div hidden={stage !== "package"}>
                    <label>
                      发布文案
                      <textarea
                        value={draft.caption}
                        maxLength={4000}
                        placeholder="标题、描述和话题。"
                        onChange={(e) => edit("caption", e.target.value)}
                      />
                    </label>
                    <p className="creator-description">
                      带走视频、封面、字幕、文案和来源记录。
                    </p>
                    <button
                      disabled={
                        busy || dirty || !output || !draft.caption.trim()
                      }
                      onClick={() =>
                        void task(async () => {
                          setProject(
                            await writeApi<CreatorProject>(
                              `${creatorBase}/projects/${project.id}/package`,
                              "POST",
                              { revision: project.revision },
                            ),
                          );
                        })
                      }
                    >
                      生成发布包
                    </button>
                    {pack ? (
                      <ResultFile project={project.id} file={pack} />
                    ) : (
                      project.packages.length > 0 && (
                        <p>内容已变化，请重新生成当前版本。</p>
                      )
                    )}
                    <p className="creator-hint">
                      由你核对后手动发布到短视频平台。
                    </p>
                    <HistoryFiles project={project} />
                  </div>
                  <details className="creator-provenance">
                    <summary>素材来源与许可备注</summary>
                    <label>
                      来源记录
                      <textarea
                        value={draft.provenance}
                        maxLength={4000}
                        onChange={(e) => edit("provenance", e.target.value)}
                      />
                    </label>
                  </details>
                  <footer className="creator-editor-footer">
                    <span>
                      {dirty
                        ? "保存后可采用结果与合成"
                        : "每一步都留在同一个项目"}
                    </span>
                    <button
                      className="creator-primary"
                      disabled={busy || !dirty}
                      onClick={() => void task(save)}
                    >
                      {dirty ? "保存任务内容" : "内容已保存"}
                    </button>
                  </footer>
                </section>
                <aside className="creator-preview">
                  <div className="creator-preview-heading">
                    <strong>
                      {["video", "package"].includes(stage) && output ? "当前成片" : stage === "facts" || !project.assets.cover ? "商品原图" : "已采用图片"}
                    </strong>
                    <span>{output && ['video','package'].includes(stage) ? (draft.mode === "portrait" ? "9:16" : "16:9") : '图片原比例'}</span>
                  </div>
                  <div className="creator-preview-surface">
                    {output && ["video","package"].includes(stage) ? (
                      <ResultFile
                        key={output.id}
                        project={project.id}
                        file={output}
                        poster={project.assets.cover}
                        preview
                      />
                    ) : (stage === "facts" ? project.assets.source : project.assets.cover || project.assets.source) ? (
                      <ResultFile
                        key={(stage === "facts" ? project.assets.source : project.assets.cover || project.assets.source)!.id}
                        project={project.id}
                        file={(stage === "facts" ? project.assets.source : project.assets.cover || project.assets.source)!}
                        image imageLabel={stage === "facts" || !project.assets.cover ? "商品原图" : "采用图片"}
                      />
                    ) : (
                      <div className="creator-preview-empty">
                        <span>＋</span>
                        <strong>先放入一张商品图</strong>
                        <p>图片、修改结果和主稿会留在这个项目里。</p>
                        <button onClick={() => { setStage("facts"); sourceInput.current?.click(); }}>
                          上传商品原图
                        </button>
                      </div>
                    )}
                  </div>
                  <div className="creator-preview-caption">
                    <small>当前项目 · 当前素材</small>
                    <p>{project.name}</p>
                    <span>
                      {stage === 'facts' ? '这是商品原图，用于核对信息；修改结果另存。' : project.steps.video && ['video','package'].includes(stage)
                        ? "已有成片，播放核对后验收"
                        : project.assets.cover ? "这是当前采用图。新修改不会自动替换它。" : "原图保留，修改后先比较，再决定采用。"}
                    </span>
                  </div>
                </aside>
              </div>
              </div>
              {review && (
                <dialog
                  className="creator-review"
                  ref={reviewDialog}
                  role="dialog"
                  aria-modal="true"
                  aria-label="采用回传结果"
                    onCancel={() => {
                     setReview(undefined);
                      onReturnDone?.();
                      onBack?.();
                  }}
                >
                  <div>
                    <small>RETURN TO PROJECT</small>
                    <h2>
                      {review.kind === "script"
                        ? "确认口播主稿"
                        : review.kind === 'brief' ? '确认创作依据' : "确认项目封面"}
                    </h2>
                    <p>
                      将采用到「{project.name}」· v{review.revision}
                      。确认后才替换现有内容。
                    </p>
                    {review.kind === "script" ? (
                      <label>
                        保留要读出的主稿
                        <textarea
                          autoFocus
                          value={reviewText}
                          maxLength={12000}
                          onChange={(e) => setReviewText(e.target.value)}
                        />
                      </label>
                    ) : review.kind === 'brief' && reviewBrief ? (
                      <div className="creator-brief-review"><p className="creator-hint">这是Chat的候选建议。请核对事实来源；审美偏好、购买理由与场景建议不等于已验证的产品性能。采用后图片与口播可能需要重新核对。</p>{briefFields.map(([key, label, limit]) => <label key={key}>{label}<textarea aria-label={`待采用${label}`} value={reviewBrief[key]} maxLength={limit} onChange={e => setReviewBrief({...reviewBrief, [key]: e.target.value})} /></label>)}</div>
                    ) : review.kind === 'cover' ? (
                      <CoverReturn incoming={review} />
                    ) : null}
                    <div className="creator-actions">
                      <button
                        disabled={busy}
                        onClick={() => {
                            setReview(undefined);
                            onReturnDone?.();
                            onBack?.();
                        }}
                      >
                         暂不采用
                      </button>
                      <button
                        className="creator-primary"
                        disabled={
                          busy ||
                          (review.kind === "script" && !reviewText.trim()) || (review.kind === 'brief' && !reviewBrief?.facts.trim())
                        }
                        onClick={() => void task(adopt)}
                      >
                        确认采用
                      </button>
                    </div>
                  </div>
                </dialog>
              )}
            </>
          )}
        </div>
      </div>
    </main>
  );
}
function HistoryFiles({ project }: { project: CreatorProject }) {
  const [selected, setSelected] = useState("");
  useEffect(() => setSelected(""), [project.id]);
  const versions = [
    ...project.outputs.map((file, i) => ({ file, label: `成片第${i + 1}版` })),
    ...project.packages.map((file, i) => ({
      file,
      label: `发布包第${i + 1}版`,
    })),
  ];
  const choice = versions.find((v) => v.file.id === selected);
  if (!versions.length) return null;
  return (
    <details className="creator-history">
      <summary>历史成片与发布包 · {versions.length}份</summary>
      <label>
        选择保留版本
        <select value={selected} onChange={(e) => setSelected(e.target.value)}>
          <option value="">选择版本后查看或下载</option>
          {versions.map((v) => (
            <option key={v.file.id} value={v.file.id}>
              {v.label} · {v.file.current ? "当前素材" : "旧素材/内容"} ·{" "}
              {v.file.created
                ? new Date(v.file.created * 1000).toLocaleString()
                : ""}
            </option>
          ))}
        </select>
      </label>
      {choice && (
        <ResultFile
          key={choice.file.id}
          project={project.id}
          file={choice.file}
          preview={choice.file.name.endsWith(".mp4")}
        />
      )}
    </details>
  );
}
