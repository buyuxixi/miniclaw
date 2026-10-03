import { useEffect, useRef, useState } from 'react';
import type { ChatController } from './chat-controller';
import type { ChatState } from './types';
import { SkillPicker } from './SkillPicker';
import { Icon } from './Icon';
import { skillDetails } from './skill-readiness';
import { uploadFile, type Attachment } from './attachments';
import { AttachmentCard } from './AttachmentCard';
import { loadDraft, saveDraft } from './drafts';
import { readApi } from './management-api';

export function Composer({ controller, chat, suggestion, onManage }: { controller: ChatController; chat: ChatState; suggestion?: { text: string; nonce: number; attachment?: Attachment }; onManage: () => void }) {
  const [draft, setDraft] = useState(() => loadDraft(chat.storedId));
  const [picker, setPicker] = useState(false);
  const [sending, setSending] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const [vision, setVision] = useState(false);
  const [ready, setReady] = useState(false);
  const editImages = Object.values(chat.info.tools ?? {}).flat().includes('miniclaw_edit_image');
  const input = useRef<HTMLTextAreaElement>(null);
  const file = useRef<HTMLInputElement>(null);
  const mounted = useRef(true);
  const draftRef = useRef(draft); draftRef.current = draft;
  const blocked = controller.connection !== 'open' || chat.busy || chat.running || sending || uploading;
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { if (!saveDraft(chat.storedId, draft)) setError('浏览器存储已满，草稿暂时无法保存；请保留页面。'); }, [draft, chat.storedId]);
  useEffect(() => { if (suggestion) {
    if (suggestion.attachment && draftRef.current.attachments.length >= 4 && !draftRef.current.attachments.some(a => a.id === suggestion.attachment!.id)) { setError('输入框已有4个附件，请先移除一项后再添加修图结果。'); return; }
    setDraft(v => ({ ...v, text: suggestion.text || (suggestion.attachment ? v.text : ''), attachments: suggestion.attachment && !v.attachments.some(a => a.id === suggestion.attachment!.id) ? [...v.attachments, suggestion.attachment] : v.attachments })); input.current?.focus();
  } }, [suggestion]);
  useEffect(() => { if (input.current) { input.current.style.height = 'auto'; input.current.style.height = `${Math.min(input.current.scrollHeight, 180)}px`; } }, [draft.text]);
  useEffect(() => {
    const abort = new AbortController();
    setReady(false); setVision(false);
    if (controller.connection === 'open' && chat.sessionId) void (async () => {
      for (let attempt = 0; attempt < 100 && !abort.signal.aborted; attempt++) {
        const value = await readApi<{ images: boolean; ready: boolean }>(`/api/miniclaw/session-capabilities?session_id=${encodeURIComponent(chat.sessionId)}`, abort.signal);
        if (abort.signal.aborted) return;
        setReady(value.ready); setVision(value.images);
        if (value.ready) return;
        await new Promise(resolve => setTimeout(resolve, 300));
      }
    })().catch(() => { if (!abort.signal.aborted) { setVision(false); setReady(false); } });
    return () => abort.abort();
  }, [chat.sessionId, chat.info.model, chat.info.tools, controller.connection]);
  async function addFiles(files: File[]) {
    if (blocked || !files.length) return;
    if (draftRef.current.attachments.length + files.length > 4) { setError('每次最多4个附件'); return; }
    setUploading(true); setError('');
    // Preserve successful uploads if a later file fails. Never append to the
    // next session when the user switches while an upload is in flight.
    try { for (const next of files) { const uploaded = await uploadFile(chat.storedId, next); if (mounted.current) setDraft(v => ({ ...v, attachments: [...v.attachments, uploaded] })); } }
    catch (reason) { if (mounted.current) setError(String(reason)); }
    finally { if (mounted.current) setUploading(false); }
  }
  async function submit() {
    if (blocked || (!draft.text.trim() && !draft.attachments.length)) return;
    if (!ready && (draft.skill || draft.attachments.length)) { setError('会话正在初始化，技能与附件暂未就绪，请稍候再发送。草稿已保留。'); return; }
    if (!vision && !editImages && draft.attachments.some(a => a.kind === 'image')) { setError('当前模型不支持原生看图。可先移除图片发送文本；配置视觉模型或修图工具后再使用图片。'); return; }
    const sent = draft; setSending(true); setError('');
    const accepted = await controller.send(sent.text, sent.skill, sent.attachments);
    if (mounted.current) { if (accepted) setDraft(v => ({ text: v.text === sent.text ? '' : v.text, attachments: v.attachments.filter(a => !sent.attachments.some(s => s.id === a.id)), skill: undefined })); setSending(false); input.current?.focus(); }
  }
  return <>
    {error && <div className="error-banner" role="alert">{error}<button onClick={() => setError('')} aria-label="关闭提示"><Icon name="close" size={14} /></button></div>}
    <form className="composer" onSubmit={e => { e.preventDefault(); void submit(); }} onDragOver={e => { if (e.dataTransfer.types.includes('Files')) e.preventDefault(); }} onDrop={e => { if (e.dataTransfer.files.length) { e.preventDefault(); void addFiles(Array.from(e.dataTransfer.files)); } }}>
      {draft.skill && <div className="composer-skill"><Icon name="skills" size={16} /><span>{skillDetails({ name: draft.skill, description: '' }).title}</span><small>本次任务</small><button type="button" className="icon-button" aria-label="移除技能" disabled={blocked} onClick={() => setDraft(v => ({ ...v, skill: undefined }))}><Icon name="close" size={14} /></button></div>}
      {!!draft.attachments.length && <div className="attachments">{draft.attachments.map(a => <AttachmentCard key={a.id} attachment={a} owner={chat.storedId} onRemove={blocked ? undefined : () => setDraft(v => ({ ...v, attachments: v.attachments.filter(x => x.id !== a.id) }))} />)}</div>}
      <textarea id="message-input" name="message" autoComplete="off" ref={input} aria-label="消息" placeholder="描述任务，选择技能，或拖入资料…" rows={2} value={draft.text} maxLength={100000} onChange={e => setDraft(v => ({ ...v, text: e.target.value }))}
        onPaste={e => { const images = Array.from(e.clipboardData.files).filter(f => f.type.startsWith('image/')); if (images.length) { e.preventDefault(); void addFiles(images); } }}
        onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229) { e.preventDefault(); void submit(); } }} />
      <div className="composer-toolbar"><div className="composer-options"><input ref={file} type="file" hidden multiple accept=".png,.jpg,.jpeg,.webp,.txt,.md,.markdown" onChange={e => { void addFiles(Array.from(e.target.files ?? [])); e.target.value = ''; }} />
        <button type="button" className="attach-button icon-button" disabled={blocked} aria-label="添加附件" title="图片、TXT或Markdown；最多4个" onClick={() => file.current?.click()}><Icon name="plus" /></button>
        <span className="model-badge" translate="no"><span className="model-dot" />{chat.info.model || '连接中'}</span>
        <button className="skill-picker" type="button" disabled={blocked} onClick={() => setPicker(true)}><Icon name="skills" size={16} />选择技能<Icon name="chevron" size={14} /></button></div>
        {chat.running ? <button type="button" className="send-button stop" aria-label="停止" onClick={() => void controller.stop()}><Icon name="stop" size={15} /></button> : <button type="submit" className="send-button" aria-label="发送" disabled={blocked || (!draft.text.trim() && !draft.attachments.length)}><Icon name="arrow" size={20} /></button>}
      </div>{uploading && <p className="upload-status" role="status">正在上传…</p>}
      {!vision && draft.attachments.some(a => a.kind === 'image') && <p className="upload-status">{editImages ? '当前模型通过图片ID调用修图工具，不直接读取画面。' : '图片可预览，当前模型尚未支持看图。'}</p>}
    </form>
    <div className="composer-hint">Enter 发送 · Shift + Enter 换行<span>草稿自动保存在本机</span></div>
    {picker && <SkillPicker controller={controller} chat={chat} selected={draft.skill} onClose={() => { setPicker(false); input.current?.focus(); }} onChoose={name => { setDraft(v => ({ ...v, skill: name })); setPicker(false); requestAnimationFrame(() => input.current?.focus()); }} onManage={() => { setPicker(false); onManage(); }} />}
  </>;
}
