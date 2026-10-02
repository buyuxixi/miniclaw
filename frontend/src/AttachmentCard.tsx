import { useEffect, useState } from 'react';
import { attachmentBlob, type Attachment } from './attachments';
import { Icon } from './Icon';
export function AttachmentCard({ attachment, owner, onRemove }: { attachment: Attachment; owner: string; onRemove?: () => void }) {
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');
  useEffect(() => {
    const abort = new AbortController(); let blobUrl = '';
    void attachmentBlob(owner, attachment, abort.signal).then(blob => { if (!abort.signal.aborted) { blobUrl = URL.createObjectURL(blob); setUrl(blobUrl); } })
      .catch(reason => { if (!abort.signal.aborted) setError(String(reason)); });
    return () => { abort.abort(); if (blobUrl) URL.revokeObjectURL(blobUrl); };
  }, [attachment.id, owner]);
  return <div className="attachment-card">{attachment.kind === 'image' && url ? <a href={url} target="_blank" rel="noreferrer" aria-label={`预览 ${attachment.name}`}><img src={url} alt={attachment.name} /></a> : <Icon name="file" size={22} />}
    <div><strong title={attachment.name}>{attachment.name}</strong><small>{error || `${(attachment.bytes / 1024).toFixed(1)} KiB`}</small>{url && attachment.kind === 'text' && <a href={url} download={attachment.name}>下载原文</a>}</div>
    {onRemove && <button type="button" className="icon-button" aria-label={`移除 ${attachment.name}`} onClick={onRemove}><Icon name="close" size={14} /></button>}
  </div>;
}
