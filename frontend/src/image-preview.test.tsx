// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { AttachmentCard } from './AttachmentCard';
import { attachmentBlob, type Attachment } from './attachments';

vi.mock('./attachments', () => ({ attachmentBlob: vi.fn() }));
let host: HTMLDivElement, root: Root;
const image: Attachment = { id: 'one', name: '产品图.png', kind: 'image', mime: 'image/png', bytes: 100 };
const preview = () => document.querySelector<HTMLDialogElement>('.image-lightbox');
const click = async (label: string) => act(async () => document.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`)!.click());
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:fixture') });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
  vi.mocked(attachmentBlob).mockResolvedValue(new Blob(['fixture']));
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); });
const render = async (attachment = image, owner = 'owner') => act(async () => root.render(<AttachmentCard attachment={attachment} owner={owner} />));

test('thumbnail opens an in-page modal with the same image and no navigation link', async () => {
  await render();
  expect(host.querySelector('a[target="_blank"]')).toBeNull();
  await click('预览 产品图.png');
  expect(preview()?.hasAttribute('open')).toBe(true);
  expect(preview()?.getAttribute('aria-label')).toBe('图片预览：产品图.png');
  expect(preview()?.querySelector('img')?.getAttribute('src')).toBe('blob:fixture');
  expect(preview()?.querySelector('a[download]')?.getAttribute('download')).toBe(image.name);
  expect(attachmentBlob).toHaveBeenCalledTimes(1);
  await click('关闭图片预览');
  expect(preview()).toBeNull();
  expect(URL.revokeObjectURL).not.toHaveBeenCalled();
});

test('zoom and reset work, clicking the image keeps it open, background closes it', async () => {
  await render(); await click('预览 产品图.png');
  await click('放大图片');
  expect(preview()?.querySelector('output')?.textContent).toBe('125%');
  await act(async () => preview()!.querySelector('img')!.click());
  expect(preview()).not.toBeNull();
  await click('适应窗口');
  expect(preview()?.querySelector('output')?.textContent).toBe('100%');
  await click('缩小图片');
  expect(preview()?.querySelector('output')?.textContent).toBe('75%');
  await act(async () => preview()!.querySelector<HTMLElement>('.image-lightbox-stage')!.click());
  expect(preview()).toBeNull();
});

test('Escape cancels only the preview and releases it on owner changes or unmount', async () => {
  await render(); await click('预览 产品图.png');
  const cancel = new Event('cancel', { bubbles: true, cancelable: true });
  await act(async () => preview()!.dispatchEvent(cancel));
  expect(cancel.defaultPrevented).toBe(true); expect(preview()).toBeNull();
  await click('预览 产品图.png');
  await render(image, 'another-owner');
  expect(preview()).toBeNull();
  await click('预览 产品图.png');
  await act(async () => root.render(null));
  expect(preview()).toBeNull(); expect(URL.revokeObjectURL).toHaveBeenCalled();
});

test('text downloads and failed image loading do not open a preview', async () => {
  await render({ ...image, id: 'text', kind: 'text', name: '资料.txt' });
  expect(host.querySelector('a[download]')?.textContent).toBe('下载原文');
  expect(host.querySelector('button[aria-label^="预览"]')).toBeNull();
  vi.mocked(attachmentBlob).mockRejectedValueOnce(new Error('附件不可用'));
  await render({ ...image, id: 'missing' });
  expect(host.textContent).toContain('附件不可用');
  expect(host.querySelector('button[aria-label^="预览"]')).toBeNull();
});

test('a tall image fits fully, wheel zoom enables dragging, and a drag never dismisses it', async () => {
  await render(); await click('预览 产品图.png');
  const pane = preview()!.querySelector<HTMLDivElement>('.image-lightbox-stage')!;
  const img = preview()!.querySelector<HTMLImageElement>('img')!;
  Object.defineProperties(pane, { clientWidth: { value: 800 }, clientHeight: { value: 600 } });
  Object.defineProperties(img, { naturalWidth: { value: 800 }, naturalHeight: { value: 1600 } });
  pane.setPointerCapture = vi.fn(); pane.hasPointerCapture = () => true; pane.releasePointerCapture = vi.fn();
  await act(async () => img.dispatchEvent(new Event('load')));
  expect(img.style.height).toBe('568px'); expect(img.style.width).toBe('284px');
  await act(async () => pane.dispatchEvent(new WheelEvent('wheel', { bubbles: true, deltaY: -100 })));
  expect(preview()?.querySelector('output')?.textContent).toBe('125%');
  // At 2x, this portrait is taller than the viewport but still narrower than it.
  await act(async () => img.dispatchEvent(new MouseEvent('dblclick', { bubbles: true })));
  await act(async () => img.dispatchEvent(new MouseEvent('dblclick', { bubbles: true })));
  const pointer = (target: Element, type: string, x: number, y: number) => {
    const event = new MouseEvent(type, { bubbles: true, clientX: x, clientY: y, button: 0 });
    Object.defineProperty(event, 'pointerId', { value: 1 }); target.dispatchEvent(event);
  };
  await act(async () => pointer(img, 'pointerdown', 400, 300));
  await act(async () => pointer(pane, 'pointermove', 600, 200));
  expect(img.style.transform).toContain('translate(0px, -100px)');
  await act(async () => pointer(pane, 'pointerup', 600, 200));
  await act(async () => pane.click());
  expect(preview()).not.toBeNull();
  await click('适应窗口'); expect(img.style.transform).toBe('translate(0px, 0px) scale(1)');
});
