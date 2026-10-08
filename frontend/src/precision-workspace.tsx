import { createRoot } from 'react-dom/client';
import { useEffect, useState } from 'react';
import CanvasApp from './CanvasApp';
import { ChatController } from './chat-controller';
import { readApi } from './management-api';
import './styles.css';
import './canvas.css';
import './workflow.css';
import './studio.css';
import './precision-workspace.css';

// The video host supplies its authenticated, same-origin Canvas service. Reuse
// the real editor, not another reduced set of image-editing controls.
const query = new URLSearchParams(location.search);
const project = query.get('project') || '';
const nonce = query.get('nonce') || '';
const controller = new ChatController();
const send = (action: string, extra = {}) => parent.postMessage({type:'miniclaw.precision', action, nonce, project, ...extra}, location.origin);
function Workspace() {
  useEffect(()=>{send('ready')},[]);
  const [context,setContext]=useState('');
  useEffect(()=>{const workspace=query.get('workspace');if(workspace)void readApi<{state:{facts?:string}}>(`/api/workspaces/${encodeURIComponent(workspace)}`).then(p=>setContext(p.state.facts||'')).catch(()=>{});},[]);
  const [ready] = useState(() => ({session:'', nonce:Date.now(), precision:true,
    attachment:{id:'',name:'视频画面',kind:'image' as const,mime:'image/png',bytes:0,canvas_project_id:project}}));
  if (!/^[a-f0-9]{32}$/.test(project) || !nonce) return <p role="alert">请从自由画布中的图片打开精修。</p>;
  return <CanvasApp controller={controller} active initialImport={ready}
    onChat={() => send('close')} onUse={() => {}} onSettings={() => {}}
    workspaceHost={{project, name:query.get('label')||undefined, context, onClose:() => send('close'), onReview:async (id,revision) => send('review',{project:id,revision})}} />;
}
createRoot(document.getElementById('root')!).render(<Workspace />);
