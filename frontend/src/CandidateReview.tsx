import { useState } from 'react';
import type { ReactNode } from 'react';
import type { CanvasJob } from './canvas-api';
const checks = [['shape', '轮廓与比例没有变'], ['color', '各部件颜色没有改错'], ['parts', '把手、盖钮、绳线等部件完整'], ['texture', '原有纹理和标识没有被磨掉']] as const;

export function CandidateReview({ job, busy, onReview, children }: { job: CanvasJob; busy: boolean; onReview: (decision: 'keep' | 'reject', checks: string[], reason: string) => void; children?: (ready: boolean) => ReactNode }) {
  const [checked, setChecked] = useState<string[]>(job.review?.checks || []);
  const [reason, setReason] = useState(job.review?.reason || '');
  return <fieldset className="candidate-review" disabled={busy}>
    <legend>先核对商品，再决定采用</legend>
    <p>逐项对照上方原图；这是你的核对记录，系统不会自动判断细节是否正确。</p>
    {job.review && <p role="status">{job.review.decision === 'reject' ? `未采用：${job.review.reason}` : '已记录四项核对，可以采用或继续修改。'}</p>}
    {checks.map(([key, label]) => <label key={key}><input type="checkbox" checked={checked.includes(key)} onChange={e => setChecked(current => e.target.checked ? [...current, key] : current.filter(c => c !== key))} />{label}</label>)}
    <label>未采用原因<textarea aria-label="未采用原因" maxLength={300} value={reason} placeholder="例如：纹理磨平、绳线变形" onChange={e => setReason(e.target.value)} /></label>
    <div className="canvas-button-grid"><button disabled={checked.length !== 4} onClick={() => onReview('keep', checked, '')}>核对完成，允许采用</button><button disabled={!reason.trim()} onClick={() => onReview('reject', checked, reason)}>细节有误，保留原图</button></div>
    {children?.(job.review?.decision === 'keep' && checked.length === 4)}
  </fieldset>;
}
