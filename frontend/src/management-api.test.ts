import { afterEach, expect, test, vi } from 'vitest';
import { searchSessions } from './management-api';

afterEach(() => vi.unstubAllGlobals());

test('title search covers older pages and deduplicates FTS matches', async () => {
  vi.stubGlobal('window', { __HERMES_SESSION_TOKEN__: 'test' });
  const row = (id: string, title: string) => ({ id, title, message_count: 1, preview: '' });
  const first = Array.from({ length: 100 }, (_, index) => row(String(index), index === 0 ? '商品资料' : '其他'));
  const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ results: [first[0]] }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ sessions: first, total: 101 }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ sessions: [row('old', '商品复核')], total: 101 }) });
  vi.stubGlobal('fetch', fetchMock);
  expect((await searchSessions('商品', new AbortController().signal)).map(value => value.id)).toEqual(['0', 'old']);
  expect(fetchMock.mock.calls[2][0]).toContain('offset=100');
});
