import {useEffect, useRef, useState} from 'react';
import type {ChatController} from './chat-controller';
import {useChat} from './use-chat';
import {readApi, writeApi} from './management-api';
import {ImagePlanPanel, type PlanPreview} from './ImagePlanPanel';
import {Message} from './Message';
import {saveStudioIdea} from './studio-api';
import {exportBlob, loadProject, type CanvasJob, type Project} from './canvas-api';
import './studio-director.css';
import {Icon} from './Icon';
import {directImageAction, flipDirectorImage, singleShotPrompt, shotOptimizationMessage, adoptDirectorPrompt, singleImagePrompt, imageOptimizationMessage, adoptImagePrompt} from './director-actions';

const query=new URLSearchParams(location.search);
const workspace=query.get('director') || '';
const initialTarget=query.get('target') || '';
type EditingTarget={project:string;revision:number;layer:string;object:string;source:string;shot?:string};
type ImageChoice={id:string;name:string;file:string;imagePrompt?:string;imageModel?:string};
type EditingResponse=EditingTarget&{selection_required?:boolean;discussion_only?:boolean;assets?:ImageChoice[]};
function thumbnail(file:string){return file.startsWith('/api/precision/projects/')?file.replace('/api/precision/projects/','/studio/media/'):file.startsWith('/')||file.startsWith('data:')?file:'/studio/'+file;}
type TargetRequest={target:string;label:string;request:number;intent?:string;node?:string;result?:string};
type ShotBasis={target:string;prompt:string;goal:string;known:string[];task?:'image-edit'|'image-generate';file?:string;replyId?:string;owner?:string};
function optimizationKey(target:string,intent:string){return `studio-prompt-advice:${workspace}:${target}:${intent}`;}
function savedOptimization(target:string,intent:string):ShotBasis|undefined{
  if(!intent.startsWith('optimize'))return;
  try{const value=JSON.parse(localStorage.getItem(optimizationKey(target,intent))||'null');const task=intent==='optimize-generate'?'image-generate':intent==='optimize-edit'?'image-edit':undefined;
    if(value?.target===target&&value.task===task&&typeof value.prompt==='string'&&typeof value.goal==='string'&&Array.isArray(value.known)&&value.known.every((v:unknown)=>typeof v==='string')&&/^row-\d+$/.test(value.replyId)&&typeof value.owner==='string')return value;
  }catch{}return;
}
function savedDraft(){try{const r=JSON.parse(localStorage.getItem(`studio-director-scoped-draft:${workspace}:${initialTarget}`)||localStorage.getItem(`studio-director-scoped-draft:${workspace}`)||'null');return r?.target===initialTarget&&typeof r.text==='string'?r.text:'';}catch{return '';}}
export function StudioDirector({controller}:{controller:ChatController}) {
  const chat=useChat(controller);
  const [target,setTarget]=useState(initialTarget), [label,setLabel]=useState(query.get('label') || '当前项目');
  const [draft,setDraft]=useState(savedDraft);
  const [project,setProject]=useState<Project>(), [editing,setEditing]=useState<EditingTarget>();
  const [choices,setChoices]=useState<ImageChoice[]>([]);
  const [image,setImage]=useState(()=>({target:initialTarget,id:localStorage.getItem(`studio-director-image:${workspace}:${initialTarget}`)||''}));
  const selectedImage=image.target===target?image.id:'';
  const [jobs,setJobs]=useState<CanvasJob[]>([]);
  const [busy,setBusy]=useState(false), [error,setError]=useState('');
  const [localResult,setLocalResult]=useState('');
  const localFlight=useRef(false);
  const [requests,setRequests]=useState(0);
  const [reading,setReading]=useState(false),[pendingTarget,setPendingTarget]=useState<TargetRequest>();
  const modeTarget=useRef('');
  const [intent,setIntent]=useState(query.get('intent')||'discuss'),[targetReading,setTargetReading]=useState(true),[basis,setBasis]=useState<ShotBasis|undefined>(()=>savedOptimization(initialTarget,query.get('intent')||'discuss'));
  useEffect(()=>{setBasis(savedOptimization(target,intent));},[target,intent]);
  const [contextNode,setContextNode]=useState(''),[resultId,setResultId]=useState('');
  const [contextOpen,setContextOpen]=useState(false),[refining,setRefining]=useState(false),[showOriginal,setShowOriginal]=useState(false);
  const [invalidBasis,setInvalidBasis]=useState(false);
  const conversation=useRef<HTMLElement>(null);
  const [selectedAsset,setSelectedAsset]=useState<ImageChoice>();
  const [mode,setMode]=useState<'image'|'shot'>('image'),[selectedShot,setSelectedShot]=useState<{id:string;name:string;prompt:string;inputs:ImageChoice[]}>();
  useEffect(()=>{let canceled=false;setTargetReading(true);setSelectedShot(undefined);setSelectedAsset(undefined);void readApi<{state:{shots:{id:string;name:string;prompt:string;mode:string;first:string;refs:string[]}[];assets:ImageChoice[]}}>(`/api/workspaces/${workspace}`).then(r=>{if(!canceled){const shot=r.state.shots.find(s=>s.id===target);setSelectedAsset(r.state.assets.find(a=>a.id===target));setSelectedShot(shot?{...shot,inputs:(shot.mode==='first'?[shot.first]:shot.refs).map(id=>r.state.assets.find(a=>a.id===id)).filter((a):a is ImageChoice=>!!a)}:undefined);if(modeTarget.current!==target){setMode(shot?'shot':'image');modeTarget.current=target;}};}).catch(e=>{if(!canceled)setError(e.message);}).finally(()=>{if(!canceled)setTargetReading(false);});return()=>{canceled=true;};},[target,requests]);
  const serial=useRef(0), bottom=useRef<HTMLDivElement>(null), results=useRef<HTMLDivElement>(null), scope=useRef({target,draft,label});
  scope.current={target,draft,label};
  useEffect(()=>{setChoices([]);setLocalResult('');setContextOpen(false);setRefining(false);setShowOriginal(false);setInvalidBasis(false);},[target,selectedImage]);
  useEffect(()=>{controller.workspace={id:workspace,target};},[controller,target]);
  useEffect(()=>{try{localStorage.setItem(`studio-director-scoped-draft:${workspace}:${target}`,JSON.stringify({target,label,text:draft}));}catch{}},[workspace,target,label,draft]);
  useEffect(()=>{if(!intent.startsWith('optimize'))bottom.current?.scrollIntoView({block:'end'});},[chat.items.length,chat.items.at(-1)?.text,mode,intent]);
  useEffect(()=>{results.current?.scrollIntoView({block:'nearest'});},[jobs.map(j=>j.id+':'+j.state).join('|')]);
  useEffect(()=>{
    const listener=(e:MessageEvent)=>{if(e.source!==parent || e.origin!==location.origin || e.data?.workspace!==workspace)return;
      if(e.data.type==='miniclaw.director.image'&&e.data.target===scope.current.target&&typeof e.data.asset==='string'){
        localStorage.setItem(`studio-director-image:${workspace}:${scope.current.target}`,e.data.asset);
        setImage({target:scope.current.target,id:e.data.asset});return;
      }
      if(e.data.type==='miniclaw.director.refresh'){setRequests(v=>v+1);return;}
      if(e.data.type!=='miniclaw.director.target'||typeof e.data.target!=='string')return;
      const next=e.data as TargetRequest;
      if((localFlight.current || scope.current.draft.trim() || controller.state.running)&&next.target!==scope.current.target){setPendingTarget(next);parent.postMessage({type:'miniclaw.director.context',workspace,request:next.request,target:scope.current.target,label:scope.current.label,pending:true},location.origin);return;}
      parent.postMessage({type:'miniclaw.director.context',workspace,request:next.request,target:next.target,label:next.label,pending:false},location.origin);
      setIntent(next.intent||'discuss');setContextNode(next.node||'');setResultId(next.result||'');
      setPendingTarget(undefined);
      setTarget(e.data.target || '');setLabel(e.data.label || '当前项目');};
    window.addEventListener('message',listener);parent.postMessage({type:'miniclaw.director.ready',workspace},location.origin);return()=>window.removeEventListener('message',listener);
  },[controller]);
  useEffect(()=>{
    const ticket=++serial.current;
    setProject(undefined);setEditing(undefined);setReading(false);setError('');
    if(chat.connection!=='open' || !chat.sessionId || chat.busy)return;
    if(!target||targetReading||mode!=='image'||intent.startsWith('optimize'))return;
    setReading(true);
    void writeApi<EditingResponse>(`/api/workspaces/${workspace}/editing-target`,'POST',{target,session_id:chat.sessionId,...(selectedImage?{asset:selectedImage}:{})}).then(async meta=>{
      if(ticket!==serial.current)return;
      setChoices(meta.assets||[]);
      if(meta.selection_required||meta.discussion_only)return;
      const row=await loadProject(meta.project);
      if(ticket===serial.current){setEditing(meta);setProject(row.project);setJobs(row.jobs);}
    }).catch(e=>{if(ticket===serial.current)setError(e.message);}).finally(()=>{if(ticket===serial.current)setReading(false);});
  },[target,selectedImage,chat.connection,chat.sessionId,chat.busy,requests,targetReading,mode,intent]);
  async function refresh() {if(editing){const ticket=serial.current;const row=await loadProject(editing.project);if(ticket===serial.current){setProject(row.project);setJobs(row.jobs);}}}
  useEffect(()=>{if(!editing)return;const timer=setInterval(()=>void refresh().catch(e=>setError(e.message)),2500);return()=>clearInterval(timer);},[editing]);
  const tools=Object.values(chat.info.tools||{}).flat();
  const canPlan=tools.includes('miniclaw_canvas_propose');
  const blocked=busy||reading||targetReading||chat.busy||chat.running||chat.connection!=='open';
  const imageOptimizing=mode==='image'&&intent.startsWith('optimize');
  const imageTask=intent==='optimize-generate'?'image-generate':'image-edit';
  const optimizing=(mode==='shot'&&intent==='optimize')||imageOptimizing;
  const optimizationReply=basis?.target===target&&(!basis.owner||basis.owner===chat.storedId)&&(imageOptimizing?basis.task===imageTask:!basis.task)?[...chat.items].reverse().find(i=>i.kind==='assistant'&&(basis.replyId?i.id===basis.replyId:!basis.known.includes(i.id))):undefined;
  const suggestion=optimizationReply&&/^row-\d+$/.test(optimizationReply.id)?basis?.task?singleImagePrompt(optimizationReply.text,basis.task):singleShotPrompt(optimizationReply.text):null;
  const explanation=optimizationReply?.text.replace(/```(?:studio-plan|product-prompt)\s*\n[\s\S]*?```/g,'').trim()||'';
  const firstExplanation=explanation.split(/\n\s*\n|\n/).map(p=>p.trim()).find(p=>p&&!/^#{1,6}\s/.test(p))?.replace(/\*\*|^修改说明[：:]/g,'')||'';
  const summaryLine=firstExplanation.match(/^[\s\S]*?[。；;]/)?.[0]||firstExplanation;
  const changeSummary=summaryLine.length>90?summaryLine.slice(0,87)+'…':summaryLine;
  useEffect(()=>{if(!basis||!suggestion||!optimizationReply||chat.running||basis.replyId)return;const cached={...basis,replyId:optimizationReply.id,owner:chat.storedId};setBasis(cached);try{localStorage.setItem(optimizationKey(target,intent),JSON.stringify(cached));}catch{}},[basis,suggestion,optimizationReply?.id,chat.running,target,intent,chat.storedId]);
  const staleSuggestion=!!suggestion&&invalidBasis;
  useEffect(()=>{setShowOriginal(false);if(conversation.current)conversation.current.scrollTop=0;},[optimizationReply?.id]);
  const objectName=label.replace(/ · (视频结果|镜头设置)$/,'');
  const readyJob=project&&jobs.find(j=>j.state==='succeeded'&&j.output&&j.revision===project.revision&&!project.document.layers.some(l=>l.id===j.layer_id&&l.asset_id===j.output!.id));
  async function send(goal=draft.trim()||(optimizing?'优化当前提示词，检查相互冲突的要求，清楚描述需要变化的部分，保留产品包装与标识。':'')) {
    if(blocked||!goal.trim())return;
    const direct=mode==='image'&&!optimizing?directImageAction(goal):null;
    if(direct){await flip(direct);return;}
    const previousBasis=basis,wasRefining=refining,wasInvalid=invalidBasis;
    setError('');setBusy(true);
    try {
      if(mode==='image'&&!optimizing&&project&&!canPlan)throw Error('当前对话未启用修图工具。请在创作助手的设置中启用画布助手，再从项目重新连接。');
      if(imageOptimizing&&!selectedAsset)throw Error('请选择要优化提示词的图片。');
      // Shadow decisions never gate or execute a task, and failures never resend.
      if(!optimizing)void readApi<{revision:number}>(`/api/workspaces/${workspace}`).then(record=>writeApi(`/api/workspaces/${workspace}/decisions`,'POST',{
        request_id:crypto.randomUUID(),revision:record.revision,instruction:goal.slice(0,1200),target,
      })).catch(()=>{});
      const requestGoal=refining&&basis?.goal?`${basis.goal}；${goal}`:goal;
      const requestBasis:ShotBasis|undefined=imageOptimizing&&selectedAsset?{target,prompt:selectedAsset.imagePrompt||'',file:selectedAsset.file,task:imageTask,goal:requestGoal,known:chat.items.map(i=>i.id)}:mode==='shot'&&selectedShot?{target,prompt:selectedShot.prompt,goal:requestGoal,known:chat.items.map(i=>i.id)}:undefined;
      const message=imageOptimizing&&selectedAsset?imageOptimizationMessage({name:selectedAsset.name,prompt:refining&&suggestion?suggestion:selectedAsset.imagePrompt||'',model:selectedAsset.imageModel},requestGoal,imageTask):mode==='shot'&&selectedShot?shotOptimizationMessage(refining&&suggestion?{...selectedShot,prompt:suggestion}:selectedShot,requestGoal):goal;
      if(requestBasis)setBasis(requestBasis);
      setInvalidBasis(false);
      setRefining(false);
      const ok=await controller.send(message,optimizing?'product-prompt-optimize':mode==='shot'?'product-video-plan':project?'canvas-editor':undefined,[],!optimizing&&project&&editing?{project_id:project.id,revision:project.revision,layer_id:editing.layer,mode:'plan'}:undefined);
      if(ok)setDraft('');else {setBasis(previousBasis);setRefining(wasRefining);setInvalidBasis(wasInvalid);setError(controller.state.error||'尚未发送，修改要求已保留');}
    }catch(e){setBasis(previousBasis);setRefining(wasRefining);setInvalidBasis(wasInvalid);setError((e as Error).message);}finally{setBusy(false);}
  }
  async function flip(direction:'horizontal'|'vertical') {
    if(blocked||localFlight.current)return;
    if(!editing||!project){setError(choices.length>1?'先选择要翻转的图片。':'请先在画布选中图片。');return;}
    localFlight.current=true;setBusy(true);setError('');
    try {
      const next=await flipDirectorImage(project,editing.layer,direction);
      setProject(next);setDraft('');setLocalResult(direction==='horizontal'?'已水平翻转':'已垂直翻转');
      try{await compare();}catch{setError('翻转已完成，比较未打开。请点击“比较修改”重试。');}
    }catch(e){setError((e as Error).message);}finally{localFlight.current=false;setBusy(false);}
  }
  async function run(work:()=>Promise<void>) {setBusy(true);setError('');try{await work();await refresh();}catch(e){const message=(e as Error).message;if(/提示词已修改|镜头已变化|重新选中/.test(message))setInvalidBasis(true);setError(message);}finally{setBusy(false);}}
  async function showPreview(candidate: {project:string;revision:number;before?:Blob;after?:Blob;output?:string;before_output?:string;comparison?:{id:string;job:string};plan?:PlanPreview['plan'];job?:CanvasJob}) {
    if(!editing)return;
    const record=await readApi<{revision:number;state:{assets:{id:string;file:string}[]}}>(`/api/workspaces/${workspace}`);
    if(record.state.assets.find(a=>a.id===editing.object)?.file!==editing.source)throw Error('原素材已有变化，请重新读取后比较。');
    parent.postMessage({type:'miniclaw.director.compare',workspace,candidate,target:editing,basis:record.revision},location.origin);
  }
  async function compareJob(job:CanvasJob) {
    if(!project||!job.output) return;
    const latest=await loadProject(project.id);
    try {
      const candidate=await writeApi<{project:string;revision:number;output:string;output_id:string;before_output:string;comparison:{id:string;job:string}}>(`/api/precision/full/${project.id}/compare-job`,'POST',{revision:latest.project.revision,job:job.id});
      await showPreview(candidate);
    }catch(e){
      if(!/Method Not Allowed|HTTP (404|405)/.test((e as Error).message))throw e;
      const record=await readApi<{revision:number;state:{assets:ImageChoice[]}}>(`/api/workspaces/${workspace}`);
      if(!editing||record.state.assets.find(a=>a.id===editing.object)?.file!==editing.source)throw Error('原素材已有变化，请重新读取后比较。');
      parent.postMessage({type:'miniclaw.director.compare-retained',workspace,target:editing,basis:record.revision,candidate:{project:project.id,revision:latest.project.revision,job}},location.origin);
    }
  }
  async function compare() {
    if(!project||!editing)return;
    setBusy(true);setError('');
    try {
      const latest=await loadProject(project.id);
      const output=await writeApi<{project:string;revision:number;output:string;output_id:string}>(`/api/precision/full/${project.id}/preview`,'POST',{revision:latest.project.revision});
      const record=await readApi<{revision:number;state:{assets:{id:string;file:string}[]}}>(`/api/workspaces/${workspace}`);
      if(record.state.assets.find(a=>a.id===editing.object)?.file!==editing.source)throw Error('原素材已有变化，请重新读取后比较。');
      parent.postMessage({type:'miniclaw.director.compare',workspace,candidate:output,target:editing,basis:record.revision},location.origin);
    }catch(e){setError((e as Error).message);throw e;}finally{setBusy(false);}
  }
  async function adoptSuggestion(){
    if(!basis||!optimizationReply||!suggestion)return;
    const captured=basis;
    const record=await readApi<{revision:number;state:{shots:{id:string;prompt:string}[];assets:ImageChoice[]}}>(`/api/workspaces/${workspace}`);
    if(captured.task){
      const asset=record.state.assets.find(a=>a.id===captured.target);
      if(!asset||asset.file!==captured.file)throw Error('图片已变化，请重新选中后优化。');
      if((asset.imagePrompt||'')!==captured.prompt&&(asset.imagePrompt||'')!==suggestion)throw Error('图片提示词已修改，建议仍保留，请重新优化后比较。');
      await adoptImagePrompt(workspace,{target:captured.target,prompt:captured.prompt,file:captured.file!,task:captured.task},suggestion);
    }else{
      if(record.state.shots.find(s=>s.id===captured.target)?.prompt!==captured.prompt)throw Error('镜头提示词已修改，建议仍保留，请重新优化后比较。');
      await adoptDirectorPrompt(workspace,captured,chat.storedId,Number(optimizationReply.id.slice(4)));
    }
    localStorage.removeItem(optimizationKey(target,intent));setBasis(undefined);setRequests(v=>v+1);
    parent.postMessage({type:'miniclaw.director.return',workspace},location.origin);
  }
  return <div className={`studio-director${optimizing?' director-optimization':''}${suggestion&&!refining?' has-suggestion':''}`}>
    <section className="director-context" aria-label="当前导演上下文">{(selectedShot?.inputs[0]||selectedAsset)?.file&&<img src={thumbnail((selectedShot?.inputs[0]||selectedAsset)!.file)} alt={selectedShot?'镜头输入图片':'当前图片'}/>}<div><strong title={objectName}>{objectName}</strong><small>{targetReading?'正在读取…':resultId?'视频结果':selectedShot?'镜头':target?'图片':'项目'}</small></div><button className="director-context-toggle" aria-expanded={contextOpen} onClick={()=>setContextOpen(v=>!v)}>上下文 {contextOpen?'⌃':'⌄'}</button></section>
    {selectedShot&&<nav className="director-modes" aria-label="导演任务"><button aria-pressed={optimizing} disabled={blocked} onClick={()=>{setMode('shot');setIntent('optimize');}}>优化提示词</button><button aria-pressed={mode==='shot'&&!optimizing} disabled={blocked} onClick={()=>{setMode('shot');setIntent('discuss');}}>讨论</button><button aria-pressed={mode==='image'} disabled={blocked} onClick={()=>{setMode('image');setIntent('discuss');}}>修图</button></nav>}
    {mode==='image'&&choices.length>1&&<section className="director-image-choice" aria-label="选择要修改的参考图"><strong>选择图片</strong><div>{choices.map((a,i)=><button key={a.id} title={a.name} aria-label={`选择图片 ${a.name}`} aria-pressed={editing?.object===a.id} disabled={blocked} onClick={()=>{localStorage.setItem(`studio-director-image:${workspace}:${target}`,a.id);setImage({target,id:a.id});}}><img src={thumbnail(a.file)} alt=""/><span>{i+1}. {a.name}</span></button>)}</div></section>}
    {mode==='image'&&editing&&<div className="director-quick-actions"><button disabled={blocked} onClick={()=>void flip('horizontal')}><Icon name="flip" size={16}/>水平翻转</button><button disabled={blocked} onClick={()=>void compare().catch(()=>{})}>比较修改</button></div>}
    {localResult&&<p className="director-local-result" role="status">{localResult}{mode==='image'?' · 在对比中采用后更新画布':''}</p>}
    {mode==='image'&&readyJob&&<div className="director-ready-result"><span>新候选已生成 · 尚未采用</span><button disabled={blocked} onClick={()=>void run(()=>compareJob(readyJob))}>比较新候选</button></div>}
    <main ref={conversation} aria-label={optimizing?'提示词优化':'导演项目对话'}>
      {contextOpen&&<section className="director-context-details"><strong>图片输入</strong><div className="director-inputs">{selectedShot?.inputs.map(a=><figure key={a.id}><img src={thumbnail(a.file)} alt=""/><figcaption>{a.name}</figcaption></figure>)}</div>{!optimizing&&selectedShot&&<details><summary>当前提示词</summary><p>{selectedShot.prompt||'尚未填写提示词'}</p></details>}{resultId&&<p>再次生成使用此镜头的图片输入。</p>}{contextNode&&<small>对象编号 {contextNode.slice(-6)}</small>}</section>}
      {optimizing?<>
        {suggestion&&basis?<section className="prompt-comparison" key={optimizationReply?.id} aria-label="优化提示词比较"><div className="prompt-result-heading"><h2>优化建议</h2><span>尚未采用</span></div>{changeSummary&&<p className="prompt-change-summary">{changeSummary}</p>}<div className="prompt-compare-tabs" aria-label="提示词比较"><button type="button" aria-pressed={!showOriginal} onClick={()=>{setShowOriginal(false);if(conversation.current)conversation.current.scrollTop=0;}}>新提示词</button><button type="button" aria-pressed={showOriginal} onClick={()=>{setShowOriginal(true);if(conversation.current)conversation.current.scrollTop=0;}}>原提示词</button></div><p className="prompt-compare-body" key={String(showOriginal)}>{showOriginal?basis.prompt:suggestion}</p>{explanation&&explanation!==changeSummary&&<details><summary>完整修改说明</summary><p>{explanation}</p></details>}</section>:<details className="director-current-prompt"><summary>查看当前提示词</summary><p>{imageOptimizing?selectedAsset?.imagePrompt||'尚未填写提示词':selectedShot?.prompt||'尚未填写提示词'}</p></details>}
        {(chat.running||busy&&!suggestion)&&<p className="director-progress" role="status">正在优化…</p>}
        {optimizationReply&&!suggestion&&!chat.running&&<Message item={optimizationReply} owner={chat.storedId} onReuse={setDraft}/>}
      </>:<>{!chat.items.length&&<p className="director-intro">告诉我想怎么改。</p>}{chat.items.map(item=><Message key={item.id} item={item} owner={chat.storedId} onReuse={setDraft} onSaveIdea={async id=>{await saveStudioIdea(workspace,chat.storedId,id);parent.postMessage({type:'miniclaw.director.adopted',workspace},location.origin);}}/>)}</>}
      {project&&mode==='image'&&<ImagePlanPanel project={project} busy={blocked} activeJob={jobs.some(j=>['queued','running'].includes(j.state))} canPlan={canPlan} hasTarget={!!editing} targetLayerId={editing?.layer} onSend={send} onRun={run} onRefresh={refresh} onPreview={p=>showPreview({project:project.id,revision:project.revision,...p})} compact/>}
      <div ref={results} hidden={mode!=='image'}>{jobs.map(job=>{const used=!!job.output&&project?.document.layers.some(l=>l.id===job.layer_id&&l.asset_id===job.output!.id);return <section className="director-job" key={job.id}><strong>{used?'已用于当前工作图':({queued:'等待修图',running:'正在修图',succeeded:'候选已生成，等待比较',failed:'修图未完成',canceled:'已停止接收'} as const)[job.state]}</strong><p>{job.model||'历史任务未记录模型'} · {job.audit?.estimate_cny==null?'费用待核对':`参考 ¥${job.audit.estimate_cny.toFixed(2)}`}</p>{job.error&&<p>{job.error}</p>}{job.output&&!used&&<button disabled={blocked} onClick={()=>void run(()=>compareJob(job))}>{project?.revision!==job.revision?'与当前工作图比较':'比较这张新候选'}</button>}{job.state==='failed'&&<p>要求、原图和已成功步骤已保留。先核对任务状态，再明确决定是否新生成；不会自动重发。</p>}</section>;})}</div>
      {project&&mode==='image'&&editing&&<div className="director-worktools" aria-label="工作图操作"><button disabled={blocked} onClick={()=>parent.postMessage({type:'miniclaw.director.precision',workspace,target:editing},location.origin)}><Icon name="brush" size={16}/>精细修图</button></div>}
      <div ref={bottom}/>
    </main>
    {(error||chat.error||staleSuggestion)&&<div className="director-error" role="alert">{error||chat.error||'当前提示词已有更新，请重新优化。'}{(!suggestion||staleSuggestion||chat.connection!=='open')&&<button onClick={()=>{if(selectedImage){localStorage.removeItem(`studio-director-image:${workspace}:${target}`);setImage({target,id:''});}setRequests(v=>v+1);if(chat.connection!=='open')void controller.connect();}}>{chat.connection!=='open'?'重新连接':'重新读取'}</button>}</div>}
    <form onSubmit={e=>{e.preventDefault();void send();}}>
      {optimizing&&<p className="director-model-note">{chat.info.model||'当前聊天模型'} · 仅优化文字，采用后再生成</p>}
      {pendingTarget&&<p>草稿仍针对“{label}”。<button type="button" disabled={chat.running||busy||localFlight.current} onClick={()=>{parent.postMessage({type:'miniclaw.director.context',workspace,request:pendingTarget.request,target:pendingTarget.target,label:pendingTarget.label,pending:false},location.origin);setTarget(pendingTarget.target);setLabel(pendingTarget.label);setIntent(pendingTarget.intent||'discuss');setContextNode(pendingTarget.node||'');setResultId(pendingTarget.result||'');setBasis(undefined);setPendingTarget(undefined);}}>{draft.trim()?'将草稿改为':'切换到'}“{pendingTarget.label}”</button></p>}
      {optimizing&&suggestion&&!refining?<div className="director-adopt-actions"><button type="button" disabled={blocked} onClick={()=>setRefining(true)}>继续调整</button><button className="director-adopt" type="button" disabled={blocked||staleSuggestion} onClick={()=>void run(adoptSuggestion)}>{busy?'正在采用…':staleSuggestion?'建议需重新优化':error?'重试采用建议':'采用建议并返回'}</button></div>:<>
        <div className="director-composer-label"><label htmlFor="director-goal">{refining?'进一步调整':mode==='shot'?'修改要求':'图片想怎么改？'}</label>{draft&&<button className="director-clear" type="button" disabled={chat.running} onClick={()=>setDraft('')}>清空</button>}</div>{refining&&basis?.goal&&<p className="director-previous-goal">当前目标：{basis.goal}</p>}<textarea id="director-goal" value={draft} onChange={e=>setDraft(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();void send();}}} placeholder={mode==='shot'?'例如：让泥膜持续流动，包装保持不动':'例如：保留产品，把背景压暗一点'} disabled={chat.running}/>
        <div>{suggestion&&refining?<button type="button" className="director-clear" disabled={blocked} onClick={()=>setRefining(false)}>返回建议</button>:<a href={`/?workspace=${workspace}&target=${encodeURIComponent(target)}`} target="_top">完整对话</a>}<button type="submit" aria-label={optimizing?'优化并预览提示词':'发送修改要求'} disabled={blocked||(!draft.trim()&&!optimizing)}>{optimizing?<span>{chat.running?'正在优化…':'优化提示词'}</span>:<Icon name={chat.running?'stop':'arrow'} size={18}/>}</button></div>
      </>}
    </form>

  </div>;
}
