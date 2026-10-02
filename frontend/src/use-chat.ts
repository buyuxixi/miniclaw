import { useEffect, useReducer } from 'react';
import { ChatController } from './chat-controller';

export function useChat(controller: ChatController) {
  const [, render] = useReducer(value => value + 1, 0);
  useEffect(() => controller.subscribe(render), [controller]);
  useEffect(() => { void controller.connect(); return () => controller.dispose(); }, [controller]);
  return { ...controller.state, connection: controller.connection };
}
