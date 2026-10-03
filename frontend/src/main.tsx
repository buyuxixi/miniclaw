import { createRoot } from 'react-dom/client';
import { AppShell } from './AppShell';
import { ChatController } from './chat-controller';
import './styles.css';
import './canvas.css';

const controller = new ChatController();
createRoot(document.getElementById('root')!).render(<AppShell controller={controller} />);
