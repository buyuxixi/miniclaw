import { useEffect, useState } from 'react';
import { readApi, writeApi } from './management-api';
interface MemoryValue { text: string; hash: string; limit: number }
export function MemoryEditor({ blocked, onBusy, onDirty }: { blocked: boolean; onBusy: (busy: boolean) => void; onDirty: (dirty: boolean) => void }) {
  const [values, setValues] = useState<Record<'memory' | 'user', MemoryValue>>(); const [target, setTarget] = useState<'memory' | 'user'>('memory'); const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [notice, setNotice] = useState('');
  const [original, setOriginal] = useState('');
  useEffect(() => { onBusy(busy); }, [busy, onBusy]);
  useEffect(() => { onDirty(Boolean(values) && JSON.stringify(values) !== original); return () => onDirty(false); }, [values, original, onDirty]);
  useEffect(() => { const abort = new AbortController(); void readApi<Record<'memory' | 'user', MemoryValue>>('/api/miniclaw/memory', abort.signal).then(v => { setValues(v); setOriginal(JSON.stringify(v)); }).catch(e => { if (!abort.signal.aborted) setError(String(e)); }); return () => abort.abort(); }, []);
  async function save() { if (!values || blocked || busy) return; setBusy(true); setError(''); try { const result = await writeApi<{ hash: string }>('/api/miniclaw/memory', 'PUT', { target, ...values[target] }); const next = { ...values, [target]: { ...values[target], hash: result.hash } }; setValues(next); setOriginal(previous => JSON.stringify({ ...JSON.parse(previous), [target]: next[target] })); setNotice('内容已保存。开启对应加载开关后，在新对话中使用。'); } catch (e) { setError(String(e)); } finally { setBusy(false); } }
  return <section className="memory-editor"><h3>你希望记住什么？</h3><p className="settings-description">手动维护跨对话使用的事实和偏好。这里只保存你明确填写的内容。</p>{error && <p role="alert" className="settings-error">{error}</p>}{notice && <p role="status" className="settings-notice">{notice}</p>}
    <div className="picker-scopes"><button aria-pressed={target === 'memory'} onClick={() => setTarget('memory')}>长期事实</button><button aria-pressed={target === 'user'} onClick={() => setTarget('user')}>个人偏好</button></div>
    <textarea aria-label={target === 'memory' ? '长期记忆内容' : '个人偏好内容'} disabled={blocked || busy || !values} value={values?.[target].text ?? ''} placeholder={target === 'memory' ? '例如：项目目标、已确认的业务事实…' : '例如：使用中文回答，解释时先给结论…'} onChange={e => setValues(v => ({ ...v!, [target]: { ...v![target], text: e.target.value } }))} />
    <div className="editor-footer"><span>{Array.from(values?.[target].text ?? '').length} / {values?.[target].limit ?? '…'} 字符 · 保存不自动开启加载</span><button className="primary-button" disabled={blocked || busy || !values} onClick={() => void save()}>{busy ? '保存中…' : '保存内容'}</button></div>
  </section>;
}
