// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { Composer } from './Composer';
import { SettingsDialog } from './SettingsDialog';
import { SkillEditor } from './SkillEditor';
import { MemoryEditor } from './MemoryEditor';
import { App } from './App';
import { attachmentBlob, uploadFile, type Attachment } from './attachments';
import { readApi, writeApi } from './management-api';
import type { ChatController } from './chat-controller';
import type { ChatState } from './types';

vi.mock('./management-api', () => ({ readApi: vi.fn(), writeApi: vi.fn() }));
vi.mock('./attachments', () => ({ uploadFile: vi.fn(), attachmentBlob: vi.fn() }));
let host: HTMLDivElement;
let root: Root;
const fakeAttachment: Attachment = { id: 'fixture-image', name: 'fixture.png', kind: 'image', mime: 'image/png', bytes: 10 };
const chat = (owner = 'owner-a'): ChatState => ({ sessions: [], sessionId: 'live-' + owner, storedId: owner, items: [], info: {}, running: false, busy: false, status: '', error: '' });
function controller() {
  return { connection: 'open', send: vi.fn().mockResolvedValue(true), stop: vi.fn(), client: { request: vi.fn().mockResolvedValue({}) } } as unknown as ChatController;
}
const input = () => host.querySelector<HTMLTextAreaElement>('textarea[aria-label="消息"]')!;
const button = (label: string) => [...host.querySelectorAll<HTMLButtonElement>('button')].find(el => el.getAttribute('aria-label') === label || el.textContent === label)!;
async function click(label: string) { await act(async () => button(label).click()); }
async function files(eventName: 'paste' | 'drop', supplied: File[]) {
  const event = new Event(eventName, { bubbles: true, cancelable: true });
  Object.defineProperty(event, eventName === 'paste' ? 'clipboardData' : 'dataTransfer', { value: { files: supplied, types: ['Files'] } });
  await act(async () => (eventName === 'paste' ? input() : host.querySelector('form')!).dispatchEvent(event));
}

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:fixture'), revokeObjectURL: vi.fn() });
  vi.resetAllMocks();
  vi.mocked(attachmentBlob).mockResolvedValue(new Blob(['fixture']));
  vi.mocked(readApi).mockResolvedValue({ ready: true, images: true });
  vi.mocked(writeApi).mockResolvedValue({});
  localStorage.clear();
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value: function(this: HTMLDialogElement) { this.setAttribute('open', ''); } });
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value: function(this: HTMLDialogElement) { this.removeAttribute('open'); } });
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); });

test('IME Enter and Shift+Enter cannot send; ordinary Enter sends the persisted draft', async () => {
  localStorage.setItem('miniclaw.draft.owner-a', JSON.stringify({ text: '你好', attachments: [] }));
  const c = controller();
  await act(async () => root.render(<Composer controller={c} chat={chat()} onManage={() => {}} />));
  for (const options of [{ isComposing: true }, { keyCode: 229 }, { shiftKey: true }]) {
    await act(async () => input().dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true, ...options })));
  }
  expect(c.send).not.toHaveBeenCalled();
  expect(input().value).toBe('你好');
  await act(async () => input().dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })));
  expect(c.send).toHaveBeenCalledWith('你好', undefined, []);
  expect(input().value).toBe('');
});

test('paste and drop upload owned files; remove only cancels that reference and attachment-only send works', async () => {
  const text: Attachment = { id: 'fixture-text', name: 'note.md', kind: 'text', mime: 'text/plain', bytes: 4 };
  vi.mocked(uploadFile).mockResolvedValueOnce(fakeAttachment).mockResolvedValueOnce(text);
  const c = controller();
  await act(async () => root.render(<Composer controller={c} chat={chat()} onManage={() => {}} />));
  const imageFile = new File(['image'], 'fixture.png', { type: 'image/png' });
  const textFile = new File(['note'], 'note.md', { type: 'text/markdown' });
  await files('paste', [imageFile]); await files('drop', [textFile]);
  expect(uploadFile).toHaveBeenNthCalledWith(1, 'owner-a', imageFile);
  expect(uploadFile).toHaveBeenNthCalledWith(2, 'owner-a', textFile);
  expect(host.querySelector('a[aria-label="预览 fixture.png"]')).not.toBeNull();
  expect(host.querySelector('a[download="note.md"]')).not.toBeNull();
  await click('移除 fixture.png');
  await click('发送');
  expect(c.send).toHaveBeenCalledWith('', undefined, [text]);
  expect(JSON.parse(localStorage.getItem('miniclaw.draft.owner-a')!).attachments).toEqual([]);
});

test('a completed upload cannot enter a different session after the Composer unmounts', async () => {
  let finish!: (attachment: Attachment) => void;
  vi.mocked(uploadFile).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const c = controller();
  await act(async () => root.render(<Composer key="a" controller={c} chat={chat()} onManage={() => {}} />));
  await files('paste', [new File(['image'], 'fixture.png', { type: 'image/png' })]);
  await act(async () => root.render(<Composer key="b" controller={c} chat={chat('owner-b')} onManage={() => {}} />));
  await act(async () => finish(fakeAttachment));
  expect(host.textContent).not.toContain('fixture.png');
  expect(JSON.parse(localStorage.getItem('miniclaw.draft.owner-b')!).attachments).toEqual([]);
});

test('refused sending preserves the text and attachments for correction', async () => {
  localStorage.setItem('miniclaw.draft.owner-a', JSON.stringify({ text: 'retain this', attachments: [fakeAttachment] }));
  const c = controller(); vi.mocked(c.send).mockResolvedValue(false);
  await act(async () => root.render(<Composer controller={c} chat={chat()} onManage={() => {}} />));
  await click('发送');
  expect(input().value).toBe('retain this');
  expect(host.textContent).toContain('fixture.png');
  expect(JSON.parse(localStorage.getItem('miniclaw.draft.owner-a')!).attachments).toHaveLength(1);
});

