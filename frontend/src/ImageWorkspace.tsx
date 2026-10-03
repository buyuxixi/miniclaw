import { useEffect, useRef, useState } from 'react';
import type { ChatController } from './chat-controller';
import type { ChatState } from './types';
import { uploadFile, type Attachment } from './attachments';
import { readApi, writeApi } from './management-api';
import { imageLabels, jobLabels, type ImageHistory, type ImageJob } from './image-api';
import { ImageComparison } from './ImageJobCard';
import { Icon } from './Icon';

export function ImageWorkspace({ controller, chat, initial, onClose, onUse, onTools }: {
  controller: ChatController; chat: ChatState; initial?: Attachment;
  onClose: () => void; onUse: (image: Attachment) => void; onTools: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null); const picker = useRef<HTMLInputElement>(null);
  const [history, setHistory] = useState<ImageHistory>(); const [selected, setSelected] = useState(initial?.id ?? '');
  const [operation, setOperation] = useState('adjust'); const [brightness, setBrightness] = useState(0.15);
  const [contrast, setContrast] = useState(0); const [saturation, setSaturation] = useState(0);
  const [ratio, setRatio] = useState('1:1'); const [angle, setAngle] = useState(90); const [direction, setDirection] = useState('horizontal');
  const [width, setWidth] = useState(1024); const [height, setHeight] = useState(1024); const [prompt, setPrompt] = useState('');
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const [request, setRequest] = useState<{ id: string; body: object }>();
  const mounted = useRef(true);
  const loaded = Object.values(chat.info.tools ?? {}).flat().includes('miniclaw_edit_image');
  const active = history?.jobs.find(j => ['queued', 'running'].includes(j.state));
  const source = history?.images.find(image => image.id === selected) ?? (initial?.id === selected ? initial : undefined);
  const comparison = active?.source.id === selected ? undefined : history?.jobs.find(j => j.source.id === selected && j.state === 'succeeded');
  const blocked = busy || chat.running || chat.busy || controller.connection !== 'open';
  useEffect(() => { mounted.current = true; dialog.current?.showModal(); return () => { mounted.current = false; dialog.current?.close(); }; }, []);
  useEffect(() => {
    const abort = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const state = await readApi<ImageHistory>(`/api/miniclaw/image-jobs?owner=${encodeURIComponent(chat.storedId)}`, abort.signal);
        if (abort.signal.aborted) return;
        setHistory(state); setSelected(value => value || state.images.at(-1)?.id || '');
      } catch (reason) { if (!abort.signal.aborted) setError(String(reason)); }
      if (!abort.signal.aborted) timer = setTimeout(poll, 2000);
    }
    void poll();
    return () => { abort.abort(); clearTimeout(timer); };
  }, [chat.storedId]);
  async function refresh() { const state = await readApi<ImageHistory>(`/api/miniclaw/image-jobs?owner=${encodeURIComponent(chat.storedId)}`); if (mounted.current) setHistory(state); }
  async function add(file?: File) {
    if (!file || blocked) return;
    setBusy(true); setError('');
    try { const image = await uploadFile(chat.storedId, file); if (mounted.current) { setSelected(image.id); await refresh(); } }
    catch (reason) { if (mounted.current) setError(String(reason)); }
    finally { if (mounted.current) setBusy(false); }
  }
  async function execute(retry = false) {
    if (blocked || active || !source || !loaded) return;
    const params = operation === 'adjust' ? { brightness, contrast, saturation } : operation === 'crop' ? { ratio } : operation === 'rotate' ? { angle } : operation === 'flip' ? { direction } : operation === 'resize' ? { width, height } : { prompt };
    const submission = retry && request ? request : { id: crypto.randomUUID(), body: { session_id: chat.sessionId, source_id: source.id, operation, params, request_id: crypto.randomUUID() } };
    setRequest(submission); setBusy(true); setError('');
    try { await writeApi<ImageJob>('/api/miniclaw/image-jobs', 'POST', submission.body); if (mounted.current) { setRequest(undefined); await refresh(); } }
    catch (reason) { if (mounted.current) setError(`${String(reason)}。若连接超时，可核对原请求；不会自动重发。`); }
    finally { if (mounted.current) setBusy(false); }
  }
  async function cancel(job: ImageJob) {
    setBusy(true); setError('');
    try { await writeApi(`/api/miniclaw/image-jobs/${encodeURIComponent(job.id)}/cancel`, 'POST', { session_id: chat.sessionId }); if (mounted.current) await refresh(); }
    catch (reason) { if (mounted.current) setError(String(reason)); }
    finally { if (mounted.current) setBusy(false); }
  }
  return <dialog ref={dialog} className="image-workspace" aria-label="图片编辑" onCancel={onClose}>
    <header className="image-workspace-header"><div><h2>图片编辑</h2><p>保留原图，每次修改都是一个新版本。</p></div><button className="icon-button" aria-label="关闭图片编辑" onClick={onClose}><Icon name="close" /></button></header>
    <div className="image-workspace-body">
      <aside className="image-controls">
        <input ref={picker} hidden type="file" accept=".png,.jpg,.jpeg,.webp" onChange={e => { void add(e.target.files?.[0]); e.target.value = ''; }} />
        <button className="primary-action" disabled={blocked} onClick={() => picker.current?.click()}><Icon name="plus" size={16} />上传图片</button>
        <label className="field-label">选择图片版本<select aria-label="选择图片版本" value={selected} onChange={e => setSelected(e.target.value)}>{!selected && <option value="">请上传图片</option>}{history?.images.map(image => <option key={image.id} value={image.id}>{image.name}</option>)}</select></label>
        {!loaded && <p className="image-note">当前对话没有修图工具。<button onClick={onTools}>打开工具设置</button>，启用“图片编辑”后新建对话。</p>}
        <label className="field-label">编辑方式<select aria-label="编辑方式" value={operation} onChange={e => setOperation(e.target.value)}>{Object.entries(imageLabels).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></label>
        {operation === 'adjust' && <>{[['亮度', brightness, setBrightness], ['对比度', contrast, setContrast], ['饱和度', saturation, setSaturation]].map(([label, value, setter]) => <label className="image-slider" key={String(label)}>{String(label)}<span>{Math.round(Number(value) * 100)}%</span><input aria-label={String(label)} type="range" min="-100" max="100" value={Number(value) * 100} onChange={e => (setter as (v: number) => void)(Number(e.target.value) / 100)} /></label>)}</>}
        {operation === 'crop' && <label className="field-label">居中裁剪比例<select aria-label="裁剪比例" value={ratio} onChange={e => setRatio(e.target.value)}>{['1:1', '4:3', '3:4', '16:9', '9:16'].map(v => <option key={v}>{v}</option>)}</select></label>}
        {operation === 'rotate' && <label className="field-label">顺时针角度<select aria-label="旋转角度" value={angle} onChange={e => setAngle(Number(e.target.value))}>{[90, 180, 270].map(v => <option key={v} value={v}>{v}°</option>)}</select></label>}
        {operation === 'flip' && <label className="field-label">方向<select aria-label="翻转方向" value={direction} onChange={e => setDirection(e.target.value)}><option value="horizontal">水平</option><option value="vertical">垂直</option></select></label>}
        {operation === 'resize' && <><label className="field-label">宽度<input type="number" min="32" max="4096" value={width} onChange={e => setWidth(Number(e.target.value))} /></label><label className="field-label">高度<input type="number" min="32" max="4096" value={height} onChange={e => setHeight(Number(e.target.value))} /></label><p className="image-note">按指定尺寸缩放，宽高比不一致会拉伸。</p></>}
        {operation === 'ai_edit' && <><label className="field-label">修图要求<textarea aria-label="修图要求" value={prompt} maxLength={2000} onChange={e => setPrompt(e.target.value)} placeholder="例如：换成干净的米白背景，保留商品轮廓和文字。" /></label><p className="image-note">源图与要求会发送给百炼，可能计费。{history?.cloud.configured ? `使用 ${history.cloud.model}` : '尚未配置百炼 Key；本地编辑可直接使用。'}</p></>}
        <button className="primary-action" disabled={blocked || !!active || !source || !loaded || (operation === 'ai_edit' && (!history?.cloud.configured || !prompt.trim()))} onClick={() => void execute()}>{busy ? '正在提交…' : '开始修图'}</button>
        {request && error && <button className="secondary-action" disabled={blocked || !!active} onClick={() => void execute(true)}>核对原请求</button>}
      </aside>
      <section className="image-preview-area">
        {error && <p className="settings-error" role="alert">{error}</p>}
        {active && <div className="image-job-status" role="status"><span><strong>{jobLabels[active.state]}</strong> · {imageLabels[active.operation]}</span><button disabled={busy} onClick={() => void cancel(active)}>取消任务</button></div>}
        {!source ? <div className="image-empty"><Icon name="image" size={40} /><h3>先放入一张图片</h3><p>也可以选择聊天中已经上传的图片。</p></div> : <><ImageComparison owner={chat.storedId} source={source} output={comparison?.output} /><div className="image-version-actions"><button className="secondary-action" disabled={blocked} onClick={() => onUse(source)}>{comparison?.output ? '把修改前的图放回聊天' : '把这张图放回聊天'}</button>{comparison?.output && <><button className="secondary-action" disabled={blocked} onClick={() => onUse(comparison.output!)}>把结果放回聊天</button><button className="primary-action" disabled={blocked} onClick={() => setSelected(comparison.output!.id)}>用结果继续修改</button></>}</div></>}
        <h3 className="image-history-title">修改记录</h3>
        {!history?.jobs.length && <p className="image-note">还没有修改记录。原图不会被覆盖。</p>}
        {history?.jobs.map(job => <article className="image-version" key={job.id}><div><strong>{imageLabels[job.operation]} · {jobLabels[job.state]}</strong><small>{job.provider === 'local' ? '本地处理' : '百炼 AI'} · {job.source.name}</small>{job.error && <p>{job.error}</p>}</div>{job.output && <button className="secondary-action" onClick={() => setSelected(job.output!.id)}>选择结果</button>}<button className="secondary-action" onClick={() => setSelected(job.source.id)}>查看原图</button></article>)}
      </section>
    </div>
    <footer>关闭面板不会自动取消任务。云端已提交的请求可能继续执行或计费；请核对商品结构、颜色和文字。</footer>
  </dialog>;
}
