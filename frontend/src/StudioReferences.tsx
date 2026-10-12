import {useEffect,useRef,useState} from 'react';
import {ImagePreview} from './ImagePreview';
import './studio-references.css';

export interface StudioReference {
  id:string;
  name:string;
  kind:'image'|'shot'|'note';
  current?:boolean;
  text?:string;
  images:{id:string;name:string;file:string;image_index?:number}[];
}
export function studioThumbnail(file:string){return file.startsWith('/api/precision/projects/')?file.replace('/api/precision/projects/','/studio/media/'):file.startsWith('/')||file.startsWith('data:')?file:'/studio/'+file;}

export function StudioReferences({items,onRemove,disabled=false}:{items:StudioReference[];onRemove?:(id:string)=>void;disabled?:boolean}){
  const [preview,setPreview]=useState<StudioReference>();
  return <><div className="studio-references" aria-label={onRemove?'本轮画布引用':'此消息引用的画布内容'}>{items.map(item=><div className="studio-reference" key={item.id}>
    <button type="button" className="studio-reference-open" onClick={()=>setPreview(item)} aria-label={`查看引用：${item.name}`} title={item.name}>
      {item.images[0]?<img src={studioThumbnail(item.images[0].file)} alt=""/>:<span className="studio-reference-symbol">{item.kind==='shot'?'▶':'✎'}</span>}
      <span><small>{item.current?'当前':''}{item.kind==='shot'?'镜头':item.kind==='image'?'图片':'创意'}{!item.current&&onRemove?' · 参考':''}</small><strong>{item.name}</strong></span>
    </button>{onRemove&&<button type="button" className="studio-reference-remove" disabled={disabled} aria-label={`移除引用：${item.name}`} onClick={()=>onRemove(item.id)}>×</button>}
  </div>)}</div>{preview&&(preview.kind==='image'&&preview.images[0]?<ImagePreview url={studioThumbnail(preview.images[0].file)} name={preview.name} onClose={()=>setPreview(undefined)}/>:<ReferenceDetails item={preview} onClose={()=>setPreview(undefined)}/>)}</>;
}
function ReferenceDetails({item,onClose}:{item:StudioReference;onClose:()=>void}){
  const [image,setImage]=useState<StudioReference['images'][number]>();
  const dialog=useRef<HTMLDialogElement>(null);
  useEffect(()=>{const opener=document.activeElement as HTMLElement|null;const modal=dialog.current!;if(modal.showModal)modal.showModal();else modal.setAttribute('open','');return()=>{modal.close?.();opener?.isConnected&&opener.focus();};},[]);
  return <><dialog ref={dialog} onCancel={e=>{e.preventDefault();onClose();}} aria-label={item.name} className="studio-reference-details" onClick={e=>{if(e.target===e.currentTarget)onClose();}}><header><strong>{item.name}</strong><button type="button" onClick={onClose} aria-label="关闭引用详情">×</button></header>{item.images.map(i=><button type="button" key={i.id} onClick={()=>setImage(i)} aria-label={`放大查看 ${i.name}`}><img src={studioThumbnail(i.file)} alt={i.name}/></button>)}<p>{item.text||'尚未填写内容'}</p></dialog>{image&&<ImagePreview url={studioThumbnail(image.file)} name={image.name} onClose={()=>setImage(undefined)}/>}</>;
}
