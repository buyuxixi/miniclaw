import { writeApi } from './management-api';
import type { CreatorTurn } from './creator-api';
import type {StudioReference} from './StudioReferences';
import { validateAttachmentFile } from './attachment-policy';
export interface AttachmentWarning { code?: string; message: string; source?: Record<string, unknown> }
export interface Attachment { id: string; name: string; kind: 'image' | 'text' | 'document'; mime: string; bytes: number; canvas_project_id?: string; parse_status?: 'queued' | 'parsing' | 'ready' | 'failed' | 'partial' | 'cancelled'; parse_error?: string; chunks?: number; warnings?: (string | AttachmentWarning)[]; coverage?: {warning_count?:number;[key:string]:unknown} }
export interface TurnDisplay { text: string; attachments: Attachment[]; skill?: string; creator_context?: CreatorTurn; studio_refs?: StudioReference[] }
export interface UploadSession { id: string; name: string; size: number; part_size: number; state: string; parts: { part_no: number; size: number; sha256: string }[]; attachment?: Attachment }
export interface UploadOptions { signal?: AbortSignal; onProgress?: (bytes: number, total: number) => void; onSession?: (id: string) => void }
interface UploadManifest { id?: string; requestId: string; hashes: Record<string, string> }
const uploadPath = '/api/miniclaw/uploads';
const base = () => window.__HERMES_BASE_PATH__ ?? '';
const auth = () => ({ 'X-Hermes-Session-Token': window.__HERMES_SESSION_TOKEN__ ?? '' });
export async function uploadRequest<T>(path: string, method: string, body?: unknown, signal?: AbortSignal, headers?: Record<string, string>): Promise<T> {
  const response = await fetch(`${base()}${path}`, { method, headers: { ...auth(), ...(body instanceof Blob ? {} : {'Content-Type':'application/json'}), ...headers }, ...(body === undefined ? {} : {body: body instanceof Blob ? body : JSON.stringify(body)}), signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(60_000)]) : AbortSignal.timeout(60_000) });
  if (!response.ok) { const details = await response.json().catch(() => ({})); throw new Error(typeof details.detail === 'string' ? details.detail : `附件请求失败（HTTP ${response.status}）`); }
  return response.status === 204 ? undefined as T : response.json() as Promise<T>;
}
async function sha256(blob: Blob): Promise<string> {
  const bytes = await blob.arrayBuffer();
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), b => b.toString(16).padStart(2, '0')).join('');
}
function readManifest(key: string): UploadManifest | undefined { try { const v = JSON.parse(localStorage.getItem(key) || 'null'); return v && typeof v.requestId === 'string' ? v : undefined; } catch { return undefined; } }
function remember(key: string, value: UploadManifest) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* File bytes are never stored in browser storage. */ } }
export async function cancelUpload(owner: string, id: string): Promise<void> { await uploadRequest(`${uploadPath}/${encodeURIComponent(id)}?owner=${encodeURIComponent(owner)}`, 'DELETE'); }
export async function uploadFile(owner: string, file: File, options: UploadOptions = {}): Promise<Attachment> {
  validateAttachmentFile(file);
  options.signal?.throwIfAborted();
  // This small identity only locates a candidate. Every retained part is checked
  // against the newly selected bytes before it can be reused.
  const key = `miniclaw.upload:${owner}:${encodeURIComponent(file.name)}:${file.size}:${file.lastModified}`;
  let manifest = readManifest(key) || { requestId: crypto.randomUUID(), hashes: {} };
  remember(key, manifest);
  let session: UploadSession | undefined;
  if (manifest.id) {
    try { session = await uploadRequest<UploadSession>(`${uploadPath}/${encodeURIComponent(manifest.id)}?owner=${encodeURIComponent(owner)}`, 'GET', undefined, options.signal); }
    catch (error) { if (options.signal?.aborted) throw error; /* Expired sessions can be initialized again. */ }
  }
  if (session && ['canceled','cancelled','expired'].includes(session.state)) { manifest = {requestId:crypto.randomUUID(),hashes:{}};remember(key,manifest);session=undefined; }
  if (!session) session = await uploadRequest<UploadSession>(uploadPath, 'POST', { owner, name: file.name, size: file.size, request_id: manifest.requestId }, options.signal);
  if (!Number.isSafeInteger(session.part_size) || session.part_size <= 0 || session.part_size > 4 * 1024 * 1024) throw new Error('服务返回的上传分片大小无效');
  options.onSession?.(session.id);
  manifest.id = session.id; remember(key, manifest);
  let parts = new Map(session.parts.map(p => [p.part_no, p]));
  // Verify all old chunks first. A same-name replacement must not combine new
  // bytes with an earlier upload or silently return its completed attachment.
  let mismatch = false;
  for (const part of session.parts) {
    options.signal?.throwIfAborted();
    const blob = file.slice(part.part_no * session.part_size, (part.part_no + 1) * session.part_size);
    if (blob.size !== part.size || await sha256(blob) !== part.sha256) { mismatch = true; break; }
  }
  if (mismatch) {
    manifest = { requestId: crypto.randomUUID(), hashes: {} }; remember(key, manifest);
    session = await uploadRequest<UploadSession>(uploadPath, 'POST', { owner, name: file.name, size: file.size, request_id: manifest.requestId }, options.signal);
    manifest.id = session.id; remember(key, manifest); parts = new Map(); options.onSession?.(session.id);
  }
  let completed = [...parts.values()].reduce((sum, p) => sum + p.size, 0);
  options.onProgress?.(completed, file.size);
  if (session.attachment && !mismatch && parts.size === Math.ceil(file.size / session.part_size)) return session.attachment;
  for (let n = 0; n * session.part_size < file.size; n++) {
    options.signal?.throwIfAborted();
    if (parts.has(n)) continue;
    const blob = file.slice(n * session.part_size, (n + 1) * session.part_size), hash = await sha256(blob);
    await uploadRequest(`${uploadPath}/${encodeURIComponent(session.id)}/parts/${n}?owner=${encodeURIComponent(owner)}`, 'PUT', blob, options.signal, {'Content-Type':'application/octet-stream','X-Part-SHA256':hash});
    manifest.hashes[n] = hash; remember(key, manifest); completed += blob.size; options.onProgress?.(completed, file.size);
  }
  return uploadRequest<Attachment>(`${uploadPath}/${encodeURIComponent(session.id)}/complete`, 'POST', { owner }, options.signal);
}
export function documentStatus(owner: string, id: string, signal?: AbortSignal): Promise<Partial<Attachment>> { return uploadRequest(`/api/miniclaw/documents/${encodeURIComponent(id)}?owner=${encodeURIComponent(owner)}`, 'GET', undefined, signal); }
export function retryDocument(owner: string, id: string): Promise<Partial<Attachment>> { return writeApi(`/api/miniclaw/documents/${encodeURIComponent(id)}/retry`, 'POST', {owner}); }
export async function attachmentBlob(owner: string, attachment: Attachment, signal?: AbortSignal): Promise<Blob> {
  const response = await fetch(`${window.__HERMES_BASE_PATH__ ?? ''}/api/miniclaw/attachments/${encodeURIComponent(attachment.id)}?owner=${encodeURIComponent(owner)}`, {
    headers: { 'X-Hermes-Session-Token': window.__HERMES_SESSION_TOKEN__ ?? '' }, signal,
  });
  if (!response.ok) throw new Error('附件不可用，请重新上传');
  return response.blob();
}
