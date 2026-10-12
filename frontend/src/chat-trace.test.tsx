// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { App } from './App';
import { useChatTrace, mergeTracePage, type TracePage } from './use-chat-trace';
import { withTraceHistory, traceHistoryRedact } from './trace-history';
import { readApi } from './management-api';
import type { ChatController } from './chat-controller';
import type { ChatState } from './types';
import type { TraceStep } from './trace-view';

vi.mock('./management-api', () => ({ readApi: vi.fn(), writeApi: vi.fn() }));
let host: HTMLDivElement, root: Root;
const step = (id: string, sequence = 1, update = 1): TraceStep => ({ id, sequence, updated_at: update, kind: 'model', name: id, status: 'completed', started_at: 10, ended_at: 11 });
const page = (steps: TraceStep[], has_more = false, revision = 1): TracePage => ({ steps, has_more, next_before: has_more ? steps[0]?.sequence ?? null : null, revision });
const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; };
function Hook({ owner, running = false, enabled = true, version = '' }: { owner: string; running?: boolean; enabled?: boolean; version?: string }) {
  const trace = useChatTrace(owner, enabled, running, version);
  return <div><output>{trace.steps.map(s => s.name).join(',')}</output><span role="alert">{trace.error}</span><button onClick={trace.refresh}>刷新</button><button disabled={!trace.hasMore} onClick={trace.loadMore}>更早</button></div>;
}
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() });
  Object.defineProperty(Element.prototype, 'scrollTo', { configurable: true, value: vi.fn() });
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value: function(this: HTMLDialogElement) { this.open = true; } });
  vi.resetAllMocks();
  localStorage.clear();
  history.replaceState(null, '', '/c/owner-a');
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.useRealTimers(); vi.unstubAllGlobals(); });

test('Chat tabs preserve the exact composer instance, draft and conversation position', async () => {
  const state: ChatState = { sessions: [], sessionId: 'live-a', storedId: 'owner-a', items: [{ id: 'row-1', kind: 'user', text: '只讨论，不执行写入' }], info: {}, running: false, busy: false, status: '', error: '' };
  const controller = { state, connection: 'open', connect: vi.fn(), dispose: vi.fn(), subscribe: () => () => {}, send: vi.fn(), client: { request: vi.fn().mockResolvedValue({}) } } as unknown as ChatController;
  vi.mocked(readApi).mockImplementation(async url => url.startsWith('/api/miniclaw/traces') ? page([]) : url.startsWith('/api/workspaces?') ? [] : url === '/api/miniclaw/skills' ? [] : { ready: true, images: true });
  localStorage.setItem('miniclaw.draft.owner-a', JSON.stringify({ text: '还没发送的草稿', attachments: [] }));
  await act(async () => root.render(<App controller={controller}/>));
  const input = host.querySelector<HTMLTextAreaElement>('textarea[aria-label="消息"]')!;
  const conversation = host.querySelector<HTMLElement>('.conversation')!;
  Object.defineProperty(conversation, 'scrollHeight', { configurable: true, value: 2000 });
  Object.defineProperty(conversation, 'clientHeight', { configurable: true, value: 600 });
  conversation.scrollTop = 77;
  await act(async () => conversation.dispatchEvent(new Event('scroll', { bubbles: true })));
  await act(async () => host.querySelector<HTMLButtonElement>('#chat-trace-tab')!.click());
  expect(host.querySelector('[aria-label="Agent 执行轨迹"]')).not.toBeNull();
  expect(conversation.hidden).toBe(true);
  expect(host.querySelector('textarea[aria-label="消息"]')).toBe(input);
  expect(input.value).toBe('还没发送的草稿');
  expect(location.search).toBe('?view=trace');
  await act(async () => host.querySelector<HTMLButtonElement>('#chat-conversation-tab')!.click());
  expect(conversation.hidden).toBe(false);
  expect(conversation.scrollTop).toBe(77);
  expect(input.value).toBe('还没发送的草稿');
  expect(controller.send).not.toHaveBeenCalled();
  expect(vi.mocked(readApi).mock.calls.filter(([url]) => url.startsWith('/api/miniclaw/traces'))).toHaveLength(1);
});

