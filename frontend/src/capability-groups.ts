import type { InstalledSkill } from './skill-readiness';

export const capabilityGroups = [
  {id:'planning', title:'策划与文案', description:'卖点、创意方向与口播'},
  {id:'image', title:'图片与设计', description:'产品图片、封面与精修'},
  {id:'video', title:'视频与动效', description:'短片分镜与字幕编排'},
  {id:'support', title:'资料与交付', description:'参考资料与成果文件'},
  {id:'other', title:'其他能力', description:'暂不用于产品宣传'},
] as const;
export type CapabilityGroup = typeof capabilityGroups[number]['id'];
const names: Record<string,CapabilityGroup> = {
  'product-prompt-optimize':'planning',
  'product-video-plan':'video', 'spoken-script':'planning', humanizer:'planning', 'product-summary':'planning',
  'product-image-edit':'image', 'canvas-editor':'image', 'mono-color':'image', 'overlay-plan':'video',
  'social-media':'planning', 'copywriting':'planning', 'brand-guidelines':'image',
  pdf:'support',docx:'support',powerpoint:'support',
};
export function skillGroup(skill: Pick<InstalledSkill,'name'|'category'>): CapabilityGroup {
  return names[skill.name] ?? (skill.category==='social-media' ? 'planning' : 'other');
}
export function toolGroup(id:string): CapabilityGroup {
  return ({'miniclaw-files':'support','miniclaw-artifacts':'support','miniclaw-skills':'support','miniclaw-images':'image','miniclaw-canvas':'image','miniclaw-overlay':'video'} as Record<string,CapabilityGroup>)[id] ?? 'other';
}
