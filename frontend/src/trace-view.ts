import {documentToolLabel} from './tool-label';

export type TraceKind = 'input'|'context'|'model'|'assistant'|'tool'|'recovery'|'task';
export type TraceStatus = 'running'|'completed'|'failed'|'interrupted'|'unknown'|'waiting';
export type TraceStep = {
  id:string;
  kind:TraceKind;
  name:string;
  status:TraceStatus;
  task_id?:string|null;
  session_id?:string|null;
  sequence?:number;
  updated_at?:number|null;
  started_at?:number|null;
  ended_at?:number|null;
  turn_id?:string|null;
  turn_index?:number|null;
  call_index?:number|null;
  provider?:string|null;
  model?:string|null;
  tool_name?:string|null;
  request_id?:string|null;
  operation_id?:string|null;
  attempt?:number|null;
  duration_ms?:number|null;
  input_tokens?:number|null;
  output_tokens?:number|null;
  summary?:string|null;
  content?:string|null;
  input?:unknown;
  output?:unknown;
  error?:string|null;
  attributes?:Record<string,unknown>|null;
  source?:'trace'|'history';
};
export type TraceMode = 'duration'|'turns'|'calls';
export const traceKindLabel:Record<TraceKind,string>={input:'用户',context:'上下文',model:'模型',assistant:'助手',tool:'工具',recovery:'恢复',task:'任务'};
export const traceStatusLabel:Record<TraceStatus,string>={running:'进行中',completed:'已完成',failed:'失败',interrupted:'已中断',unknown:'待核对',waiting:'等待中'};
export const hasTraceNumber=(value:unknown):value is number=>typeof value==='number'&&Number.isFinite(value);
export function traceStepLabel(step:TraceStep) {
  if(step.kind==='task'&&step.status!=='running')return '本轮结束';
  const name=step.tool_name||step.name;
  return step.kind==='tool'&&name==='miniclaw_document_query'?documentToolLabel(name,step.input,step.output):step.name;
}
export function traceDuration(step:TraceStep) {
  if(hasTraceNumber(step.duration_ms))return Math.max(0,step.duration_ms);
  if(hasTraceNumber(step.started_at)&&hasTraceNumber(step.ended_at))return Math.max(0,(step.ended_at-step.started_at)*1000);
  return null;
}
export function formatTraceDuration(value:number|null) {
  if(value===null)return '未记录';
  if(value<1000)return `${Math.round(value)} 毫秒`;
  if(value<60000)return `${(value/1000).toFixed(value<10000?2:1)} 秒`;
  return `${Math.floor(value/60000)} 分 ${Math.floor(value%60000/1000)} 秒`;
}
export function traceText(value:unknown):string {
  if(value===undefined||value===null)return '';
  if(typeof value==='string')return value;
  try{return JSON.stringify(value,null,2);}catch{return String(value);}
}
export function traceSummary(step:TraceStep) {
  let summary:string;
  if(step.kind==='task')summary=step.error||'';
  else if(step.kind==='context')summary=step.content||step.summary||step.name;
  else if(step.kind==='tool'){
    const compact=(value:unknown)=>{try{return typeof value==='string'?value:JSON.stringify(value)||'';}catch{return '';}};
    let result=step.output;
    if(typeof result==='string'){try{result=JSON.parse(result);}catch{/* Keep textual receipts. */}}
    const object=result&&typeof result==='object'?result as Record<string,unknown>:null;
    const entries=Array.isArray(object?.entries)?object.entries:[];
    const names=entries.flatMap(entry=>entry&&typeof entry==='object'&&typeof entry.name==='string'?[entry.name]:[]);
    const output=step.error||object?.error||object?.content|| (names.length?`${entries.length} 个条目：${names.join('、')}`:compact(result));
    const args=compact(step.input),shortArgs=args.slice(0,140)+(args.length>140?'…':'');
    summary=[shortArgs,output].filter(Boolean).join(' → ')||step.summary||step.name;
  }else if(step.kind==='model'){
    const output=typeof step.output==='object'&&step.output!==null?step.output as Record<string,unknown>:null;
    const content=step.content||typeof output?.content==='string'&&output.content;
    const calls=Array.isArray(output?.tool_calls)?output.tool_calls:[];
    const names=[...new Set(calls.flatMap(call=>{
      if(typeof call!=='object'||call===null)return [];
      const item=call as Record<string,unknown>,fn=typeof item.function==='object'&&item.function!==null?item.function as Record<string,unknown>:null;
      const name=item.name||fn?.name;
      return typeof name==='string'&&name?[name==='miniclaw_document_query'?documentToolLabel(name,item.args??item.arguments??fn?.arguments):name]:[];
    }))];
    summary=content||names.length&&`调用工具：${names.join('、')}`||step.error||step.summary||step.name;
  }else summary=step.summary||step.error||step.content||traceText(step.output)||traceText(step.input)||step.name;
  return summary.replace(/\s+/g,' ').trim().slice(0,600);
}
export function traceLane(step:TraceStep):'input'|'model'|'tool' {
  return step.kind==='input'||step.kind==='context'?'input':step.kind==='tool'?'tool':'model';
}

