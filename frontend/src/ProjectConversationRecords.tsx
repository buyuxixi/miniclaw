import type { ChatItem } from './types';
import { creationNodes } from './creator-api';

export function ProjectConversationRecords({ items, project, onClose, onSelect }: {
  items: ChatItem[]; project: string; onClose: () => void; onSelect: (id: string) => void;
}) {
  const records = items.filter(item => item.kind === 'user' && (!item.creator_context || item.creator_context.project_id === project));
  return <section className="studio-records" aria-label="本项目对话记录">
    <header><div><h2>讨论记录</h2><p>{records.length} 次讨论 · 点开回到对应消息</p></div><button onClick={onClose}>返回对话</button></header>
    <div className="studio-record-list">{records.length ? [...records].reverse().map(item => <button key={item.id} onClick={() => onSelect(item.id)}>
      <span className="studio-record-kind">{creationNodes.find(([node]) => node === item.creator_context?.node)?.[1] || '项目讨论'}</span>
      <strong title={item.text}>{item.text.trim().replace(/^\/[\w-]+\s+/, '') || item.attachments?.map(a => a.name).join('、') || '附件讨论'}</strong><span aria-hidden="true">↗</span>
    </button>) : <p className="studio-record-empty">还没有讨论记录。返回对话，说说你想怎样打磨这件作品。</p>}</div>
  </section>;
}
