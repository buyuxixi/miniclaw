import { afterEach, expect, test, vi } from 'vitest';
import { ChatController } from './chat-controller';

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function setup(enabled = true) {
  vi.stubGlobal('window', { __HERMES_SESSION_TOKEN__: 'test' });
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => [{ name: 'lesson', enabled }] }));
  const controller = new ChatController();
  controller.connection = 'open';
  controller.state.sessionId = 'live';
  controller.state.storedId = 'stored';
  const request = vi.spyOn(controller.client, 'request').mockImplementation(async method => {
    if (method === 'commands.catalog') return { skills: { '/lesson': {} }, categories: [] };
    if (method === 'command.dispatch') return { type: 'skill', message: 'FULL SKILL BODY\nuser task', display: '/lesson user task' };
    return {};
  });
  return { controller, request };
}

test('loads full skill for the model while showing only the invocation in chat', async () => {
  const { controller, request } = setup();
  expect(await controller.send('user task', 'lesson')).toBe(true);
  expect(request).toHaveBeenLastCalledWith('prompt.submit', { session_id: 'live', text: 'FULL SKILL BODY\nuser task' });
  expect(controller.state.items[0].text).toBe('/lesson user task');
});

test('revoked skill fails before dispatch or model submission and keeps the transcript', async () => {
  const { controller, request } = setup(false);
  expect(await controller.send('user task', 'lesson')).toBe(false);
  expect(request).not.toHaveBeenCalled();
  expect(controller.state.items).toEqual([]);
  expect(controller.state.running).toBe(false);
});

test('command name collision does not execute a quick or plugin command', async () => {
  const { controller, request } = setup();
  request.mockResolvedValue({ skills: { '/lesson': {} }, categories: [{ name: 'User commands', pairs: [['/lesson', 'exec']] }] });
  expect(await controller.send('user task', 'lesson')).toBe(false);
  expect(request.mock.calls.map(call => call[0])).toEqual(['commands.catalog']);
});

test('stop during skill loading prevents delayed prompt submission', async () => {
  const { controller, request } = setup();
  let finish!: (value: unknown) => void;
  request.mockImplementation(method => method === 'commands.catalog' ? new Promise(resolve => { finish = resolve; }) : Promise.resolve({ type: 'skill', message: 'body' }));
  const sent = controller.send('user task', 'lesson');
  await vi.waitFor(() => expect(finish).toBeTypeOf('function'));
  await controller.stop();
  finish({ skills: { '/lesson': {} }, categories: [] });
  expect(await sent).toBe(false);
  expect(request.mock.calls.map(call => call[0])).not.toContain('prompt.submit');
  expect(controller.state.items).toEqual([]);
});
