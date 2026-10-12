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
