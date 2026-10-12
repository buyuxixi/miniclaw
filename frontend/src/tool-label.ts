const DOCUMENT_QUERY = 'miniclaw_document_query';
const MAX_LABEL = 120;

function bounded(value: string, limit = MAX_LABEL) {
  const text = value.slice(0, 4096).replace(/[\u0000-\u001f\u007f-\u009f]/g, ' ').replace(/\s+/g, ' ').trim();
  return text.length > limit || value.length > 4096 ? text.slice(0, limit - 1) + '…' : text;
}

function record(value: unknown): Record<string, unknown> | null {
  if (typeof value === 'string') {
    if (value.length > 128000) return null;
    try { value = JSON.parse(value); } catch { return null; }
  }
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

const position = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value > 0;
type Locator = { key: string; prefix: string; suffix: string; start: number; end: number };

function locator(value: unknown): Locator | null {
  const source = record(value);
  if (!source) return null;
  if (position(source.page)) return { key: 'page', prefix: '第', suffix: '页', start: source.page, end: source.page };
  if (position(source.paragraph)) return { key: 'paragraph', prefix: '第', suffix: '段', start: source.paragraph, end: source.paragraph };
  if (position(source.line_start)) return { key: 'line', prefix: '第', suffix: '行', start: source.line_start,
    end: position(source.line_end) && source.line_end >= source.line_start ? source.line_end : source.line_start };
  if (position(source.row_number)) {
    const scope = typeof source.sheet === 'string' ? source.sheet : typeof source.table === 'string' ? source.table : '';
    return { key: `row:${scope}`, prefix: scope ? `${bounded(scope, 32)} 第` : '第', suffix: '行', start: source.row_number, end: source.row_number };
  }
  return null;
}

function readLocation(value: unknown) {
  const result = record(value);
  if (!result) return '';
  const sources = Array.isArray(result.items) ? result.items.slice(0, 100).flatMap(item => {
    const located = locator(record(item)?.source);
    return located ? [located] : [];
  }) : [];
  if (!sources.length) {
    const located = locator(result.source);
    if (located) sources.push(located);
  }
  // Merge only locations actually covered by returned sources. A chunk ordinal
  // or a gap between two sources is never presented as a paragraph range.
  const groups = new Map<string, Locator[]>();
  for (const source of sources) {
    const group = groups.get(source.key) || [];
    group.push(source); groups.set(source.key, group);
  }
  const ranges: Locator[] = [];
  for (const group of groups.values()) {
    group.sort((a, b) => a.start - b.start);
    let current: Locator | undefined;
    for (const source of group) {
      if (current && source.start <= current.end + 1) current.end = Math.max(current.end, source.end);
      else { current = { ...source }; ranges.push(current); }
    }
  }
  return ranges.slice(0, 3).map(source => `${source.prefix}${source.start}${source.end > source.start ? `–${source.end}` : ''}${source.suffix}`).join(' / ') + (ranges.length > 3 ? ' / …' : '');
}

/** Presentation only: retain the real tool name and arguments in details/history. */
export function documentToolLabel(name: string | undefined, args: unknown, result?: unknown): string {
  const fallback = typeof name === 'string' ? bounded(name) || '工具调用' : '工具调用';
  if (name !== DOCUMENT_QUERY) return fallback;
  try {
    const input = record(args);
    switch (input?.action) {
      case 'search': {
        const queries = Array.isArray(input.queries) ? input.queries.slice(0, 5) : [input.query];
        const terms = queries.flatMap(query => typeof query === 'string' && bounded(query, 40) ? [bounded(query, 40)] : []);
        return bounded('搜索资料' + (terms.length ? `：${terms.join(' / ')}` : ''));
      }
      case 'read': {
        const source = readLocation(result);
        return bounded('读取资料' + (source ? `：${source}` : ''));
      }
      case 'inspect': return '查看资料结构';
      case 'calculate': return '计算资料';
      case 'analysis_status': return '查看分析进度';
      default: return fallback;
    }
  } catch {
    return fallback;
  }
}
