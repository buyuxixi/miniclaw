export interface InstalledSkill { name: string; description: string; category?: string; enabled: boolean }
export interface SkillReadiness { state: 'ready' | 'missing' | 'unverified' | 'disabled'; label: string; reason: string }
const documentSkills = new Set(['pdf', 'docx', 'xlsx', 'powerpoint']);
const details: Record<string, { title: string; description: string }> = {
  humanizer: { title: '自然表达', description: '让文案更自然，减少生硬和模板化的表达。' },
  pdf: { title: 'PDF 文档', description: '生成、提取和整理 PDF 文档。' },
  docx: { title: 'Word 文档', description: '创建、编辑和审阅 Word 文档。' },
  xlsx: { title: '电子表格', description: '整理数据，创建 Excel 表格和报表。' },
  powerpoint: { title: '演示文稿', description: '把内容组织成可编辑的幻灯片。' },
  'claude-code': { title: 'Claude 编程助手', description: '调用 Claude Code 执行开发任务。' },
  codex: { title: 'Codex 编程助手', description: '调用 Codex 执行开发任务。' },
  'computer-use': { title: '电脑操作', description: '通过桌面操作完成任务。' },
  'architecture-diagram': { title: '架构图', description: '将系统结构整理成图示。' },
};
export function skillDetails(skill: Pick<InstalledSkill, 'name' | 'description'>) {
  return details[skill.name] ?? { title: skill.name, description: skill.description };
}
// This is an explicit assessment of the pinned bundled flows, not a generic
// dependency inference or security boundary. Unknown environments stay unknown.
export function skillReadiness(skill: Pick<InstalledSkill, 'name' | 'enabled'>, tools: string[]): SkillReadiness {
  if (!skill.enabled) return { state: 'disabled', label: '未启用', reason: '可在技能管理中启用，再检查执行条件。' };
  if (skill.name === 'humanizer') return { state: 'ready', label: '当前可用', reason: '已核对的文本改写流程，不依赖执行工具。' };
  if (documentSkills.has(skill.name) && !tools.includes('terminal')) return { state: 'missing', label: '缺少执行工具', reason: '需要终端运行文档脚本，当前对话未开放。' };
  return { state: 'unverified', label: '运行条件待核对', reason: '已安装流程，所需工具和运行环境尚未验证。' };
}