// Stored task rows are opened first and updated at completion. Their summary is
// a terminal event, not the first message. Preserve the recorded event sequence
// and legacy history anchors; only move a sealed task to the end of its span.
export function traceReadingOrder(steps:TraceStep[]):TraceStep[] {
  const ordered=steps.every(step=>hasTraceNumber(step.sequence))
    ? [...steps].sort((a,b)=>a.sequence!-b.sequence!) : steps;
  const after=new Map<number,TraceStep[]>(), moved=new Set<string>();
  ordered.forEach((step,index)=>{
    if(step.kind!=='task'||step.status==='running')return;
    let last=index;
    for(let next=index+1;next<ordered.length;next++){
      const other=ordered[next];
      if(other.kind==='task'||other.kind==='input'&&other.source==='history')break;
      if(!step.task_id||other.task_id===step.task_id)last=next;
    }
    moved.add(step.id);
    after.set(last,[...(after.get(last)||[]),step]);
  });
  return ordered.flatMap((step,index)=>[...(moved.has(step.id)?[]:[step]),...(after.get(index)||[])]);
}

export type TraceReadingRow={step:TraceStep;requests:TraceStep[];round:number;order:number};
export function traceReadingRows(steps:TraceStep[],events=false):TraceReadingRow[] {
  const requests=new Map(steps.filter(step=>step.kind==='model').map(step=>[step.id,step]));
  const represented=new Set(steps.filter(step=>step.kind==='assistant').flatMap(step=>
    typeof step.attributes?.model_step_id==='string'?[step.attributes.model_step_id]:[]));
  let round=0;
  return traceReadingOrder(steps).filter(step=>events||!(step.kind==='task'&&step.status==='running')&&
    !(step.kind==='model'&&step.status==='completed'&&represented.has(step.id))).map((step,index)=>{
    if(step.kind==='input')round++;
    const modelId=step.attributes?.model_step_id;
    const request=typeof modelId==='string'?requests.get(modelId):undefined;
    return {step,requests:request?[request]:[],round,order:index+1};
  });
}
export function traceRoundKey(step:TraceStep) {
  if(step.turn_id)return `turn:${step.turn_id}`;
  if(hasTraceNumber(step.turn_index))return `round:${step.turn_index}`;
  if(step.task_id)return `task:${step.task_id}`;
  return 'unknown';
}
export function traceSpan(steps:TraceStep[]) {
  const starts=steps.map(step=>step.started_at).filter(hasTraceNumber);
  const ends=steps.flatMap(step=>[step.ended_at,step.started_at]).filter(hasTraceNumber);
  if(!starts.length)return null;
  const start=Math.min(...starts),end=Math.max(...ends);
  return {start,end,duration:Math.max(0,(end-start)*1000)};
}
