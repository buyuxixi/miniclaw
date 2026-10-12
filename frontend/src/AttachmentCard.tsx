import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { attachmentBlob, documentStatus, retryDocument, type Attachment, type AttachmentWarning } from './attachments';
import { fileSize } from './attachment-policy';
import { Icon } from './Icon';
import { ChatImageCanvasAction, type ChatImageCanvasTarget } from './ChatImageCanvasAction';
import { ImagePreview } from './ImagePreview';
import './attachment-card.css';
function parseErrorText(message: string | undefined, status: Attachment['parse_status']) {
  if(!message)return '';
  if(/utf[-_]?8|UnicodeEncodeError/i.test(message)&&/surrogates?\s+not\s+allowed/i.test(message))return status==='partial'
    ?'部分文字编码异常，已保留可读取内容，可重试解析。':'文字编码异常，暂时无法完成解析，可重试解析。';
  return message;
}
const errorMessage=(error:unknown)=>error instanceof Error?error.message:String(error);
function warningText(warning: string | AttachmentWarning, status: Attachment['parse_status']) {
  if(typeof warning==='string')return parseErrorText(warning,status);
  const source=warning.source;
  const row=source?.row ?? source?.row_number;
  const line=source?.line_start;
  const location=source?[source.page!=null?`第${source.page}页`:'',source.sheet!=null?`工作表 ${source.sheet}`:source.table&&source.table!=='csv'?`表格 ${source.table}`:'',row!=null?`第${row}行`:'',line!=null?`原文件第${line}${source.line_end&&source.line_end!==line?`–${source.line_end}`:''}行`:'',source.paragraph!=null?`第${source.paragraph}段`:''].filter(Boolean).join(' · '):'';
  return `${location?`${location}：`:''}${parseErrorText(warning.message,status)}`;
}
const count=(value:unknown):value is number=>typeof value==='number'&&Number.isSafeInteger(value)&&value>=0;
function coverageText(attachment:Attachment) {
  const coverage=attachment.coverage;
  if(!coverage)return '';
  const pdf=attachment.mime==='application/pdf'||/\.pdf$/i.test(attachment.name),unit=pdf?'页':'个解析单元';
  const seen=coverage.units_seen,total=coverage.total_units;
  const messages:string[]=[];
  if(count(seen))messages.push(`已处理${seen}${count(total)?`/${total}`:''}${unit}${count(total)?'':'；总量未确定'}`);
  const warnings=attachment.warnings||[],warningCount=count(coverage.warning_count)?Math.max(coverage.warning_count,warnings.length):warnings.length;
  if(warningCount){
    const pages=warnings.flatMap(warning=>{const page=typeof warning==='object'?warning.source?.page:undefined;return count(page)&&page>0?[page]:[];});
    messages.push(pdf&&warningCount===warnings.length&&pages.length===warnings.length?`${new Set(pages).size}页有读取警告`:`${warningCount}项读取警告`);
  }
  if(coverage.stopped_early===true)messages.push('解析提前停止，后续内容尚未处理');
  else if(count(seen)&&count(total)&&seen<total)messages.push('后续内容尚未处理');
  if(coverage.complete===true)messages.push('已完成当前解析范围');
  return messages.join('；');
}
function AttachmentDetails({attachment,parseLabel,error,actions,onClose}:{attachment:Attachment;parseLabel:string;error:string;actions:ReactNode;onClose:()=>void}) {
  const dialog=useRef<HTMLDialogElement>(null),close=useRef<HTMLButtonElement>(null),heading=useId();
  useEffect(()=>{
    const opener=document.activeElement instanceof HTMLElement?document.activeElement:null,modal=dialog.current!;
    if(typeof modal.showModal==='function')modal.showModal();else modal.setAttribute('open','');
    close.current?.focus({preventScroll:true});
    return()=>{modal.close?.();if(opener?.isConnected)opener.focus({preventScroll:true});};
  },[]);
  const warnings=attachment.warnings||[],serverWarningCount=attachment.coverage?.warning_count,warningCount=count(serverWarningCount)?Math.max(serverWarningCount,warnings.length):warnings.length;
  const coverage=coverageText(attachment);
  return createPortal(<dialog ref={dialog} className="attachment-details" aria-labelledby={heading} aria-modal="true" onCancel={event=>{event.preventDefault();event.stopPropagation();onClose();}} onClick={event=>{if(event.target===event.currentTarget)onClose();}}>
    <header className="attachment-details-header"><h2 id={heading}>{attachment.name}</h2><button ref={close} type="button" className="attachment-details-close icon-button" aria-label="关闭附件详情" onClick={onClose}><Icon name="close" size={18}/></button></header>
    <div className="attachment-details-body"><dl className="attachment-details-meta"><div><dt>文件大小</dt><dd>{fileSize(attachment.bytes)}</dd></div><div><dt>解析状态</dt><dd>{parseLabel||'原文附件'}</dd></div>{count(attachment.chunks)&&<div><dt>文本块</dt><dd>{attachment.chunks}</dd></div>}</dl>
      {coverage&&<p className="attachment-details-coverage">{coverage}</p>}
      {error&&<p className="attachment-error" role="alert">{error}</p>}
      {!!warningCount&&<section className="attachment-details-warnings attachment-warnings"><h3>读取范围说明（{warningCount}项）</h3>{warnings.map((warning,index)=><p key={index}>{warningText(warning,attachment.parse_status)}</p>)}{warningCount>warnings.length&&<p>当前显示服务返回的{warnings.length}项警告，完整警告共{warningCount}项。</p>}</section>}
    </div><footer className="attachment-details-actions">{actions}</footer>
  </dialog>,document.body);
}
export function AttachmentCard({ attachment, owner, onRemove, onEdit, onStatus, canvasTarget, variant='row' }: { attachment: Attachment; owner: string; onRemove?: () => void; onEdit?: () => void; onStatus?: (attachment: Attachment) => void; canvasTarget?: ChatImageCanvasTarget; variant?: 'row'|'tile' }) {
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');
  const [preview, setPreview] = useState(false);
  const tileStatusId = useId();
  const [details,setDetails]=useState(false);
  const [metadata,setMetadata]=useState(attachment),[retrying,setRetrying]=useState(false),[downloading,setDownloading]=useState(false),[refresh,setRefresh]=useState(0);
  const statusCallback=useRef(onStatus);statusCallback.current=onStatus;
  const scope=useRef({owner,id:attachment.id});scope.current={owner,id:attachment.id};
  const lifecycle=useRef({alive:false,generation:0});
  function isCurrent(generation:number){return lifecycle.current.alive&&lifecycle.current.generation===generation&&scope.current.owner===owner&&scope.current.id===attachment.id;}
  useEffect(() => {
    lifecycle.current.alive=true;const generation=++lifecycle.current.generation;
    setUrl(''); setError(''); setPreview(false);setDetails(false);
    setMetadata(attachment);setRetrying(false);setDownloading(false);
    const abort = new AbortController(); let blobUrl = '';
    if(attachment.kind==='image'||attachment.kind==='text'&&attachment.bytes<=64*1024)void attachmentBlob(owner, attachment, abort.signal).then(blob => { if (!abort.signal.aborted) { blobUrl = URL.createObjectURL(blob); setUrl(blobUrl); } })
      .catch(reason => { if (!abort.signal.aborted) setError(String(reason)); });
    return () => { if(lifecycle.current.generation===generation){lifecycle.current.alive=false;lifecycle.current.generation++;}abort.abort(); if (blobUrl) URL.revokeObjectURL(blobUrl); };
  }, [attachment.id, owner]);
  useEffect(()=>{
    if(attachment.kind==='image'||attachment.kind==='text'&&!attachment.parse_status)return;
    const abort=new AbortController();let timer:ReturnType<typeof setTimeout>;
    async function poll(){
      try{
        const status=await documentStatus(owner,attachment.id,abort.signal);if(abort.signal.aborted)return;
        const updated={...attachment,...status,parse_error:status.parse_error??''};setMetadata(updated);setError('');statusCallback.current?.(updated);
        if(status.parse_status==='queued'||status.parse_status==='parsing')timer=setTimeout(()=>void poll(),2000);
      }catch(e){if(!abort.signal.aborted){setError(errorMessage(e));timer=setTimeout(()=>void poll(),5000);}}
    }
    void poll();return()=>{abort.abort();clearTimeout(timer);};
  },[attachment.id,owner,refresh]);
  async function retry(){
    const generation=lifecycle.current.generation;if(!isCurrent(generation))return;
    setRetrying(true);setError('');
    try{const status=await retryDocument(owner,attachment.id);if(!isCurrent(generation))return;const updated={...metadata,...status,parse_error:status.parse_error??''};setMetadata(updated);statusCallback.current?.(updated);if(isCurrent(generation))setRefresh(v=>v+1);}
    catch(e){if(isCurrent(generation))setError(errorMessage(e));}finally{if(isCurrent(generation))setRetrying(false);}
  }
  async function download(){
    const generation=lifecycle.current.generation;if(!isCurrent(generation))return;
    setDownloading(true);setError('');
    try{const blob=await attachmentBlob(owner,attachment);if(!isCurrent(generation))return;const link=document.createElement('a'),blobUrl=URL.createObjectURL(blob);link.href=blobUrl;link.download=attachment.name;link.click();setTimeout(()=>URL.revokeObjectURL(blobUrl),1000);}
    catch(e){if(isCurrent(generation))setError(errorMessage(e));}finally{if(isCurrent(generation))setDownloading(false);}
  }
  const parseLabel=metadata.parse_status?({queued:'等待解析',parsing:'正在解析',ready:'可使用',partial:'部分可读取',failed:'解析失败',cancelled:'解析已停止'} as const)[metadata.parse_status]:attachment.kind==='document'?'等待解析':'';
  const displayedError=parseErrorText(error||metadata.parse_error,metadata.parse_status);
  const downloadAction=url&&attachment.kind==='text'?<a href={url} download={attachment.name}>下载原文</a>:attachment.kind!=='image'&&<button type="button" className="attachment-text-action" disabled={downloading} onClick={()=>void download()}>{downloading?'正在下载…':'下载原文件'}</button>;
  const retryAction=attachment.kind!=='image'&&['failed','cancelled','partial'].includes(metadata.parse_status||'')&&<button type="button" className="attachment-text-action" disabled={retrying} onClick={()=>void retry()}>{retrying?'正在重试…':'重试解析'}</button>;
  if(variant==='tile'){
    const tileStatus=error?'error':metadata.parse_status,showStatus=!!error||metadata.parse_status&&metadata.parse_status!=='ready'||attachment.kind==='document'&&!metadata.parse_status;
    const type=attachment.name.split('.').at(-1)?.toUpperCase().slice(0,8)||'文件';
    const hasActions=attachment.kind==='image'&&!!(onEdit||canvasTarget);
    return <div className={`attachment-card attachment-card-tile${hasActions?' has-actions':''}`}>
      <button type="button" className="attachment-tile-open" aria-label={`${attachment.kind==='image'?'预览':'查看附件'} ${attachment.name}`} aria-describedby={showStatus?tileStatusId:undefined} title={attachment.name} disabled={attachment.kind==='image'&&!url} onClick={()=>attachment.kind==='image'?setPreview(true):setDetails(true)}>
        <span className="attachment-tile-preview">{attachment.kind==='image'&&url?<img src={url} alt=""/>:<><Icon name={attachment.kind==='image'?'image':'file'} size={32}/><span className="attachment-tile-type">{type}</span></>}{showStatus&&<span id={tileStatusId} className={`attachment-tile-status is-${tileStatus||'queued'}`} title={displayedError||parseLabel}>{error?'加载失败':parseLabel}</span>}</span>
        <span className="attachment-tile-name" title={attachment.name}>{attachment.name}</span>
      </button>
      {hasActions&&<div className="attachment-tile-actions">
        {onEdit&&<button type="button" className="attachment-tile-edit icon-button" aria-label={`编辑 ${attachment.name}`} onClick={onEdit}><Icon name="edit" size={14}/><span>编辑</span></button>}
        {canvasTarget&&<ChatImageCanvasAction key={`${owner}:${canvasTarget.workspace}:${canvasTarget.sessionId}:${attachment.id}`} image={attachment} target={canvasTarget}/>}
      </div>}
      {onRemove&&<button type="button" className="attachment-tile-remove icon-button" aria-label={`移除 ${attachment.name}`} onClick={onRemove}><Icon name="close" size={14}/></button>}
      {details&&<AttachmentDetails key={`${owner}:${attachment.id}`} attachment={metadata} parseLabel={parseLabel} error={displayedError} actions={<>{downloadAction}{retryAction}</>} onClose={()=>setDetails(false)}/>}
      {preview&&url&&<ImagePreview key={`${owner}:${attachment.id}`} url={url} name={attachment.name} onClose={()=>setPreview(false)}/>}
    </div>;
  }
  return <div className="attachment-card">{attachment.kind === 'image' && url ? <button type="button" className="attachment-preview" aria-label={`预览 ${attachment.name}`} onClick={() => setPreview(true)}><img src={url} alt={attachment.name} /></button> : <Icon name="file" size={22} />}
    <div><strong title={attachment.name}>{attachment.name}</strong><small>{fileSize(attachment.bytes)}{parseLabel&&` · ${parseLabel}`}</small>{displayedError&&<small className="attachment-error" role="alert">{displayedError}</small>}{!!metadata.warnings?.length&&<details className="attachment-warnings"><summary>读取范围说明{metadata.coverage?.warning_count&&metadata.coverage.warning_count>metadata.warnings.length?`（${metadata.coverage.warning_count}项）`:''}</summary>{metadata.warnings.map((warning,index)=><p key={index}>{warningText(warning,metadata.parse_status)}</p>)}</details>}{downloadAction}{retryAction}{attachment.kind === 'image' && canvasTarget && <ChatImageCanvasAction key={`${owner}:${canvasTarget.workspace}:${canvasTarget.sessionId}:${attachment.id}`} image={attachment} target={canvasTarget} />}</div>
    {attachment.kind === 'image' && onEdit && <button type="button" className="icon-button" aria-label={`编辑 ${attachment.name}`} onClick={onEdit}><Icon name="edit" size={14} /></button>}
    {onRemove && <button type="button" className="icon-button" aria-label={`移除 ${attachment.name}`} onClick={onRemove}><Icon name="close" size={14} /></button>}
    {preview && url && <ImagePreview key={`${owner}:${attachment.id}`} url={url} name={attachment.name} onClose={() => setPreview(false)} />}
  </div>;
}
