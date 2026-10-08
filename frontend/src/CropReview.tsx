import { useEffect, useRef, useState } from 'react';
import type { CanvasDocument } from './canvas-api';
export interface CropCandidate { project: string; revision: number; original: CanvasDocument; document: CanvasDocument; before: Blob; after: Blob; top: number; bottom: number }

export function cropDocument(original: CanvasDocument, top: number, bottom: number) {
  if (!Number.isInteger(top) || !Number.isInteger(bottom) || top < 0 || bottom > original.height || bottom - top < 16) throw new Error('上下界须在原画面内，至少保留16像素。');
  const document = structuredClone(original);
  document.height = bottom - top; document.layers.forEach(layer => { layer.y -= top; });
  return document;
}

export function CropReview({ candidate, busy, onPreview, onApply, onClose }: { candidate: CropCandidate; busy: boolean; onPreview: (top: number, bottom: number) => void; onApply: () => void; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const range = useRef<SVGSVGElement>(null);
  const dragging = useRef<'top' | 'bottom' | undefined>(undefined);
  const [displayWidth, setDisplayWidth] = useState(200);
  const [urls, setUrls] = useState<string[]>([]);
  const [top, setTop] = useState(String(candidate.top)), [bottom, setBottom] = useState(String(candidate.bottom));
  const dirty = Number(top) !== candidate.top || Number(bottom) !== candidate.bottom;
  const filled = !!top.trim() && !!bottom.trim();
  const height = candidate.original.height, width = candidate.original.width;
  const valid = filled && Number.isInteger(Number(top)) && Number.isInteger(Number(bottom)) && Number(top) >= 0 && Number(bottom) <= height && Number(bottom) - Number(top) >= 16;
  const visibleTop = valid ? Number(top) : candidate.top, visibleBottom = valid ? Number(bottom) : candidate.bottom;
  const pixel = width / Math.max(1, displayWidth), hitHeight = Math.max(width*.15, 44*pixel);
  const handleHeight = Math.max(width*.11, 28*pixel), handleWidth = Math.min(width, Math.max(width*.42, 84*pixel));
  const fontSize = Math.max(width*.046, 12*pixel);
  useEffect(() => {
    const svg = range.current; if (!svg) return;
    const update = () => { const measured=svg.getBoundingClientRect().width; if (measured>0) setDisplayWidth(measured); };
    update(); const observer = new ResizeObserver(update); observer.observe(svg);
    return () => observer.disconnect();
  }, []);
  function move(edge: 'top' | 'bottom', value: number) {
    if (busy || !Number.isFinite(value)) return;
    if (edge === 'top') setTop(String(Math.max(0, Math.min(visibleBottom - 16, Math.round(value)))));
    else setBottom(String(Math.min(height, Math.max(visibleTop + 16, Math.round(value)))));
    if (!valid) { if (edge === 'top') setBottom(String(candidate.bottom)); else setTop(String(candidate.top)); }
  }
  useEffect(() => {
    if (typeof dialog.current?.showModal === 'function') dialog.current.showModal(); else dialog.current?.setAttribute('open', '');
    const links = [candidate.before, candidate.after].map(URL.createObjectURL); setUrls(links);
    return () => links.forEach(URL.revokeObjectURL);
  }, [candidate]);
  return <dialog ref={dialog} className="canvas-compare photo-layout-review" aria-label="截图裁剪预览" onCancel={e => { if (busy) e.preventDefault(); else onClose(); }}>
    <header><strong>先确认要保留的画面</strong><button disabled={busy} onClick={onClose}>放弃裁剪</button></header>
    <p>拖动原图上的上下沿，保留商品完整。也可选中拖柄，用方向键微调。建议来自黑色留空；“找同款”等内部标签仍需检查。</p>
    <div className="crop-review-images">
      <figure><div className="crop-range-stage" style={{aspectRatio:`${width}/${height}`, width:`min(100%, ${52 * width / height}vh)`}}>
        {urls[0] && <img src={urls[0]} alt="完整截图" draggable={false} />}
        <svg ref={range} viewBox={`0 0 ${width} ${height}`} aria-label="调整截图保留范围" onPointerMove={e => {
          if (!dragging.current) return;
          const rect = range.current!.getBoundingClientRect();
          if (rect.height) move(dragging.current, (e.clientY - rect.top) / rect.height * height);
        }} onPointerUp={() => { dragging.current = undefined; }} onPointerCancel={() => { dragging.current = undefined; }}>
          <rect width={width} height={visibleTop} fill="#0009" pointerEvents="none" />
          <rect y={visibleBottom} width={width} height={height-visibleBottom} fill="#0009" pointerEvents="none" />
          {(['top','bottom'] as const).map(edge => <g key={edge} role="slider" tabIndex={busy ? -1 : 0} aria-label={edge === 'top' ? '保留上沿' : '保留下沿'} aria-orientation="vertical" aria-disabled={busy} aria-valuemin={edge === 'top' ? 0 : visibleTop + 16} aria-valuemax={edge === 'top' ? visibleBottom - 16 : height} aria-valuenow={edge === 'top' ? visibleTop : visibleBottom} transform={`translate(0 ${edge === 'top' ? visibleTop : visibleBottom})`}
            onPointerDown={e => { if (busy) return; e.preventDefault(); e.currentTarget.focus(); dragging.current = edge; e.currentTarget.setPointerCapture(e.pointerId); }}
            onKeyDown={e => {
              if (!['ArrowUp','ArrowDown','Home','End'].includes(e.key)) return;
              e.preventDefault(); const value = edge === 'top' ? visibleTop : visibleBottom;
              move(edge, e.key === 'Home' ? 0 : e.key === 'End' ? height : value + (e.key === 'ArrowUp' ? -1 : 1) * (e.shiftKey ? 10 : 1));
            }}>
            <rect y={-hitHeight/2} width={width} height={hitHeight} fill="transparent" />
            <line x2={width} stroke="#70d4ee" strokeWidth={width*.009} />
            <rect x={(width-handleWidth)/2} y={-handleHeight/2} width={handleWidth} height={handleHeight} rx={width*.025} fill="#1e5666" stroke="#a2eeff" strokeWidth={width*.006} />
            <text x={width*.5} y={fontSize*.35} fill="white" fontSize={fontSize} textAnchor="middle" pointerEvents="none">{edge === 'top' ? '↕ 上沿' : '↕ 下沿'}</text>
          </g>)}
        </svg>
      </div><figcaption>拖动两条线之间的范围将被保留</figcaption></figure>
      <figure>{urls[1] && <img src={urls[1]} alt="裁剪候选" />}<figcaption>{dirty ? '范围已调整，请更新右侧预览' : `保留范围 · ${candidate.document.width} × ${candidate.document.height}`}</figcaption></figure>
    </div>
    <details><summary>精确调整边界</summary><div className="canvas-button-grid"><label>上边界<input aria-label="裁剪上边界" type="number" min={0} max={height - 16} disabled={busy} value={top} onChange={e => setTop(e.target.value)} /></label><label>下边界<input aria-label="裁剪下边界" type="number" min={16} max={height} disabled={busy} value={bottom} onChange={e => setBottom(e.target.value)} /></label></div></details>
    <button disabled={busy || !dirty || !valid} onClick={() => onPreview(Number(top), Number(bottom))}>更新裁剪预览</button>
    <button className="canvas-primary" disabled={busy || dirty || !valid} onClick={onApply}>确认范围，应用裁剪</button>
    <p>修改边界后先更新预览。应用可撤销，原素材保留。</p>
  </dialog>;
}
