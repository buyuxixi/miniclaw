import { useEffect, useRef, useState, type PointerEvent } from 'react';
import { createPortal } from 'react-dom';
import { Icon } from './Icon';
import './image-preview.css';

export function ImagePreview({ url, name, onClose }: { url: string; name: string; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const image = useRef<HTMLImageElement>(null);
  const drag = useRef<{ id: number; x: number; y: number; left: number; top: number } | null>(null);
  const dragged = useRef(false);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [error, setError] = useState(false);

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const modal = dialog.current!;
    if (typeof modal.showModal === 'function') modal.showModal();
    else modal.setAttribute('open', '');
    const measure = () => {
      const pane = stage.current, img = image.current;
      if (!pane || !img?.naturalWidth) return;
      const fit = Math.min(Math.max(1, pane.clientWidth - 32) / img.naturalWidth, Math.max(1, pane.clientHeight - 32) / img.naturalHeight);
      setSize({ width: img.naturalWidth * fit, height: img.naturalHeight * fit });
      setPan({ x: 0, y: 0 });
    };
    const img = image.current!;
    img.addEventListener('load', measure);
    const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(measure) : null;
    observer?.observe(stage.current!);
    window.addEventListener('resize', measure);
    measure();
    return () => {
      observer?.disconnect();
      img.removeEventListener('load', measure);
      window.removeEventListener('resize', measure);
      if (typeof modal.close === 'function') modal.close();
      if (opener?.isConnected) opener.focus({ preventScroll: true });
    };
  }, []);

  function changeZoom(value: number) {
    setZoom(Math.max(0.25, Math.min(8, value)));
    setPan({ x: 0, y: 0 });
  }
  function startDrag(event: PointerEvent<HTMLDivElement>) {
    dragged.current = false;
    if (event.button !== 0 || event.target !== image.current || zoom <= 1) return;
    event.preventDefault();
    drag.current = { id: event.pointerId, x: event.clientX, y: event.clientY, left: pan.x, top: pan.y };
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  function moveDrag(event: PointerEvent<HTMLDivElement>) {
    const start = drag.current, pane = stage.current;
    if (!start || start.id !== event.pointerId || !pane) return;
    const dx = event.clientX - start.x, dy = event.clientY - start.y;
    if (Math.abs(dx) + Math.abs(dy) > 4) dragged.current = true;
    const limitX = Math.max(0, (size.width * zoom - pane.clientWidth) / 2);
    const limitY = Math.max(0, (size.height * zoom - pane.clientHeight) / 2);
    setPan({ x: Math.max(-limitX, Math.min(limitX, start.left + dx)), y: Math.max(-limitY, Math.min(limitY, start.top + dy)) });
  }
  function endDrag(event: PointerEvent<HTMLDivElement>) {
    if (drag.current?.id !== event.pointerId) return;
    drag.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  }

  return createPortal(<dialog ref={dialog} className="image-lightbox" aria-label={`图片预览：${name}`} onCancel={event => { event.preventDefault(); event.stopPropagation(); onClose(); }}>
    <header className="image-lightbox-header"><strong title={name}>{name}</strong><button type="button" aria-label="关闭图片预览" title="关闭（Esc）" onClick={onClose}><Icon name="close" size={22} /></button></header>
    <div ref={stage} className={`image-lightbox-stage ${zoom > 1 ? 'can-pan' : ''}`} onPointerDown={startDrag} onPointerMove={moveDrag} onPointerUp={endDrag} onPointerCancel={endDrag} onClick={event => { if (event.target === event.currentTarget && !dragged.current) onClose(); }} onWheel={event => { if (event.deltaY) changeZoom(zoom + (event.deltaY < 0 ? 0.25 : -0.25)); }}>
      {error ? <p role="alert">图片加载失败，请关闭后重新打开。</p> : <img ref={image} src={url} alt={name} title="滚轮或双击缩放，放大后拖动查看" draggable={false} onError={() => setError(true)} style={{ width: size.width || undefined, height: size.height || undefined, transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})` }} onDoubleClick={() => changeZoom(zoom === 1 ? 2 : 1)} />}
    </div>
    <footer className="image-lightbox-toolbar"><button type="button" aria-label="缩小图片" disabled={zoom <= 0.25} onClick={() => changeZoom(zoom - 0.25)}>−</button><output aria-label="图片缩放倍率" title="相对适配窗口的大小">{Math.round(zoom * 100)}%</output><button type="button" aria-label="放大图片" disabled={zoom >= 8} onClick={() => changeZoom(zoom + 0.25)}>＋</button><button type="button" aria-label="适应窗口" onClick={() => changeZoom(1)}>适应窗口</button><a href={url} download={name}>下载</a></footer>
  </dialog>, document.body);
}
