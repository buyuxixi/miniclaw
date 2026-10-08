import { useEffect, useRef, useState, type ReactNode } from 'react';

export function ActionMenu({ label = '更多', className = '', children }: { label?: string; className?: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    function outside(e: PointerEvent) { if (!root.current?.contains(e.target as Node)) setOpen(false); }
    function escape(e: KeyboardEvent) { if (e.key === 'Escape') { e.preventDefault(); setOpen(false); trigger.current?.focus(); } }
    document.addEventListener('pointerdown', outside);
    document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape); };
  }, [open]);
  return <div ref={root} className={`action-menu ${className}`}>
    <button ref={trigger} aria-expanded={open} onClick={() => setOpen(v => !v)}>{label}</button>
    {open && <div className="action-menu-panel" onClick={e => { if ((e.target as HTMLElement).closest('button:not(:disabled)')) setOpen(false); }}>{children}</div>}
  </div>;
}
