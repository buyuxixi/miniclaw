import type { ChatItem } from './types';
import type { TraceStep } from './trace-view';

const secretField = /api[_-]?key|(?:^|[_-])(?:authorization|cookie|password|passwd|secret|credential|access[_-]?token|refresh[_-]?token|session[_-]?token|signature)(?:$|[_-])|^(?:token|key)$/i;

// Legacy tool receipts predate server trace redaction. Keep their presentation
// safe without rewriting the authoritative conversation or tool arguments.
export function traceHistoryRedact(value: unknown): unknown {
  return redact(value, 0, { nodes: 1000, chars: 64000 });
}

function redact(value: unknown, depth: number, budget: { nodes: number; chars: number }): unknown {
  if (--budget.nodes < 0 || budget.chars <= 0) return '[内容已截断]';
  if (depth > 8) return '[内容过深]';
  if (typeof value === 'string') {
    if (value.length <= 64000 && /^\s*[\[{]/.test(value)) {
      try { return JSON.stringify(redact(JSON.parse(value), depth + 1, budget), null, 2); } catch { /* Plain text is still bounded and redacted below. */ }
    }
    const clipped = value.slice(0, Math.min(16000, budget.chars));
    budget.chars -= clipped.length;
    return clipped
    .replace(/\bBearer\s+[^\s"'<>]+/gi, 'Bearer [已隐藏]')
    .replace(/\bsk-[A-Za-z0-9_-]{8,}/g, '[已隐藏]')
    .replace(/data:[^;\s]+;base64,[A-Za-z0-9+/=]+/g, '[媒体内容]')
    .replace(/([?&](?:api_key|key|token|access_token|signature|x-amz-signature|x-amz-credential|x-amz-security-token)=)[^&#\s]+/gi, '$1[已隐藏]')
    .replace(/\b((?:[A-Z0-9_]{0,64}API_KEY|password|passwd|secret|access_token|refresh_token|token|key|signature|authorization|cookie)["']?\s*[=:]\s*["']?)[^\s,;，；&#}"']+/gi, '$1[已隐藏]')
    + (value.length > clipped.length ? '\n[内容已截断]' : '');
  }
  if (Array.isArray(value)) return value.slice(0, 100).map(item => redact(item, depth + 1, budget));
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).slice(0, 100)
    .map(([key, item]) => [key, secretField.test(key) ? '[已隐藏]' : redact(item, depth + 1, budget)]));
  return value;
}

function historicalStep(item: ChatItem, turn: number, order: number): TraceStep {
  let receipt = item.result;
  if (typeof receipt === 'string') { try { receipt = JSON.parse(receipt); } catch { /* Unknown text is not a definitive receipt. */ } }
  const uncertain = receipt && typeof receipt === 'object' && ('outcome_uncertain' in receipt && receipt.outcome_uncertain ||
    'effect_disposition' in receipt && receipt.effect_disposition === 'unknown' || 'state' in receipt && ['unknown','timeout'].includes(String(receipt.state)));
  const status: TraceStep['status'] = uncertain ? 'unknown' : item.status === 'running' ? 'running' : item.status === 'error' ? 'failed'
    : item.status === 'interrupted' ? 'interrupted' : item.status === 'unavailable' ? 'unknown' : 'completed';
  const content = traceHistoryRedact(item.text) as string;
  return {
    id: `history:${item.id}`, kind: item.kind === 'user' ? 'input' : item.kind,
    name: item.kind === 'user' ? '用户输入' : item.kind === 'assistant' ? '助手回复' : item.name || '工具调用',
    status, source: 'history', turn_index: turn, call_index: order,
    started_at: null, ended_at: null, duration_ms: null, input_tokens: null, output_tokens: null,
    content, summary: content || (item.kind === 'tool' ? `${item.name || '工具'} · ${status === 'failed' ? '执行失败' : status === 'unknown' ? '结果未记录' : '工具结果'}` : item.attachments?.map(a => a.name).join('、')),
    ...(item.kind === 'tool' ? { tool_name: item.name, input: traceHistoryRedact(item.args), output: traceHistoryRedact(item.result) } : {}),
    attributes: { message_id: item.id, ...(item.kind === 'tool' ? { call_id: item.id } : {}) },
  };
}

// Canonical row ids are preferred. Content matching is sequential and limited
// to the same role; identical text in another turn must remain visible.
export function withTraceHistory(items: ChatItem[], recorded: TraceStep[]): TraceStep[] {
  const consumed = new Set<number>();
  const anchors = new Map<number, number>();
  let cursor = 0;
  recorded.forEach((step, traceIndex) => {
    const kind = step.kind === 'input' ? 'user' : step.kind;
    if (!['user', 'assistant', 'tool'].includes(kind)) return;
    const rawId = step.attributes?.message_id;
    const messageId = typeof rawId === 'number' || typeof rawId === 'string'
      ? String(rawId).startsWith('row-') ? String(rawId) : `row-${rawId}` : undefined;
    const callId = step.attributes?.call_id;
    let index = items.findIndex((item, i) => !consumed.has(i) && item.kind === kind &&
      (messageId === item.id || kind === 'tool' && typeof callId === 'string' && callId === item.id));
    if (index < 0 && step.content && (kind === 'user' || cursor > 0)) {
      index = items.findIndex((item, i) => i >= cursor && !consumed.has(i) && item.kind === kind &&
        // A known canonical row which is absent here may still be represented
        // by an optimistic UUID. Never consume an equal older canonical row.
        (!messageId || !/^row-\d+$/.test(item.id)) &&
        traceHistoryRedact(item.text) === step.content);
    }
    if (index >= 0) { consumed.add(index); anchors.set(index, traceIndex); cursor = index + 1; }
  });
  const insertions = new Map<number, TraceStep[]>();
  const orderedAnchors = [...anchors].sort(([a], [b]) => a - b);
  let turn = 0;
  items.forEach((item, index) => {
    if (item.kind === 'user') turn += 1;
    if (consumed.has(index)) return;
    const nextAnchor = orderedAnchors.find(([position]) => position > index);
    const insertAt = nextAnchor?.[1] ?? recorded.length;
    const bucket = insertions.get(insertAt) ?? [];
    bucket.push(historicalStep(item, turn || 1, index + 1));
    insertions.set(insertAt, bucket);
  });
  const steps = recorded.flatMap((step, index) => [...(insertions.get(index) ?? []), { ...step, source: 'trace' as const }]);
  steps.push(...(insertions.get(recorded.length) ?? []));
  return steps;
}
