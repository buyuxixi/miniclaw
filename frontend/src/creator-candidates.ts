import type { CreatorProject } from './creator-api';

export const briefFields = [
  ['facts', '商品事实', 8000],
  ['selling_points', '已确认卖点', 4000],
  ['audience', '目标受众', 1000],
  ['style', '统一风格', 2000],
  ['constraints', '必须保留与避免', 2000],
] as const;
export type BriefCandidate = Required<Pick<CreatorProject, typeof briefFields[number][0]>>;

// Model output is a proposal, never a command or an automatic project mutation.
export function parseBrief(text: string): BriefCandidate | undefined {
  const blocks = [...text.matchAll(/^```(?:creator-brief|json)\s*\r?\n([\s\S]*?)^```\s*$/gm)];
  if (blocks.length !== 1 || blocks[0][1].length > 20000) return;
  try {
    const value = JSON.parse(blocks[0][1]);
    if (!value || Array.isArray(value) || Object.keys(value).length !== briefFields.length) return;
    for (const [key, , limit] of briefFields)
      if (typeof value[key] !== 'string' || value[key].length > limit || value[key].includes('\0')) return;
    return value;
  } catch { return; }
}

export function briefDisplay(text: string): string {
  const brief = parseBrief(text);
  if (!brief) return text;
  const summary = text.replace(/^```(?:creator-brief|json)\s*\r?\n[\s\S]*?^```\s*$/gm, '').trim();
  return `${summary}\n\n${briefFields.map(([key, label]) => `**${label}**\n\n${brief[key] || '待确认'}`).join('\n\n')}`;
}

export function spokenMain(text: string): string {
  const blocks = [...text.matchAll(/^```spoken-script\s*\r?\n([\s\S]*?)^```\s*$/gm)];
  if (blocks.length === 1 && blocks[0][1].trim()) return blocks[0][1].trim();
  // Existing replies use Markdown section headings. Unknown formats remain editable in preview.
  const lines = text.split(/\r?\n/);
  const start = lines.findIndex(line => /^(?:#{1,6}\s*|\*\*)(?:口播稿|口播主稿|主稿)(?:\*\*)?\s*[：:]?\s*$/.test(line.trim()));
  if (start < 0) return text;
  const end = lines.findIndex((line, i) => i > start && /^(?:#{1,6}\s+|\*\*[^*]+\*\*\s*[：:]?\s*$)/.test(line.trim()));
  return lines.slice(start + 1, end < 0 ? undefined : end).join('\n').trim() || text;
}

export const briefPrompt = `请依据本项目本轮保存资料和附件，先区分已知事实、未知信息与创意建议，再整理一套图片和口播共用的创作依据。不要猜测材质、工艺、容量、价格、功能或体验。看不到图片就说明，只使用已有文字事实。
商品特征→有事实支持的卖点→适合哪类人的购买理由→证据，要区分；审美喜好和场景设想标为建议，不能冒充验证过的需求。优先一个清楚的视觉方向，口播随后再做。
请简洁给出商品事实、卖点及可能的购买理由、目标受众、统一风格、必须保留与避免五项建议；不要把现有稿件或编辑记录当成商品事实。这些是待我核对、修改后采用的创作依据，不直接写入项目。
五栏各不超过80字，合计不超过350字；只给一套建议，不重复长篇分析和五栏正文。按壶身、壶嘴、壶盖、盖钮、把手等实际可见部件分别核对颜色，不把一个部件的颜色推及其他部件；看不清就写待确认。本轮只整理依据，不需要操作或查看未关联画布，不读取无关练习文件。`;
