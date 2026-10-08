import type { CreatorProject } from './creator-api';
export function nextCreation(p: CreatorProject) {
  if (!p.assets.source) return { stage: 'facts', title: '先给我一张商品图', detail: '上传原素材，再用Chat一起明确特点和表达方向。无需先填完所有资料。', action: '上传商品原图' };
  if (!p.facts.trim()) return { stage: 'facts', title: '一起确定这件商品怎么讲', detail: 'Chat整理可见特点、卖点与风格。你核对后采用，图片与口播共用这份依据。', action: '和Chat确定创作方向' };
  if (!p.assets.cover || p.flow?.cover === 'review') return { stage: 'cover', title: p.flow?.cover === 'review' ? '先核对图片与新依据' : '把原素材打磨成展示图', detail: '选择构图方案或摄影精修，比较结果后采用。原图和编辑历史始终保留。', action: '选择图片方案' };
  if (!p.script.trim() || p.flow?.script === 'review') return { stage: 'script', title: p.flow?.script === 'review' ? '让口播跟上当前图片' : '让图片有一段自然的讲解', detail: '用同一商品依据和采用图生成主稿，在Chat继续改，满意后只采用要读出的文字。', action: p.flow?.script === 'review' ? '核对现有主稿' : '在Chat打磨口播' };
  return { stage: 'script', title: '图片与主稿已经放在一起', detail: '现在可以核对图文、试读主稿，或继续打磨。准备好后再展开视频与交付。', action: '继续打磨主稿' };
}
