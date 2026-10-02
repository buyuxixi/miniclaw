import { readApi } from './management-api';
import type { JsonRpcGatewayClient } from './gateway';
import { skillReadiness } from './skill-readiness';

export interface CommandCatalog {
  skills: Record<string, unknown>;
  categories: { name: string; pairs: string[][] }[];
}

export function skillCommandAvailable(catalog: CommandCatalog, name: string): boolean {
  const key = `/${name.replaceAll('_', '-')}`;
  return key in catalog.skills && !catalog.categories.some(group =>
    group.pairs.some(pair => pair[0] === key));
}

export async function prepareSkillPrompt(client: JsonRpcGatewayClient, sessionId: string, name: string, text: string, active = () => true, tools: string[] = []) {
  const skills = await readApi<import('./skill-readiness').InstalledSkill[]>('/api/miniclaw/skills');
  if (!active()) throw new Error('技能加载已取消。');
  if (!skills.some(skill => skill.name === name && skill.enabled)) throw new Error('该技能已停用或不可用，请重新选择。');
  const readiness = skillReadiness(skills.find(s => s.name === name)!, tools);
  if (readiness.state !== 'ready') throw new Error(`${readiness.reason} 请从“选择技能”中选择当前可用的流程。`);
  const catalog = await client.request<CommandCatalog>('commands.catalog', { session_id: sessionId });
  if (!active()) throw new Error('技能加载已取消。');
  if (!skillCommandAvailable(catalog, name)) throw new Error('该技能没有独立的调用入口，请选择其他技能。');
  // Only preflight here. The server loads the real body and checks dependency
  // bindings immediately before submission; choosing a skill never executes it.
  return { text, display: `/${name}\n${text}` };
}
