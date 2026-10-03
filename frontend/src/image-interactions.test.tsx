// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { ImageWorkspace } from './ImageWorkspace';
import { ImageJobCard } from './ImageJobCard';
import { Composer } from './Composer';
import { readApi, writeApi } from './management-api';
import { attachmentBlob, type Attachment } from './attachments';
import type { ImageHistory, ImageJob } from './image-api';
import type { ChatController } from './chat-controller';
import type { ChatState } from './types';

vi.mock('./management-api', () => ({ readApi: vi.fn(), writeApi: vi.fn() }));
vi.mock('./attachments', () => ({ attachmentBlob: vi.fn(), uploadFile: vi.fn() }));
const source: Attachment = { id: 'source-id', name: 'original.png', kind: 'image', mime: 'image/png', bytes: 100 };
const output: Attachment = { ...source, id: 'output-id', name: 'edit.png' };
const done: ImageJob = { id: 'job-id', state: 'succeeded', source, output, root_id: source.id, operation: 'adjust', params: { brightness: .2 }, provider: 'local' };
const history: ImageHistory = { images: [output, source], jobs: [done], cloud: { configured: false, model: 'qwen-image-edit-max' } };
const controller = { connection: 'open', send: vi.fn() } as unknown as ChatController;
const state: ChatState = { storedId: 'owner-a', sessionId: 'session-a', sessions: [], items: [], info: { tools: { images: ['miniclaw_edit_image'] } }, running: false, busy: false, status: '', error: '' };
let host: HTMLDivElement; let root: Root;

beforeEach(() => {
  vi.clearAllMocks(); localStorage.clear();
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  HTMLDialogElement.prototype.showModal = vi.fn(); HTMLDialogElement.prototype.close = vi.fn();
  URL.createObjectURL = vi.fn(() => 'blob:fixture'); URL.revokeObjectURL = vi.fn();
  vi.mocked(attachmentBlob).mockResolvedValue(new Blob(['image']));
  vi.mocked(readApi).mockImplementation(async path => path.includes('session-capabilities') ? { ready: true, images: true } : history);
  vi.mocked(writeApi).mockResolvedValue(done);
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.useRealTimers(); });
async function click(text: string) {
  const button = [...host.querySelectorAll<HTMLButtonElement>('button')].find(b => b.textContent === text || b.getAttribute('aria-label') === text);
  expect(button).toBeDefined(); await act(async () => button!.click());
}
async function workspace(props: Partial<Parameters<typeof ImageWorkspace>[0]> = {}) {
  await act(async () => root.render(<ImageWorkspace controller={controller} chat={state} initial={source} onClose={() => {}} onUse={() => {}} onTools={() => {}} {...props} />));
}

test('comparison uses owned blobs; continue selects output and can put it back into chat', async () => {
  const use = vi.fn(); await workspace({ onUse: use });
  expect(attachmentBlob).toHaveBeenCalledWith('owner-a', source, expect.any(AbortSignal));
  expect(attachmentBlob).toHaveBeenCalledWith('owner-a', output, expect.any(AbortSignal));
  expect(host.querySelector('a[download="edit.png"]')).not.toBeNull();
  await click('把结果放回聊天'); expect(use).toHaveBeenCalledWith(output);
  use.mockClear();
  await click('用结果继续修改'); await click('把这张图放回聊天');
  expect(use).toHaveBeenCalledWith(output);
  expect(host.querySelector('a[download="edit.png"]')?.textContent).toBe('下载这张图');
});

test('manual and retry requests preserve runtime ownership and the same idempotency key', async () => {
  vi.mocked(writeApi).mockRejectedValueOnce(new Error('fixture timeout')).mockResolvedValueOnce(done);
  await workspace(); await click('开始修图');
  const first = vi.mocked(writeApi).mock.calls[0];
  expect(first[2]).toMatchObject({ session_id: 'session-a', source_id: source.id, operation: 'adjust' });
  expect(first[2]).not.toHaveProperty('owner');
  await click('核对原请求');
  expect(vi.mocked(writeApi).mock.calls[1][2]).toEqual(first[2]);
});

test('a new running edit never presents an older result as the current output', async () => {
  vi.mocked(readApi).mockResolvedValue({ ...history, jobs: [{ ...done, id: 'new-job', state: 'running', operation: 'ai_edit', output: undefined }, done] });
  await workspace();
  expect(host.textContent).toContain('正在修图');
  expect(host.querySelector('img[alt^="修改后"]')).toBeNull();
  expect(host.querySelector('a[download="original.png"]')).not.toBeNull();
});

test('missing actual tools disables execution; AI without credentials never submits', async () => {
  const tools = vi.fn(); await workspace({ chat: { ...state, info: {} }, onTools: tools });
  await click('开始修图'); expect(writeApi).not.toHaveBeenCalled();
  await click('打开工具设置'); expect(tools).toHaveBeenCalledOnce();
  await workspace();
  const select = host.querySelector<HTMLSelectElement>('select[aria-label="编辑方式"]')!;
  await act(async () => { select.value = 'ai_edit'; select.dispatchEvent(new Event('change', { bubbles: true })); });
  expect(host.textContent).toContain('源图与要求会发送给百炼');
  await click('开始修图'); expect(writeApi).not.toHaveBeenCalled();
});

test('pending tool result polls its owned job and publishes a completed comparison', async () => {
  vi.useFakeTimers(); vi.mocked(readApi).mockResolvedValue(done);
  await act(async () => root.render(<ImageJobCard owner="owner-a" result={{ ...done, state: 'running', output: undefined }} />));
  expect(host.textContent).toContain('正在修图'); expect(host.querySelector('a[download="edit.png"]')).toBeNull();
  await act(async () => vi.advanceTimersByTimeAsync(600));
  expect(readApi).toHaveBeenCalledWith('/api/miniclaw/image-jobs/job-id?owner=owner-a', expect.any(AbortSignal));
  expect(host.textContent).toContain('修图完成'); expect(host.querySelector('a[download="edit.png"]')).not.toBeNull();
});

test('putting an image into a full chat draft preserves all existing attachments and text', async () => {
  const attachments = [1, 2, 3, 4].map(i => ({ ...source, id: 'prior-' + i }));
  localStorage.setItem('miniclaw.draft.owner-a', JSON.stringify({ text: '不要丢失', attachments }));
  await act(async () => root.render(<Composer controller={controller} chat={state} onManage={() => {}} suggestion={{ text: '', attachment: output, nonce: 1 }} />));
  expect(host.textContent).toContain('输入框已有4个附件');
  expect(JSON.parse(localStorage.getItem('miniclaw.draft.owner-a')!).attachments).toEqual(attachments);
  expect(host.querySelector<HTMLTextAreaElement>('#message-input')?.value).toBe('不要丢失');
});
