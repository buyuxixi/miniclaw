import { useEffect, useState } from 'react';
export function ArtifactDownload({ result }: { result: unknown }) {
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');
  let parsed: { success?: boolean; path?: string } = {};
  try { parsed = typeof result === 'string' ? JSON.parse(result) : result as typeof parsed; } catch { /* failed tool body */ }
  const name = parsed?.success && typeof parsed.path === 'string' && /^artifacts\/[\w-][\w .-]{0,99}\.(txt|md|json|csv)$/i.test(parsed.path) ? parsed.path.slice(10) : '';
  useEffect(() => {
    if (!name) return;
    const abort = new AbortController(); let objectUrl = '';
    void fetch(`${window.__HERMES_BASE_PATH__ ?? ''}/api/miniclaw/artifacts/${encodeURIComponent(name)}`, { headers: { 'X-Hermes-Session-Token': window.__HERMES_SESSION_TOKEN__ ?? '' }, signal: abort.signal })
      .then(async r => { if (!r.ok) throw new Error('产物不可用'); const blob = await r.blob(); if (!abort.signal.aborted) { objectUrl = URL.createObjectURL(blob); setUrl(objectUrl); } })
      .catch(e => { if (!abort.signal.aborted) setError(String(e)); });
    return () => { abort.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [name]);
  if (!name) return null;
  return <p>{url ? <a href={url} download={name}>下载 {name}</a> : error || '正在准备产物…'}</p>;
}
