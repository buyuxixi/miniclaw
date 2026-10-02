import type { HistoryRow } from './types';

export async function storedToolRows(storedId: string): Promise<HistoryRow[]> {
  const base = window.__HERMES_BASE_PATH__ ?? '';
  const response = await fetch(`${base}/api/sessions/${encodeURIComponent(storedId)}/messages?order=latest&limit=500`, {
    headers: { 'X-Hermes-Session-Token': window.__HERMES_SESSION_TOKEN__ ?? '' },
    cache: 'no-store',
    signal: AbortSignal.timeout(15_000),
  });
  if (!response.ok) throw new Error(`读取工具记录失败（HTTP ${response.status}）`);
  const result = await response.json() as { messages: HistoryRow[] };
  // Keep only tool bodies in the display state. The WS projection supplies
  // message ordering, labels and args; this never becomes a prompt submission.
  return result.messages.filter(row => row.role === 'tool');
}
