export type IconName = 'plus' | 'menu' | 'settings' | 'search' | 'close' | 'chat' | 'file' | 'edit' | 'skills' | 'arrow' | 'stop' | 'copy' | 'check' | 'chevron' | 'lock';
const paths: Record<IconName, string> = {
  plus: 'M12 5v14M5 12h14', menu: 'M4 6h16M4 12h16M4 18h16',
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
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false"><path d={paths[name]} /></svg>;
}
