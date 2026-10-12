import type {ChatItem} from './types';
import type {ImagePlan} from './ImagePlanPanel';

// Only a successful proposal tool owns a plan; reading or mentioning one does not.
export function plansByMessage(items:ChatItem[],plans:ImagePlan[]) {
  const grouped=new Map<string,ImagePlan[]>(),used=new Set<string>();
  items.forEach((item,index)=>{
    if(item.kind!=='tool'||item.name!=='miniclaw_canvas_propose')return;
    try {
      const result=typeof item.result==='string'?JSON.parse(item.result):item.result;
      if(!result||typeof result!=='object'||result.success!==true||typeof result.id!=='string')return;
      const plan=plans.find(p=>p.id===result.id&&p.project===result.project);
      if(!plan||used.has(plan.id))return;
      let anchor=item.id;
      for(let i=index+1;i<items.length&&items[i].kind!=='user';i++)if(items[i].kind==='assistant'){anchor=items[i].id;break;}
      used.add(plan.id);grouped.set(anchor,[plan,...(grouped.get(anchor)||[])]);
    }catch{/* Incomplete or unavailable tool output never fabricates ownership. */}
  });
  return grouped;
}

export function fullImagePlanPrompt(plan:ImagePlan) {
  const step=plan.steps[0];
  if(plan.steps.length!==1||step.action!=='ai_edit'||step.params.region!==false||typeof step.params.prompt!=='string'||!step.params.prompt.trim())return null;
  const prompt=step.params.prompt.trim()+(plan.preserve.trim()?`\n必须保留：${plan.preserve.trim()}`:'');
  return prompt.length<=2000?prompt:null;
}

export type DirectorQuestion={title:string;options:string[]};
export function clarification(text:string):{body:string;questions:DirectorQuestion[]}|null {
  const blocks=[...text.matchAll(/```studio-question\s*\n([\s\S]*?)```/g)];
  if(blocks.length!==1)return null;
  try {
    const value=JSON.parse(blocks[0][1]);
    if(!value||Object.keys(value).join(',')!=='questions'||!Array.isArray(value.questions)||value.questions.length<1||value.questions.length>3)return null;
    const questions:DirectorQuestion[]=[];
    for(const q of value.questions){
      if(!q||Object.keys(q).sort().join(',')!=='options,title'||typeof q.title!=='string'||!q.title.trim()||q.title.length>200||!Array.isArray(q.options)||q.options.length<2||q.options.length>3||!q.options.every((o:unknown)=>typeof o==='string'&&!!o.trim()&&o.length<=80)||new Set(q.options).size!==q.options.length)return null;
      questions.push({title:q.title,options:q.options});
    }
    return {body:text.replace(blocks[0][0], '').trim(),questions};
  }catch{return null;}
}
