import { afterEach, expect, test, vi } from 'vitest';
import { ChatController } from './chat-controller';

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

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
