import { useEffect, useRef, useState } from 'react';
import { cancelUpload, uploadFile, type Attachment } from './attachments';
import { MAX_ATTACHMENTS, validateAttachmentFile } from './attachment-policy';

export interface UploadRow { id: string; name: string; size: number; lastModified: number; state: 'queued' | 'uploading' | 'failed' | 'reselect'; bytes: number; error?: string; session?: string }
interface Job extends UploadRow { file?: File; abort?: AbortController }
function restored(key: string): Job[] {
  try { const rows = JSON.parse(localStorage.getItem(key) || '[]'); return Array.isArray(rows) ? rows.filter(r => r && typeof r.id === 'string' && typeof r.name === 'string' && Number.isFinite(r.size)).slice(0, MAX_ATTACHMENTS).map(r => ({...r, state:'reselect', error:'重新选择原文件可继续上传'})) : []; } catch { return []; }
}
export function useAttachmentQueue(owner: string, getCount: () => number, onUploaded: (attachment: Attachment) => void) {
  const key = `miniclaw.upload-queue.${owner}`;
  const jobs = useRef<Job[]>(restored(key)), running = useRef(0), alive = useRef(true);
  const [rows, setRows] = useState<UploadRow[]>(jobs.current), [error, setError] = useState('');
  const callbacks = useRef({ getCount, onUploaded }); callbacks.current = { getCount, onUploaded };
  function publish() {
    const display = jobs.current.map(({file: _file, abort: _abort, ...row}) => row);
    try { localStorage.setItem(key, JSON.stringify(display)); } catch { if (alive.current) setError('上传进度暂时无法保存，请保留页面。'); }
    if (alive.current) setRows(display);
  }
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  function pump() {
    while (running.current < 2) {
      const job = jobs.current.find(r => r.state === 'queued' && r.file);
      if (!job) break;
      job.state = 'uploading'; job.error = undefined; job.abort = new AbortController(); running.current++; publish();
      void uploadFile(owner, job.file!, { signal:job.abort.signal, onSession:id => {job.session=id;publish();}, onProgress:bytes => {job.bytes=bytes;publish();} }).then(attachment => {
        if (!jobs.current.includes(job) || job.abort?.signal.aborted) return;
        callbacks.current.onUploaded(attachment);
        jobs.current = jobs.current.filter(r => r !== job); publish();
      }).catch(reason => {
        if (!jobs.current.includes(job)) return;
        job.state = 'failed'; job.error = reason instanceof Error ? reason.message : String(reason); publish();
      }).finally(() => { running.current--; pump(); });
    }
  }
  function addFiles(files: File[]) {
    if (!owner || !files.length) return;
    setError('');
    // Restored rows reserve a place and are replaced by the reselected source.
    const claimed = new Set<string>();
    const matches = files.map(file => { const job = jobs.current.find(r => !r.file && !claimed.has(r.id) && r.name === file.name && r.size === file.size && r.lastModified === file.lastModified); if(job)claimed.add(job.id); return job; });
    if (callbacks.current.getCount() + jobs.current.length + files.length - claimed.size > MAX_ATTACHMENTS) { setError(`每轮最多${MAX_ATTACHMENTS}个附件，已上传和待上传文件都计入数量。`); return; }
    files.forEach((file, i) => {
      let validation: string | undefined;
      try { validateAttachmentFile(file); } catch (e) { validation = (e as Error).message; }
      const job = matches[i] || {id:crypto.randomUUID(),name:file.name,size:file.size,lastModified:file.lastModified,state:'queued' as const,bytes:0};
      Object.assign(job, {file,state:validation?'failed':'queued',error:validation});
      if (!matches[i]) jobs.current.push(job);
    });
    publish(); pump();
  }
  function retry(id: string) { const job=jobs.current.find(r=>r.id===id); if(!job||!job.file||job.state==='uploading')return; try{validateAttachmentFile(job.file);}catch(e){job.error=(e as Error).message;publish();return;} job.state='queued';publish();pump(); }
  function remove(id: string) {
    const job=jobs.current.find(r=>r.id===id); if(!job)return;
    job.abort?.abort(); jobs.current=jobs.current.filter(r=>r!==job);publish();
    if(job.session)void cancelUpload(owner,job.session).catch(()=>{if(alive.current)setError('本次上传已停止，服务端临时分片将在过期后清理。');});
    pump();
  }
  return {rows,error,addFiles,retry,remove,count:()=>jobs.current.length,active:rows.some(r=>r.state==='queued'||r.state==='uploading')};
}
