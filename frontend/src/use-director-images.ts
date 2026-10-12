import {useEffect,useRef,useState} from 'react';
import {readApi} from './management-api';
import {uploadFile,type Attachment} from './attachments';

function saved(key:string):Attachment[]{
  try{const value=JSON.parse(localStorage.getItem(key)||'[]');return Array.isArray(value)?value.filter(a=>a&&typeof a.id==='string'&&typeof a.name==='string'&&a.kind==='image'&&typeof a.mime==='string'&&Number.isFinite(a.bytes)).slice(0,4):[];}catch{return [];}
}
// Chat uploads belong to the project composer; optimization uploads stay scoped to a node.
export function useDirectorImages(owner:string,workspace:string,target:string,session:string,model:string|undefined,disabled:boolean,referenceImages=false,legacyTarget?:string){
  const key=`studio-director-images:${owner}:${workspace}:${target}`;
  function load(){
    if(owner&&(target==='chat'||target.startsWith('optimize:'))&&legacyTarget&&!localStorage.getItem(key))return saved(`studio-director-images:${owner}:${workspace}:${legacyTarget}`);
    return saved(key);
  }
  const [draft,setDraft]=useState(()=>({key,items:load()}));
  const items=draft.key===key?draft.items:load();
  const current=useRef({key,items,disabled,owner});current.current={key,items,disabled,owner};
  const alive=useRef(true),flight=useRef(false);
  const [uploading,setUploading]=useState(false),[error,setError]=useState('');
  const [capability,setCapability]=useState<{session:string;model?:string;ready:boolean;images:boolean;error?:boolean}>();
  const file=useRef<HTMLInputElement>(null);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  useEffect(()=>{setDraft({key,items:load()});setError('');},[key]);
  useEffect(()=>{if(draft.key===key)try{localStorage.setItem(key,JSON.stringify(draft.items));}catch{setError('图片草稿暂时无法保存，请保留页面。');}},[draft,key]);
  useEffect(()=>{
    if(!(items.length||referenceImages)||!session)return;
    const abort=new AbortController();
    void (async()=>{
      for(let i=0;i<100&&!abort.signal.aborted;i++){
        const value=await readApi<{ready:boolean;images:boolean}>(`/api/miniclaw/session-capabilities?session_id=${encodeURIComponent(session)}`,abort.signal);
        if(abort.signal.aborted)return;
        setCapability({session,model,ready:value.ready,images:value.images});
        if(value.ready)return;
        await new Promise(resolve=>setTimeout(resolve,300));
      }
      if(!abort.signal.aborted)setCapability({session,model,ready:false,images:false,error:true});
    })().catch(()=>{if(!abort.signal.aborted)setCapability({session,model,ready:false,images:false,error:true});});
    return()=>abort.abort();
  },[session,model,items.length>0||referenceImages]);
  const capabilityCurrent=capability?.session===session&&capability.model===model?capability:undefined;
  async function addFiles(files:File[]){
    const scope=current.current;
    if(scope.disabled||flight.current||!scope.owner||!files.length)return;
    if(scope.items.length+files.length>4){setError('最多上传4张图片，请先移除一张。');return;}
    if(files.some(f=>!/\.(png|jpe?g|webp)$/i.test(f.name)||!f.size||f.size>5*1024*1024)){setError('请上传PNG、JPEG或WebP图片，每张最大5 MiB。');return;}
    flight.current=true;setUploading(true);setError('');
    try{for(const f of files){
      const uploaded=await uploadFile(scope.owner,f);
      // A late upload remains in the original node's draft, even after a switch.
      if(!alive.current||current.current.key!==scope.key){const previous=saved(scope.key);try{localStorage.setItem(scope.key,JSON.stringify([...previous,uploaded].slice(0,4)));}catch{}continue;}
      setDraft(v=>({key:scope.key,items:[...(v.key===scope.key?v.items:scope.items),uploaded]}));
    }}catch(e){if(alive.current&&current.current.key===scope.key)setError(e instanceof Error?e.message:String(e));}
    finally{flight.current=false;if(alive.current)setUploading(false);}
  }
  function remove(id:string){setDraft(v=>({key,items:(v.key===key?v.items:items).filter(a=>a.id!==id)}));}
  function clearSent(sent:Attachment[],sentKey:string){
    const keep=(rows:Attachment[])=>rows.filter(a=>!sent.some(s=>s.id===a.id));
    if(current.current.key===sentKey)setDraft(v=>({key:sentKey,items:keep(v.key===sentKey?v.items:saved(sentKey))}));
    else try{localStorage.setItem(sentKey,JSON.stringify(keep(saved(sentKey))));}catch{}
  }
  const needsVision=!!items.length||referenceImages;
  const status=uploading?'正在上传图片…':needsVision?(capabilityCurrent?.error?'暂时无法检查看图能力，请重新连接。':!capabilityCurrent?.ready?'正在检查看图能力…':capabilityCurrent.images?'':'当前聊天模型不能看图。请在设置中配置视觉模型并重新连接；图片和引用草稿已保留。'):'';
  return{items,key,file,uploading,error,status,canSend:!needsVision||!!(capabilityCurrent?.ready&&capabilityCurrent.images),addFiles,remove,clearSent,hasUpload:()=>flight.current,hasPending:()=>flight.current||current.current.items.length>0};
}
