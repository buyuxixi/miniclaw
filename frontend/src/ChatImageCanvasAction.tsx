import '../public/studio/project-name.js';
import { useRef, useState } from 'react';
import type { Attachment } from './attachments';
import { writeApi } from './management-api';

export interface ChatImageCanvasTarget { workspace: string; sessionId: string }
export interface ChatImageCanvasResult { workspace: string; revision: number; object: string; added: boolean }

export function ChatImageCanvasAction({ image, target }: { image: Attachment; target: ChatImageCanvasTarget }) {
  const [requestId] = useState(() => crypto.randomUUID());
  const pending = useRef(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ChatImageCanvasResult>();
  const [error, setError] = useState('');
  async function add() {
    if (pending.current || result) return;
    pending.current = true;
    setBusy(true); setError('');
    try {
      const saved = await writeApi<ChatImageCanvasResult>(`/api/workspaces/${encodeURIComponent(target.workspace)}/assets/from-chat`, 'POST', {
        request_id: requestId, session_id: target.sessionId, attachment: image.id,
      });
      setResult(saved);
      // The server save is already complete; cross-tab notification is optional.
      try {
        const channel = new BroadcastChannel('miniclaw-studio');
        channel.postMessage({type:'asset-added', workspace:saved.workspace, object:saved.object, revision:saved.revision});
        channel.close();
      } catch { /* Browsers without BroadcastChannel still read the saved canvas. */ }
    } catch (reason) { setError(reason instanceof Error ? reason.message : '加入画布失败，请重试'); }
    finally { pending.current = false; setBusy(false); }
  }
  if (result) return <span role="status">{result.added ? '已加入画布' : '画布已有这张图片'} · <a href={studioCanvasHref(result.workspace, result.object)}>在画布查看</a></span>;
  return <><button type="button" className="secondary-action" disabled={busy} aria-label={`将 ${image.name} 加入画布`} onClick={() => void add()}>{busy ? '正在加入…' : '加入画布'}</button>{error && <small role="alert">{error}</small>}</>;
}
