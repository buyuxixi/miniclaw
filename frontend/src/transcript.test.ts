import { describe, expect, it } from 'vitest';
import { assistantText, finishItems, historyItems, resultFailed, storedSessionId, withToolResults } from './transcript';

describe('the visible transcript', () => {
  it('preserves commentary before tools and replaces only the final streaming segment', () => {
    let items = assistantText([], '先读取资料。', true);
    items = finishItems(items, 'done');
    items.push({ id: 'call-1', kind: 'tool', name: 'read', text: '', status: 'done' });
    items = assistantText(items, '根据', true);
    items = assistantText(items, '根据资料，这是结论。', false);
    expect(items.map(item => item.text)).toEqual(['先读取资料。', '', '根据资料，这是结论。']);
    expect(items.filter(item => item.kind === 'assistant')).toHaveLength(2);
  });

  it('restores durable tool errors and hides instruction-only rows', () => {
    const rows = [
      { role: 'system', text: 'instructions' },
      { role: 'user', text: 'invisible', display_kind: 'hidden' },
      { role: 'user', text: '读取不存在的文件', row_id: 10 },
      { role: 'assistant', text: '', tool_calls: [{ id: 'call-1' }] },
      { role: 'tool', tool_call_id: 'call-1', name: 'read', content: '{"error":"missing file"}' },
      { role: 'assistant', text: '文件不存在。', row_id: 13 },
    ];
    const items = historyItems(rows);
    expect(items.map(item => item.kind)).toEqual(['user', 'tool', 'assistant']);
    expect(items[1]).toMatchObject({ id: 'call-1', status: 'error' });
    expect(items.at(-1)?.text).toBe('文件不存在。');
    expect(resultFailed('{"success":true,"content":"ok"}')).toBe(false);
    const compact = [{ role: 'tool', name: 'read', tool_call_id: 'call-1' }];
    expect(historyItems(compact)[0].status).toBe('unavailable');
    const restored = historyItems(withToolResults(compact, rows));
    expect(restored[0].status).toBe('error');
    expect(restored[0].result).toBe('{"error":"missing file"}');
    expect(storedSessionId({ session_id: 'live-8', session_key: 'persisted-2026', info: {}, messages: [] })).toBe('persisted-2026');
    expect(() => storedSessionId({ session_id: 'live-8', info: {}, messages: [] })).toThrow();
  });
});
