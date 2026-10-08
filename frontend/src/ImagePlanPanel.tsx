import { ImageDetailReview } from './ImageDetailReview';
import { useEffect, useRef, useState } from 'react';
import { readApi, writeApi } from './management-api';
import { exportBlob, projectPath, type Project, type CanvasCapabilities } from './canvas-api';
import { GenerationPrice } from './GenerationPrice';

export interface ImagePlan {
  id: string; project: string; revision: number; input_revision: number;
  layer_id: string; goal: string; preserve: string;
  state: 'proposed' | 'ready' | 'prepared' | 'applied' | 'submitted' | 'canceled';
  steps: { action: string; label: string; params: Record<string, unknown> }[];
  job_id?: string;
}
export type PlanPreview = { plan: ImagePlan; before: Blob; after: Blob };
type Preview = PlanPreview;

export function ImagePlanReview({ candidate, busy, onClose, onApply }: {
  candidate: Preview; busy: boolean; onClose: () => void; onApply: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [urls, setUrls] = useState<string[]>([]);
  const [detail, setDetail] = useState(false);
  useEffect(() => {
    if (typeof dialog.current?.showModal === 'function') dialog.current.showModal();
    else dialog.current?.setAttribute('open', '');
    const links = [candidate.before, candidate.after].map(URL.createObjectURL);
    setUrls(links); return () => links.forEach(URL.revokeObjectURL);
  }, [candidate]);
  return <dialog className="canvas-compare photo-layout-review" aria-label="修改方案预览" ref={dialog}
    onCancel={e => { if (busy) e.preventDefault(); else onClose(); }}>
    <header><strong>{candidate.plan.goal}</strong><button disabled={busy} onClick={onClose}>返回继续调整</button></header>
    <p>左边是当前画面，右边是本地修改预览。应用后可撤销；AI步骤需随后单独生成候选。</p>
    {candidate.plan.steps.some(s => s.action === 'replace_background') && <p>已确认主体选区内保留原像素，选区外换为纯色。请放大检查细绳、壶嘴和轮廓；选区遗漏会被替换，不会自动补阴影。</p>}
    {candidate.plan.steps.some(s => s.action === 'split_subject') && <p>主体与背景按当前选区拆开，未补全主体留下的背景空洞。请检查选区边缘；拆层不会自动换背景。</p>}
    <div>{urls.map((url, i) => <figure key={url}><img src={url} alt={i ? '方案预览' : '修改前画面'} /><figcaption>{i ? '本地修改预览' : '修改前'}</figcaption></figure>)}</div>
    <button disabled={urls.length !== 2} onClick={() => setDetail(true)}>放大检查方案细节</button>
    {detail && urls.length === 2 && <ImageDetailReview before={urls[0]} after={urls[1]} onClose={() => setDetail(false)} />}
    <button className="canvas-primary" disabled={busy} onClick={onApply}>应用本地修改到画布</button>
  </dialog>;
}

export function ImagePlanPanel({ project, busy, activeJob = false, canPlan, hasTarget, targetLayerId, hasSubjectSelection = false, onSend, onRun, onRefresh, onPreview, compact = false }: {
  project: Project; busy: boolean; activeJob?: boolean; canPlan: boolean; hasTarget: boolean;
  targetLayerId?: string; hasSubjectSelection?: boolean;
  onSend: (goal: string) => Promise<void>;
  onRun: (work: () => Promise<void>) => Promise<void>;
  onRefresh: () => Promise<void>;
  onPreview?: (preview: PlanPreview) => Promise<void>;
  compact?: boolean;
}) {
  const [goal, setGoal] = useState('');
  const [backgroundColor, setBackgroundColor] = useState('#f2efe7');
  const [plans, setPlans] = useState<ImagePlan[]>([]);
  const [error, setError] = useState('');
  const [candidate, setCandidate] = useState<Preview>();
  const [showHistory, setShowHistory] = useState(false);
  const [cloud,setCloud] = useState<CanvasCapabilities['cloud']>();
  useEffect(()=>{let alive=true;void readApi<CanvasCapabilities>('/api/miniclaw/canvas/capabilities').then(v=>{if(alive)setCloud(v.cloud)}).catch(()=>{});return()=>{alive=false}},[]);
  const request = useRef(0);
  const current = useRef(project);
  current.current = project;
  async function reload() {
    const serial = ++request.current;
    try {
      const next = await readApi<ImagePlan[]>(`${projectPath(project.id)}/plans`);
      if (serial === request.current) { setPlans(next); setError(''); }
    } catch (e) {
      if (serial === request.current) setError(e instanceof Error ? e.message : String(e));
    }
  }
  useEffect(() => {
    void reload();
    const timer = setInterval(() => void reload(), 2500);
    return () => { clearInterval(timer); ++request.current; };
  }, [project.id, project.revision]);
  useEffect(() => {
    if (candidate && (candidate.plan.project !== project.id || candidate.plan.revision !== project.revision)) setCandidate(undefined);
  }, [project.id, project.revision, candidate]);
  useEffect(() => () => { ++request.current; }, []);

  async function preview(plan: ImagePlan) {
    const source = project;
    const response = await fetch(`${window.__HERMES_BASE_PATH__ ?? ''}${projectPath(source.id)}/plans/${plan.id}/preview`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Hermes-Session-Token': window.__HERMES_SESSION_TOKEN__ ?? '' },
      body: JSON.stringify({ revision: source.revision }), signal: AbortSignal.timeout(30000),
    });
    if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.detail || '方案预览失败'); }
    const [after, before] = await Promise.all([response.blob(), exportBlob(source.id, source.cursor)]);
    if (current.current.id !== source.id || current.current.revision !== source.revision) throw new Error('当前工作图已变化，请重新预览');
    if (onPreview && !plan.steps.some(s => s.action === 'ai_edit')) await onPreview({ plan, before, after });
    else setCandidate({ plan, before, after });
    await reload();
  }
  async function apply() {
    if (!candidate) return;
    const c = candidate;
    await writeApi(`${projectPath(c.plan.project)}/plans/${c.plan.id}/apply`, 'POST', { revision: c.plan.revision });
    setCandidate(undefined); await onRefresh(); await reload();
  }
  if (compact && !plans.length && !error && !candidate) return null;
  return <section className="image-plan-panel" aria-label="Chat修改方案">
    {!compact && <>
    <h3>说说这张图想怎么改</h3>
    <p className="canvas-hint">Chat先给修改方案。看预览、满意再应用；生成AI候选需要你明确点击。</p>
    <label className="canvas-field">修改目标<textarea aria-label="图片修改目标" maxLength={1000} value={goal} onChange={e => setGoal(e.target.value)}
      placeholder="例如：让画面暖一点，保留壶身颜色、纹理和细绳；先给方案。" /></label>
    <button className="canvas-primary" disabled={busy || !canPlan || !hasTarget || !goal.trim()}
      onClick={() => void onRun(() => onSend(goal))}>让Chat制定修改方案</button>
    <details><summary>保留商品，换纯色背景</summary>
      <p className="canvas-hint">先在选区工具中选好商品，包含细绳、壶嘴和把手；选区外会替换为纯色。本机完成，不调用AI。</p>
      <label className="canvas-field">背景颜色<input aria-label="商品背景颜色" type="color" value={backgroundColor} onChange={e => setBackgroundColor(e.target.value)} /></label>
      {!hasSubjectSelection && <p className="canvas-hint">请先为当前图片确认主体选区，再预览背景。</p>}
      <button disabled={busy || activeJob || !hasTarget || !targetLayerId || !hasSubjectSelection} onClick={() => void onRun(async () => {
        const source = project;
        const plan = await writeApi<ImagePlan>(`${projectPath(source.id)}/plans`, 'POST', {
          revision: source.revision, layer_id: targetLayerId,
          goal: '保留商品，换纯色背景', preserve: '已确认主体选区内的原始像素',
          steps: [{ action: 'replace_background', params: { color: backgroundColor } }],
        });
        if (current.current.id !== source.id || current.current.revision !== source.revision) throw new Error('工作图已变化，请重新预览');
        await preview(plan);
      })}>预览商品纯色背景</button>
    </details>
    {!canPlan && <p className="canvas-hint">需要关联当前聊天并加载新版修图方案工具，可在下方启用画布工具或打开关联聊天。</p>}
    </>}
    {error && <p role="status">{error}</p>}
    {plans.map((plan, index) => {
      if (index > 0 && !showHistory) return null;
      const stale = plan.revision !== project.revision;
      const ai = plan.steps.at(-1)?.action === 'ai_edit';
      const local = plan.steps.some(s => s.action !== 'ai_edit');
      if (compact && ['applied','canceled'].includes(plan.state)) return <article className="image-plan-complete" key={plan.id}>
        <div><span className="plan-complete-status">{plan.state==='canceled'?'已取消':stale?'曾应用 · 图已更新':'已应用'}</span><strong>{plan.goal}</strong><button disabled={busy} onClick={()=>void onSend(`继续修改：${plan.goal}\n必须保留：${plan.preserve}\n这次还想调整：`)}>继续调整</button></div>
        <details><summary>查看修改详情</summary><p>必须保留：{plan.preserve || '未指定'}</p><ol>{plan.steps.map((s,i)=><li key={i}>{s.label}</li>)}</ol><pre>{JSON.stringify(plan.steps.map(s=>({action:s.action,params:s.params})),null,2)}</pre><p>已应用的本地修改可从画布历史撤销。</p></details>
      </article>;
      return <article className="image-plan-card" key={plan.id}>
        <div className="image-plan-title"><strong>{plan.goal}</strong><span>{plan.state==='canceled'?'已取消':plan.state==='applied'?stale?'曾应用 · 图已更新':'已应用到工作图':plan.state==='submitted'?'已提交候选':stale?'已过期':plan.state==='prepared'?'已预览，待确认':ai&&!local?'待生成':'待预览'}</span></div>
        <p>必须保留：{plan.preserve || '未指定，请先核对修改范围'}</p>
        <ol>{plan.steps.map((s, i) => <li key={i}>{s.label}{s.action === 'ai_edit' && <small>{String(s.params.prompt)}</small>}</li>)}</ol>
        <details><summary>查看具体参数</summary><pre>{JSON.stringify(plan.steps.map(s => ({ action:s.action, params:s.params })), null, 2)}</pre></details>
        <p className="canvas-hint">{plan.state === 'canceled' ? '已取消；已应用的本地修改可以从历史撤销。' : plan.state === 'applied' ? stale ? '本方案曾应用，当前工作图已变化。可以继续提出新要求。' : '本地修改已应用，可从历史撤销或继续提新要求。' : plan.state === 'submitted' ? '已提交一次AI候选，请在下方任务结果中比较。' : stale ? '工作图已变化，本方案过期，请重新提出修改要求。' : ai ? local ? '包含一次云端编辑，可能计费；本地修改先预览。' : '点击生成会提交一次云端编辑，可能计费。原图保留。' : '本机完成，无云端图片调用。'}</p>
        <div className="canvas-button-grid">
          {ai && <GenerationPrice cloud={cloud}/>}
          {local && ['proposed','ready'].includes(plan.state) && <button disabled={busy || stale || activeJob} onClick={() => void onRun(() => preview(plan))}>预览本地修改</button>}
          {ai && (plan.state === 'prepared' || !local && plan.state === 'proposed') && <button disabled={busy || stale || activeJob} onClick={() => void onRun(async () => {
            await writeApi(`${projectPath(project.id)}/plans/${plan.id}/generate`, 'POST', { revision: project.revision });
            await onRefresh(); await reload();
          })}>生成AI候选 · 可能计费</button>}
          <button disabled={busy} onClick={() => { const prompt=`继续修改：${plan.goal}\n必须保留：${plan.preserve}\n这次还想调整：`; if (compact) void onSend(prompt); else setGoal(prompt); }}>继续调整要求</button>
          {!['canceled','applied'].includes(plan.state) && <button disabled={busy} onClick={() => void onRun(async () => {
            await writeApi(`${projectPath(project.id)}/plans/${plan.id}/cancel`, 'POST', {}); await onRefresh(); await reload();
          })}>取消方案</button>}
        </div>
      </article>;
    })}
    {plans.length > 1 && <button onClick={() => setShowHistory(!showHistory)}>{showHistory ? '收起历史方案' : `历史方案（${plans.length - 1}）`}</button>}
    {candidate && <ImagePlanReview candidate={candidate} busy={busy} onClose={() => setCandidate(undefined)} onApply={() => void onRun(apply)} />}
  </section>;
}
