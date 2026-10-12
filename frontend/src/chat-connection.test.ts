// @vitest-environment jsdom
import {afterEach, beforeEach, expect, test, vi} from 'vitest';
import {ChatController} from './chat-controller';
import {JsonRpcGatewayClient} from './gateway';

class Socket extends EventTarget {
  static instances: Socket[] = [];
  readyState: number = WebSocket.CONNECTING;
  sent: {id: string; method: string; params: Record<string, unknown>}[] = [];
  constructor(readonly url: string) { super(); Socket.instances.push(this); }
  open() {
    this.readyState = WebSocket.OPEN;
    this.dispatchEvent(new Event('open'));
    this.frame({method: 'event', params: {type: 'gateway.ready', payload: {heartbeat: true, replay_epoch: 'fixture'}}});
  }
  frame(frame: unknown) { this.dispatchEvent(new MessageEvent('message', {data: JSON.stringify({jsonrpc: '2.0', ...frame as object})})); }
  send(text: string) {
    const frame = JSON.parse(text); this.sent.push(frame);
    if (frame.method === 'gateway.ping' && !answerPings) return;
    if (frame.method === 'session.resume' && holdResume) return;
    const result = frame.method === 'session.list' ? {sessions: []} : frame.method === 'session.resume' ? {
      session_id: 'live', stored_session_id: 'saved', info: {}, running: true, messages: [], inflight: {assistant: '保留的半段回复', streaming: true},
    } : {};
    this.frame({id: frame.id, result});
  }
  close() { this.readyState = WebSocket.CLOSED; this.dispatchEvent(new CloseEvent('close', {code: 1006})); }
}

let answerPings: boolean;
let holdResume: boolean;
let controllers: ChatController[];
let clients: JsonRpcGatewayClient[];
const socket = () => Socket.instances.at(-1)!;
const flush = async () => { for (let i = 0; i < 15; i++) await Promise.resolve(); };
const chat = () => { const c = new ChatController(); c.resumeId = 'saved'; controllers.push(c); return c; };

beforeEach(() => {
  vi.useFakeTimers(); Socket.instances = []; answerPings = true; holdResume = false; controllers = []; clients = [];
  const NativeWebSocket = WebSocket;
  vi.stubGlobal('WebSocket', Object.assign(Socket, {OPEN: NativeWebSocket.OPEN, CLOSED: NativeWebSocket.CLOSED, CONNECTING: NativeWebSocket.CONNECTING}));
  window.__HERMES_SESSION_TOKEN__ = 'old-token';
  localStorage.clear();
  Object.defineProperty(document, 'visibilityState', {configurable: true, value: 'visible'});
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ok: true, text: async () => 'window.__HERMES_SESSION_TOKEN__="fresh-token"', json: async () => ({})}));
});
afterEach(() => {
  controllers.forEach(c => c.dispose()); clients.forEach(c => c.close());
  vi.useRealTimers(); vi.unstubAllGlobals(); delete window.__HERMES_SESSION_TOKEN__;
});

test('a delayed browser heartbeat probes a healthy socket instead of closing it', async () => {
  const client = new JsonRpcGatewayClient(); clients.push(client);
  const connecting = client.connect('ws://localhost/api/ws'); socket().open(); await connecting;
  await vi.advanceTimersByTimeAsync(15_000);
  vi.setSystemTime(Date.now() + 60_000);
  await vi.advanceTimersByTimeAsync(15_000);
  expect(client.connectionState).toBe('open');
  expect(socket().sent.filter(f => f.method === 'gateway.ping').length).toBeGreaterThan(1);
});

test('an actually silent socket is still closed after the probe window', async () => {
  const client = new JsonRpcGatewayClient(); clients.push(client);
  const connecting = client.connect('ws://localhost/api/ws'); socket().open(); await connecting;
  answerPings = false;
  vi.setSystemTime(Date.now() + 60_000);
  await vi.advanceTimersByTimeAsync(15_000);
  expect(client.connectionState).toBe('open');
  await vi.advanceTimersByTimeAsync(45_000);
  expect(client.connectionState).toBe('closed');
});

test('ordinary silent failures expire but streamed events keep the connection alive', async () => {
  const client = new JsonRpcGatewayClient(); clients.push(client);
  const connecting = client.connect('ws://localhost/api/ws'); socket().open(); await connecting;
  answerPings = false;
  for (let i = 0; i < 6; i++) {
    await vi.advanceTimersByTimeAsync(15_000);
    socket().frame({method: 'event', params: {type: 'status.update', payload: {text: '执行中'}}});
  }
  expect(client.connectionState).toBe('open');
  await vi.advanceTimersByTimeAsync(45_000); expect(client.connectionState).toBe('closed');
  const count = socket().sent.length;
  window.dispatchEvent(new Event('pageshow')); await vi.advanceTimersByTimeAsync(60_000);
  expect(socket().sent).toHaveLength(count);
});