test('switching sessions aborts an old request and discards its late response', async () => {
  const old = deferred<TracePage>();
  vi.mocked(readApi).mockImplementation(url => url.includes('owner=old') ? old.promise : Promise.resolve(page([step('new-session')])));
  await act(async () => root.render(<Hook owner="old"/>));
  const signal = vi.mocked(readApi).mock.calls[0][1]!;
  await act(async () => root.render(<Hook owner="new"/>));
  expect(signal.aborted).toBe(true);
  expect(host.querySelector('output')!.textContent).toBe('new-session');
  await act(async () => old.resolve(page([step('late-old-session')])));
  expect(host.querySelector('output')!.textContent).toBe('new-session');
});

test('hiding the trace aborts reads without touching the Agent conversation', async () => {
  const response = deferred<TracePage>();
  vi.mocked(readApi).mockReturnValue(response.promise);
  await act(async () => root.render(<Hook owner="a"/>));
  const signal = vi.mocked(readApi).mock.calls[0][1]!;
  await act(async () => root.render(<Hook owner="a" enabled={false}/>));
  expect(signal.aborted).toBe(true);
  await act(async () => response.resolve(page([step('hidden-result')])));
  expect(host.querySelector('output')!.textContent).toBe('');
});

test('running polls are bounded and the final state receives one last refresh', async () => {
  vi.useFakeTimers();
  vi.mocked(readApi).mockResolvedValue(page([step('request')]));
  await act(async () => root.render(<Hook owner="a" running/>));
  expect(readApi).toHaveBeenCalledTimes(1);
  await act(async () => vi.advanceTimersByTimeAsync(1500));
  expect(readApi).toHaveBeenCalledTimes(2);
  await act(async () => root.render(<Hook owner="a" running={false} version="complete"/>));
  expect(readApi).toHaveBeenCalledTimes(3);
  await act(async () => vi.advanceTimersByTimeAsync(5000));
  expect(readApi).toHaveBeenCalledTimes(3);
});

test('a refresh error retains loaded spans and a deliberate retry recovers them', async () => {
  vi.mocked(readApi).mockResolvedValueOnce(page([step('retained')])).mockRejectedValueOnce(new Error('HTTP 503')).mockResolvedValueOnce(page([step('retained'), step('recovered', 2)]));
  await act(async () => root.render(<Hook owner="a"/>));
  const refresh = [...host.querySelectorAll('button')].find(b => b.textContent === '刷新')!;
  await act(async () => refresh.click());
  expect(host.querySelector('output')!.textContent).toBe('retained');
  expect(host.querySelector('[role="alert"]')!.textContent).toContain('已保留');
  await act(async () => refresh.click());
  expect(host.querySelector('output')!.textContent).toBe('retained,recovered');
});

test('an exhausted older page stays exhausted when the recent window refreshes', () => {
  const initial = { owner: 'a', steps: [], loading: false, error: '', hasMore: false, before: null };
  const recent = mergeTracePage(initial, page([step('recent', 3)], true), false);
  const complete = mergeTracePage(recent, page([step('oldest', 1), step('older', 2)]), true);
  const refreshed = mergeTracePage(complete, page([step('recent', 3, 3), step('newest', 4, 3)], true, 3), false);
  expect(refreshed.steps.map(s => s.id)).toEqual(['oldest','older','recent','newest']);
  expect(refreshed.hasMore).toBe(false);
  expect(refreshed.before).toBeNull();
});

test('a stale record never reopens a settled span during page merging', () => {
  const initial = { owner: 'a', steps: [], loading: false, error: '', hasMore: false, before: null };
  const settled = mergeTracePage(initial, page([step('call', 2, 20)], false, 20), false);
  const late = mergeTracePage(settled, page([{ ...step('call', 2, 10), status: 'running', ended_at: null }], false, 10), true);
  expect(late.steps[0].status).toBe('completed');
  expect(late.steps[0].ended_at).toBe(11);
});

