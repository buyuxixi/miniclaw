import { useEffect, useState } from 'react';
import type { Attachment } from './attachments';
import { readApi } from './management-api';
import { imageLabels, jobLabels, useImageBlob, type ImageJob } from './image-api';

export function ImageComparison({ owner, source, output }: { owner: string; source: Attachment; output?: Attachment }) {
  const before = useImageBlob(owner, source); const after = useImageBlob(owner, output);
  return <div className={`image-comparison ${output ? '' : 'single'}`}>
    <figure><div className="image-stage">{before.url ? <img src={before.url} alt={`修改前 ${source.name}`} /> : <p>{before.error || '正在读取原图…'}</p>}</div><figcaption>{output ? '修改前' : '当前版本'} · {before.url && <a href={before.url} download={source.name}>{output ? '下载原图' : '下载这张图'}</a>}</figcaption></figure>
    {output && <figure><div className="image-stage">{after.url ? <img src={after.url} alt={`修改后 ${output.name}`} /> : <p>{after.error || '正在读取结果…'}</p>}</div><figcaption>修改后 · {after.url && <a href={after.url} download={output.name}>下载 PNG</a>}</figcaption></figure>}
  </div>;
}

export function ImageJobCard({ owner, result, onEdit }: { owner: string; result: unknown; onEdit?: (image: Attachment) => void }) {
  let parsed: Partial<ImageJob> = {};
  try { parsed = typeof result === 'string' ? JSON.parse(result) : result as Partial<ImageJob>; } catch { /* invalid tool result */ }
  const initial = parsed?.id && parsed.source && parsed.state ? parsed as ImageJob : undefined;
  const [job, setJob] = useState(initial); const [error, setError] = useState('');
  useEffect(() => { setJob(initial); setError(''); }, [result]);
  useEffect(() => {
    if (!job || !['queued', 'running'].includes(job.state)) return;
    const abort = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const updated = await readApi<ImageJob>(`/api/miniclaw/image-jobs/${encodeURIComponent(job!.id)}?owner=${encodeURIComponent(owner)}`, abort.signal);
        if (abort.signal.aborted) return;
        setJob(updated);
        if (['queued', 'running'].includes(updated.state)) timer = setTimeout(poll, 1500);
      } catch (reason) { if (!abort.signal.aborted) setError(String(reason)); }
    }
    timer = setTimeout(poll, 500);
    return () => { abort.abort(); clearTimeout(timer); };
  }, [owner, job?.id, job?.state]);
  if (!job) return null;
  return <section className="image-result"><header><strong>{jobLabels[job.state]}</strong><span>{imageLabels[job.operation]} · {job.provider === 'local' ? '本地处理' : '百炼'}</span></header>
    {(job.error || error) && <p role="status">{job.error || error}</p>}
    {job.state === 'succeeded' && job.output && <><ImageComparison owner={owner} source={job.source} output={job.output} />{onEdit && <button className="secondary-action" onClick={() => onEdit(job.output!)}>继续修改这张图</button>}</>}
    {['queued', 'running'].includes(job.state) && <p>原图已保留。可在修图面板查看进度；停止聊天不会自动取消此任务。</p>}
  </section>;
}
