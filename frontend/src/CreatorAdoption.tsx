import { useEffect, useRef, useState } from 'react';
import { attachmentBlob } from './attachments';
import { creatorBase, getCreator, saveCreator, type CreatorProject, type CreatorReturn } from './creator-api';
import { writeApi } from './management-api';
import type { BriefCandidate } from './creator-candidates';

const briefLabels: [keyof BriefCandidate,string,number][] = [['facts','商品事实',8000],['selling_points','卖点与建议',4000],['audience','目标受众',1000],['style','统一风格',2000],['constraints','保留与避免',2000]];
export function CreatorAdoption({ incoming, owner, onClose, onDone }: {incoming:CreatorReturn;owner:string;onClose:()=>void;onDone:(p:CreatorProject)=>void}) {
  const dialog=useRef<HTMLDialogElement>(null);
  const [p,setProject]=useState<CreatorProject>();
  const [text,setText]=useState(incoming.kind==='script'?incoming.text:'');
  const [fields,setFields]=useState<BriefCandidate|undefined>(incoming.kind==='brief'?incoming.fields:undefined);
  const [url,setUrl]=useState('');
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  useEffect(()=>{if(dialog.current?.showModal)dialog.current.showModal();else dialog.current?.setAttribute('open','');return()=>dialog.current?.close?.();},[]);
  useEffect(()=>{let alive=true,link='';void getCreator(incoming.project).then(value=>{
    if(!alive)return;
    if(value.chat_id!==owner||incoming.owner!==owner||value.revision!==incoming.revision)throw new Error('项目或版本已经变化，未采用任何结果。请回到当前任务重新生成或核对。');
    setProject(value);
  }).catch(e=>{if(alive)setError(e instanceof Error?e.message:String(e));});
  if(incoming.kind==='cover')void attachmentBlob(incoming.owner,{id:incoming.attachment,name:incoming.name,kind:'image',mime:'image/png',bytes:0}).then(blob=>{if(alive){link=URL.createObjectURL(blob);setUrl(link);}}).catch(()=>{if(alive)setError('图片无法读取，未采用任何结果。请重新导出。');});
  return()=>{alive=false;if(link)URL.revokeObjectURL(link);};},[incoming.nonce,owner]);
  async function adopt(){
    if(!p||busy||error)return;setBusy(true);
    try{
      const latest=await getCreator(p.id);
      if(latest.chat_id!==owner||latest.revision!==incoming.revision)throw new Error('项目已更新，旧候选不能覆盖当前结果。请关闭后重新核对。');
      const result=incoming.kind==='script'?await saveCreator(latest,{script:text}):incoming.kind==='brief'?await saveCreator(latest,fields!):await writeApi<CreatorProject>(`${creatorBase}/projects/${p.id}/adopt-cover`,'POST',{revision:incoming.revision,owner,attachment:incoming.attachment});
      onDone(result);
    }catch(e){setError(e instanceof Error?e.message:String(e));}finally{setBusy(false);}
  }
  return <dialog ref={dialog} className="adoption-dialog" aria-label="确认采用创作结果" onCancel={e=>{e.preventDefault();if(!busy)onClose();}}>
    <header><div><span>{p?.name || '当前项目'}</span><h2>{incoming.kind==='brief'?'确认创作方向':incoming.kind==='script'?'确认口播主稿':'确认采用工作图'}</h2></div><button aria-label="关闭采用确认" disabled={busy} onClick={onClose}>×</button></header>
    <div className="adoption-body">{error&&<p role="alert" className="creator-error">{error}</p>}
      {!p&&!error&&<p role="status">正在核对项目版本…</p>}
      {incoming.kind==='script'?<label>要朗读的正文<textarea aria-label="待采用口播稿" maxLength={12000} value={text} onChange={e=>setText(e.target.value)} disabled={busy}/></label>:incoming.kind==='brief'&&fields?<><p className="adoption-note">核对商品事实；卖点和风格建议由你决定。方向改变后，已有图片和口播可能需要重新核对。</p>{briefLabels.map(([key,label,limit])=><label key={key}>{label}<textarea aria-label={`待采用${label}`} maxLength={limit} value={fields[key]} disabled={busy} onChange={e=>setFields({...fields,[key]:e.target.value})}/></label>)}</>:url?<img src={url} alt="待采用工作图"/>:<p role="status">正在读取工作图…</p>}
    </div><footer><span>确认后保存为项目采用稿，继续留在当前对话。</span><div><button disabled={busy} onClick={onClose}>暂不采用</button><button className="primary-button" disabled={busy||!p||!!error||incoming.kind==='script'&&!text.trim()||incoming.kind==='brief'&&!fields?.facts.trim()||incoming.kind==='cover'&&!url} onClick={()=>void adopt()}>{busy?'正在采用…':'确认采用'}</button></div></footer>
  </dialog>;
}