test('canonical ids de-duplicate new records while equal older messages remain', () => {
  const items = [{ id: 'row-1', kind: 'user' as const, text: '重复提问' }, { id: 'row-2', kind: 'assistant' as const, text: '旧回复' }, { id: 'row-3', kind: 'user' as const, text: '重复提问' }, { id: 'tool-1', kind: 'tool' as const, text: '', name: 'read', status: 'done' as const, result: 'ok' }, { id: 'row-5', kind: 'assistant' as const, text: '新回复' }];
  const recorded: TraceStep[] = [{ ...step('input'), kind: 'input', content: '重复提问', attributes: { message_id: 3 } }, { ...step('model', 2) }, { ...step('tool', 3), kind: 'tool', attributes: { call_id: 'tool-1' } }, { ...step('assistant', 4), kind: 'assistant', content: '新回复', attributes: { message_id: 5 } }];
  const merged = withTraceHistory(items, recorded);
  expect(merged.map(s => s.id)).toEqual(['history:row-1','history:row-2','input','model','tool','assistant']);
  expect(merged[0].duration_ms).toBeNull();
  expect(merged[0].input_tokens).toBeNull();
});

test('legacy receipts remain uncertain and redact nested JSON credentials', () => {
  const merged = withTraceHistory([{ id: 'write', kind: 'tool', text: '', name: 'pay', status: 'done', args: { api_key: 'secret-key' }, result: '{"outcome_uncertain":true,"token":"oauth-secret","url":"https://example.test/a?signature=secret-signature"}' }], []);
  expect(merged[0].status).toBe('unknown');
  expect(JSON.stringify(merged)).not.toContain('oauth-secret');
  expect(JSON.stringify(merged)).not.toContain('secret-signature');
  expect(JSON.stringify(merged)).not.toContain('secret-key');
  expect(traceHistoryRedact('data:image/png;base64,YWJjZA==')).toBe('[媒体内容]');
  const header = JSON.stringify(traceHistoryRedact({ headers: { Cookie: 'sessionid=private-cookie', proxy_authorization: 'private-auth' }, AWS_SECRET_ACCESS_KEY: 'private-storage' }));
  expect(header).not.toContain('private-cookie');
  expect(header).not.toContain('private-auth');
  expect(header).not.toContain('private-storage');
});

test('an optimistic repeated question does not consume an older canonical question', () => {
  const recorded: TraceStep[] = [{ ...step('new-input'), kind: 'input', content: '再来一次', attributes: { message_id: 9 } }, step('new-request', 2)];
  const merged = withTraceHistory([{ id: 'row-1', kind: 'user', text: '再来一次' }, { id: 'row-2', kind: 'assistant', text: '上次回答' }, { id: 'optimistic-uuid', kind: 'user', text: '再来一次' }], recorded);
  expect(merged.map(s => s.id)).toEqual(['history:row-1','history:row-2','new-input','new-request']);
});

test('opening a saved trace waits for Chat restoration before declaring an empty history', async () => {
  history.replaceState(null, '', '/c/owner-a?view=trace');
  const state: ChatState = { sessions: [], sessionId: '', storedId: 'owner-a', items: [], info: {}, running: false, busy: true, status: '正在读取对话', error: '' };
  const controller = { state, connection: 'open', connect: vi.fn(), dispose: vi.fn(), subscribe: () => () => {}, send: vi.fn(), client: { request: vi.fn().mockResolvedValue({}) } } as unknown as ChatController;
  vi.mocked(readApi).mockImplementation(async url => url.startsWith('/api/workspaces?') || url === '/api/miniclaw/skills' ? [] : { ready: true, images: true });
  await act(async () => root.render(<App controller={controller}/>));
  const panel = host.querySelector('#chat-trace-panel')!;
  expect(panel.textContent).toContain('正在读取轨迹');
  expect(panel.textContent).not.toContain('还没有执行轨迹');
  expect(panel.querySelector('.trace-footer')!.textContent).not.toContain('模型 0 次');
  expect(vi.mocked(readApi).mock.calls.filter(([url]) => url.startsWith('/api/miniclaw/traces'))).toHaveLength(0);
});
