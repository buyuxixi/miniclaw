import { useEffect, useRef, useState } from 'react';
import { readApi } from './management-api';
import type { TraceStep } from './trace-view';

export interface TracePage {
  steps: TraceStep[];
  has_more: boolean;
  next_before: number | null;
  revision: number | null;
}

interface TraceState {
  owner: string;
  steps: TraceStep[];
  loading: boolean;
  error: string;
  hasMore: boolean;
  before: number | null;
  versions?: Record<string, number>;
}

const empty = (owner: string): TraceState => ({ owner, steps: [], loading: false, error: '', hasMore: false, before: null });

// A poll updates existing spans as well as discovering new ones. An older page
// must survive a concurrent refresh of the most recent window.
export function mergeTracePage(previous: TraceState, page: TracePage, older: boolean): TraceState {
  const byId = new Map(previous.steps.map(step => [step.id, step]));
  const versions = { ...previous.versions };
  for (const step of page.steps) {
    const version = step.updated_at ?? page.revision ?? 0;
    if (!byId.has(step.id) || version >= (versions[step.id] ?? 0)) {
      byId.set(step.id, step);
      versions[step.id] = version;
    }
  }
  const steps = [...byId.values()].sort((a, b) => (a.sequence ?? 0) - (b.sequence ?? 0));
  const earliest = (values: TraceStep[]) => values.reduce((min, step) => Math.min(min, step.sequence ?? Infinity), Infinity);
  const alreadyOlder = previous.steps.length > 0 && earliest(previous.steps) < earliest(page.steps);
  return {
    ...previous, steps, versions, loading: false, error: '',
    hasMore: older || !alreadyOlder ? page.has_more : previous.hasMore,
    before: older || !alreadyOlder ? page.next_before : previous.before,
  };
}

export function useChatTrace(owner: string, enabled: boolean, running: boolean, version: string) {
  const [state, setState] = useState<TraceState>(() => empty(owner));
  const runningRef = useRef(running);
  runningRef.current = running;
  const loader = useRef<{ owner: string; running: boolean; version: string; refresh: () => void; more: () => void } | null>(null);

  useEffect(() => {
    setState(empty(owner));
    if (!enabled || !owner) { loader.current = null; return; }
    let disposed = false;
    let latestBusy = false;
    let olderBusy = false;
    let pendingRefresh = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let before: number | null = null;
    const controllers = new Set<AbortController>();

    async function load(older = false) {
      if (disposed) return;
      if (older ? olderBusy || before == null : latestBusy) {
        if (!older) pendingRefresh = true;
        return;
      }
      if (timer) clearTimeout(timer);
      if (older) olderBusy = true; else latestBusy = true;
      const abort = new AbortController();
      controllers.add(abort);
      const requestedBefore = older ? before : null;
      setState(previous => previous.owner === owner ? { ...previous, loading: true } : { ...empty(owner), loading: true });
      try {
        const page = await readApi<TracePage>(`/api/miniclaw/traces?owner=${encodeURIComponent(owner)}&limit=500${requestedBefore == null ? '' : `&before=${requestedBefore}`}`, abort.signal);
        if (!Array.isArray(page.steps)) throw new Error('轨迹响应格式不正确');
        if (disposed || abort.signal.aborted) return;
        setState(previous => {
          const next = mergeTracePage(previous.owner === owner ? previous : empty(owner), page, older);
          before = next.before;
          return next;
        });
      } catch (error) {
        if (disposed || abort.signal.aborted) return;
        setState(previous => ({ ...(previous.owner === owner ? previous : empty(owner)), loading: false,
          error: `轨迹读取失败，已加载的步骤已保留。${error instanceof Error ? error.message : ''}` }));
      } finally {
        controllers.delete(abort);
        if (older) olderBusy = false; else latestBusy = false;
        if (!disposed) {
          if (!older && pendingRefresh) { pendingRefresh = false; void load(); }
          else if (runningRef.current && !latestBusy) timer = setTimeout(() => { void load(); }, 1500);
        }
      }
    }

    const current = { owner, running: runningRef.current, version, refresh: () => { void load(); }, more: () => { void load(true); } };
    loader.current = current;
    void load();
    return () => {
      disposed = true;
      if (timer) clearTimeout(timer);
      for (const abort of controllers) abort.abort();
      if (loader.current === current) loader.current = null;
    };
  }, [owner, enabled]);

  // Refresh once at state transitions, including the final completion after the
  // running poll stops. Streaming text changes do not create HTTP requests.
  useEffect(() => {
    const current = loader.current;
    if (enabled && current?.owner === owner && (current.running !== running || current.version !== version)) {
      current.running = running; current.version = version; current.refresh();
    }
  }, [owner, enabled, running, version]);

  const current = state.owner === owner && enabled ? state : empty(owner);
  return { ...current,
    refresh: () => { if (loader.current?.owner === owner) loader.current.refresh(); },
    loadMore: () => { if (loader.current?.owner === owner) loader.current.more(); },
  };
}
