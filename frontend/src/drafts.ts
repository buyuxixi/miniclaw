import type { Attachment } from './attachments';
export interface Draft { text: string; skill?: string; attachments: Attachment[] }
const blank = (): Draft => ({ text: '', attachments: [] });
export function loadDraft(owner: string): Draft {
  try {
    const saved = JSON.parse(localStorage.getItem(`miniclaw.draft.${owner}`) ?? 'null');
    if (!saved || typeof saved.text !== 'string' || !Array.isArray(saved.attachments)) return blank();
    return { text: saved.text.slice(0, 100000), skill: typeof saved.skill === 'string' ? saved.skill : undefined,
      attachments: saved.attachments.filter((a: Attachment) => a && typeof a.id === 'string' && typeof a.name === 'string' && ['image', 'text'].includes(a.kind)).slice(0, 4) };
  } catch { return blank(); }
}
export function saveDraft(owner: string, draft: Draft): boolean {
  if (!owner) return true;
  try { localStorage.setItem(`miniclaw.draft.${owner}`, JSON.stringify(draft)); return true; } catch { return false; }
}
