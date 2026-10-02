import { afterEach, expect, test, vi } from 'vitest';
import { ChatController } from './chat-controller';

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

for (const hasTool of [false, true]) test(hasTool ? 'replay still restores durable tool failure bodies' : 'an empty live session resumes without querying a missing database record', async () => {
  vi.stubGlobal('window', { __HERMES_SESSION_TOKEN__: 'test' });
  vi.stubGlobal('localStorage', { setItem: vi.fn() });
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ messages: [{ role: 'tool', tool_call_id: 'call', content: '{"error":"missing file"}' }] }) });
  vi.stubGlobal('fetch', fetchMock);
  const controller = new ChatController();
  const messages = hasTool ? [{ role: 'tool', name: 'read', tool_call_id: 'call' }] : [];
  vi.spyOn(controller.client, 'request').mockImplementation(async method => {
    if (method === 'session.resume') return { session_id: 'live', stored_session_id: 'new', info: {}, messages };
    if (method === 'session.history') return { messages };
    return { sessions: [] };
  });
  await controller.open('new');
  expect(controller.state.error).toBe('');
  expect(fetchMock).toHaveBeenCalledTimes(hasTool ? 1 : 0);
  if (hasTool) expect(controller.state.items[0]).toMatchObject({ kind: 'tool', status: 'error', result: '{"error":"missing file"}' });
  else expect(controller.state.items).toEqual([]);
});

test('reload resumes the durable selection even outside the recent list window', async () => {
  vi.stubGlobal('window', { __HERMES_SESSION_TOKEN__: 'test' });
  vi.stubGlobal('location', { href: 'http://localhost:9120/' });
  vi.stubGlobal('localStorage', { getItem: () => 'older-than-sidebar' });
  const controller = new ChatController();
  vi.spyOn(controller.client, 'connect').mockResolvedValue();
  vi.spyOn(controller.client, 'request').mockResolvedValue({ sessions: [] });
  const resume = vi.spyOn(controller, 'open').mockResolvedValue();
  const create = vi.spyOn(controller, 'newSession').mockResolvedValue();
  await controller.connect();
  expect(resume).toHaveBeenCalledWith('older-than-sidebar', true);
  expect(create).not.toHaveBeenCalled();
});
