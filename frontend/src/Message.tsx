import Markdown from 'react-markdown';
import { useState } from 'react';
import remarkGfm from 'remark-gfm';
import type { ChatItem } from './types';

function pretty(value: unknown) {
  if (typeof value === 'string') {
    try { return JSON.stringify(JSON.parse(value), null, 2); } catch { return value; }
  }
  return JSON.stringify(value, null, 2) ?? '';
}

export function Message({ item }: { item: ChatItem }) {
  const [copyStatus, setCopyStatus] = useState('');
  async function copy() {
    try { await navigator.clipboard.writeText(item.text); setCopyStatus('已复制'); }
    catch { setCopyStatus('复制失败，请选中文字复制'); }
  }
  if (item.kind === 'tool') return <details className={`tool-card ${item.status}`}>
    <summary><span className="tool-icon">⌘</span><span>{item.name}</span><span className="tool-status">{
      { running: '执行中', done: '已完成', error: '执行失败', interrupted: '已停止', unavailable: '结果未加载' }[item.status ?? 'unavailable']
    }</span></summary>
    <div className="tool-details"><p>调用参数</p><pre>{pretty(item.args)}</pre>
      {item.result !== undefined && <><p>执行结果</p><pre>{pretty(item.result)}</pre></>}
    </div>
  </details>;
  return <article className={`message ${item.kind}`}>
    <div className="message-label">{item.kind === 'user' ? '你' : 'miniclaw'}</div>
    <div className="message-body">{item.kind === 'user' ? <p>{item.text}</p> : <Markdown
      remarkPlugins={[remarkGfm]} skipHtml
      components={{ a: props => <a {...props} target="_blank" rel="noreferrer" />,
        img: () => <span>图片预览将在后续阶段开放</span> }}
    >{item.text}</Markdown>}</div>
    {item.status === 'running' && !item.text && <span className="thinking">正在思考…</span>}
    {item.kind === 'assistant' && item.text && item.status !== 'running' && <div className="message-actions"><button aria-label="复制回复" onClick={() => void copy()}>▢ 复制</button><span role="status">{copyStatus}</span></div>}
  </article>;
}
