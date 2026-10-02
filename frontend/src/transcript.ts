import type { ChatItem, HistoryRow, SessionSnapshot } from './types';

export function storedSessionId(snapshot: SessionSnapshot): string {
  const id = snapshot.stored_session_id ?? snapshot.session_key ?? snapshot.info.stored_session_id;
  if (!id) throw new Error('后端未返回持久化会话 ID，无法可靠恢复会话。');
  return id;
}

export function resultFailed(result: unknown): boolean {
  if (typeof result === 'string') {
    try { return resultFailed(JSON.parse(result)); } catch { return false; }
  }
  return Boolean(result && typeof result === 'object' &&
    ('error' in result && (result as { error?: unknown }).error ||
     'success' in result && (result as { success?: unknown }).success === false));
}

export function historyItems(rows: HistoryRow[]): ChatItem[] {
  return rows.flatMap((row, index): ChatItem[] => {
    if (row.display_kind === 'hidden') return [];
    const id = `row-${row.row_id ?? index}`;
    const text = row.text ?? (typeof row.content === 'string' ? row.content : '');
    if (row.role === 'tool') return [{
      id: row.tool_call_id ?? id, kind: 'tool', text: '', name: row.name ?? '工具',
      args: row.args, result: row.content ?? row.text ?? undefined,
      status: row.content == null && row.text == null ? 'unavailable' : resultFailed(row.content ?? text) ? 'error' : 'done',
    }];
    if ((row.role === 'user' || row.role === 'assistant') && text) {
      return [{ id, kind: row.role, text }];
    }
    return [];
  });
}

export function withToolResults(projected: HistoryRow[], stored: HistoryRow[]): HistoryRow[] {
  const results = new Map(stored.filter(row => row.role === 'tool' && row.tool_call_id)
    .map(row => [row.tool_call_id, row.content]));
  return projected.map(row => row.role === 'tool' && results.has(row.tool_call_id)
    ? { ...row, content: results.get(row.tool_call_id) } : row);
}

// An interim assistant message seals the text before a tool; the final answer
// belongs to the following segment, rather than replacing that commentary.
export function assistantText(items: ChatItem[], text: string, append: boolean): ChatItem[] {
  const next = [...items];
  const last = next.at(-1);
  if (last?.kind === 'assistant' && last.status === 'running') {
    next[next.length - 1] = { ...last, text: append ? last.text + text : text };
  } else if (text || append) {
    next.push({ id: crypto.randomUUID(), kind: 'assistant', text, status: 'running' });
  }
  return next;
}

export function finishItems(items: ChatItem[], status: ChatItem['status']): ChatItem[] {
  return items.map(item => item.status === 'running' ? { ...item, status } : item);
}
