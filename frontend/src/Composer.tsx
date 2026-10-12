import { useEffect, useRef, useState } from 'react';
import type { ChatController } from './chat-controller';
import type { ChatState } from './types';
import { SkillPicker } from './SkillPicker';
import { Icon } from './Icon';
import { skillDetails } from './skill-readiness';
import { uploadFile, type Attachment } from './attachments';
import { AttachmentCard } from './AttachmentCard';
import { loadDraft, saveDraft, type Draft } from './drafts';
import { readApi } from './management-api';
import type { CreatorContext } from './creator-api';
import { creatorBlob } from './creator-api';
import { exportBlob } from './canvas-api';
import type { WorkingImageContext, ProjectImageReference } from './ProjectCompanion';
import { hasPendingClarification } from './ClarificationCards';
import { ATTACHMENT_ACCEPT, MAX_ATTACHMENTS, fileSize } from './attachment-policy';
import { useAttachmentQueue } from './use-attachment-queue';

export function Composer({ controller, chat, suggestion, onSuggestionUsed, onManage, creatorContext, canvasContext, projectImage }: { controller: ChatController; chat: ChatState; suggestion?: { text: string; nonce: number; attachment?: Attachment; skill?: string }; onSuggestionUsed?: () => void; onManage: (tab?: 'skills' | 'tools') => void; creatorContext?: CreatorContext; canvasContext?: WorkingImageContext; projectImage?: ProjectImageReference }) {
  const [draft, setDraft] = useState(() => loadDraft(chat.storedId));
  const [picker, setPicker] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [vision, setVision] = useState(false);
  const [ready, setReady] = useState(false);
  const editImages = Object.values(chat.info.tools ?? {}).flat().includes('miniclaw_edit_image');
  const input = useRef<HTMLTextAreaElement>(null);
  const file = useRef<HTMLInputElement>(null);
  const mounted = useRef(true);
  const draftRef = useRef(draft); draftRef.current = draft;
  function changeDraft(update: (value: Draft) => Draft) {
    const next=update(draftRef.current);draftRef.current=next;setDraft(next);
    if(!saveDraft(chat.storedId,next))setError('浏览器存储已满，草稿暂时无法保存；请保留页面。');
  }
  function updateAttachment(attachment: Attachment, existingOnly = false) {
    const owner = chat.storedId;
    const previous = mounted.current ? draftRef.current : loadDraft(owner);
    if (existingOnly && !previous.attachments.some(a => a.id === attachment.id)) return;
    const next = {...previous, attachments: previous.attachments.some(a=>a.id===attachment.id) ? previous.attachments.map(a=>a.id===attachment.id?attachment:a) : [...previous.attachments, attachment]};
    saveDraft(owner,next);
    if (mounted.current) { draftRef.current=next; setDraft(next); }
  }
  const uploads = useAttachmentQueue(chat.storedId,()=>draftRef.current.attachments.length,updateAttachment);
  const uploading = uploads.active;
  const taskRef = useRef(creatorContext); taskRef.current = creatorContext;
  const requiredSkill = creatorContext?.node==='cover' ? 'canvas-editor' : undefined;
  const defaultSkill = creatorContext?.node==='script' ? 'spoken-script' : undefined;
  const effectiveSkill = requiredSkill || draft.skill || defaultSkill;
  const busyBlocked = controller.connection !== 'open' || chat.busy || chat.running || sending;
  const blocked = busyBlocked || uploading;
  const waiting = hasPendingClarification(chat.clarifications);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { if (!saveDraft(chat.storedId, draft)) setError('浏览器存储已满，草稿暂时无法保存；请保留页面。'); }, [draft, chat.storedId]);
  useEffect(() => { if (suggestion) {
    if (suggestion.attachment && draftRef.current.attachments.length + uploads.count() >= MAX_ATTACHMENTS && !draftRef.current.attachments.some(a => a.id === suggestion.attachment!.id)) { setError('输入框已有10个附件，请先移除一项后再添加修图结果。'); return; }
    changeDraft(v => ({ ...v, ...(suggestion.skill ? {skill: suggestion.skill} : {}), text: suggestion.text || (suggestion.attachment ? v.text : ''), attachments: suggestion.attachment && !v.attachments.some(a => a.id === suggestion.attachment!.id) ? [...v.attachments, suggestion.attachment] : v.attachments })); input.current?.focus(); onSuggestionUsed?.();
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
    if (busyBlocked || !files.length) return;
    setError(''); uploads.addFiles(files);
  }
  async function submit() {
    if (blocked || (!draft.text.trim() && !draft.attachments.length)) return;
    if (waiting && draft.attachments.length) { setError('任务正在等待补充。请先发送文字说明，或在问题卡选择“修改需求”后再补附件；附件草稿已保留。'); return; }
    if (!waiting && !ready && (draft.skill || draft.attachments.length || creatorContext)) { setError('会话正在初始化，技能与附件暂未就绪，请稍候再发送。草稿已保留。'); return; }
    if (uploads.count()) { setError('还有未完成的附件。请重试、重新选择原文件，或移除失败项后发送；已成功附件已保留。'); return; }
    if (draft.attachments.some(a=>a.kind!=='image' && (a.kind==='document'||a.parse_status) && !['ready','partial'].includes(a.parse_status || 'queued'))) { setError('文档尚未解析完成，请等待或在附件上重试解析；草稿已保留。'); return; }
    if (!waiting && creatorContext?.node==='cover' && !canvasContext) { setError('工作图尚未准备，请在创作结果中准备工作图；没有原图时先从顶部“资料”上传。草稿已保留。'); return; }
    if (!waiting && creatorContext?.node==='cover' && !Object.values(chat.info.tools ?? {}).flat().includes('miniclaw_canvas_propose')) { setError('当前对话未加载修图方案工具，请在设置中检查工具配置。草稿已保留。'); return; }
    if (!waiting && !vision && !editImages && draft.attachments.some(a => a.kind === 'image')) { setError('当前模型不支持原生看图。可先移除图片发送文本；配置视觉模型或修图工具后再使用图片。'); return; }
    const sent = draft; setSending(true); setError('');
    try {
      const attachments = [...sent.attachments];
      if (!waiting && creatorContext && (canvasContext || projectImage) && !attachments.some(a=>a.kind==='image') && (vision || editImages)) {
        if (attachments.length >= MAX_ATTACHMENTS) throw new Error('需要附上当前商品图片，请先移除一个附件再发送。草稿已保留。');
        const blob=canvasContext ? await exportBlob(canvasContext.project_id) : await creatorBlob(projectImage!.project,projectImage!.file.id);
        if (!mounted.current || JSON.stringify(taskRef.current)!==JSON.stringify(creatorContext)) throw new Error('任务已切换，未发送内容。草稿已保留。');
        attachments.push(await uploadFile(chat.storedId,new File([blob],canvasContext ? '当前商品工作图.png' : projectImage!.file.name,{type:blob.type || 'image/png'})));
      }
      if (!mounted.current || JSON.stringify(taskRef.current)!==JSON.stringify(creatorContext)) throw new Error('任务已切换，未发送内容。草稿已保留。');
      const skill = requiredSkill || sent.skill || defaultSkill;
      const accepted = waiting ? await controller.send(sent.text,undefined,[]) : creatorContext ? await controller.send(sent.text,skill,attachments,canvasContext,creatorContext) : await controller.send(sent.text,sent.skill,attachments);
      if (mounted.current && accepted) changeDraft(v=>({...v,text:v.text===sent.text ? '' : v.text,attachments:v.attachments.filter(a=>!sent.attachments.some(s=>s.id===a.id))}));
    } catch(e) { if (mounted.current) setError(e instanceof Error ? e.message : String(e)); }
    finally { if (mounted.current) {setSending(false);input.current?.focus();} }
  }
  return <>
    {error && <div className="error-banner" role="alert">{error}<button onClick={() => setError('')} aria-label="关闭提示"><Icon name="close" size={14} /></button></div>}
    <form className="composer" onSubmit={e => { e.preventDefault(); void submit(); }} onDragOver={e => { if (e.dataTransfer.types.includes('Files')) e.preventDefault(); }} onDrop={e => { if (e.dataTransfer.files.length) { e.preventDefault(); void addFiles(Array.from(e.dataTransfer.files)); } }}>
      {draft.skill && !requiredSkill && <div className="composer-skill" title="在当前对话中持续使用，直到移除或切换"><Icon name="skills" size={16} /><span>{skillDetails({ name: draft.skill, description: '' }).title}</span><small>持续使用</small><button type="button" className="icon-button" aria-label="移除技能" disabled={blocked} onClick={() => changeDraft(v => ({ ...v, skill: undefined }))}><Icon name="close" size={14} /></button></div>}
      {!!draft.attachments.length && <div className="attachments composer-attachments">{draft.attachments.map(a => <AttachmentCard key={a.id} variant="tile" attachment={a} owner={chat.storedId} onStatus={value => updateAttachment(value, true)} onRemove={busyBlocked ? undefined : () => changeDraft(v => ({ ...v, attachments: v.attachments.filter(x => x.id !== a.id) }))} />)}</div>}
      {!!uploads.rows.length && <div className="attachment-upload-list" aria-label="附件上传队列">{uploads.rows.map(row=><div key={row.id} className={`attachment-upload-row is-${row.state}`}><div><strong title={row.name}>{row.name}</strong><small>{row.error || (row.state==='queued'?'等待上传':row.state==='uploading'?`上传 ${Math.round(row.bytes/row.size*100)}% · ${fileSize(row.size)}`:'等待重新选择原文件')}</small>{row.state==='uploading'&&<progress aria-label={`${row.name} 上传进度`} max={row.size} value={row.bytes}/>}</div><div className="attachment-upload-actions">{row.state==='failed'&&<button type="button" disabled={busyBlocked} onClick={()=>uploads.retry(row.id)} aria-label={`重试上传 ${row.name}`}>重试</button>}{row.state==='reselect'&&<button type="button" disabled={busyBlocked} onClick={()=>file.current?.click()}>选择原文件</button>}<button type="button" disabled={busyBlocked} onClick={()=>uploads.remove(row.id)} aria-label={`${row.state==='uploading'||row.state==='queued'?'取消上传':'移除'} ${row.name}`}>{row.state==='uploading'||row.state==='queued'?'取消':'移除'}</button></div></div>)}</div>}
      {uploads.error&&<p className="upload-status" role="alert">{uploads.error}</p>}
      <textarea id="message-input" name="message" autoComplete="off" ref={input} aria-label="消息" disabled={controller.connection !== 'open' || chat.busy || !chat.storedId} placeholder={chat.busy || !chat.storedId ? '正在恢复项目对话与草稿…' : creatorContext?.node==='cover' ? '说说图片哪里还不满意，先给修改方案…' : creatorContext?.node==='script' ? '说说口播怎么改，或先让 Agent 起一稿…' : creatorContext?.node==='video' ? '讨论短视频的镜头、节奏、字幕与素材…' : creatorContext ? '说说这件商品的用途、特点和创作方向…' : '输入消息…'} rows={2} value={draft.text} maxLength={100000} onChange={e => changeDraft(v => ({ ...v, text: e.target.value }))}
        onPaste={e => { const images = Array.from(e.clipboardData.files).filter(f => f.type.startsWith('image/')); if (images.length) { e.preventDefault(); void addFiles(images); } }}
        onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229) { e.preventDefault(); void submit(); } }} />
      <div className="composer-toolbar"><div className="composer-options"><input ref={file} type="file" hidden multiple accept={ATTACHMENT_ACCEPT} onChange={e => { void addFiles(Array.from(e.target.files ?? [])); e.target.value = ''; }} />
        <button type="button" className="attach-button icon-button" disabled={busyBlocked} aria-label="添加附件" title="最多10个；PDF、DOCX、CSV、XLSX和文本50 MiB，图片5 MiB" onClick={() => file.current?.click()}><Icon name="plus" /></button>
        <span className="model-badge" translate="no"><span className="model-dot" />{chat.info.model || '连接中'}</span>
        <button className="skill-picker" type="button" disabled={blocked} aria-label={effectiveSkill ? `当前技能：${skillDetails({name:effectiveSkill,description:''}).title}` : creatorContext ? '当前技能：通用对话' : '选择技能'} onClick={() => setPicker(true)}><Icon name="skills" size={16} />{effectiveSkill ? skillDetails({name:effectiveSkill,description:''}).title : creatorContext ? '通用对话' : '选择技能'}{(requiredSkill || !draft.skill && defaultSkill)&&<small>任务默认</small>}<Icon name="chevron" size={14} /></button></div>
        {chat.running ? <button type="button" className="send-button stop" aria-label="停止" onClick={() => void controller.stop()}><Icon name="stop" size={15} /></button> : <button type="submit" className="send-button" aria-label="发送" disabled={blocked || (!draft.text.trim() && !draft.attachments.length)}><Icon name="arrow" size={20} /></button>}
      </div>
      {ready && draft.attachments.some(a => a.kind === 'image') && <p className="upload-status">{vision ? '当前配置会把图片发给模型；识别结果仍需核对。' : editImages ? '当前模型通过图片ID调用修图工具，不直接读取画面。' : '图片可预览，当前模型尚未支持看图。'}</p>}
    </form>
    <div className="composer-hint">Enter 发送 · Shift + Enter 换行<span>草稿自动保存在本机</span></div>
    {picker && <SkillPicker controller={controller} chat={chat} selected={effectiveSkill} requiredSkill={requiredSkill} defaultSkill={requiredSkill||(!draft.skill?defaultSkill:undefined)} onClose={() => { setPicker(false); input.current?.focus(); }} onChoose={name => { changeDraft(v => ({ ...v, skill: requiredSkill ? undefined : name })); setPicker(false); requestAnimationFrame(() => input.current?.focus()); }} onManage={tab => { setPicker(false); onManage(tab); }} />}
  </>;
}
