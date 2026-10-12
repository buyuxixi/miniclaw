import {Fragment, useEffect, useRef, useState} from 'react';
import type {ChatController} from './chat-controller';
import {useChat} from './use-chat';
import {readApi, writeApi} from './management-api';
import {ImagePlanPanel, type PlanPreview, type ImagePlan} from './ImagePlanPanel';
import {Message} from './Message';
import {ClarificationCards,hasPendingClarification} from './ClarificationCards';
import {saveStudioIdea} from './studio-api';
import {exportBlob, loadProject, type CanvasJob, type Project} from './canvas-api';
import './studio-director.css';
import {Icon} from './Icon';
import {directImageAction, flipDirectorImage, singleShotPrompt, adoptDirectorPrompt, singleImagePrompt, adoptImagePrompt} from './director-actions';
import type {DirectorContext} from './turn-display';
import {plansByMessage,fullImagePlanPrompt} from './director-conversation';
import {useDirectorImages} from './use-director-images';
import {AttachmentCard} from './AttachmentCard';
import {StudioReferences,type StudioReference} from './StudioReferences';

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
function draftKey(target:string,intent:string){return intent.startsWith('optimize')?`studio-director-scoped-draft:${workspace}:${target}:${intent}`:`studio-director-chat-draft:${workspace}`;}
function savedDraft(target=initialTarget,intent=query.get('intent')||'discuss'){try{const current=localStorage.getItem(draftKey(target,intent));const r=JSON.parse(current||localStorage.getItem(`studio-director-scoped-draft:${workspace}:${target}:chat`)||localStorage.getItem(`studio-director-scoped-draft:${workspace}:${target}`)||localStorage.getItem(`studio-director-scoped-draft:${workspace}`)||'null');return (current&&!intent.startsWith('optimize')||r?.target===target)&&typeof r?.text==='string'?r.text:'';}catch{return '';}}
const referenceKey=`studio-director-chat-references:${workspace}`;
const focusKey=`studio-director-chat-focus:${workspace}`;
function savedReferences(){try{const ids=JSON.parse(localStorage.getItem(referenceKey)||'null');if(Array.isArray(ids)&&ids.every(i=>typeof i==='string'))return [...new Set(ids)].slice(0,6);}catch{}return !query.get('intent')?.startsWith('optimize')&&initialTarget?[initialTarget]:[];}
export function StudioDirector({controller}:{controller:ChatController}) {
  const chat=useChat(controller);
  const [optimizationTarget,setTarget]=useState(initialTarget), [label,setLabel]=useState(query.get('label') || '当前项目');
  const [intent,setIntent]=useState(query.get('intent')||'discuss');
  const [references,setReferences]=useState<string[]>(savedReferences);
  const [contextTarget,setContextTarget]=useState(()=>localStorage.getItem(focusKey)??(!query.get('intent')?.startsWith('optimize')?initialTarget:''));
  const target=intent.startsWith('optimize')?optimizationTarget:references.includes(contextTarget)?contextTarget:'';
  const [draft,setDraft]=useState(()=>savedDraft());
  const [referenceObjects,setReferenceObjects]=useState<StudioReference[]>([]);
  const referenceItems=references.map(id=>({...referenceObjects.find(o=>o.id===id)||{id,name:'已删除或暂时无法读取的引用',kind:'note' as const,images:[]},current:id===contextTarget}));
  const referenceScope=useRef({references,intent,contextTarget});referenceScope.current={references,intent,contextTarget};
  useEffect(()=>{try{localStorage.setItem(referenceKey,JSON.stringify(references));}catch{}},[references]);
  useEffect(()=>{try{localStorage.setItem(focusKey,contextTarget);}catch{}},[contextTarget]);
  const [project,setProject]=useState<Project>(), [editing,setEditing]=useState<EditingTarget>();
  const [choices,setChoices]=useState<ImageChoice[]>([]);
  const [image,setImage]=useState(()=>({target:initialTarget,id:localStorage.getItem(`studio-director-image:${workspace}:${initialTarget}`)||''}));
  const selectedImage=image.target===target?image.id:'';
  const [jobs,setJobs]=useState<CanvasJob[]>([]);
  const [plans,setPlans]=useState<ImagePlan[]>([]);
  const planRead=useRef(0);
  const [busy,setBusy]=useState(false), [error,setError]=useState('');
  const [localResult,setLocalResult]=useState('');
  const localFlight=useRef(false);
  const sendFlight=useRef(false);
  const [requests,setRequests]=useState(0);
  const [reading,setReading]=useState(false),[pendingTarget,setPendingTarget]=useState<TargetRequest>();
  const modeTarget=useRef('');
  const [targetReading,setTargetReading]=useState(true),[basis,setBasis]=useState<ShotBasis|undefined>(()=>savedOptimization(initialTarget,query.get('intent')||'discuss'));
  useEffect(()=>{setBasis(savedOptimization(target,intent));},[target,intent]);
  const [contextNode,setContextNode]=useState(''),[resultId,setResultId]=useState('');
  const [contextOpen,setContextOpen]=useState(false),[refining,setRefining]=useState(false),[showOriginal,setShowOriginal]=useState(false);
  const [invalidBasis,setInvalidBasis]=useState(false);
  const conversation=useRef<HTMLElement>(null);
  const followLatest=useRef(true);
  const [following,setFollowing]=useState(true);
  function showLatest(){followLatest.current=true;setFollowing(true);if(conversation.current)conversation.current.scrollTop=conversation.current.scrollHeight;}
  const [selectedAsset,setSelectedAsset]=useState<ImageChoice>();
  const [mode,setMode]=useState<'image'|'shot'>('image'),[selectedShot,setSelectedShot]=useState<{id:string;name:string;prompt:string;inputs:ImageChoice[]}>();
  const feedback=useDirectorImages(chat.storedId,workspace,intent.startsWith('optimize')?`optimize:${target}:${intent}`:'chat',chat.sessionId,chat.info.model,busy||reading||targetReading||chat.busy||chat.running||chat.connection!=='open',!intent.startsWith('optimize')&&referenceItems.some(r=>r.images.length>0),initialTarget);
  useEffect(()=>{let canceled=false;setTargetReading(true);setSelectedShot(undefined);setSelectedAsset(undefined);void readApi<{state:{shots:{id:string;name:string;prompt:string;mode:string;first:string;refs:string[]}[];assets:ImageChoice[];notes?:{id:string;title:string;text?:string}[]}}>(`/api/workspaces/${workspace}`).then(r=>{if(!canceled){setReferenceObjects([...r.state.assets.map(a=>({id:a.id,name:a.name,kind:'image' as const,images:[a]})),...r.state.shots.map(s=>({id:s.id,name:s.name,kind:'shot' as const,text:s.prompt,images:(s.mode==='first'?[s.first]:s.refs).map(id=>r.state.assets.find(a=>a.id===id)).filter((a):a is ImageChoice=>!!a)})),...(r.state.notes||[]).map(n=>({id:n.id,name:n.title,kind:'note' as const,text:n.text,images:[]}))]);const shot=r.state.shots.find(s=>s.id===target);setSelectedAsset(r.state.assets.find(a=>a.id===target));setSelectedShot(shot?{...shot,inputs:(shot.mode==='first'?[shot.first]:shot.refs).map(id=>r.state.assets.find(a=>a.id===id)).filter((a):a is ImageChoice=>!!a)}:undefined);if(modeTarget.current!==target){setMode(shot?'shot':'image');modeTarget.current=target;}};}).catch(e=>{if(!canceled)setError(e.message);}).finally(()=>{if(!canceled)setTargetReading(false);});return()=>{canceled=true;};},[target,requests]);
  const serial=useRef(0), scope=useRef({target,draft,label,intent});
  scope.current={target,draft,label,intent};
  useEffect(()=>{setChoices([]);setLocalResult('');setContextOpen(false);setRefining(false);setShowOriginal(false);setInvalidBasis(false);},[target,selectedImage]);
  useEffect(()=>{controller.workspace={id:workspace,target,...(!intent.startsWith('optimize')?{references}: {})};},[controller,target,references,intent]);
  useEffect(()=>{
    if(!workspace||parent===window)return;
    let activeTurn=false;
    // Gateway events describe fresh execution; restored transcript items do not.
    // The parent checks the project revision before reporting an actual change.
    const stopEvents=controller.client.onAny(event=>{
      if(event.replayed||event.session_id!==controller.state.sessionId||controller.connection!=='open')return;
      if(event.type==='message.start'||event.type==='tool.start'){activeTurn=true;return;}
      if(event.type!=='tool.complete'&&event.type!=='message.complete'&&!(event.type==='error'&&activeTurn))return;
      parent.postMessage({type:'miniclaw.director.changed',workspace},location.origin);
      if(event.type!=='tool.complete')activeTurn=false;
    });
    const stopState=controller.client.onState(state=>{if(state==='closed'||state==='error')activeTurn=false;});
    return()=>{stopEvents();stopState();};
  },[controller]);
  useEffect(()=>{try{localStorage.setItem(draftKey(target,intent),JSON.stringify({target,label,text:draft}));}catch{}},[workspace,target,label,draft,intent]);
  useEffect(()=>{if(!intent.startsWith('optimize')&&followLatest.current&&conversation.current)conversation.current.scrollTop=conversation.current.scrollHeight;},[chat.items.length,chat.items.at(-1)?.text,mode,intent,jobs.map(j=>j.id+':'+j.state).join('|'),plans.map(p=>p.id+':'+p.state).join('|')]);
  useEffect(()=>{
    const listener=(e:MessageEvent)=>{if(e.source!==parent || e.origin!==location.origin || e.data?.workspace!==workspace)return;
      if(e.data.type==='miniclaw.director.image'&&e.data.target===scope.current.target&&typeof e.data.asset==='string'){
        localStorage.setItem(`studio-director-image:${workspace}:${scope.current.target}`,e.data.asset);
        setImage({target:scope.current.target,id:e.data.asset});return;
      }
      if(e.data.type==='miniclaw.director.refresh'){setRequests(v=>v+1);return;}
      if(e.data.type==='miniclaw.director.reference'&&typeof e.data.target==='string'){
        if(addReference(e.data.target))setRequests(v=>v+1);return;
      }
      if(e.data.type!=='miniclaw.director.target'||typeof e.data.target!=='string')return;
      const next=e.data as TargetRequest;
      if(!(next.intent||'discuss').startsWith('optimize')&&!scope.current.intent.startsWith('optimize')){
        addReference(next.target);setRequests(v=>v+1);
        parent.postMessage({type:'miniclaw.director.context',workspace,request:next.request,target:next.target,label:next.label,intent:'discuss',pending:false},location.origin);return;
      }
      const changing=next.target!==scope.current.target||(next.intent||'discuss')!==scope.current.intent;
      const movingOptimization=scope.current.intent.startsWith('optimize')&&(next.intent||'discuss').startsWith('optimize')&&next.target!==scope.current.target;
      if(changing&&(localFlight.current||sendFlight.current||feedback.hasUpload()||controller.state.running||movingOptimization&&(feedback.hasPending()||scope.current.draft.trim()))){setPendingTarget(next);parent.postMessage({type:'miniclaw.director.context',workspace,request:next.request,target:scope.current.target,label:scope.current.label,intent:scope.current.intent,pending:true},location.origin);return;}
      parent.postMessage({type:'miniclaw.director.context',workspace,request:next.request,target:next.target,label:next.label,intent:next.intent||'discuss',pending:false},location.origin);
      if(changing)setDraft(savedDraft(next.target,next.intent||'discuss'));
      if(!(next.intent||'discuss').startsWith('optimize'))addReference(next.target);
      setIntent(next.intent||'discuss');setContextNode(next.node||'');setResultId(next.result||'');
      setPendingTarget(undefined);
      setTarget(e.data.target || '');setLabel(e.data.label || '当前项目');};
    window.addEventListener('message',listener);parent.postMessage({type:'miniclaw.director.ready',workspace},location.origin);return()=>window.removeEventListener('message',listener);
  },[controller]);
  function addReference(id:string){
    if(!id)return false;
    const context=referenceScope.current;
    if(context.references.includes(id)&&context.references.includes(context.contextTarget))return true;
    if(sendFlight.current||localFlight.current||controller.state.running){setError('当前任务执行中，完成后再加入引用。');return false;}
    if(!context.references.includes(id)&&context.references.length>=6){setError('最多引用6项画布内容，请先移除一项。');return false;}
    if(!context.references.includes(context.contextTarget)){
      setContextTarget(id);referenceScope.current={...context,contextTarget:id};
    }
    if(context.references.includes(id))return true;
    referenceScope.current={...referenceScope.current,references:[...context.references,id]};
    setReferences(rows=>rows.includes(id)?rows:rows.length<6?[...rows,id]:rows);
    return true;
  }
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
  async function refreshPlans(){if(!project)return;const ticket=++planRead.current;const rows=await readApi<ImagePlan[]>(`/api/miniclaw/canvas/projects/${project.id}/plans`);if(ticket===planRead.current)setPlans(rows);}
  useEffect(()=>{setPlans([]);if(!project||mode!=='image')return;void refreshPlans().catch(e=>setError(e.message));const timer=setInterval(()=>void refreshPlans().catch(e=>setError(e.message)),2500);return()=>{clearInterval(timer);++planRead.current;};},[project?.id,project?.revision,mode]);
  const tools=Object.values(chat.info.tools||{}).flat();
  const canPlan=tools.includes('miniclaw_canvas_propose');
  const blocked=busy||reading||targetReading||chat.busy||chat.running||feedback.uploading||chat.connection!=='open';
  const waiting=hasPendingClarification(chat.clarifications);
  const sendBlocked=waiting?busy||chat.busy||chat.running||feedback.uploading||chat.connection!=='open':blocked;
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
  const visiblePlans=plans.filter(p=>p.project===project?.id&&p.layer_id===editing?.layer);
  const messagePlans=plansByMessage(chat.items,visiblePlans);
  const attachedPlans=new Set([...messagePlans.values()].flat().map(p=>p.id));
  const oldPlans=visiblePlans.filter(p=>!attachedPlans.has(p.id));
  function editDraft(text:string){setDraft(text);document.getElementById('director-goal')?.focus();}
  function openPrecision(){if(editing)parent.postMessage({type:'miniclaw.director.precision',workspace,target:editing},location.origin);}
  async function fillPlan(plan:ImagePlan){
    const prompt=fullImagePlanPrompt(plan);
    if(!selectedAsset||!editing||plan.project!==editing.project||plan.layer_id!==editing.layer||!prompt)throw Error('请在精细修图中继续处理此方案。');
    const current=await readApi<{state:{assets:ImageChoice[]}}>(`/api/workspaces/${workspace}`);
    if(scope.current.target!==target)throw Error('选择的图片已变化，请在当前图片上重新确认方案。');
    const asset=current.state.assets.find(a=>a.id===target);
    if(!asset||asset.file!==selectedAsset.file||(asset.imagePrompt||'')!==(selectedAsset.imagePrompt||''))throw Error('图片或提示词已变化，请重新读取后回填。');
    await adoptImagePrompt(workspace,{target,prompt:asset.imagePrompt||'',file:asset.file,task:'image-edit'},prompt);
    if(scope.current.target!==target)return;
    parent.postMessage({type:'miniclaw.director.return',workspace,target,task:'image-edit'},location.origin);
  }
  function planPanel(rows:ImagePlan[]){return project&&rows.length>0?<ImagePlanPanel project={project} plans={rows} onPlansRefresh={refreshPlans} busy={blocked} activeJob={jobs.some(j=>['queued','running'].includes(j.state))} canPlan={canPlan} hasTarget={!!editing} targetLayerId={editing?.layer} onSend={async text=>{await send(text);}} onRun={run} onRefresh={refresh} onPreview={p=>showPreview({project:project.id,revision:project.revision,...p})} onFillPrompt={fillPlan} onPrecision={openPrecision} onDraft={editDraft} compact/>:null;}
  async function send(goal=draft.trim()||(!waiting&&optimizing?'优化当前提示词，检查相互冲突的要求，清楚描述需要变化的部分，保留产品包装与标识。':'')):Promise<boolean> {
    if(sendBlocked||(!goal.trim()&&!feedback.items.length))return false;
    if(waiting&&feedback.items.length){setError('任务正在等待补充。请先发送文字说明，或在问题卡选择“修改需求”后再补附件；附件草稿已保留。');return false;}
    if(!waiting&&!feedback.canSend){setError(feedback.status);return false;}
    const sentImages=[...feedback.items],sentKey=feedback.key,sentDraft=draft,sentTarget=target,sentOwner=chat.storedId;
    const direct=!waiting&&mode==='image'&&!!selectedAsset&&!optimizing&&!sentImages.length?directImageAction(goal):null;
    if(direct){await flip(direct);return false;}
    const previousBasis=basis,wasRefining=refining,wasInvalid=invalidBasis;
    sendFlight.current=true;setError('');setBusy(true);
    try {
      if(!waiting&&imageOptimizing&&!selectedAsset)throw Error('请选择要优化提示词的图片。');
      // The server owns one bounded decision per business task; no shadow call.
      const requestGoal=refining&&basis?.goal?`${basis.goal}；${goal}`:goal;
      const requestBasis:ShotBasis|undefined=!waiting&&imageOptimizing&&selectedAsset?{target,prompt:selectedAsset.imagePrompt||'',file:selectedAsset.file,task:imageTask,goal:requestGoal,known:chat.items.map(i=>i.id)}:!waiting&&optimizing&&selectedShot?{target,prompt:selectedShot.prompt,goal:requestGoal,known:chat.items.map(i=>i.id)}:undefined;
      const directorContext:DirectorContext|undefined=!waiting&&imageOptimizing&&selectedAsset?{task:imageTask}:!waiting&&optimizing&&selectedShot?{task:'video'}:undefined;
      if(directorContext&&refining&&suggestion){directorContext.prompt=suggestion;if(basis?.goal)directorContext.previous_goal=basis.goal;}
      if(requestBasis)setBasis(requestBasis);
      setInvalidBasis(false);
      setRefining(false);
      const skill=!waiting&&optimizing?'product-prompt-optimize':undefined;
      const canvasContext=!optimizing&&project&&editing&&canPlan?{project_id:project.id,revision:project.revision,layer_id:editing.layer,mode:'plan' as const}:undefined;
      const ok=waiting?await controller.send(goal,undefined,[]):directorContext?await controller.send(goal,skill,sentImages,canvasContext,undefined,directorContext):await controller.send(goal,skill,sentImages,canvasContext);
      if(ok){feedback.clearSent(sentImages,sentKey);if(scope.current.target===sentTarget&&controller.state.storedId===sentOwner)setDraft((v:string)=>v===sentDraft?'':v);showLatest();}else {setBasis(previousBasis);setRefining(wasRefining);setInvalidBasis(wasInvalid);setError(controller.state.error||(sentImages.length?'尚未发送，修改要求已保留，图片也已保留':'尚未发送，修改要求已保留'));}
      return ok;
    }catch(e){setBasis(previousBasis);setRefining(wasRefining);setInvalidBasis(wasInvalid);setError((e as Error).message);return false;}finally{sendFlight.current=false;setBusy(false);}
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
    {optimizing&&<section className="director-context" aria-label="当前项目上下文">{(selectedShot?.inputs[0]||selectedAsset)?.file&&<img src={thumbnail((selectedShot?.inputs[0]||selectedAsset)!.file)} alt={selectedShot?'镜头输入图片':'当前图片'}/>}<div><strong title={objectName}>{objectName}</strong><small>{targetReading?'正在读取…':resultId?'视频结果':selectedShot?'镜头':selectedAsset?'图片':target?'创意':'项目'}</small></div><button className="director-context-toggle" aria-expanded={contextOpen} onClick={()=>setContextOpen(v=>!v)}>上下文 {contextOpen?'⌃':'⌄'}</button></section>}

    {mode==='image'&&choices.length>1&&<section className="director-image-choice" aria-label="选择要修改的参考图"><strong>选择图片</strong><div>{choices.map((a,i)=><button key={a.id} title={a.name} aria-label={`选择图片 ${a.name}`} aria-pressed={editing?.object===a.id} disabled={blocked} onClick={()=>{localStorage.setItem(`studio-director-image:${workspace}:${target}`,a.id);setImage({target,id:a.id});}}><img src={thumbnail(a.file)} alt=""/><span>{i+1}. {a.name}</span></button>)}</div></section>}

    {localResult&&<p className="director-local-result" role="status">{localResult}{mode==='image'?' · 在对比中采用后更新画布':''}</p>}
    {mode==='image'&&readyJob&&<div className="director-ready-result"><span>新候选已生成 · 尚未采用</span><button disabled={blocked} onClick={()=>void run(()=>compareJob(readyJob))}>比较新候选</button></div>}
    <main ref={conversation} aria-label={optimizing?'提示词优化':'项目对话'} onScroll={e=>{if(optimizing)return;const pane=e.currentTarget;const near=pane.scrollHeight-pane.clientHeight-pane.scrollTop<100;followLatest.current=near;setFollowing(near);}}>
      {contextOpen&&<section className="director-context-details"><strong>图片输入</strong><div className="director-inputs">{selectedShot?.inputs.map(a=><figure key={a.id}><img src={thumbnail(a.file)} alt=""/><figcaption>{a.name}</figcaption></figure>)}</div>{!optimizing&&selectedShot&&<details><summary>当前提示词</summary><p>{selectedShot.prompt||'尚未填写提示词'}</p></details>}{resultId&&<p>再次生成使用此镜头的图片输入。</p>}{contextNode&&<small>对象编号 {contextNode.slice(-6)}</small>}{oldPlans.length>0&&<details><summary>历史修改方案</summary>{planPanel(oldPlans)}</details>}</section>}
      {optimizing?<>
        {suggestion&&basis?<section className="prompt-comparison" key={optimizationReply?.id} aria-label="优化提示词比较"><div className="prompt-result-heading"><h2>优化建议</h2><span>尚未采用</span></div>{changeSummary&&<p className="prompt-change-summary">{changeSummary}</p>}<div className="prompt-compare-tabs" aria-label="提示词比较"><button type="button" aria-pressed={!showOriginal} onClick={()=>{setShowOriginal(false);if(conversation.current)conversation.current.scrollTop=0;}}>新提示词</button><button type="button" aria-pressed={showOriginal} onClick={()=>{setShowOriginal(true);if(conversation.current)conversation.current.scrollTop=0;}}>原提示词</button></div><p className="prompt-compare-body" key={String(showOriginal)}>{showOriginal?basis.prompt:suggestion}</p>{explanation&&explanation!==changeSummary&&<details><summary>完整修改说明</summary><p>{explanation}</p></details>}</section>:<details className="director-current-prompt" open><summary>当前提示词</summary><p>{imageOptimizing?selectedAsset?.imagePrompt||'尚未填写提示词':selectedShot?.prompt||'尚未填写提示词'}</p></details>}
        {(chat.running||busy&&!suggestion)&&<p className="director-progress" role="status">正在优化…</p>}
        {optimizationReply&&!suggestion&&!chat.running&&<Message item={optimizationReply} owner={chat.storedId} onReuse={setDraft}/>}
      </>:<>{!chat.items.length&&<p className="director-intro">告诉我想怎么改。</p>}{chat.items.map((item,index)=>{const rows=messagePlans.get(item.id)||[];return <Fragment key={item.id}><Message item={item} owner={chat.storedId} onReuse={setDraft} onAnswer={send} answerDisabled={blocked||chat.items.slice(index+1).some(i=>i.kind==='user')} onSaveIdea={async id=>{await saveStudioIdea(workspace,chat.storedId,id);parent.postMessage({type:'miniclaw.director.adopted',workspace},location.origin);}}/>{mode==='image'&&planPanel(rows)}{mode==='image'&&jobs.filter(j=>rows.some(p=>p.job_id===j.id)).map(job=>{const used=!!job.output&&project?.document.layers.some(l=>l.id===job.layer_id&&l.asset_id===job.output!.id);return <section className="director-job" key={job.id}><strong>{used?'已用于当前工作图':({queued:'等待修图',running:'正在修图',succeeded:'候选已生成，等待比较',failed:'修图未完成',canceled:'已停止接收'} as const)[job.state]}</strong><p>{job.model||'历史任务未记录模型'} · {job.audit?.estimate_cny==null?'费用待核对':`参考 ¥${job.audit.estimate_cny.toFixed(2)}`}</p>{job.error&&<p>{job.error}</p>}{job.output&&!used&&<button disabled={blocked} onClick={()=>void run(()=>compareJob(job))}>比较这张候选</button>}</section>;})}</Fragment>;})}</>}
      {contextOpen&&mode==='image'&&jobs.length>0&&<details className="director-job-history"><summary>历史修图结果</summary>{jobs.map(job=>{const used=!!job.output&&project?.document.layers.some(l=>l.id===job.layer_id&&l.asset_id===job.output!.id);return <section className="director-job" key={job.id}><strong>{used?'已用于当前工作图':({queued:'等待修图',running:'正在修图',succeeded:'候选已生成，等待比较',failed:'修图未完成',canceled:'已停止接收'} as const)[job.state]}</strong><p>{job.model||'历史任务未记录模型'} · {job.audit?.estimate_cny==null?'费用待核对':`参考 ¥${job.audit.estimate_cny.toFixed(2)}`}</p>{job.error&&<p>{job.error}</p>}{job.output&&!used&&<button disabled={blocked} onClick={()=>void run(()=>compareJob(job))}>{project?.revision!==job.revision?'与当前工作图比较':'比较这张新候选'}</button>}{job.state==='failed'&&<p>要求、原图和已成功步骤已保留。先核对任务状态，再明确决定是否新生成；不会自动重发。</p>}</section>;})}</details>}
      {project&&mode==='image'&&editing&&<details className="director-worktools" aria-label="工作图操作"><summary>图片操作与修改记录</summary><button disabled={blocked} onClick={()=>void flip('horizontal')}><Icon name="flip" size={16}/>水平翻转</button><button disabled={blocked} onClick={()=>void compare().catch(()=>{})}>比较修改</button><button onClick={()=>setContextOpen(v=>!v)}>修改记录</button><button disabled={blocked} onClick={()=>parent.postMessage({type:'miniclaw.director.precision',workspace,target:editing},location.origin)}><Icon name="brush" size={16}/>精细修图</button></details>}
    </main>
    {!optimizing&&!following&&<div className="director-latest"><button type="button" onClick={showLatest}>↓ 回到最新消息</button></div>}
    <ClarificationCards controller={controller}/>
    {!chat.running&&chat.status&&<p className="director-progress" role="status">{chat.status}</p>}
    {(error||chat.error||staleSuggestion)&&<div className="director-error" role="alert">{error||chat.error||'当前提示词已有更新，请重新优化。'}{(!suggestion||staleSuggestion||chat.connection!=='open')&&<button onClick={()=>{if(selectedImage){localStorage.removeItem(`studio-director-image:${workspace}:${target}`);setImage({target,id:''});}setRequests(v=>v+1);if(chat.connection!=='open')void controller.connect();}}>{chat.connection!=='open'?'重新连接':'重新读取'}</button>}</div>}
    <form onSubmit={e=>{e.preventDefault();void send();}} onDragOver={e=>{if(e.dataTransfer.types.includes('Files'))e.preventDefault();}} onDrop={e=>{if(e.dataTransfer.files.length){e.preventDefault();void feedback.addFiles(Array.from(e.dataTransfer.files));}}}>
      {optimizing&&<p className="director-model-note">{chat.info.model||'当前聊天模型'} · 仅优化文字，采用后再生成</p>}
      {pendingTarget&&<p>{chat.running?'当前任务完成后再切换。':`草稿仍针对“${label}”。`}{feedback.items.length>0&&'图片会保留在原节点的草稿中。'}<button type="button" disabled={chat.running||busy||feedback.uploading||localFlight.current} onClick={()=>{parent.postMessage({type:'miniclaw.director.context',workspace,request:pendingTarget.request,target:pendingTarget.target,label:pendingTarget.label,intent:pendingTarget.intent||'discuss',pending:false},location.origin);if(pendingTarget.target===target||intent.startsWith('optimize')!==(pendingTarget.intent||'discuss').startsWith('optimize'))setDraft(savedDraft(pendingTarget.target,pendingTarget.intent||'discuss'));if(!(pendingTarget.intent||'discuss').startsWith('optimize'))addReference(pendingTarget.target);setTarget(pendingTarget.target);setLabel(pendingTarget.label);setIntent(pendingTarget.intent||'discuss');setContextNode(pendingTarget.node||'');setResultId(pendingTarget.result||'');setBasis(undefined);setPendingTarget(undefined);}}>{draft.trim()&&pendingTarget.target!==target?'将草稿改为':'切换到'}“{pendingTarget.label}”</button></p>}
      {optimizing&&suggestion&&!refining?<div className="director-adopt-actions"><button type="button" disabled={blocked} onClick={()=>setRefining(true)}>继续调整</button><button className="director-adopt" type="button" disabled={blocked||staleSuggestion} onClick={()=>void run(adoptSuggestion)}>{busy?'正在采用…':staleSuggestion?'建议需重新优化':error?'重试采用建议':'采用建议并返回'}</button></div>:<>
        {!optimizing&&(referenceItems.length>0?<div className="director-composer-references"><div className="director-reference-heading"><span>本轮引用 · {referenceItems.length}项</span><button type="button" disabled={blocked} onClick={()=>setReferences([])}>移除全部</button></div><StudioReferences items={referenceItems} disabled={blocked} onRemove={id=>setReferences(rows=>rows.filter(r=>r!==id))}/></div>:<p className="director-context-hint">点击画布内容带入引用，也可以上传或粘贴图片</p>)}
        <div className="director-composer-label"><label htmlFor="director-goal">{refining?'进一步调整':optimizing?'优化要求':'聊聊你的想法'}</label>{draft&&<button className="director-clear" type="button" disabled={chat.running} onClick={()=>setDraft('')}>清空</button>}</div>
        {feedback.items.length>0&&<div className="attachments director-attachments" aria-label="待发送的参考图片">{feedback.items.map(a=><AttachmentCard key={a.id} attachment={a} owner={chat.storedId} onRemove={blocked?undefined:()=>feedback.remove(a.id)}/>)}</div>}
        {refining&&basis?.goal&&<p className="director-previous-goal">当前目标：{basis.goal}</p>}<textarea id="director-goal" value={draft} onChange={e=>setDraft(e.target.value)} onPaste={e=>{const images=Array.from(e.clipboardData.files).filter(f=>f.type.startsWith('image/'));if(images.length){e.preventDefault();void feedback.addFiles(images);}}} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();void send();}}} placeholder={optimizing?'例如：动作更自然，保留原有妆容和包装':'说说你的想法或哪里不满意，也可以粘贴截图'} disabled={chat.running}/>
        <div className="director-composer-toolbar"><div className="director-composer-options"><input ref={feedback.file} type="file" hidden multiple accept=".png,.jpg,.jpeg,.webp" aria-label="选择反馈图片" onChange={e=>{void feedback.addFiles(Array.from(e.target.files||[]));e.target.value='';}}/><button type="button" className="director-attach" disabled={blocked||!chat.storedId} aria-label="上传参考图片" title="上传对比图或圈选截图；最多4张，每张5 MiB" onClick={()=>feedback.file.current?.click()}><Icon name="plus" size={16}/><span>图片</span></button>{suggestion&&refining&&<button type="button" className="director-clear" disabled={blocked} onClick={()=>setRefining(false)}>返回建议</button>}</div><button type="submit" aria-label={waiting?'发送要求':optimizing?'优化并预览提示词':'发送修改要求'} disabled={sendBlocked||!waiting&&!feedback.canSend||(!draft.trim()&&(waiting||!optimizing)&&!feedback.items.length)}>{!waiting&&optimizing?<span>{chat.running?'正在优化…':'优化提示词'}</span>:<Icon name={chat.running?'stop':'arrow'} size={18}/>}</button></div>
        {feedback.status&&<p className="director-upload-status" role="status">{feedback.status}</p>}{feedback.error&&<p className="director-upload-error" role="alert">{feedback.error}</p>}
      </>}
    </form>

  </div>;
}
