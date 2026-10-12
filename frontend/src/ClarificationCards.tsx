import {useState} from 'react';
import {Icon} from './Icon';
import type {ClarificationRequest} from './types';
import type {ChatController} from './chat-controller';
import './clarification.css';

type Answers = Record<string,string|string[]>;
const answered = (value: string|string[]|undefined) => Array.isArray(value) ? value.length > 0 : !!value?.trim();
function read(key: string) {try {return localStorage.getItem(key);} catch {return null;}}
function save(key: string,value: string) {try {localStorage.setItem(key,value);} catch {/* The current answer remains usable. */}}

export function hasPendingClarification(requests?: ClarificationRequest[]) {
  return !!requests?.some(request=>request.status==='pending');
}

function QuestionPanel({request,controller}: {request: ClarificationRequest;controller: ChatController}) {
  const key = `miniclaw.clarification.${request.id}`;
  const [answers,setAnswers] = useState<Answers>(()=>{try {return JSON.parse(read(key)||'{}');} catch {return {};}});
  const [submission] = useState(()=>{const value=read(key+'.submission')||crypto.randomUUID();save(key+'.submission',value);return value;});
  const [page,setPage] = useState(0);
  const [other,setOther] = useState<Record<string,boolean>>({});
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  const blocked = busy || controller.state.running || controller.connection !== 'open';
  const q = request.questions[Math.min(page,request.questions.length-1)];
  if(!q)return null;
  const value=answers[q.id];
  const custom=typeof value==='string'&&!q.choices.includes(value)?value:'';
  const open=!q.choices.length||!!other[q.id]||!!custom;
  const complete=request.questions.every(question=>answered(answers[question.id]));
  const last=page===request.questions.length-1;
  function change(value: string|string[]) {const next={...answers,[q.id]:value};setAnswers(next);save(key,JSON.stringify(next));}
  async function run(action: ()=>Promise<void>) {
    if(blocked)return;setBusy(true);setError('');
    try {await action();} catch(e) {setError(e instanceof Error?e.message:String(e));await controller.refreshClarifications();}
    finally {setBusy(false);}
  }
  function proceed() {
    if(blocked||!answered(value))return;
    if(!last){setPage(page+1);return;}
    if(!complete){setPage(request.questions.findIndex(question=>!answered(answers[question.id])));return;}
    void run(()=>controller.answerClarification(request,answers,submission));
  }
  return <section className="clarification-panel" aria-label="任务澄清" onKeyDown={e=>{
    if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)&&!e.nativeEvent.isComposing){e.preventDefault();proceed();}
  }}>
    <header className="clarification-heading">
      <div><h2 id={`clarification-${request.id}-${q.id}`}>{q.question}</h2>{q.multi_select&&<span className="clarification-multiple">可多选</span>}</div>
      {request.questions.length>1&&<nav aria-label="澄清问题导航">
        <button type="button" aria-label="上一题" disabled={blocked||page===0} onClick={()=>setPage(page-1)}><Icon name="left" size={14}/></button>
        <span>{page+1} / {request.questions.length}</span>
        <button type="button" aria-label="下一题" disabled={blocked||last} onClick={()=>setPage(page+1)}><Icon name="right" size={14}/></button>
      </nav>}
    </header>
    <fieldset className="clarification-options" aria-labelledby={`clarification-${request.id}-${q.id}`} disabled={blocked}>
      {q.choices.map((choice,index)=>{
        const selected=Array.isArray(value)?value.includes(choice):!open&&value===choice;
        return <label key={choice} className={`clarification-option${selected?' is-selected':''}`}>
          <input type={q.multi_select?'checkbox':'radio'} name={`${request.id}-${q.id}`} checked={selected} onChange={e=>{
            setOther({...other,[q.id]:false});
            change(q.multi_select?(e.target.checked?[...(Array.isArray(value)?value:[]),choice]:(Array.isArray(value)?value:[]).filter(item=>item!==choice)):choice);
          }}/>
          <span className="clarification-index" aria-hidden="true">{index+1}</span><span>{choice}</span><Icon name="check" size={16}/>
        </label>;
      })}
      {!!q.choices.length&&<label className={`clarification-option${open?' is-selected':''}`}>
        <input type="radio" name={`${request.id}-${q.id}`} aria-label="其他，自己填写" checked={open} onChange={()=>{setOther({...other,[q.id]:true});change(custom);}}/>
        <span className="clarification-index" aria-hidden="true">{q.choices.length+1}</span><span>其他，自己填写</span><Icon name="edit" size={15}/>
      </label>}
      {open&&<textarea aria-label={`${q.question} 自由回答`} maxLength={2000} autoFocus={!!other[q.id]} value={custom} placeholder="写下你的回答…" onChange={e=>change(e.target.value)}/>}
    </fieldset>
    {error&&<p className="clarification-error" role="alert">{error}。回答已保留，可重试。</p>}
    <footer className="clarification-footer">
      <div><button type="button" disabled={blocked} onClick={()=>void run(()=>controller.cancelClarification(request,true))}>修改需求</button><button type="button" disabled={blocked} onClick={()=>void run(()=>controller.cancelClarification(request))}>取消任务</button></div>
      <button type="button" className="clarification-submit" disabled={blocked||!answered(value)} onClick={proceed}>
        {busy?'正在提交…':last?'回答并继续':'下一题'}{!busy&&<Icon name="right" size={14}/>}</button>
    </footer>
    <p className="composer-hint">也可在下方输入取消、修改需求或新话题。问题答案请在此提交。</p>
  </section>;
}

function RecoveryNotice({request,controller}: {request: ClarificationRequest;controller: ChatController}) {
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  const blocked=busy||controller.state.running||controller.connection!=='open';
  async function cancel(revise=false) {if(blocked)return;setBusy(true);try {await controller.cancelClarification(request,revise);} catch(e) {setError((e as Error).message);} finally {setBusy(false);}}
  const expired=request.status==='timed_out';
  return <section className="clarification-notice" aria-label="任务澄清">
    <div><Icon name={expired?'history':'activity'} size={16}/><p>{expired?'问题已过期，没有自动选择答案。':request.reason||'执行记录需要核对，已停止自动重试。'}</p></div>
    <div className="clarification-recovery-actions"><button disabled={blocked} onClick={()=>void cancel(true)}>{expired?'重新确认后继续':'修改需求'}</button><button disabled={blocked} onClick={()=>void cancel()}>取消任务</button></div>
    {error&&<p role="alert">{error}</p>}
  </section>;
}

export function ClarificationCards({controller}: {controller: ChatController}) {
  const requests=controller.state.clarifications||[];
  const pending=requests.find(request=>request.status==='pending');
  if(pending)return <QuestionPanel key={pending.id} request={pending} controller={controller}/>;
  const recovery=requests.find(request=>request.task_status==='reconciling'||request.status==='blocked'||request.status==='timed_out'&&request===requests[0]);
  if(recovery)return <RecoveryNotice key={recovery.id} request={recovery} controller={controller}/>;
  const queued=requests.find(request=>request.status==='answered'&&request.task_status==='resume_queued');
  if(queued)return <p className="clarification-resuming" role="status"><span className="loading-dot"/>回答已提交，正在继续…</p>;
  // Completed answers belong to the transcript, never a permanent composer card.
  return null;
}