test('foreground wake replaces a stale probe and preserves a still healthy socket', async () => {
  const client = new JsonRpcGatewayClient(); clients.push(client);
  const connecting = client.connect('ws://localhost/api/ws'); socket().open(); await connecting;
  answerPings = false; await vi.advanceTimersByTimeAsync(15_000);
  vi.setSystemTime(Date.now() + 60_000); answerPings = true;
  window.dispatchEvent(new Event('pageshow')); await flush();
  await vi.advanceTimersByTimeAsync(15_000); expect(client.connectionState).toBe('open');
  expect(socket().sent.filter(f => f.method === 'gateway.ping')).toHaveLength(3);
});

test('automatic reconnect refreshes credentials and resumes the same running conversation without submitting a turn', async () => {
  const controller = chat(), connecting = controller.connect(); await flush(); socket().open(); await connecting;
  const first = socket(); first.close();
  await vi.advanceTimersByTimeAsync(1_000);
  expect(Socket.instances).toHaveLength(2);
  expect(new URL(socket().url).searchParams.get('token')).toBe('fresh-token');
  socket().open(); await flush();
  expect(controller.state.storedId).toBe('saved'); expect(controller.state.running).toBe(true);
  expect(controller.state.items.some(i => i.text.includes('保留的半段回复'))).toBe(true);
  expect(socket().sent.find(f => f.method === 'session.resume')?.params.session_id).toBe('saved');
  expect(Socket.instances.flatMap(s => s.sent).some(f => /submit|task\./.test(f.method))).toBe(false);
  expect(controller.state.error).toBe('');
});

test('failed dials back off and a foreground event retries immediately', async () => {
  const controller = chat(), connecting = controller.connect(); await flush(); socket().close(); await connecting;
  await vi.advanceTimersByTimeAsync(1_000); expect(Socket.instances).toHaveLength(2); socket().close(); await flush();
  await vi.advanceTimersByTimeAsync(1_000); expect(Socket.instances).toHaveLength(2);
  await vi.advanceTimersByTimeAsync(1_000); expect(Socket.instances).toHaveLength(3); socket().close(); await flush();
  document.dispatchEvent(new Event('visibilitychange')); await flush(); expect(Socket.instances).toHaveLength(4);
  socket().open(); await flush(); expect(controller.connection).toBe('open');
  await vi.advanceTimersByTimeAsync(35_000); expect(Socket.instances).toHaveLength(4);
});

test('continued failures cap the retry interval at thirty seconds', async () => {
  const controller = chat(), initial = controller.connect(); await flush(); socket().close(); await initial;
  for (const delay of [1000, 2000, 4000, 8000, 16000, 30000, 30000]) {
    const count = Socket.instances.length;
    await vi.advanceTimersByTimeAsync(delay - 1); expect(Socket.instances).toHaveLength(count);
    await vi.advanceTimersByTimeAsync(1); expect(Socket.instances).toHaveLength(count + 1);
    socket().close(); await flush();
  }
});

test('manual and automatic reconnect share one attempt', async () => {
  const controller = chat(); const first = controller.connect(), second = controller.connect(); await flush();
  expect(Socket.instances).toHaveLength(1); socket().open(); await Promise.all([first, second]);
  socket().close(); const manual = controller.connect(); await flush();
  await vi.advanceTimersByTimeAsync(1_000); expect(Socket.instances).toHaveLength(2);
  socket().open(); await manual;
});

test('another disconnect during session recovery retries without replacing the selected session', async () => {
  const controller = chat(), initial = controller.connect(); await flush(); socket().open(); await initial;
  socket().close(); await vi.advanceTimersByTimeAsync(1_000);
  holdResume = true; socket().open(); await flush(); expect(controller.state.busy).toBe(true);
  socket().close(); await flush(); holdResume = false;
  await vi.advanceTimersByTimeAsync(1_000); expect(Socket.instances).toHaveLength(3);
  socket().open(); await flush();
  expect(controller.state.storedId).toBe('saved'); expect(controller.state.busy).toBe(false);
  expect(Socket.instances.flatMap(s => s.sent).some(f => f.method === 'session.create' || /submit/.test(f.method))).toBe(false);
});

test('disposing cancels retries, wake listeners and a pending credential read', async () => {
  const controller = chat(), initial = controller.connect(); await flush(); socket().open(); await initial; socket().close();
  let resolve!: (response: unknown) => void;
  vi.mocked(fetch).mockImplementation(() => new Promise(r => {resolve = r as typeof resolve;}));
  const retry = controller.connect(); await flush(); controller.dispose();
  resolve({ok: true, text: async () => 'window.__HERMES_SESSION_TOKEN__="late-token"'}); await retry;
  window.dispatchEvent(new Event('online')); window.dispatchEvent(new Event('pageshow')); document.dispatchEvent(new Event('visibilitychange'));
  await vi.advanceTimersByTimeAsync(60_000);
  expect(Socket.instances).toHaveLength(1);
});

test('an initial credential fetch failure also retries without a reload', async () => {
  delete window.__HERMES_SESSION_TOKEN__;
  const controller = chat(); await controller.connect();
  await vi.advanceTimersByTimeAsync(1_000); await flush();
  expect(Socket.instances).toHaveLength(1);
  socket().open(); await flush(); expect(controller.connection).toBe('open');
});
