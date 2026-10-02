import { readApi } from './management-api';
import type { JsonRpcGatewayClient } from './gateway';

export interface CommandCatalog {
  skills: Record<string, unknown>;
  categories: { name: string; pairs: string[][] }[];
}

export function skillCommandAvailable(catalog: CommandCatalog, name: string): boolean {
  const key = `/${name.replaceAll('_', '-')}`;
  return key in catalog.skills && !catalog.categories.some(group =>
    group.pairs.some(pair => pair[0] === key));
}

export async function prepareSkillPrompt(client: JsonRpcGatewayClient, sessionId: string, name: string, text: string, active = () => true) {
  const skills = await readApi<{ name: string; enabled: boolean }[]>('/api/skills');
  if (!active()) throw new Error('技能加载已取消。');
  if (!skills.some(skill => skill.name === name && skill.enabled)) throw new Error('该技能已停用或不可用，请重新选择。');
  const catalog = await client.request<CommandCatalog>('commands.catalog', { session_id: sessionId });
  if (!active()) throw new Error('技能加载已取消。');
  if (!skillCommandAvailable(catalog, name)) throw new Error('该技能没有独立的调用入口，请选择其他技能。');
  const result = await client.request<{ type: string; message?: string; display?: string }>('command.dispatch', {
    session_id: sessionId, name: name.replaceAll('_', '-'), arg: text,
  });
  if (result.type !== 'skill' || !result.message?.trim()) throw new Error('技能加载失败，消息未发送。');
  return { text: result.message, display: result.display?.trim() || `/${name}\n${text}` };
}
