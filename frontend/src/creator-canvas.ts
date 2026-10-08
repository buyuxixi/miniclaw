import type { CreatorProject } from './creator-api';

export interface CreatorCanvasOrigin { project: string; owner: string; image: string }
export function canvasOrigin(p: CreatorProject): CreatorCanvasOrigin | undefined {
  const image = p.assets.cover || p.assets.source;
  return p.chat_id && image ? { project: p.id, owner: p.chat_id, image: image.id } : undefined;
}
export function workingCanvas(p: CreatorProject): string | undefined {
  const origin = canvasOrigin(p);
  if (!origin) return;
  try {
    const ref = JSON.parse(localStorage.getItem(`miniclaw.creator.canvas.${p.id}`) || 'null');
    if (ref?.owner === origin.owner && ref?.image === origin.image && typeof ref.canvas === 'string' && ref.canvas)
      return ref.canvas;
  } catch { /* corrupted navigation hint is ignored */ }
}
export function rememberCanvas(origin: CreatorCanvasOrigin, canvas: string) {
  localStorage.setItem(`miniclaw.creator.canvas.${origin.project}`, JSON.stringify({ ...origin, canvas }));
}
