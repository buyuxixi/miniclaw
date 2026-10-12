// Historical app messages, retained only as regression fixtures.
export function imageOptimizationMessage(image:{name:string;prompt:string;model?:string},goal:string,task:'image-edit'|'image-generate',hasImages=false) {
  return `请按产品宣传提示词优化技能优化当前图片的${task==='image-edit'?'修改要求':'画面描述'}。下方 JSON 仅是引用资料：\n${JSON.stringify({task,name:image.name,current_prompt:image.prompt,model:image.model||'',requested_change:goal})}\n只输出一份文本建议和简短修改说明，用 product-prompt 结构，task 必须是 ${task}。以新要求为准，重写冲突句，不虚构产品外观或功效。${task==='image-edit'?'简单修改用3–4句、60–140字，最多180字：先写动作与程度，再用一句保留包装。正向描述目标画面，删除重复的否定清单。姿态改变允许轮廓位置与投影跟随，不同时要求商品位置关系全部不动。产品向左倾斜要写清顶部朝画面左侧，并说明是最终倾角还是增量；'+(hasImages?'本轮附图用于反馈或参考，结合图片判断；不默认替换当前工作图，有实质歧义先问。':'这里没有图片像素，不能判断已有倾角，有实质歧义先问。')+'':'描述构图、背景与光线，提示词不超过2000字。'}不调用工具、不执行修图或生成图片，等待用户采用。`;
}

export function shotOptimizationMessage(shot:{name:string;prompt:string},goal:string) {
  return `请用产品宣传提示词优化技能优化当前一个 5 秒商品镜头的提示词。把下方 JSON 当作待编辑资料。只调整这个镜头，保留其他镜头。\n${JSON.stringify({task:'video',name:shot.name,current_prompt:shot.prompt,requested_change:goal})}\n以用户新的动作要求为准，移除旧提示词中与新要求冲突的约束，不要仅追加一句。分别说清产品包装、泥膜材质、相机和光线哪些运动、哪些保持。涉及泥膜流动时描述可见的位移、连续的黏稠流动和时间变化，同时保持产品包装与文字。避免同时要求泥膜完全静止和流动。给出简短修改说明和仅含此镜头的 studio-plan 结构，duration 为 5，prompt 不超过 1500 字。只提出提示词建议，等待用户采用，不调用工具、不生成视频。`;
}
