import {useEffect,useMemo,useRef,useState,type KeyboardEvent} from 'react';
import {Icon} from './Icon';
import {formatTraceDuration,hasTraceNumber,traceDuration,traceKindLabel,traceLane,traceReadingRows,traceRoundKey,traceSpan,traceStatusLabel,traceStepLabel,traceSummary,traceText,type TraceMode,type TraceStep} from './trace-view';
import './trace.css';

export type TraceViewProps={steps:TraceStep[];running?:boolean;loading?:boolean;error?:string;onRefresh?:()=>void;hasMore?:boolean;onLoadMore?:()=>void};
type StatusFilter='all'|'active'|'completed'|'failed'|'unknown';
const modes:{id:TraceMode;label:string}[]=[{id:'duration',label:'时长'},{id:'turns',label:'轮次'},{id:'calls',label:'调用'}];
const isStatus=(step:TraceStep,filter:StatusFilter)=>filter==='all'||filter==='active'&&['running','waiting'].includes(step.status)||filter==='completed'&&step.status==='completed'||filter==='failed'&&['failed','interrupted'].includes(step.status)||filter==='unknown'&&step.status==='unknown';
const clock=(value:number)=>new Date(value*1000).toLocaleTimeString('zh-CN',{hour12:false,hour:'2-digit',minute:'2-digit',second:'2-digit'});
const searchable=(step:TraceStep)=>[traceStepLabel(step),step.name,step.summary,step.content,step.provider,step.model,step.tool_name,step.error,step.request_id,step.operation_id,traceText(step.input),traceText(step.output),traceText(step.attributes)].join(' ').toLocaleLowerCase();
function briefPreview(value:unknown) {
  let text:string;
  try{text=typeof value==='string'?value:JSON.stringify(value);}catch{text=traceText(value);}
  text=text.trim().replace(/\s+/g,' ');
  const short=text.slice(0,220);
  return short+(short.length<text.length?'…':'');
}

