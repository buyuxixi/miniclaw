import {useEffect,useRef,useState} from 'react';
import {writeApi} from './management-api';
import {Icon} from './Icon';
import '../public/studio/project-name.js';

export function StudioProjectDialog({owner,sessionId,message,onClose}:{owner:string;sessionId:string;message?:string;onClose:()=>void}) {
  const [name,setName]=useState('');
  const [facts,setFacts]=useState('');
  const [includeImages,setIncludeImages]=useState(true);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [requestId]=useState(()=>crypto.randomUUID());
  const dialog=useRef<HTMLDialogElement>(null);
  useEffect(()=>{dialog.current?.showModal();dialog.current?.querySelector('input')?.focus();return()=>dialog.current?.close();},[]);
  async function create() {
    setBusy(true);setError('');
    try {
      const result=await writeApi<{id:string;state:{notes:{id:string}[]}}>('/api/workspaces','POST',{
        request_id:requestId,name:name.trim(),facts,include_images:includeImages,session_id:sessionId,...(message?{message:Number(message.slice(4))}:{})
      });
      location.href=studioCanvasHref(result.id,result.state.notes[0]?.id);
    } catch(e) {setError((e as Error).message);setBusy(false);}
  }
  return <dialog ref={dialog} className="studio-create-dialog" aria-labelledby="studio-create-title" onCancel={e=>{e.preventDefault();if(!busy)onClose();}}>
    <header><div><span className="form-eyebrow">产品宣传 · 创作项目</span><h2 id="studio-create-title">把想法带到画布</h2></div><button className="icon-button" aria-label="关闭新建项目" disabled={busy} onClick={onClose}><Icon name="close"/></button></header>
    <form onSubmit={e=>{e.preventDefault();if(name.trim()&&!busy)void create();}}>
      <p className="create-context"><Icon name="chat" size={18}/>{message?'当前方案将作为创意节点带入，原讨论随时可回看。':'关联当前对话，在画布中继续整理方案、图片和镜头。'}</p>
      <label htmlFor="project-name">项目名称<span className="field-meta">必填</span></label><input id="project-name" autoFocus required maxLength={80} value={name} onChange={e=>setName(e.target.value)} placeholder="BUV 小绿泥 · 产品短片" disabled={busy}/>
      <label htmlFor="project-facts">共同要求<span className="field-meta">选填</span></label><textarea id="project-facts" maxLength={1000} value={facts} onChange={e=>setFacts(e.target.value)} placeholder="只展示产品，不出现人物；包装文字保持准确。" disabled={busy}/><small className="field-help">所有素材和镜头共用这些要求，可在项目资料中修改。</small>
      <label className="create-materials"><input type="checkbox" checked={includeImages} onChange={e=>setIncludeImages(e.target.checked)} disabled={busy}/>同时带入本对话上传的图片</label><small className="field-help">进入画布后为每个镜头选择首帧，可先修图再使用。</small>
      {error&&<p className="settings-error" role="alert">{error}</p>}<footer><button type="button" onClick={onClose} disabled={busy}>取消</button><button className="primary-action" type="submit" disabled={!name.trim()||busy}>{busy?'正在建立…':'建立并打开画布'}<Icon name="right" size={16}/></button></footer>
    </form>
  </dialog>;
}
