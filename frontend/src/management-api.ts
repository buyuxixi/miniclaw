import type { SessionRow } from './types';

export async function readApi<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${window.__HERMES_BASE_PATH__ ?? ''}${path}`, {
    headers: { 'X-Hermes-Session-Token': window.__HERMES_SESSION_TOKEN__ ?? '' },
    cache: 'no-store', signal: signal ?? AbortSignal.timeout(15_000),
  });
  if (!response.ok) throw new Error(`读取失败（HTTP ${response.status}）`);
  return response.json() as Promise<T>;
}

export async function writeApi<T>(path: string, method: 'PUT' | 'POST' | 'PATCH', body: unknown): Promise<T> {
  const response = await fetch(`${window.__HERMES_BASE_PATH__ ?? ''}${path}`, {
    method, headers: { 'Content-Type': 'application/json', 'X-Hermes-Session-Token': window.__HERMES_SESSION_TOKEN__ ?? '' },
    body: JSON.stringify(body), signal: AbortSignal.timeout(30_000),
  });
  if (!response.ok) {
    const details = await response.json().catch(() => ({})) as { detail?: unknown };
    throw new Error(typeof details.detail === 'string' ? details.detail : `保存失败（HTTP ${response.status}）`);
  }
  return response.json() as Promise<T>;
}

export async function searchSessions(query: string, signal: AbortSignal, archived = false): Promise<SessionRow[]> {
  const params = `exclude_sources=cron,delegate,kanban&archived=${archived ? 'only' : 'exclude'}`;
  const body = await readApi<{ results: SessionRow[] }>(`/api/sessions/search?q=${encodeURIComponent(query)}&limit=100&${params}`, signal);
  const found = new Map(body.results.filter(row => Boolean(row.archived) === archived).map(row => [row.id, row]));
  // The upstream FTS endpoint searches messages and ids, not titles. Page
  // compact session metadata so title lookup also covers older sessions.
  for (let offset = 0; !signal.aborted; offset += 100) {
    const page = await readApi<{ sessions: SessionRow[]; total: number }>(`/api/sessions?limit=100&offset=${offset}&order=recent&${params}`, signal);
    for (const row of page.sessions) if ((row.title ?? '').toLocaleLowerCase().includes(query.toLocaleLowerCase())) found.set(row.id, row);
    if (!page.sessions.length || offset + page.sessions.length >= page.total) break;
  }
  return [...found.values()];
}
