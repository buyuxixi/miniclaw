import { useEffect, useRef, useState } from 'react';

export function ImageDetailReview({ before, after, onClose }: { before: string; after?: string; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const panes = useRef<(HTMLDivElement | null)[]>([]);
  const [zoom, setZoom] = useState(100);
  useEffect(() => {
    if (typeof dialog.current?.showModal === 'function') dialog.current.showModal();
    else dialog.current?.setAttribute('open','');
  }, []);
  function sync(index: number) {
    const source = panes.current[index], target = panes.current[1-index];
    if (!source || !target) return;
    const x = source.scrollLeft / Math.max(1, source.scrollWidth-source.clientWidth) * Math.max(0,target.scrollWidth-target.clientWidth);
    const y = source.scrollTop / Math.max(1, source.scrollHeight-source.clientHeight) * Math.max(0,target.scrollHeight-target.clientHeight);
    if (Math.abs(target.scrollLeft-x)>1) target.scrollLeft=x;
    if (Math.abs(target.scrollTop-y)>1) target.scrollTop=y;
  }
  function reset() { setZoom(100); panes.current.forEach(pane => { if (pane) { pane.scrollLeft=0; pane.scrollTop=0; } }); }
  return <dialog ref={dialog} className="image-detail-dialog" aria-label={after ? '商品细节对照' : '图片放大查看'} onCancel={e => { e.preventDefault(); e.stopPropagation(); onClose(); }}>
    <header><strong>{after ? '放大核对商品细节' : '放大查看图片'}</strong><button onClick={onClose}>关闭细节查看</button></header>
    <p>先看轮廓，再看部件颜色、绳线和纹理。查看不会采用图片或修改核对记录。</p>
    <div className="image-detail-toolbar"><button disabled={zoom<=100} onClick={() => setZoom(z=>z-50)} aria-label="缩小对照">−</button><output aria-label="对照倍率">{zoom}%</output><button disabled={zoom>=400} onClick={() => setZoom(z=>z+50)} aria-label="放大对照">＋</button><button onClick={reset}>恢复全图</button></div>
    <div className={`image-detail-grid ${after ? '' : 'single'}`}>
      {[before,...(after ? [after] : [])].map((url,i)=><figure key={i}><figcaption>{i ? '修改后' : after ? '修改前' : '当前图片'}</figcaption><div className="image-detail-pane" ref={el => { panes.current[i]=el; }} onScroll={()=>sync(i)} tabIndex={0} aria-label={i ? '修改后细节' : '修改前细节'}><img src={url} alt={i ? '修改后放大图' : '修改前放大图'} draggable={false} style={{width:`${zoom}%`}} /></div></figure>)}
    </div>
    <p>100%适配窗口宽度。左右倍率同步，滚动联动查看相对位置；不同尺寸或构图不会自动对齐。</p>
  </dialog>;
}
