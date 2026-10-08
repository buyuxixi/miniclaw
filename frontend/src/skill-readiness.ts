export interface SkillBinding { version: number; required_tools: string[]; content_hash: string; current: boolean; resource_error?: string }
export interface InstalledSkill { name: string; description: string; category?: string; enabled: boolean; binding?: SkillBinding | null }
export interface SkillReadiness { state: 'ready' | 'missing' | 'unverified' | 'disabled'; label: string; reason: string }
const toolNames: Record<string,string> = {skill_view:'技能资料读取',miniclaw_overlay_compile:'字幕动效编排',miniclaw_save_artifact:'产物保存',miniclaw_canvas_view:'工作图读取',miniclaw_canvas_propose:'修图方案',miniclaw_edit_image:'图片编辑'};
const documentSkills = new Set(['pdf', 'docx', 'xlsx', 'powerpoint']);
const details: Record<string, { title: string; description: string }> = {
  'product-prompt-optimize': {title:'产品宣传提示词优化',description:'为修图和视频整理清晰的变化要求，保护包装标识，比较后再采用。'},
  'hermes-agent': {title:'基础系统说明',description:'运行时保留的助手说明，独立于产品宣传流程。'},
  'product-video-plan': {title:'产品短片策划',description:'从产品卖点到创意方向，整理镜头、画面与视频生成要求。'},
  'product-summary': {title:'产品卖点整理',description:'提取产品事实、受众与核心卖点，为宣传内容提供依据。'},
  'canvas-editor': {title:'修图方案',description:'把修改要求整理成可预览的方案，确认后应用到当前工作图。'},
  'product-image-edit': { title: '商品修图', description: '编辑本对话的图片，保留原图和结果版本，可对比后继续修改。' },
  'mono-color': { title: '单双色封面设计', description: '根据配色和构图资料生成设计方案与提示词，再到图片工作区制作。' },
  'spoken-script': { title: '口播优化', description: '优化口语表达与开头，整理简单分镜，保留事实并标明待确认项。' },
  'overlay-plan': { title: '口播动效编排', description: '上传真实SRT，生成按原字幕时间校验的动效文件，再导入外部工作台。' },
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
  return Object.hasOwn(details, skill.name) ? details[skill.name] : { title: skill.name, description: skill.description };
}
// This is an explicit assessment of the pinned bundled flows, not a generic
// dependency inference or security boundary. Unknown environments stay unknown.
export function skillReadiness(skill: Pick<InstalledSkill, 'name' | 'enabled' | 'binding'>, tools: string[]): SkillReadiness {
  if (!skill.enabled) return { state: 'disabled', label: '未启用', reason: '可在技能管理中启用，再检查执行条件。' };
  if (skill.binding) {
    if (skill.binding.resource_error) return { state: 'missing', label: '配套资料不可用', reason: skill.binding.resource_error };
    if (!skill.binding.current) return { state: 'unverified', label: '正文已变化', reason: '请重新核对技能流程的工具依赖。' };
    const missing = skill.binding.required_tools.filter(t => !tools.includes(t));
    if (missing.length) return { state: 'missing', label: '缺少工具', reason: `当前对话缺少：${missing.map(t=>toolNames[t] ? `${toolNames[t]}（${t}）` : t).join('、')}。到设置 → 工具检查；配置更改在新对话生效。` };
    return { state: 'ready', label: '当前可用', reason: skill.binding.required_tools.length ? '已声明的工具均已加载；运行依赖仍由技能维护者负责。' : '已声明为文本流程，不依赖执行工具。' };
  }
  if (documentSkills.has(skill.name) && !tools.includes('terminal')) return { state: 'missing', label: '缺少执行工具', reason: '需要终端运行文档脚本，当前对话未开放。' };
  return { state: 'unverified', label: '运行条件待核对', reason: '已安装流程，所需工具和运行环境尚未验证。' };
}
