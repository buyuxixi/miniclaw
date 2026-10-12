import "../public/studio/project-name.js";
import { useEffect, useRef, useState } from "react";
import { readApi, writeApi } from "./management-api";
import { Icon } from "./Icon";
import "./studio-home.css";
export type StudioProject = {
  id: string;
  name: string;
  chat_id?: string;
  cover?: string;
  plan: string;
  notes: number;
  pictures: number;
  shots: number;
  adopted: number;
  updated_at: number;
};
export function studioImage(file: string) {
  return file.startsWith("/api/precision/projects/")
    ? file.replace("/api/precision/projects/", "/studio/media/")
    : file.startsWith("/") || file.startsWith("data:")
      ? file
      : "/studio/" + file;
}
export type LibraryItem = {
  id: string;
  name: string;
  kind: "image" | "video";
  source?: string;
  url: string;
  created_at: number;
};
type View = "projects" | "library" | "archived";
const VIEWS: [View, string][] = [
  ["projects", "项目"],
  ["library", "素材库"],
  ["archived", "已归档"],
];
const PAGE_SIZE = 6;
export default function StudioHome({
  active,
  onChat,
  onBack,
}: {
  active: boolean;
  onChat: () => Promise<void>;
  onBack?: () => void;
}) {
  const [projects, setProjects] = useState<StudioProject[]>([]),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState(
    () => new URLSearchParams(location.search).get("q") || "",
  );
  const [page, setPage] = useState(() =>
    Math.max(
      1,
      Math.floor(Number(new URLSearchParams(location.search).get("page")) || 1),
    ),
  );
  const [total, setTotal] = useState(0),
    [current, setCurrent] = useState(1);
  const [view, setView] = useState<View>(() => {
    const v = new URLSearchParams(location.search).get("view");
    return v === "library" || v === "archived" ? v : "projects";
  });
  const [library, setLibrary] = useState<LibraryItem[]>([]),
    [notice, setNotice] = useState("");
  const list = useRef<HTMLDivElement>(null),
    request = useRef(0);
  function syncUrl(shown: number) {
    const url = new URL(location.href);
    if (shown > 1) url.searchParams.set("page", String(shown));
    else url.searchParams.delete("page");
    if (filter) url.searchParams.set("q", filter);
    else url.searchParams.delete("q");
    if (view !== "projects") url.searchParams.set("view", view);
    else url.searchParams.delete("view");
    history.replaceState(null, "", url);
  }
  async function archive(p: StudioProject, archived: boolean) {
    try {
      const result = await writeApi<{ collected: number }>(
        `/api/workspaces/${encodeURIComponent(p.id)}/archive`,
        "POST",
        archived ? { archived, collect: true } : { archived },
      );
      setNotice(
        archived
          ? `已归档「${p.name}」，${result.collected} 张素材收进素材库`
          : `已恢复「${p.name}」`,
      );
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function removeFromLibrary(item: LibraryItem) {
    try {
      await writeApi(`/api/workspaces/library/${item.id}/remove`, "POST", {});
      setNotice(`已从素材库移出「${item.name}」`);
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function load() {
    const id = ++request.current;
    setLoading(true);
    setError("");
    try {
      if (view === "library") {
        const items = await readApi<LibraryItem[]>(
          `/api/workspaces/library?q=${encodeURIComponent(filter)}`,
        );
        if (id === request.current) {
          setLibrary(items);
          setTotal(items.length);
          syncUrl(1);
        }
        return;
      }
      const result = await readApi<{
        items: StudioProject[];
        total: number;
        page: number;
      }>(
        `/api/workspaces?page=${page}&page_size=${PAGE_SIZE}&q=${encodeURIComponent(filter)}${view === "archived" ? "&archived=true" : ""}`,
      );
      if (id === request.current) {
        setProjects(result.items);
        setTotal(result.total);
        setCurrent(result.page);
        syncUrl(result.page);
      }
    } catch (e) {
      if (id === request.current) setError((e as Error).message);
    } finally {
      if (id === request.current) setLoading(false);
    }
  }
  useEffect(() => {
    if (active) void load();
    return () => {
      ++request.current;
    };
  }, [active, page, filter, view]);
  const visible = projects;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE)),
    start = (current - 1) * PAGE_SIZE;
  async function openChat() {
    try {
      await onChat();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  function go(next: number) {
    setPage(next);
    list.current?.scrollIntoView?.({ block: "start", behavior: "instant" });
  }
  return (
    <main className="studio-home">
      <header>
        <a className="studio-home-brand" href="/">
          <b>m</b> miniclaw
        </a>
        <span className="studio-home-location">项目</span>
        <button
          className="home-assistant"
          onClick={() => (onBack ? onBack() : void openChat())}
        >
          <Icon name="assistant" />
          返回对话
        </button>
      </header>
      <section className="studio-home-intro">
        <div>
          <h1>创作项目</h1>
        </div>
        <button className="primary" onClick={() => void openChat()}>
          <Icon name="plus" size={16} />
          新建对话
        </button>
      </section>
      <nav className="studio-home-views" aria-label="项目分类">
        {VIEWS.map(([key, label]) => (
          <button
            key={key}
            aria-pressed={view === key}
            onClick={() => {
              setView(key);
              setPage(1);
              setNotice("");
            }}
          >
            {label}
          </button>
        ))}
      </nav>
      <div className="studio-home-search">
        <label>
          <Icon name="search" size={16} />
          <input
            aria-label={view === "library" ? "搜索素材" : "搜索创作项目"}
            placeholder={view === "library" ? "搜索素材" : "搜索项目"}
            value={filter}
            onChange={(e) => {
              setFilter(e.target.value);
              setPage(1);
            }}
          />
          {filter && (
            <button
              className="home-clear"
              aria-label="清除搜索"
              onClick={() => {
                setFilter("");
                setPage(1);
              }}
            >
              <Icon name="close" size={14} />
            </button>
          )}
        </label>
        <span>
          {total} {view === "library" ? "个素材" : "个项目"}
        </span>
        <button
          className="home-refresh"
          aria-label="刷新项目"
          title="刷新项目"
          disabled={loading}
          onClick={() => void load()}
        >
          <Icon name="refresh" size={17} />
        </button>
      </div>
      {error && (
        <p className="home-error" role="alert">
          {error}
          <button onClick={() => void load()}>重试</button>
        </p>
      )}
      {notice && (
        <p className="home-notice" role="status">
          {notice}
        </p>
      )}
      {view === "library" ? (
        !library.length ? (
          <div className="home-empty">
            <Icon name="image" size={28} />
            <p>
              {loading
                ? "正在读取素材…"
                : filter
                  ? "没有找到匹配的素材"
                  : "素材库还是空的。归档项目时，项目里保存过的图片会收进这里。"}
            </p>
          </div>
        ) : (
          <div className="studio-library" aria-busy={loading}>
            {library.map((item) => (
              <figure key={item.id}>
                {item.kind === "video" ? (
                  <video src={item.url} muted preload="metadata" />
                ) : (
                  <img loading="lazy" src={item.url} alt={item.name} />
                )}
                <figcaption>
                  <span title={item.name}>{item.name}</span>
                  <button
                    aria-label={`从素材库移出：${item.name}`}
                    title="移出素材库"
                    onClick={() => void removeFromLibrary(item)}
                  >
                    <Icon name="close" size={13} />
                  </button>
                </figcaption>
              </figure>
            ))}
          </div>
        )
      ) : loading && !projects.length ? (
        <p className="home-empty" role="status">
          正在读取项目…
        </p>
      ) : !visible.length ? (
        <div className="home-empty">
          <Icon name="folder" size={28} />
          <p>
            {filter
              ? "没有找到匹配的项目"
              : view === "archived"
                ? "没有已归档的项目"
                : "还没有创作项目"}
          </p>
          <button
            onClick={() =>
              filter ? (setFilter(""), setPage(1)) : void openChat()
            }
          >
            {filter ? "清除搜索" : "新建对话"}
          </button>
        </div>
      ) : (
        <>
          <div className="studio-project-list" ref={list} aria-busy={loading}>
            {visible.map((p) => (
              <article key={p.id}>
                <a
                  className="studio-project-cover"
                  href={studioCanvasHref(p.id)}
                  aria-label={`打开画布：${p.name}`}
                >
                  {p.cover ? (
                    <img loading="lazy" src={studioImage(p.cover)} alt="" />
                  ) : (
                    <Icon name="canvas" size={32} />
                  )}
                </a>
                <div className="studio-project-body">
                  <h2 title={p.name}>
                    <a href={studioCanvasHref(p.id)}>{p.name}</a>
                  </h2>
                  <p>
                    {(p.plan.trim().startsWith("核对结果") ? "" : p.plan)
                      .replace(/```[\s\S]*?```/g, "")
                      .replace(/^\s*#{1,6}\s+.+$/gm, "")
                      .replace(/\*\*([^*]+)\*\*/g, "$1")
                      .replace(/`/g, "")
                      .trim() || "素材和镜头已保存在画布。"}
                  </p>
                  <div className="studio-project-meta">
                    <span>
                      <Icon name="image" size={13} />
                      {p.pictures} 张素材
                    </span>
                    <span>
                      <Icon name="video" size={13} />
                      {p.shots} 个镜头
                    </span>
                    {p.adopted > 0 && (
                      <span className="project-adopted">
                        已采用 {p.adopted}
                      </span>
                    )}
                  </div>
                  <div className="studio-project-actions">
                    <a className="project-open" href={studioCanvasHref(p.id)}>
                      <Icon name="canvas" size={15} />
                      打开画布
                    </a>
                    {p.chat_id && (
                      <a
                        className="project-discuss"
                        href={studioChatHref(p.chat_id, p.id)}
                        title="继续讨论"
                      >
                        <Icon name="assistant" size={15} />
                        继续讨论
                      </a>
                    )}
                    <button
                      className="project-archive"
                      title={
                        view === "archived"
                          ? "恢复到项目列表"
                          : "归档项目，图片收进素材库"
                      }
                      aria-label={`${view === "archived" ? "恢复" : "归档"}：${p.name}`}
                      onClick={() => void archive(p, view !== "archived")}
                    >
                      <Icon name="archive" size={14} />
                      {view === "archived" ? "恢复" : "归档"}
                    </button>
                  </div>
                </div>
              </article>
            ))}
          </div>
          <nav className="studio-pagination" aria-label="项目分页">
            <span role="status">
              {start + 1}–{start + visible.length} / {total}
            </span>
            <div>
              <button
                aria-label="上一页"
                disabled={current === 1}
                onClick={() => go(current - 1)}
              >
                <Icon name="left" size={16} />
              </button>
              {[...new Set([1, current - 1, current, current + 1, pages])]
                .filter((n) => n >= 1 && n <= pages)
                .sort((a, b) => a - b)
                .map((n, i, all) => (
                  <span key={n}>
                    {i > 0 && n - all[i - 1] > 1 && (
                      <span className="page-gap">…</span>
                    )}
                    <button
                      aria-label={`第 ${n} 页`}
                      aria-current={current === n ? "page" : undefined}
                      onClick={() => go(n)}
                    >
                      {n}
                    </button>
                  </span>
                ))}
              <button
                aria-label="下一页"
                disabled={current === pages}
                onClick={() => go(current + 1)}
              >
                <Icon name="right" size={16} />
              </button>
            </div>
          </nav>
        </>
      )}
    </main>
  );
}