test('untouched new template leaves directly; real changes use the in-page keep/discard protection', async () => {
  vi.mocked(readApi).mockImplementation(async path => path.endsWith('/tools') ? { groups: [] } : []);
  const c = controller(); const close = vi.fn();
  await act(async () => root.render(<SettingsDialog controller={c} chat={chat()} initialTab="skills" onClose={close} />));
  await click('添加技能');
  await click('关闭设置');
  expect(close).toHaveBeenCalledOnce();
  expect(host.querySelector('[role="alertdialog"]')).toBeNull();
  close.mockClear();
  await act(async () => host.querySelector<HTMLInputElement>('.binding-confirm input')!.click());
  await click('关闭设置');
  expect(close).not.toHaveBeenCalled();
  expect(host.querySelector('.settings-layout')!.hasAttribute('inert')).toBe(true);
  expect(host.querySelector('[role="alertdialog"]')).not.toBeNull();
  await click('继续编辑');
  expect(host.querySelector('.settings-layout')!.hasAttribute('inert')).toBe(false);
  await click('关闭设置'); await click('放弃修改并离开');
  expect(close).toHaveBeenCalledOnce();
});

test('imported Skill is created, declared against server hash, then reloaded without frontend dispatch', async () => {
  const content = '---\nname: import-demo\ndescription: Summarize supplied text.\n---\n\nSummarize only the supplied text.';
  vi.mocked(readApi).mockImplementation(async path => path.endsWith('/tools') ? { groups: [] } : { content_hash: 'server-hash', content });
  const c = controller(); const saved = vi.fn();
  await act(async () => root.render(<SkillEditor controller={c} sessionId="live" blocked={false} onBack={() => {}} onSaved={saved} onDirty={() => {}} onBusy={() => {}} />));
  const file = { name: 'SKILL.md', size: content.length, arrayBuffer: async () => new TextEncoder().encode(content).buffer } as File;
  const upload = host.querySelector<HTMLInputElement>('input[type="file"]')!;
  Object.defineProperty(upload, 'files', { configurable: true, value: [file] });
  await act(async () => upload.dispatchEvent(new Event('change', { bubbles: true })));
  expect(host.querySelector<HTMLInputElement>('input[aria-label="技能标识"]')!.value).toBe('import-demo');
  await act(async () => host.querySelector<HTMLInputElement>('.binding-confirm input')!.click());
  await click('保存技能与依赖');
  expect(writeApi).toHaveBeenNthCalledWith(1, '/api/miniclaw/skills', 'POST', { name: 'import-demo', content });
  expect(writeApi).toHaveBeenNthCalledWith(2, '/api/miniclaw/skills/binding', 'PUT', { name: 'import-demo', required_tools: [], content_hash: 'server-hash' });
  expect(c.client.request).toHaveBeenCalledWith('skills.reload', { session_id: 'live' });
  expect(saved).toHaveBeenCalledOnce();
});

test('memory UI describes the actual session snapshot separately from saved file content', async () => {
  vi.mocked(readApi).mockImplementation(async path => path.includes('/session-capabilities') ? { ready: true, memory: { memory: { enabled: true, loaded: true }, user: { enabled: false, loaded: false } } } : { memory: { text: 'saved fact', hash: 'm', limit: 2200 }, user: { text: 'saved preference', hash: 'u', limit: 1375 } });
  await act(async () => root.render(<MemoryEditor sessionId="live" blocked={false} onBusy={() => {}} onDirty={() => {}} />));
  expect(host.textContent).toContain('本对话已加载启动时的记忆快照');
  await click('个人偏好');
  expect(host.textContent).toContain('本对话未开启此项加载');
  expect(host.querySelector<HTMLTextAreaElement>('textarea')!.value).toBe('saved preference');
});

test('reading older messages suspends forced scrolling until the user returns to the latest message', async () => {
  const scroll = vi.fn();
  Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: scroll });
  Object.defineProperty(Element.prototype, 'scrollTo', { configurable: true, value: vi.fn() });
  vi.mocked(readApi).mockImplementation(async path => path.includes('/api/sessions?') ? { sessions: [], total: 0 } : { ready: true, images: true });
  const c = controller(); let notify = () => {};
  Object.assign(c, { state: { ...chat(), items: [{ id: 'reply', kind: 'assistant', text: 'first segment' }] }, connect: vi.fn().mockResolvedValue(undefined), dispose: vi.fn(), subscribe: (listener: () => void) => { notify = listener; return () => {}; } });
  await act(async () => root.render(<App controller={c} />));
  const conversation = host.querySelector<HTMLDivElement>('.conversation')!;
  Object.defineProperties(conversation, { scrollHeight: { configurable: true, value: 2000 }, clientHeight: { configurable: true, value: 400 }, scrollTop: { configurable: true, writable: true, value: 100 } });
  scroll.mockClear();
  await act(async () => conversation.dispatchEvent(new Event('scroll', { bubbles: true })));
  c.state = { ...c.state, items: [{ id: 'reply', kind: 'assistant', text: 'a later streamed segment' }] };
  await act(async () => notify());
  expect(scroll).not.toHaveBeenCalled();
  await click('↓ 回到最新消息');
  expect(scroll).toHaveBeenCalledWith({ behavior: 'smooth' });
  scroll.mockClear();
  c.state = { ...c.state, items: [{ id: 'reply', kind: 'assistant', text: 'final streamed segment' }] };
  await act(async () => notify());
  expect(scroll).toHaveBeenCalledWith({ behavior: 'instant' });
});
