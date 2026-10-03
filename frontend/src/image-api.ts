import { useEffect, useState } from 'react';
import { attachmentBlob, type Attachment } from './attachments';
export interface ImageJob {
  id: string; state: 'queued' | 'running' | 'succeeded' | 'failed' | 'canceled';
  source: Attachment; output?: Attachment; root_id: string; operation: string;
  params: Record<string, unknown>; provider: 'local' | 'dashscope'; error?: string;
}
export interface ImageHistory { images: Attachment[]; jobs: ImageJob[]; cloud: { configured: boolean; model: string } }
export const imageLabels: Record<string, string> = { adjust: '调色', crop: '裁剪', rotate: '旋转', flip: '翻转', resize: '缩放', ai_edit: 'AI 修图' };
export const jobLabels: Record<ImageJob['state'], string> = { queued: '排队中', running: '正在修图', succeeded: '修图完成', failed: '修图失败', canceled: '已取消' };
export function useImageBlob(owner: string, image?: Attachment) {
  const [url, setUrl] = useState(''); const [error, setError] = useState('');
  useEffect(() => {
    const abort = new AbortController(); let objectUrl = '';
    setUrl(''); setError('');
    if (image) void attachmentBlob(owner, image, abort.signal).then(blob => {
      if (!abort.signal.aborted) { objectUrl = URL.createObjectURL(blob); setUrl(objectUrl); }
    }).catch(reason => { if (!abort.signal.aborted) setError(String(reason)); });
    return () => { abort.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [owner, image?.id]);
  return { url, error };
}
