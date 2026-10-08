import { readApi, writeApi } from "./management-api";
import type { BriefCandidate } from './creator-candidates';
export interface CreatorContext { project_id: string; node: "brief" | "cover" | "script" | "video" }
export const creationNodes = [['brief', '方向'], ['cover', '修图'], ['script', '口播'], ['video', '视频']] as const;
export interface CreatorTurn extends CreatorContext { revision: number; basis: string }
export interface CreatorTarget { id: string; name: string; revision: number; owner: string; node: CreatorContext["node"]; canvas?: string; image?: string }
export interface CreatorFile {
  id: string;
  name: string;
  bytes: number;
  current?: boolean;
  width?: number;
  height?: number;
  duration?: number;
  audio?: boolean;
  mode?: string;
  created?: number;
  source?: {
    kind: string;
    owner: string;
    attachment: string;
    canvas_project_id?: string;
  };
}
export interface CreatorJob {
  id: string;
  state: "queued" | "running" | "succeeded" | "failed" | "canceled";
  error?: string;
}
export interface CreatorProject {
  id: string;
  name: string;
  facts: string;
  selling_points?: string;
  audience?: string;
  style?: string;
  constraints?: string;
  script: string;
  caption: string;
  provenance: string;
  revision: number;
  mode: "portrait" | "landscape";
  method: "plan" | "overlay" | "storyboard" | "narrated";
  speech_style?: "standard" | "warm" | "narrative";
  keep_source_audio?: boolean;
  assets: Record<string, CreatorFile>;
  outputs: CreatorFile[];
  packages: CreatorFile[];
  jobs: CreatorJob[];
  steps: Record<string, boolean>;
  flow?: { brief: "ready" | "empty"; cover: "empty" | "adopted" | "review"; script: "empty" | "adopted" | "review" };
  chat_id?: string;
}
export type CreatorReturn = {
  project: string;
  revision: number;
  nonce: number;
} & (
  | { kind: "script"; text: string; owner: string; item: string }
  | { kind: "brief"; fields: BriefCandidate; owner: string; item: string }
  | { kind: "cover"; owner: string; attachment: string; name: string }
);
export const creatorBase = "/api/miniclaw/creator";
export const getCreator = (id: string) =>
  readApi<CreatorProject>(`${creatorBase}/projects/${id}`);
export const saveCreator = (p: CreatorProject, changes: object) =>
  writeApi<CreatorProject>(`${creatorBase}/projects/${p.id}`, "PATCH", {
    revision: p.revision,
    ...changes,
  });
export async function uploadCreator(
  p: CreatorProject,
  slot: string,
  file: File,
): Promise<CreatorProject> {
  const limits: Record<string, number> = {
    video: 256 * 1024 * 1024,
    overlay: 256 * 1024 * 1024,
    srt: 65536,
    plan: 65536,
    cover: 5 * 1024 * 1024,
    source: 5 * 1024 * 1024,
    detail: 5 * 1024 * 1024,
    scene: 5 * 1024 * 1024,
  };
  if (!file.size || file.size > limits[slot])
    throw new Error(
      "文件为空或超过限制：视频256 MiB，封面5 MiB，字幕/JSON 64 KiB",
    );
  const r = await fetch(
    `${window.__HERMES_BASE_PATH__ ?? ""}${creatorBase}/projects/${p.id}/assets/${slot}?name=${encodeURIComponent(file.name)}&revision=${p.revision}`,
    {
      method: "POST",
      headers: {
        "X-Hermes-Session-Token": window.__HERMES_SESSION_TOKEN__ ?? "",
        "Content-Type": "application/octet-stream",
      },
      body: file,
      signal: AbortSignal.timeout(120000),
    },
  );
  if (!r.ok) {
    const detail = await r.json().catch(() => ({}));
    throw new Error(detail.detail ?? "素材上传失败");
  }
  return r.json();
}
export async function creatorBlob(
  project: string,
  file: string,
  signal?: AbortSignal,
): Promise<Blob> {
  const r = await fetch(
    `${window.__HERMES_BASE_PATH__ ?? ""}${creatorBase}/projects/${project}/files/${file}`,
    {
      headers: {
        "X-Hermes-Session-Token": window.__HERMES_SESSION_TOKEN__ ?? "",
      },
      signal,
    },
  );
  if (!r.ok) throw new Error("文件读取失败");
  return r.blob();
}
