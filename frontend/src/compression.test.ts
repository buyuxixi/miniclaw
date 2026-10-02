import { afterEach, expect, test, vi } from 'vitest';
import { ChatController } from './chat-controller';

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

test('compression owns the client busy gate and restores authoritative display history', async () => {
  vi.stubGlobal('window', {});
  vi.stubGlobal('localStorage', { setItem: vi.fn() });
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ messages: [] }) }));
  const controller = new ChatController();
  controller.connection = 'open';
  controller.state.sessionId = 'live'; controller.state.storedId = 'old';
  let finish!: (value: unknown) => void;
  const pending = new Promise(resolve => { finish = resolve; });
  vi.spyOn(controller.client, 'request').mockImplementation(async (method) => {
    if (method === 'session.compress') return pending;
    if (method === 'session.history') return { messages: [{ role: 'user', text: '原始聊天仍可回看' }] };
    if (method === 'session.list') return { sessions: [] };
    throw new Error(`Unexpected request: ${method}`);
  });
  const operation = controller.compressContext('保留约束');
  expect(controller.state.busy).toBe(true);
  expect(await controller.send('不能在压缩中提交')).toBe(false);
  finish({ status: 'compressed', info: { stored_session_id: 'tip' } });
  await operation;
  expect(controller.state.storedId).toBe('tip');
  expect(controller.state.items[0].text).toBe('原始聊天仍可回看');
  expect(controller.state.busy).toBe(false);
});

test('ambiguous compression failure blocks new turns until reattachment', async () => {
  const controller = new ChatController();
  controller.connection = 'open'; controller.state.sessionId = 'live';
  const request = vi.spyOn(controller.client, 'request').mockRejectedValue(new Error('timeout'));
  expect(await controller.compressContext('')).toBeUndefined();
  expect(controller.state.running).toBe(true);
  expect(await controller.send('不要自动重试')).toBe(false);
  expect(request).toHaveBeenCalledTimes(1);
});
