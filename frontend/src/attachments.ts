import { writeApi } from './management-api';
export interface Attachment { id: string; name: string; kind: 'image' | 'text'; mime: string; bytes: number; canvas_project_id?: string }
export interface TurnDisplay { text: string; attachments: Attachment[]; skill?: string }
export async function uploadFile(owner: string, file: File): Promise<Attachment> {
  const text = /\.(txt|md|markdown)$/i.test(file.name);
  if (!/\.(png|jpe?g|webp|txt|md|markdown)$/i.test(file.name)) throw new Error('支持PNG、JPEG、WebP、TXT和Markdown');
  if (!file.size || file.size > (text ? 64 * 1024 : 5 * 1024 * 1024)) throw new Error('文本最大64 KiB，图片最大5 MiB，不能上传空文件');
  const data = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(',')[1]); reader.onerror = () => reject(new Error('文件读取失败')); reader.readAsDataURL(file);
  });
  return writeApi('/api/miniclaw/attachments', 'POST', { owner, name: file.name, data });
}
export async function attachmentBlob(owner: string, attachment: Attachment, signal?: AbortSignal): Promise<Blob> {
  const response = await fetch(`${window.__HERMES_BASE_PATH__ ?? ''}/api/miniclaw/attachments/${encodeURIComponent(attachment.id)}?owner=${encodeURIComponent(owner)}`, {
    headers: { 'X-Hermes-Session-Token': window.__HERMES_SESSION_TOKEN__ ?? '' }, signal,
  });
  if (!response.ok) throw new Error('附件不可用，请重新上传');
  return response.blob();
}
