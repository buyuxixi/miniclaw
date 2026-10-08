import { describe, expect, it } from 'vitest';
import { assistantText, finishItems, historyItems, resultFailed, storedSessionId, withToolResults, withCreatorContexts } from './transcript';

describe('the visible transcript', () => {
  it('keeps each reply bound to its original project version and clears context at an unrelated turn', () => {
    const source = { project_id: 'product-one', revision: 3, node: 'script' as const, basis: 'brief-hash' };
    let items = withCreatorContexts([{id:'u1',kind:'user',text:'改稿',creator_context:source},{id:'a1',kind:'assistant',text:'候选稿'},
      {id:'u2',kind:'user',text:'普通聊天'},{id:'a2',kind:'assistant',text:'普通回复'}]);
    expect(items[1].creator_context).toEqual(source);
    expect(items[3].creator_context).toBeUndefined();
    items = assistantText(items, '后续回复', true);
    expect(items.at(-1)?.creator_context).toBeUndefined();
    const live = assistantText([{id:'u1',kind:'user',text:'改稿',creator_context:source}], '实时回复', true);
    expect(live.at(-1)?.creator_context).toEqual(source);
  });
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


it('current task history follows its user turn including tools without showing another stage',async()=>{
  const {taskItems}=await import('./transcript');
  const source={project_id:'p',node:'cover' as const,revision:1,basis:'b'};
  const items=[{id:'u',kind:'user' as const,text:'修图',creator_context:source},{id:'t',kind:'tool' as const,text:''},{id:'a',kind:'assistant' as const,text:'方案'},{id:'s',kind:'user' as const,text:'起稿',creator_context:{...source,node:'script' as const}},{id:'sa',kind:'assistant' as const,text:'稿件'}];
  expect(taskItems(items,'p','cover').map(i=>i.id)).toEqual(['u','t','a']);
  expect(taskItems(items,'p','video')).toEqual([]);
});
