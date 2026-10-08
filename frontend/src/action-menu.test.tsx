// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, test, vi } from 'vitest';
import { ActionMenu } from './ActionMenu';

test('secondary actions close on outside click, Escape and selection, restoring keyboard focus',async()=>{
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
  const host=document.createElement('div'),root=createRoot(host);document.body.append(host);
  const action=vi.fn();
  try {
    await act(async()=>root.render(<ActionMenu><button onClick={action}>导出 PNG</button></ActionMenu>));
    const trigger=host.querySelector('button')!;
    await act(async()=>trigger.click());expect(trigger.getAttribute('aria-expanded')).toBe('true');
    await act(async()=>document.body.dispatchEvent(new Event('pointerdown',{bubbles:true})));expect(host.textContent).not.toContain('导出 PNG');
    await act(async()=>trigger.click());
    await act(async()=>document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})));expect(document.activeElement).toBe(trigger);expect(trigger.getAttribute('aria-expanded')).toBe('false');
    await act(async()=>trigger.click());await act(async()=>host.querySelector('.action-menu-panel button')!.dispatchEvent(new MouseEvent('click',{bubbles:true})));
    expect(action).toHaveBeenCalledOnce();expect(trigger.getAttribute('aria-expanded')).toBe('false');
  } finally {await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();}
});
