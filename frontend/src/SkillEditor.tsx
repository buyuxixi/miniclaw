import { useEffect, useRef, useState } from 'react';
import { readApi, writeApi } from './management-api';
import type { ChatController } from './chat-controller';
import type { SkillBinding } from './skill-readiness';
const template = '---\nname: my-skill\ndescription: 描述这个技能的用途与适用场景\n---\n\n# 处理流程\n\n1. 理解用户的任务和提供的资料。\n2. 按明确要求完成任务，不补造事实。\n3. 给出清晰的结果。\n';
export function SkillEditor({ name, controller, sessionId, blocked, onBack, onSaved, onDirty, onBusy }: { name?: string; controller: ChatController; sessionId: string; blocked: boolean; onBack: () => void; onSaved: () => void; onDirty: (dirty: boolean) => void; onBusy: (busy: boolean) => void }) {
  const [title, setTitle] = useState(name ?? 'my-skill');
  const [text, setText] = useState(name ? '' : template);
  const [original, setOriginal] = useState(name ? '' : template);
  const [hash, setHash] = useState('');
  const [required, setRequired] = useState<string[]>([]);
  const [choices, setChoices] = useState<string[]>(['miniclaw_list_files', 'miniclaw_read_file', 'miniclaw_save_artifact', 'terminal']);
  const [declared, setDeclared] = useState(false);
  const [dirtyBinding, setDirtyBinding] = useState(false);
  const [loading, setLoading] = useState(Boolean(name));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const upload = useRef<HTMLInputElement>(null);
  const installed = useRef(Boolean(name));
  const locked = blocked || loading || busy;
  useEffect(() => { onBusy(busy); }, [busy, onBusy]);
  const dirty = text !== original || dirtyBinding || !installed.current;
  useEffect(() => { onDirty(dirty); return () => onDirty(false); }, [dirty, onDirty]);
  useEffect(() => {
    const abort = new AbortController();
    if (!name) {
      void readApi<{ groups: { tools: string[] }[] }>('/api/miniclaw/tools', abort.signal).then(r => { if (!abort.signal.aborted) setChoices([...r.groups.flatMap(g => g.tools), 'terminal']); }).catch(e => { if (!abort.signal.aborted) setError(String(e)); });
      return () => abort.abort();
    }
    void readApi<{ content: string; content_hash: string; binding: SkillBinding | null; tool_choices: string[] }>(`/api/miniclaw/skills/content?name=${encodeURIComponent(name)}`, abort.signal)
      .then(r => { if (!abort.signal.aborted) { setText(r.content); setOriginal(r.content); setHash(r.content_hash); setChoices(r.tool_choices); setRequired(r.binding?.required_tools ?? []); setDeclared(Boolean(r.binding?.current)); } })
      .catch(e => { if (!abort.signal.aborted) setError(String(e)); }).finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [name]);
  async function save() {
    if (locked || !declared) return;
    setBusy(true); setError(''); setNotice('');
    try {
      let currentHash = hash;
      if (!installed.current) {
        await writeApi('/api/miniclaw/skills', 'POST', { name: title, content: text }); installed.current = true;
        const current = await readApi<{ content_hash: string; content: string }>(`/api/miniclaw/skills/content?name=${encodeURIComponent(title)}`);
        currentHash = current.content_hash; setHash(currentHash); setOriginal(current.content);
      } else if (text !== original) {
        const result = await writeApi<{ content_hash: string }>('/api/miniclaw/skills/content', 'PUT', { name: title, content: text, content_hash: hash });
        currentHash = result.content_hash; setHash(currentHash); setOriginal(text);
      }
      await writeApi('/api/miniclaw/skills/binding', 'PUT', { name: title, required_tools: required, content_hash: currentHash });
      await controller.client.request('skills.reload', { session_id: sessionId });
      setDirtyBinding(false); setNotice('技能与依赖已保存，可以回到输入框选择使用。'); onSaved();
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  }
  async function importFile(file?: File) {
    if (!file || locked) return;
    try {
      if (!/\.md$/i.test(file.name) || file.size > 128 * 1024) throw new Error('请选择128 KiB以内的Markdown文件');
      const value = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer());
      setText(value); setDeclared(false); setDirtyBinding(true);
      if (!installed.current) { const match = /^name:\s*([\w-]+)/m.exec(value); if (match) setTitle(match[1]); }
    } catch (e) { setError(String(e)); }
  }
  return <div className="skill-editor"><button className="text-button" disabled={busy} onClick={onBack}>← 返回技能列表</button><h3>{name ? '编辑技能与工具依赖' : '添加技能'}</h3>
    <p className="settings-description">技能保存处理流程；依赖绑定说明它需要的能力。绑定不会启用工具，脚本与第三方环境需由维护者核对。</p>
    {error && <p className="settings-error" role="alert">{error}</p>}{notice && <p className="settings-notice" role="status">{notice}</p>}
    <label className="field-label">技能标识<input aria-label="技能标识" value={title} disabled={installed.current || locked} onChange={e => { const next = e.target.value; setTitle(next); setText(v => v.replace(/^name:[^\r\n]*$/m, `name: ${next}`)); setDeclared(false); setDirtyBinding(true); }} placeholder="如 product-summary" /></label>
    <div className="editor-toolbar"><span>SKILL.md</span><input ref={upload} type="file" accept=".md" hidden onChange={e => { void importFile(e.target.files?.[0]); e.target.value = ''; }} /><button disabled={locked} onClick={() => upload.current?.click()}>导入 SKILL.md</button></div>
    <textarea aria-label="技能内容" value={text} disabled={locked} onChange={e => { setText(e.target.value); setDeclared(false); setDirtyBinding(true); }} spellCheck={false} />
    <fieldset className="tool-binding" disabled={locked}><legend>需要哪些工具？</legend><p>只改写、总结已提供的文本，可以不选工具。文件任务选择相应工具；终端暂未开放。</p>{choices.map(tool => <label key={tool}><input type="checkbox" checked={required.includes(tool)} onChange={e => { setRequired(v => e.target.checked ? [...v, tool] : v.filter(t => t !== tool)); setDeclared(false); setDirtyBinding(true); }} /><code>{tool}</code></label>)}
      <label className="binding-confirm"><input type="checkbox" checked={declared} onChange={e => { setDeclared(e.target.checked); setDirtyBinding(true); }} />我已核对正文，以上是此流程的全部工具依赖</label></fieldset>
    <div className="editor-footer"><span>{loading ? '加载中…' : '下次发送时加载最新正文'}</span><button className="primary-button" disabled={locked || !title.trim() || !text.trim() || !declared || !dirty} onClick={() => void save()}>{busy ? '保存中…' : '保存技能与依赖'}</button></div>
  </div>;
}
