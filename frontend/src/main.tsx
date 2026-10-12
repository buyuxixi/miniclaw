import { createRoot } from 'react-dom/client';
import { AppShell } from './AppShell';
import { ChatController } from './chat-controller';
import './styles.css';
import './canvas.css';
import './workflow.css';
import './studio.css';
import {StudioDirector} from './StudioDirector';

const controller = new ChatController();
const params=new URLSearchParams(location.search);
const workspace=params.get('workspace')||params.get('director');
if(workspace)controller.workspace={id:workspace,target:params.get('target')||undefined};
if(!params.has('director'))controller.resumeId=params.get('session')||decodeURIComponent(location.pathname.match(/^\/c\/([^/]+)\/?$/)?.[1]||'')||undefined;
createRoot(document.getElementById('root')!).render(params.has('director')?<StudioDirector controller={controller}/>:<AppShell controller={controller} />);
