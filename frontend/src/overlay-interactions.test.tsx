// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, test, vi } from 'vitest';
import { Message } from './Message';
import { uploadFile } from './attachments';

test('compiled overlay uses the authenticated artifact download rather than a model URL', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('URL', { createObjectURL: () => 'blob:compiled', revokeObjectURL: vi.fn() });
  const fetcher = vi.fn().mockResolvedValue({ ok: true, blob: async () => new Blob(['{"version":1}']) });
  vi.stubGlobal('fetch', fetcher);
  window.__HERMES_SESSION_TOKEN__ = 'fixture-auth';
  const host = document.createElement('div'); document.body.append(host); const root = createRoot(host);
  try {
    await act(async () => root.render(<Message owner="owner" onReuse={() => {}} item={{ kind: 'tool', name: 'miniclaw_overlay_compile', id: 'overlay', status: 'done', text: '', result: { success: true, path: 'artifacts/overlay.json' } }} />));
    expect(host.textContent).toContain('生成动效编排');
    expect(fetcher).toHaveBeenCalledWith('/api/miniclaw/artifacts/overlay.json', expect.objectContaining({ headers: { 'X-Hermes-Session-Token': 'fixture-auth' } }));
    expect(host.querySelector('a[download="overlay.json"]')?.getAttribute('href')).toBe('blob:compiled');
  } finally {
    await act(async () => root.unmount()); host.remove(); delete window.__HERMES_SESSION_TOKEN__; vi.unstubAllGlobals();
  }
});

test('SRT upload enforces the text size cap before issuing a request', async () => {
  const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher);
  try {
    await expect(uploadFile('owner', new File(['x'.repeat(65537)], 'oversize.srt'))).rejects.toThrow('64 KiB');
    expect(fetcher).not.toHaveBeenCalled();
  } finally { vi.unstubAllGlobals(); }
});
