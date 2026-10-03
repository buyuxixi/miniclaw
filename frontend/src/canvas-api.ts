import { readApi, writeApi } from "./management-api";
import type { Attachment } from "./attachments";

export interface CanvasLayer {
  id: string;
  kind: "image" | "text" | "shape";
  name: string;
  x: number;
  y: number;
  width: number;
  height: number;
  scale_x: number;
  scale_y: number;
  rotation: number;
  opacity: number;
  visible: boolean;
  locked: boolean;
  asset_id?: string;
  text?: string;
  font_size?: number;
  fill?: string;
  shape?: "rectangle" | "ellipse";
}
export interface CanvasDocument {
  schema_version: 1;
  width: number;
  height: number;
  background: string;
  layers: CanvasLayer[];
}
export interface Project {
  id: string;
  name: string;
  revision: number;
  cursor: number;
  updated: number;
  archived: boolean;
  chat_id: string | null;
  document: CanvasDocument;
}
export type ProjectRow = Pick<
  Project,
  "id" | "name" | "revision" | "updated" | "archived" | "chat_id"
>;
export interface CanvasAsset extends Attachment {
  width: number;
  height: number;
}
export interface Selection {
  id: string;
  revision: number;
  layer_id: string;
  asset_id: string;
  mask: string;
}
export interface Version {
  seq: number;
  label: string;
  time: number;
  current: boolean;
}
export interface CanvasJob {
  id: string;
  revision: number;
  layer_id: string;
  source_id: string;
  state: "queued" | "running" | "succeeded" | "failed" | "canceled";
  prompt: string;
  output?: CanvasAsset;
  error?: string;
}
export interface CanvasCapabilities {
  sam: { state: string; installed: boolean; error?: string };
  cloud: { configured: boolean; model: string };
}
export const projectPath = (id: string) =>
  `/api/miniclaw/canvas/projects/${encodeURIComponent(id)}`;
export const projectOwner = (id: string) => `project-${id}`;
export const copyDoc = (doc: CanvasDocument) => structuredClone(doc);
export function makeLayer(
  kind: CanvasLayer["kind"],
  name: string,
  width: number,
  height: number,
  extra: Partial<CanvasLayer> = {},
): CanvasLayer {
  return {
    id: crypto.randomUUID().replaceAll("-", ""),
    kind,
    name,
    x: 0,
    y: 0,
    width,
    height,
    scale_x: 1,
    scale_y: 1,
    rotation: 0,
    opacity: 1,
    visible: true,
    locked: false,
    ...extra,
  };
}
export async function uploadCanvas(
  project: string,
  file: File,
): Promise<CanvasAsset> {
  if (
    !/\.(png|jpe?g|webp)$/i.test(file.name) ||
    file.size > 5 * 1024 * 1024 ||
    !file.size
  )
    throw new Error("请选择5 MiB以内的PNG、JPEG或WebP图片");
  const data = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1]);
    reader.onerror = () => reject(new Error("图片读取失败"));
    reader.readAsDataURL(file);
  });
  return writeApi(`${projectPath(project)}/assets`, "POST", {
    name: file.name,
    data,
  });
}
export async function exportBlob(project: string, seq?: number) {
  const response = await fetch(
    `${window.__HERMES_BASE_PATH__ ?? ""}${projectPath(project)}/export${seq === undefined ? "" : `?seq=${seq}`}`,
    {
      headers: {
        "X-Hermes-Session-Token": window.__HERMES_SESSION_TOKEN__ ?? "",
      },
      signal: AbortSignal.timeout(30_000),
      cache: "no-store",
    },
  );
  if (!response.ok) throw new Error("画布导出失败");
  return response.blob();
}
export async function downloadCanvas(project: string) {
  const url = URL.createObjectURL(await exportBlob(project));
  const link = document.createElement("a");
  link.href = url;
  link.download = "canvas.png";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
export async function loadProject(id: string) {
  const [project, assets, selection, history, jobs] = await Promise.all([
    readApi<Project>(projectPath(id)),
    readApi<CanvasAsset[]>(`${projectPath(id)}/assets`),
    readApi<Selection | null>(`${projectPath(id)}/selection`),
    readApi<Version[]>(`${projectPath(id)}/history`),
    readApi<CanvasJob[]>(`${projectPath(id)}/jobs`),
  ]);
  return { project, assets, selection, history, jobs };
}