function TraceDetails({step,requests=[],onRequest,onClose}: {step:TraceStep;requests?:TraceStep[];onRequest:(id:string)=>void;onClose:()=>void}) {
  const [tab,setTab]=useState<'overview'|'preview'|'raw'>('overview');
  const [drawer,setDrawer]=useState(()=>typeof window.matchMedia==='function'&&window.matchMedia('(max-width: 760px)').matches);
  const closeRef=useRef<HTMLButtonElement>(null);
  useEffect(()=>{setTab('overview');closeRef.current?.focus({preventScroll:true});},[step.id]);
  useEffect(()=>{
    if(typeof window.matchMedia!=='function')return;
    const media=window.matchMedia('(max-width: 760px)'),update=()=>setDrawer(media.matches);
    update();media.addEventListener('change',update);return ()=>media.removeEventListener('change',update);
  },[]);
  const measured=requests[0]||step;
  const metrics:[string,string][]=[['状态',traceStatusLabel[step.status]]];
  if(measured.provider)metrics.push(['服务',measured.provider]);
  if(measured.model)metrics.push(['模型',measured.model]);
  if(hasTraceNumber(measured.attempt))metrics.push(['第几次尝试',String(measured.attempt)]);
  metrics.push([requests.length?'模型耗时':'耗时',formatTraceDuration(traceDuration(measured))]);
  if(hasTraceNumber(measured.input_tokens))metrics.push(['输入 Token',measured.input_tokens.toLocaleString()]);
  if(hasTraceNumber(measured.output_tokens))metrics.push(['输出 Token',measured.output_tokens.toLocaleString()]);
  const identifiers:[string,string][]=[['来源',step.source==='history'?'对话记录':'执行记录']];
  if(step.kind==='tool'&&(step.tool_name||step.name==='miniclaw_document_query'))identifiers.push(['工具',step.tool_name||step.name]);
  if(hasTraceNumber(step.turn_index))identifiers.push(['轮次',String(step.turn_index)]);
  else if(!step.turn_id)identifiers.push(['轮次','未记录']);
  if(hasTraceNumber(step.call_index))identifiers.push(['调用序号',String(step.call_index)]);
  if(hasTraceNumber(step.started_at))identifiers.push(['开始时间',new Date(step.started_at*1000).toLocaleString('zh-CN',{hour12:false})]);
  if(step.task_id)identifiers.push(['任务 ID',step.task_id]);
  if(step.session_id)identifiers.push(['会话 ID',step.session_id]);
  if(step.request_id)identifiers.push(['请求 ID',step.request_id]);
  if(step.operation_id)identifiers.push(['操作 ID',step.operation_id]);
  if(typeof step.attributes?.call_id==='string')identifiers.push(['工具调用 ID',step.attributes.call_id]);
  const previews:[string,unknown][]=[['正文',step.content],['输入 / 参数',step.input],['输出 / 结果',step.output]];
  const toolPreviews=step.kind==='tool'?([['结果摘要',step.output],['参数摘要',step.input]] as [string,unknown][]).filter(([,value])=>value!==undefined&&value!==null&&value!==''):[];
  const detailTabs=[{id:'overview',label:'概述'},{id:'preview',label:'预览'},{id:'raw',label:'原始内容'}] as const;
  function navigateTab(event:KeyboardEvent<HTMLButtonElement>,index:number) {
    const next=event.key==='ArrowRight'?(index+1)%detailTabs.length:event.key==='ArrowLeft'?(index+detailTabs.length-1)%detailTabs.length:event.key==='Home'?0:event.key==='End'?detailTabs.length-1:-1;
    if(next<0)return;event.preventDefault();setTab(detailTabs[next].id);event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next]?.focus();
  }
  function containFocus(event:KeyboardEvent<HTMLElement>) {
    if(event.key==='Escape'){event.stopPropagation();onClose();return;}
    if(event.key!=='Tab'||!drawer)return;
    const controls=Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not([disabled]):not([tabindex="-1"]),[tabindex="0"]'));
    const first=controls[0],last=controls[controls.length-1];
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
  }
  return <aside className={`trace-details trace-details-${step.kind}`} role={drawer?'dialog':undefined} aria-modal={drawer||undefined} aria-label="步骤详情" onKeyDown={containFocus}>
    <header className="trace-details-heading"><span className={`trace-kind trace-kind-${step.kind}`}>{traceKindLabel[step.kind]}</span><strong>{traceStepLabel(step)}</strong><button type="button" ref={closeRef} aria-label="关闭步骤详情" onClick={onClose}><Icon name="close" size={15}/></button></header>
    <div className="trace-detail-tabs" role="tablist" aria-label="详情内容">{detailTabs.map((item,index)=><button key={item.id} type="button" role="tab" aria-selected={tab===item.id} tabIndex={tab===item.id?0:-1} aria-controls="trace-detail-panel" onKeyDown={event=>navigateTab(event,index)} onClick={()=>setTab(item.id)}>{item.label}</button>)}</div>
    <div className="trace-detail-body" id="trace-detail-panel" role="tabpanel" tabIndex={0}>
      {tab==='overview'&&<><dl className="trace-metrics">{metrics.map(([label,value])=><div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>{step.error&&<div className="trace-detail-error"><h3>失败原因</h3><p>{step.error}</p></div>}{!toolPreviews.length&&<section className="trace-content"><h3>{step.kind==='context'?'注入内容':'摘要'}</h3><p>{step.kind==='context'?step.content:traceSummary(step)}</p></section>}{toolPreviews.map(([label,value])=><section className="trace-content trace-tool-preview" key={label}><h3>{label}</h3><pre>{briefPreview(value)}</pre></section>)}{!!requests.length&&<section className="trace-content trace-related"><h3>对应模型请求</h3>{requests.map(request=><button type="button" key={request.id} onClick={()=>onRequest(request.id)}>查看模型请求 · {request.model||request.provider||request.name}</button>)}</section>}{!!identifiers.length&&<section className="trace-content trace-identifiers"><h3>关联记录</h3><dl className="trace-metrics">{identifiers.map(([label,value])=><div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl></section>}{!!step.attributes&&Object.keys(step.attributes).length>0&&<section className="trace-content"><h3>执行信息</h3><pre>{traceText(step.attributes)}</pre></section>}{step.source==='history'&&<p className="trace-history-note">历史对话未记录的耗时和用量显示为“未记录”。</p>}</>}
      {tab==='preview'&&<>{previews.filter(([,value])=>value!==undefined&&value!==null&&value!=='').map(([label,value])=><section className="trace-content" key={label}><h3>{label}</h3><pre>{traceText(value)}</pre></section>)}{!previews.some(([,value])=>value!==undefined&&value!==null&&value!=='')&&<p className="trace-detail-placeholder">此步骤没有保存正文或参数。</p>}</>}
      {tab==='raw'&&<pre className="trace-raw">{traceText(step)}</pre>}
    </div>
  </aside>;
}

export function TraceView({steps,running=false,loading=false,error='',onRefresh,hasMore=false,onLoadMore}:TraceViewProps) {
  const [query,setQuery]=useState(''),[filter,setFilter]=useState<StatusFilter>('all'),[selected,setSelected]=useState<string|null>(null),[mode,setMode]=useState<TraceMode>('duration'),[events,setEvents]=useState(false);
  const rowsRef=useRef<HTMLDivElement>(null);
  const span=useMemo(()=>traceSpan(steps),[steps]);
  const hasTurns=steps.some(step=>!!step.turn_id||hasTraceNumber(step.turn_index));
  const effectiveMode=mode==='duration'&&!span||mode==='turns'&&!hasTurns?'calls':mode;
  const reading=useMemo(()=>traceReadingRows(steps,events),[steps,events]);
  const filtered=useMemo(()=>{const search=query.trim().toLocaleLowerCase();return reading.filter(({step,requests})=>isStatus(step,filter)&&(!search||[step,...requests].some(item=>searchable(item).includes(search))));},[reading,query,filter]);
  const selectedRow=filtered.find(({step,requests})=>step.id===selected||requests.some(request=>request.id===selected));
  const selectedStep=selectedRow&&(selectedRow.step.id===selected?selectedRow.step:selectedRow.requests.find(request=>request.id===selected));
  const visibleIds=new Set(filtered.flatMap(({step,requests})=>[step.id,...requests.map(request=>request.id)]));
  const positions=useMemo(()=>{
    const turnGroups=new Map<string,TraceStep[]>();
    steps.forEach(step=>{const key=traceRoundKey(step);const group=turnGroups.get(key)||[];group.push(step);turnGroups.set(key,group);});
    const turnValues=[...turnGroups.keys()];
    const roundPositions=new Map<string,{turn:number;inner:number;count:number}>();
    turnValues.forEach((key,turn)=>{const group=turnGroups.get(key)!;group.forEach((step,inner)=>roundPositions.set(step.id,{turn,inner,count:group.length}));});
    return new Map(steps.map((step,index)=>{
      let left=index/Math.max(1,steps.length)*100,width=100/Math.max(1,steps.length);
      if(effectiveMode==='duration'&&span&&hasTraceNumber(step.started_at)){
        const total=Math.max(.001,span.end-span.start),end=hasTraceNumber(step.ended_at)?step.ended_at:step.started_at;
        left=(step.started_at-span.start)/total*100;width=Math.max(0,(end-step.started_at)/total*100);
        if(['input','context','assistant','recovery'].includes(step.kind))width=.3;
      }else if(effectiveMode==='turns'){
        const round=roundPositions.get(step.id)!;
        left=(round.turn+round.inner/round.count)/Math.max(1,turnValues.length)*100;width=100/Math.max(1,turnValues.length)/round.count;
      }
      return [step.id,{left:Math.min(99.7,Math.max(0,left)),width:Math.min(Math.max(.3,width),100-Math.min(99.7,Math.max(0,left)))}];
    }));
  },[steps,effectiveMode,span]);
  const modelCalls=steps.filter(step=>step.kind==='model').length;
  const toolCalls=steps.filter(step=>step.kind==='tool'&&step.attributes?.executed!==false&&(step.source==='history'||step.attributes?.executed===true||hasTraceNumber(step.started_at))).length;
  const recordedTokens=steps.filter(step=>step.kind==='model'&&(hasTraceNumber(step.input_tokens)||hasTraceNumber(step.output_tokens)));
  const tokens=recordedTokens.reduce((sum,step)=>sum+(step.input_tokens||0)+(step.output_tokens||0),0);
  function row(id:string|null) {const target=reading.find(({step,requests})=>step.id===id||requests.some(request=>request.id===id));return Array.from(rowsRef.current?.querySelectorAll<HTMLButtonElement>('.trace-row')||[]).find(button=>button.dataset.traceId===(target?.step.id||id));}
  function select(id:string) {setSelected(id);row(id)?.scrollIntoView?.({block:'nearest',behavior:'auto'});}
  function close() {const previous=selected;setSelected(null);requestAnimationFrame(()=>row(previous)?.focus({preventScroll:true}));}
  function navigate(event:KeyboardEvent<HTMLButtonElement>,index:number) {
    const next=event.key==='ArrowDown'?Math.min(filtered.length-1,index+1):event.key==='ArrowUp'?Math.max(0,index-1):event.key==='Home'?0:event.key==='End'?filtered.length-1:-1;
    if(next<0)return;event.preventDefault();rowsRef.current?.querySelectorAll<HTMLButtonElement>('.trace-row')[next]?.focus();
  }
  return <section className="trace-view" aria-label="Agent 执行轨迹">
    <div className="trace-toolbar"><div className="trace-modes" role="group" aria-label="时间线排列">{modes.map(item=><button key={item.id} type="button" aria-pressed={effectiveMode===item.id} disabled={item.id==='duration'&&!span||item.id==='turns'&&!hasTurns} title={item.id==='duration'&&!span?'此对话没有记录执行时间':item.id==='turns'&&!hasTurns?'此对话没有记录轮次':undefined} onClick={()=>setMode(item.id)}>{item.id==='duration'?<Icon name="history" size={13}/>:item.id==='turns'?<Icon name="layers" size={13}/>:<Icon name="activity" size={13}/>}<span>{item.label}</span></button>)}</div><div className="trace-reading-modes" role="group" aria-label="记录展示"><button type="button" aria-pressed={!events} onClick={()=>setEvents(false)}>对话顺序</button><button type="button" aria-pressed={events} onClick={()=>setEvents(true)}>全部事件</button></div><div className="trace-search"><Icon name="search" size={14}/><input type="search" aria-label="搜索轨迹" value={query} placeholder="搜索步骤、工具或错误" onChange={event=>setQuery(event.target.value)}/></div><select aria-label="筛选轨迹状态" value={filter} onChange={event=>setFilter(event.target.value as StatusFilter)}><option value="all">全部状态</option><option value="active">进行中 / 等待</option><option value="completed">已完成</option><option value="failed">失败 / 中断</option><option value="unknown">待核对</option></select></div>
    {error&&<div className="trace-fetch-error" role="alert"><span>轨迹暂时未更新：{error}</span>{onRefresh&&<button type="button" onClick={onRefresh} disabled={loading}><Icon name="refresh" size={13}/>重新加载</button>}</div>}
    {!!steps.length&&<div className="trace-timeline" aria-label="执行时间线"><div className="trace-ruler"><span>{effectiveMode==='duration'&&span?clock(span.start):effectiveMode==='turns'?'按轮次':'按执行顺序'}</span><span>{effectiveMode==='duration'&&span?formatTraceDuration(span.duration):`${steps.length} 个事件`}</span></div>{(['input','model','tool'] as const).map(lane=><div className="trace-lane" key={lane}><span className="trace-lane-label">{lane==='input'?'输入':traceKindLabel[lane]}</span><div className="trace-lane-bars">{steps.filter(step=>visibleIds.has(step.id)&&step.kind!=='task'&&traceLane(step)===lane&&(effectiveMode!=='duration'||hasTraceNumber(step.started_at))).map(step=>{const position=positions.get(step.id)!;return <button type="button" key={step.id} className={`trace-bar trace-bar-${step.kind} trace-bar-${step.status}${step.id===selected?' is-selected':''}`} style={{left:`${position.left}%`,width:`${position.width}%`}} aria-label={`${traceKindLabel[step.kind]}：${traceStepLabel(step)}，${traceStatusLabel[step.status]}`} aria-pressed={step.id===selected} title={`${traceStepLabel(step)} · ${traceStatusLabel[step.status]} · ${formatTraceDuration(traceDuration(step))}`} onClick={()=>select(step.id)}/>;})}</div></div>)}</div>}
    <div className={`trace-workspace${selectedStep?' has-detail':''}`}>
      <div className="trace-list" ref={rowsRef} aria-label="执行步骤">{!steps.length?<div className="trace-empty"><Icon name="activity" size={30}/><h2>{loading?'正在读取轨迹…':running?'正在记录执行过程':'还没有执行轨迹'}</h2><p>{running?'模型调用和工具执行会在这里实时出现。':'发送消息后，可以在这里查看模型、工具与恢复过程。'}</p></div>:!filtered.length?<div className="trace-empty trace-empty-filtered"><Icon name="search" size={24}/><h2>没有匹配的步骤</h2><button type="button" onClick={()=>{setQuery('');setFilter('all');}}>清除筛选</button></div>:<>{filtered.map(({step,requests,round,order},index)=>{
        const active=selectedRow?.step.id===step.id;
        const title=['input','assistant'].includes(step.kind)?step.kind==='assistant'&&!step.content?'调用工具':'':traceStepLabel(step);
        const timestamp=step.kind==='task'?step.ended_at:step.started_at;
        const measured=requests[0]||step;
        return <button type="button" key={step.id} className={`trace-row trace-row-${step.kind}${step.kind==='input'?' is-round-start':''}${active?' is-selected':''}`} data-trace-id={step.id} aria-pressed={active} aria-label={`${order}. ${traceKindLabel[step.kind]} ${traceStepLabel(step)}，${traceStatusLabel[step.status]}`} onClick={()=>select(step.id)} onKeyDown={event=>navigate(event,index)}>
          <span className="trace-row-order">{order}</span><span className={`trace-row-dot trace-state-${step.status}`} aria-hidden="true"/>
          <span className="trace-row-clock">{step.kind==='input'&&<span>第 {round} 轮</span>}<time title={hasTraceNumber(timestamp)?new Date(timestamp*1000).toLocaleString('zh-CN',{hour12:false}):'时间未记录'}>{hasTraceNumber(timestamp)?clock(timestamp):'—'}</time></span>
          <span className={`trace-kind trace-kind-${step.kind}`}>{traceKindLabel[step.kind]}</span>
          <span className="trace-row-text">{title&&<strong>{title}</strong>}<span>{traceSummary(step)!==title&&traceSummary(step)}</span></span>
          <span className={`trace-row-state trace-state-${step.status}`}>{traceStatusLabel[step.status]}</span>
          <span className="trace-row-time">{traceDuration(measured)===null?'—':formatTraceDuration(traceDuration(measured))}</span>
        </button>;
      })}{hasMore&&onLoadMore&&<button type="button" className="trace-load-more" disabled={loading} onClick={onLoadMore}>{loading?'正在读取…':'加载更早的步骤'}</button>}</> }</div>
      {selectedStep&&<TraceDetails key={selectedStep.id} step={selectedStep} requests={selectedStep.kind==='assistant'?selectedRow?.requests:[]} onRequest={select} onClose={close}/>}
    </div>
    <footer className="trace-footer"><span className="trace-live" role="status">{running&&<span className="trace-live-dot"/>}{loading?'正在同步…':running?'实时记录中':'执行记录'}</span>{!(loading&&!steps.length)&&<><span>{reading.length} 条记录 · {steps.length} 个事件 · 已记录模型 {modelCalls} 次 · 工具 {toolCalls} 次</span>{span&&<span>{formatTraceDuration(span.duration)}</span>}{!!recordedTokens.length&&<span>已记录 {tokens.toLocaleString()} Token</span>}{steps.some(step=>step.source==='history')&&<span className="trace-footer-history">历史步骤的耗时 / 用量未记录</span>}</>}</footer>
  </section>;
}
