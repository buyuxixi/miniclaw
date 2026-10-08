export type IconName = 'plus' | 'menu' | 'settings' | 'search' | 'close' | 'chat' | 'file' | 'edit' | 'skills' | 'arrow' | 'stop' | 'copy' | 'check' | 'chevron' | 'lock' | 'archive' | 'image' | 'folder' | 'activity' | 'canvas' | 'generate' | 'video' | 'note' | 'assistant' | 'refresh' | 'left' | 'right' | 'select' | 'hand' | 'rectangle' | 'lasso' | 'brush' | 'crop' | 'flip' | 'undo' | 'redo' | 'layers' | 'history';
const paths: Record<IconName, string> = {
  select:'M4 3l15 9-7 2-3 7Z',hand:'M7 12V6a1.5 1.5 0 0 1 3 0v5-7a1.5 1.5 0 0 1 3 0v7-6a1.5 1.5 0 0 1 3 0v6-3a1.5 1.5 0 0 1 3 0v7c0 5-3 7-6 7h-1c-2 0-3-1-5-4l-3-5a1.5 1.5 0 0 1 2-2l2 2Z',
  rectangle:'M3 8V3h5M16 3h5v5M21 16v5h-5M8 21H3v-5M3 11v2M11 3h2M21 11v2M11 21h2',lasso:'M6 18c-6-2-5-11 2-13 7-3 14 1 13 7-1 5-8 7-13 5-3-1-5 4-1 4 2 0 3-2 2-4',brush:'M15 3l6 6-9 9-6-6Z M6 12c-3 0-4 3-3 5 1 2 0 4 0 4s5 0 7-3',crop:'M6 3v15h15M3 6h15v15',flip:'M12 3v18M8 5 3 19h5Z M16 5l5 14h-5Z',undo:'M8 5l-5 5 5 5M3 10h10a7 7 0 0 1 7 7',redo:'M16 5l5 5-5 5M21 10H11a7 7 0 0 0-7 7',layers:'M12 3 2 8l10 5 10-5Z M2 12l10 5 10-5M2 16l10 5 10-5',history:'M3 5v5h5M3 10a9 9 0 1 1 1 7M12 7v6l4 2',
  canvas: 'M3 8V3h5M16 3h5v5M21 16v5h-5M8 21H3v-5M7 8h4v4H7Z M14 13h4v4h-4Z M11 10h4v3',
  generate: 'M3 9V4h5M3 15v5h5M16 4h5v5M21 15v5h-5M7 16l4-5 3 3 2-2 3 4M11 4v4M9 6h4',
  video: 'M3 7h18v14H3Z M3 7V3h18v4M6 3l-2 4M12 3l-2 4M18 3l-2 4M10 11l5 3-5 3Z',
  note: 'M5 3h14v14l-4 4H5Z M15 21v-4h4M8 7h8M8 11h8M8 15h4',
  assistant: 'M5 4h14v12H9l-5 4V4Z M8 9h8M8 12h5M19 18h3M20.5 16.5v3',
  refresh: 'M20 7V3M20 7h-4M20 7a8 8 0 1 0 0 10',left:'M15 5l-7 7 7 7',right:'M9 5l7 7-7 7',
  folder: 'M3 7V4h6l3 3h9v13H3V7Z', activity: 'M3 12h4l3-7 4 14 3-7h4',
  plus: 'M12 5v14M5 12h14', menu: 'M4 6h16M4 12h16M4 18h16',
  image: 'M3 3h18v18H3V3Z M3 16l6-6 5 5 3-3 4 4M15 7h.01',
  archive: 'M3 3h18v5H3V3Z M5 8v13h14V8M9 12h6',
  settings: 'M9 3h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1 1-3Z M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z',
  search: 'M21 21l-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z', close: 'M6 6l12 12M6 18 18 6',
  chat: 'M5 4h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H8l-5 3V6a2 2 0 0 1 2-2Z M7 9h10M7 13h6',
  file: 'M5 3h9l5 5v13H5V3Z M14 3v5h5M8 12h8M8 16h6',
  edit: 'M16 3l5 5M4 20l4-1L21 6l-4-4L4 15v5Z',
  skills: 'M12 3v6M9 6h6M6 13v8M2 17h8M17 11v10M12 16h10',
  arrow: 'M12 20V4M5 11l7-7 7 7', stop: 'M6 6h12v12H6Z',
  copy: 'M9 9h11v12H9V9Z M15 9V3H3v12h6', check: 'M4 12l5 5L20 6',
  chevron: 'M8 10l4 4 4-4', lock: 'M6 10h12v11H6V10Z M8 10V7a4 4 0 0 1 8 0v3',
};
export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  const feature=['canvas','generate','video','note','assistant'].includes(name);
  return <svg className={feature?'feature-icon':undefined} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">{feature&&<path d={name==='video'?'M3 7h18v4H3Z':name==='canvas'?'M7 8h4v4H7Z':name==='assistant'?'M5 4h14v5H5Z':name==='note'?'M5 3h14v4H5Z':'M3 15h18v5H3Z'} fill="currentColor" fillOpacity=".12" stroke="none"/>}<path d={paths[name]} /></svg>;
}
