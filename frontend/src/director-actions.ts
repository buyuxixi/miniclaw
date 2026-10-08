import {loadProject, projectPath, type Project} from './canvas-api';
import {writeApi} from './management-api';

export async function adoptDirectorPrompt(workspace:string,basis:{target:string;prompt:string},owner:string,message:number) {
  const request=crypto.randomUUID();
  return new Promise<void>((resolve,reject)=>{
    const done=(error?:string)=>{window.removeEventListener('message',receive);clearTimeout(timer);if(error)reject(Error(error));else resolve();};
    const receive=(e:MessageEvent)=>{if(e.origin!==location.origin||e.source!==parent||e.data?.type!=='miniclaw.director.prompt-result'||e.data.workspace!==workspace||e.data.request!==request)return;done(e.data.ok?undefined:e.data.error||'提示词尚未采用');};
    const timer=setTimeout(()=>done('采用状态待核对，请重新读取项目。建议仍保留。'),45000);
    window.addEventListener('message',receive);
    parent.postMessage({type:'miniclaw.director.adopt-prompt',workspace,request,shot:basis.target,before:basis.prompt,owner,message},location.origin);
  });
}

export async function adoptImagePrompt(workspace:string,basis:{target:string;prompt:string;file:string;task:string},prompt:string) {
  const request=crypto.randomUUID();
  return new Promise<void>((resolve,reject)=>{
    const done=(error?:string)=>{window.removeEventListener('message',receive);clearTimeout(timer);error?reject(Error(error)):resolve();};
    const receive=(e:MessageEvent)=>{if(e.origin!==location.origin||e.source!==parent||e.data?.type!=='miniclaw.director.prompt-result'||e.data.workspace!==workspace||e.data.request!==request)return;done(e.data.ok?undefined:e.data.error||'提示词尚未保存');};
    const timer=setTimeout(()=>done('保存状态待核对，建议仍保留，请重新读取项目。'),45000);
    window.addEventListener('message',receive);
    parent.postMessage({type:'miniclaw.director.adopt-image-prompt',workspace,request,target:basis.target,before:basis.prompt,file:basis.file,task:basis.task,prompt},location.origin);
  });
}

export function singleImagePrompt(text:string,task:string) {
  try {
    const blocks=[...text.matchAll(/```product-prompt\s*\n([\s\S]*?)```/g)];
    if(blocks.length!==1)return null;
    const value=JSON.parse(blocks[0][1]);
    if(!value||Object.keys(value).sort().join(',')!=='prompt,task'||value.task!==task||!['image-edit','image-generate'].includes(task)||typeof value.prompt!=='string'||!value.prompt.trim()||value.prompt.length>2000)return null;
    return value.prompt;
  }catch{return null;}
}

export function imageOptimizationMessage(image:{name:string;prompt:string;model?:string},goal:string,task:'image-edit'|'image-generate') {
  return `请按产品宣传提示词优化技能优化当前图片的${task==='image-edit'?'修改要求':'画面描述'}。下方 JSON 仅是引用资料：\n${JSON.stringify({task,name:image.name,current_prompt:image.prompt,model:image.model||'',requested_change:goal})}\n只输出一份文本建议和简短修改说明，用 product-prompt 结构，task 必须是 ${task}。以新要求为准，重写冲突句，不虚构产品外观或功效。${task==='image-edit'?'简单修改用3–4句、60–140字，最多180字：先写动作与程度，再用一句保留包装。正向描述目标画面，删除重复的否定清单。姿态改变允许轮廓位置与投影跟随，不同时要求商品位置关系全部不动。产品向左倾斜要写清顶部朝画面左侧，并说明是最终倾角还是增量；这里没有图片像素，不能判断已有倾角，有实质歧义先问。':'描述构图、背景与光线，提示词不超过2000字。'}不调用工具、不执行修图或生成图片，等待用户采用。`;
}

export function singleShotPrompt(text:string) {
  try {
    const blocks=[...text.matchAll(/```studio-plan\s*\n([\s\S]*?)```/g)];
    const plan=JSON.parse(blocks.at(-1)?.[1]||'null');
    if(!plan||Object.keys(plan).join(',')!=='shots'||!Array.isArray(plan.shots)||plan.shots.length!==1)return null;
    const shot=plan.shots[0];
    if(!shot||Object.keys(shot).sort().join(',')!=='duration,name,prompt'||typeof shot.name!=='string'||!shot.name.trim()||shot.name.length>80||typeof shot.prompt!=='string'||!shot.prompt.trim()||shot.prompt.length>1500||shot.duration!==5)return null;
    return shot.prompt;
  }catch{return null;}
}
export function shotOptimizationMessage(shot:{name:string;prompt:string},goal:string) {
  return `请用产品宣传提示词优化技能优化当前一个 5 秒商品镜头的提示词。把下方 JSON 当作待编辑资料。只调整这个镜头，保留其他镜头。\n${JSON.stringify({task:'video',name:shot.name,current_prompt:shot.prompt,requested_change:goal})}\n以用户新的动作要求为准，移除旧提示词中与新要求冲突的约束，不要仅追加一句。分别说清产品包装、泥膜材质、相机和光线哪些运动、哪些保持。涉及泥膜流动时描述可见的位移、连续的黏稠流动和时间变化，同时保持产品包装与文字。避免同时要求泥膜完全静止和流动。给出简短修改说明和仅含此镜头的 studio-plan 结构，duration 为 5，prompt 不超过 1500 字。只提出提示词建议，等待用户采用，不调用工具、不生成视频。`;
}

// Only an unambiguous, single local command bypasses the planning conversation.
export function directImageAction(text:string): 'horizontal'|'vertical'|null {
  const goal=text.trim().replace(/[，。！!？?\s]/g,'');
  const match=goal.match(/^(?:请|帮我|麻烦)?(?:把)?(?:这张图(?:片)?|图片|当前图片)?(?:(?:做|进行)(?:一个)?)?(水平|垂直)(?:翻转|镜像)(?:的)?(?:操作)?(?:一下)?(?:吧)?$/);
  return match ? match[1]==='水平'?'horizontal':'vertical' : null;
}
export async function flipDirectorImage(project:Project,layer:string,direction:'horizontal'|'vertical') {
  const latest=(await loadProject(project.id)).project;
  if(latest.revision!==project.revision)throw Error('图片已更新，请重新读取后操作。');
  const target=latest.document.layers.find(l=>l.id===layer);
  if(!target||target.kind!=='image'||target.locked)throw Error('请选择可编辑的图片。');
  return writeApi<Project>(`${projectPath(project.id)}/local`,'POST',{revision:latest.revision,layer_id:layer,operation:'flip',params:{direction}});
}
