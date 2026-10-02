import { createRoot } from 'react-dom/client';
import { App } from './App';
import { ChatController } from './chat-controller';
import './styles.css';

const controller = new ChatController();
createRoot(document.getElementById('root')!).render(<App controller={controller} />);
