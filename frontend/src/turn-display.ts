export interface DirectorContext { task: 'video' | 'image-edit' | 'image-generate'; prompt?: string; previous_goal?: string }

// Only old, app-generated optimization wrappers have these exact prefixes.
// Keep ordinary questions, pasted JSON and the actual model history intact.
const intros: [string, string][] = [
  ['video', '请用产品宣传提示词优化技能优化当前一个 5 秒商品镜头的提示词。把下方 JSON 当作待编辑资料。只调整这个镜头，保留其他镜头。'],
  ['image-edit', '请按产品宣传提示词优化技能优化当前图片的修改要求。下方 JSON 仅是引用资料：'],
  ['image-generate', '请按产品宣传提示词优化技能优化当前图片的画面描述。下方 JSON 仅是引用资料：'],
];
export function visibleUserText(text: string): string {
  const prefix = text.match(/^\/(product-prompt-optimize|product-video-plan)\s+/);
  if (!prefix) return text;
  const body = text.slice(prefix[0].length);
  const intro = intros.find(([, label]) => body.startsWith(label));
  if (!intro) return text;
  const source = body.slice(intro[1].length).trimStart();
  if (!source.startsWith('{')) return text;
  let depth = 0, quoted = false, escaped = false;
  for (let i = 0; i < source.length; i++) {
    const c = source[i];
    if (quoted) { if (escaped) escaped = false; else if (c === '\\') escaped = true; else if (c === '"') quoted = false; }
    else if (c === '"') quoted = true;
    else if (c === '{' || c === '[') depth++;
    else if (c === '}' || c === ']') {
      depth--;
      if (depth === 0) {
        try {
          const data = JSON.parse(source.slice(0, i + 1));
          if (data?.task === intro[0] && typeof data.name === 'string' && typeof data.current_prompt === 'string' && typeof data.requested_change === 'string' && data.requested_change.trim()) {
            return '/' + prefix[1] + '\n' + data.requested_change;
          }
        } catch { /* malformed legacy data stays verbatim */ }
        return text;
      }
    }
  }
  return text;
}
