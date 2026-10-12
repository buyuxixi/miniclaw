import { JsonRpcGatewayClient, gatewayUrl, type ConnectionState, type GatewayEvent } from './gateway';
import { assistantText, finishItems, historyItems, resultFailed, storedSessionId, withToolResults, withCreatorContexts } from './transcript';
import { storedToolRows } from './history-api';
import { prepareSkillPrompt } from './skill-prompt';
import type { ChatState, ClarificationRequest, HistoryRow, SessionRow, SessionSnapshot } from './types';
import type { Attachment, TurnDisplay } from './attachments';
import type {StudioReference} from './StudioReferences';
import { readApi } from './management-api';
import type { CreatorContext, CreatorTurn } from './creator-api';
import { visibleUserText, type DirectorContext } from './turn-display';
import { chatFailure } from './chat-failure';

type TaskControl = {action: 'cancel' | 'revise' | 'new_topic' | 'clarify'; status: string; message: string; no_model?: boolean};

const blank = (): ChatState => ({
  sessions: [], sessionId: '', storedId: '', items: [], info: {}, clarifications: [],
  running: false, busy: false, status: '', error: '',
});

export class ChatController {
  workspace?: { id: string; target?: string; references?: string[] };
  resumeId?: string;
  readonly client = new JsonRpcGatewayClient({ requestTimeoutMs: 30_000 });
  state = blank();
  connection: ConnectionState = 'idle';
  private listeners = new Set<() => void>();
  private selection = 0;
  private turn = 0;
  private preparingSkill = false;
  private disposed = false;
  private clarificationPoll?: ReturnType<typeof setInterval>;
  private clarificationLoading = false;
  private connectAttempt?: Promise<void>;
  private reconnectTimer?: ReturnType<typeof setTimeout>;
  private reconnectDelay = 1000;
  private started = false;

  constructor() {
    this.client.onAny(event => this.event(event));
    this.client.onState(state => {
      this.connection = state;
      if (this.disposed) return;
      if (state === 'closed' || state === 'error') {
        this.patch({ busy: false, openingId: undefined, error: '连接已断开，正在自动重连。恢复后会继续显示原对话，消息不会重复发送。' });
        this.scheduleReconnect();
      } else this.notify();
      if (state === 'open') { this.cancelReconnect(); this.reconnectDelay = 1000; }
      if (state === 'open' && !this.clarificationPoll) this.clarificationPoll = setInterval(() => { void this.refreshClarifications(); }, 3000);
    });
    if (typeof window !== 'undefined') {
      window.addEventListener?.('online', this.wakeConnection);
      window.addEventListener?.('pageshow', this.wakeConnection);
    }
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', this.wakeConnection);
  }

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  private notify() { for (const listener of this.listeners) listener(); }
  private patch(next: Partial<ChatState>) { this.state = { ...this.state, ...next }; this.notify(); }
  private fail(error: unknown) {
    if (!this.disposed) this.patch({ error: error instanceof Error ? error.message : String(error), busy: false, openingId: undefined, status: '' });
  }

  private cancelReconnect() {
    if (this.reconnectTimer !== undefined) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = undefined;
  }

  private scheduleReconnect() {
    if (this.disposed || !this.started || this.connectAttempt || this.reconnectTimer !== undefined) return;
    const delay = this.reconnectDelay;
    this.reconnectDelay = Math.min(delay * 2, 30_000);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = undefined;
      void this.connect();
    }, delay);
  }

  private wakeConnection = () => {
    if (this.disposed || !this.started || (typeof document !== 'undefined' && document.visibilityState === 'hidden')) return;
    if (this.connection === 'closed' || this.connection === 'error') void this.connect();
  };

  connect(): Promise<void> {
    if (this.disposed) return Promise.resolve();
    if (this.connectAttempt) return this.connectAttempt;
    this.started = true;
    this.cancelReconnect();
    this.connectAttempt = this.connectSession().finally(() => {
      this.connectAttempt = undefined;
      if (this.connection === 'closed' || this.connection === 'error') this.scheduleReconnect();
    });
    return this.connectAttempt;
  }

  private async connectSession() {
    // Keep this route stable while a new session emits updates to the Chat UI.
    const workspace = this.workspace;
    this.patch({ busy: true, error: '', workspaceConnecting: !!workspace });
    try {
      const url = await gatewayUrl(this.connection === 'closed' || this.connection === 'error');
      if (this.disposed) return;
      await this.client.connect(url);
      if (this.disposed) return;
      await this.refresh();
      if (this.disposed) return;
      const projectLink = workspace ? await readApi<{chat_id?: string}>(`/api/workspaces/${workspace.id}/chat`) : undefined;
      const explicit = this.state.storedId || this.resumeId;
      const saved = explicit || (workspace ? projectLink?.chat_id : localStorage.getItem('miniclaw.selected'));
      // A selected older session can be outside the recent sidebar window.
      // Resume by its durable id rather than silently replacing it on reload.
      if (saved) {
        await this.open(saved, true);
        if (!this.state.sessionId && this.state.error === 'session not found') {
          // Empty sessions may have a provisional id but no durable row after
          // a restart. Keep their draft when creating the replacement.
          const draft = localStorage.getItem(`miniclaw.draft.${saved}`);
          this.patch({ busy: false }); await this.newSession(draft ?? undefined);
          this.patch({ error: '之前的会话已不可用。已新建对话，文字草稿已保留；旧附件请重新上传。' });
        }
      }
      else { this.patch({ busy: false }); await this.newSession(); }
      if (workspace && !explicit && !this.state.running) {
        const linked = await readApi<{chat_id?: string}>(`/api/workspaces/${workspace.id}/chat`);
        if (linked.chat_id && linked.chat_id !== this.state.storedId) await this.open(linked.chat_id);
        if (!linked.chat_id && this.state.sessionId) {
          const {writeApi} = await import('./management-api');
          await writeApi(`/api/workspaces/${workspace.id}/chat`, 'POST', {session_id:this.state.sessionId});
        }
      }
    } catch (error) {
      if (this.connection !== 'open') {
        this.connection = 'error';
        this.fail(new Error('暂时无法连接，正在自动重连。请确认本机工作台服务仍在运行。'));
      } else this.fail(error);
    }
    finally { if (!this.disposed) this.patch({ workspaceConnecting: false }); }
  }

  async refresh() {
    const result = await this.client.request<{ sessions: SessionRow[] }>('session.list', { limit: 100 });
    if (!this.disposed) this.patch({ sessions: result.sessions });
  }

  private applySnapshot(snapshot: SessionSnapshot, restoredItems?: ChatState['items']) {
    let items = restoredItems ?? historyItems(snapshot.messages ?? []);
    const running = Boolean(snapshot.running ?? snapshot.info.running ?? snapshot.inflight?.streaming);
    if (snapshot.inflight?.assistant) items = assistantText(items, snapshot.inflight.assistant, false);
    const storedId = storedSessionId(snapshot);
    localStorage.setItem('miniclaw.selected', storedId);
    this.resumeId = storedId;
    // Preserve the selected history/new conversation across refresh without
    // changing the workspace's durable project conversation.
    if (typeof location !== 'undefined' && (location.pathname?.startsWith('/c/') || location.search?.includes('workspace=') || location.search?.includes('chat=')) && typeof history !== 'undefined') {
      const url = new URL(location.href);
      if(location.pathname?.startsWith('/c/')){url.pathname='/c/'+encodeURIComponent(storedId);url.searchParams.delete('session');}
      else url.searchParams.set('session', storedId);
      if (this.state.storedId && this.state.storedId !== storedId) {url.searchParams.delete('message');url.searchParams.delete('target');}
      history.replaceState(null, '', url);
    }
    this.patch({
      sessionId: snapshot.session_id, storedId, info: snapshot.info, items, running,
      clarifications: [],
      busy: false, openingId: undefined, status: running ? '正在继续执行' : '',
      error: snapshot.inflight?.error ? chatFailure(snapshot.inflight) : snapshot.info.credential_warning ?? '',
    });
    void this.refreshClarifications();
  }

  async refreshClarifications() {
    if (this.disposed || this.connection !== 'open' || !this.state.sessionId || this.clarificationLoading) return;
    const sessionId = this.state.sessionId;
    this.clarificationLoading = true;
    try {
      const result = await this.client.request<{requests: ClarificationRequest[]}>('miniclaw.clarification.list', {session_id: sessionId});
      if (!this.disposed && this.state.sessionId === sessionId) this.patch({clarifications: result.requests});
    } catch { /* Connection recovery owns errors; keep the last authoritative cards. */ }
    finally { this.clarificationLoading = false; }
  }

  async answerClarification(request: ClarificationRequest, answers: Record<string, string | string[]>, submissionId: string) {
    const result = await this.client.request<{request: ClarificationRequest}>('miniclaw.clarification.answer', {
      session_id: this.state.sessionId, clarification_id: request.id, expected_version: request.version,
      answers, client_submission_id: submissionId,
    });
    this.patch({clarifications: (this.state.clarifications ?? []).map(r => r.id === request.id ? result.request : r)});
    await this.refreshClarifications();
  }

  async cancelClarification(request: ClarificationRequest, revise = false) {
    const result = await this.client.request<{request: ClarificationRequest}>(revise ? 'miniclaw.task.revise' : 'miniclaw.clarification.cancel', {
      session_id: this.state.sessionId, clarification_id: request.id,
    });
    this.patch({clarifications: (this.state.clarifications ?? []).map(r => r.id === request.id ? result.request : r),
      status: revise ? '在输入框写下新的要求，已完成结果会保留。' : '已取消等待任务，可以发送新话题。'});
  }

  async newSession(recoveredDraft?: string) {
    if (this.state.running || this.state.busy) return;
    const generation = ++this.selection;
    this.patch({ busy: true, error: '', status: '' });
    try {
      const snapshot = await this.client.request<SessionSnapshot>('session.create', {
        source: 'desktop', follow_profile_config: true,
      });
      if (!this.disposed && generation === this.selection) {
        if (recoveredDraft) {
          // Copy before notifying React, so Composer cannot overwrite it with
          // its initial blank state. Attachment ownership remains the old id.
          try {
            const value = JSON.parse(recoveredDraft);
            localStorage.setItem(`miniclaw.draft.${storedSessionId(snapshot)}`, JSON.stringify({ ...value, attachments: [] }));
          } catch { /* malformed local draft */ }
        }
        this.applySnapshot(snapshot);
      }
    } catch (error) { this.fail(error); }
  }

  async open(storedId: string, recovering = false) {
    if (this.state.running && !recovering) return;
    const generation = ++this.selection;
    this.patch({ busy: true, openingId: storedId, status: '正在恢复对话…', error: '' });
    try {
      const snapshot = await this.client.request<SessionSnapshot>('session.resume', {
        session_id: storedId, source: 'desktop', eager_build: true,
      });
      if (!this.disposed && generation === this.selection) {
        const running = Boolean(snapshot.running ?? snapshot.info.running ?? snapshot.inflight?.streaming);
        let warning = '';
        const items = running ? undefined : await this.restoreItems(snapshot.messages ?? [], storedSessionId(snapshot)).catch(() => {
          warning = '对话已恢复，附件或工具详情暂时未能补齐；请稍后重新打开。';
          return undefined;
        });
        if (!this.disposed && generation === this.selection) { this.applySnapshot(snapshot, items); if(warning) this.patch({error:warning}); }
      }
    } catch (error) { if (generation === this.selection) this.fail(error); }
  }

  async send(text: string, skill?: string, attachments: Attachment[] = [], canvasContext?: { project_id: string; revision: number; layer_id: string; mode?: 'plan' | 'edit' | 'context' }, creatorContext?: CreatorContext, directorContext?: DirectorContext): Promise<boolean> {
    if ((!text.trim() && !attachments.length) || this.state.running || this.state.busy || !this.state.sessionId || this.connection !== 'open') return false;
    const waiting = this.state.clarifications?.some(request=>request.status==='pending');
    if (waiting && attachments.length) {
      this.patch({error: '任务正在等待补充。请先发送文字说明，或在问题卡选择“修改需求”后再补附件；附件草稿已保留。'});
      return false;
    }
    const previous = this.state.items;
    const sessionId = this.state.sessionId;
    const generation = this.selection;
    const workspace = this.workspace ? {...this.workspace,...(this.workspace.references?{references:[...this.workspace.references]}:{})} : undefined;
    const storedId = this.state.storedId;
    const turn = ++this.turn;
    this.preparingSkill = Boolean(skill) && !waiting;
    let submitted = false;
    this.patch({ running: true, error: '', status: skill && !waiting ? '正在加载技能' : '正在提交' });
    try {
      const prompt = skill && !waiting ? await prepareSkillPrompt(this.client, sessionId, skill, text, () => turn === this.turn && sessionId === this.state.sessionId, Object.values(this.state.info.tools ?? {}).flat()) : { text, display: text };
      if (turn !== this.turn || generation !== this.selection || !this.state.running || this.connection !== 'open' || sessionId !== this.state.sessionId) return false;
      this.preparingSkill = false;
      const userId = crypto.randomUUID();
      let studioContext: {workspace: string; target?: string; revision: number; references?:string[]} | undefined;
      if (workspace && !waiting) {
        const linked = await readApi<{chat_id?: string}>(`/api/workspaces/${workspace.id}/chat`);
        if (linked.chat_id !== storedId) throw Error('当前对话未关联此项目，请从项目入口恢复对话。草稿已保留。');
        {
          const record = await readApi<{revision:number;state?:{assets:{id:string}[]}}>(`/api/workspaces/${workspace.id}`);
          studioContext = {workspace:workspace.id,target:workspace.target,revision:record.revision,...(workspace.references?{references:workspace.references}:{})};
          const selectedImage=record.state?.assets.some(a=>a.id===workspace.target);
          if((skill==='canvas-editor'||!skill&&selectedImage&&Object.values(this.state.info.tools??{}).flat().includes('miniclaw_canvas_view')) && !canvasContext && workspace.target) {
            const {writeApi}=await import('./management-api');
            try {
              const meta=await writeApi<{project?:string;revision:number;layer:string}>(`/api/workspaces/${workspace.id}/editing-target`,'POST',{target:workspace.target,session_id:sessionId});
              if(meta.project)canvasContext={project_id:meta.project,revision:meta.revision,layer_id:meta.layer,mode:skill?'plan':'context'};
              else if(skill)throw Error('请返回自由画布，在导演助手中选择要修改的参考图。草稿已保留。');
            } catch(e) {if(skill)throw e;}
          }
        }
      }
      if (turn !== this.turn || generation !== this.selection || sessionId !== this.state.sessionId) return false;
      if (workspace?.id !== this.workspace?.id || workspace?.target !== this.workspace?.target || JSON.stringify(workspace?.references)!==JSON.stringify(this.workspace?.references)) throw Error('项目引用已变化，请重新发送。草稿已保留。');
      this.patch({ items: [...previous, { id: userId, kind: 'user', text: prompt.display, attachments, skill:waiting?undefined:skill }], status: '正在提交' });
      submitted = true;
      const accepted = await this.client.request<{ warning?: string; creator_context?: CreatorTurn; studio_refs?:StudioReference[]; task_control?:TaskControl }>('miniclaw.turn.submit', waiting ? {session_id:sessionId,text,attachments:[]} : { session_id: sessionId, text, skill, attachments: attachments.map(a => a.id), ...(canvasContext ? { canvas_context: canvasContext } : {}), ...(creatorContext ? { creator_context: creatorContext } : {}), ...(studioContext ? {studio_context:studioContext} : {}), ...(directorContext ? {director_context:directorContext} : {}) });
      if (turn !== this.turn || sessionId !== this.state.sessionId || generation !== this.selection) return false;
      if (accepted.task_control?.no_model) {
        const control=accepted.task_control;
        this.patch({running:false,status:control.action==='clarify'?'':control.message,error:control.action==='clarify'?control.message:accepted.warning??'',...(control.action==='clarify'?{items:previous}:{})});
        if(control.action!=='clarify')await this.reconcile(sessionId,generation);
        if(this.disposed||turn!==this.turn||sessionId!==this.state.sessionId||generation!==this.selection)return false;
        await this.refreshClarifications();
        if(this.disposed||turn!==this.turn||sessionId!==this.state.sessionId||generation!==this.selection)return false;
        if(accepted.warning&&!this.state.error.includes(accepted.warning))this.patch({error:[this.state.error,accepted.warning].filter(Boolean).join(' ')});
        return control.action!=='clarify';
      }
      if (accepted.creator_context) this.patch({ items: withCreatorContexts(this.state.items.map(item => item.id === userId ? { ...item, creator_context: accepted.creator_context } : item)) });
      if (accepted.studio_refs) this.patch({items:this.state.items.map(item=>item.id===userId?{...item,studio_refs:accepted.studio_refs}:item)});
      if (accepted.warning) this.patch({ error: accepted.warning });
      if (!this.state.running) await this.reconcile(sessionId, generation);
      if(this.disposed||turn!==this.turn||sessionId!==this.state.sessionId||generation!==this.selection)return false;
      return true;
    } catch (error) {
      if (turn !== this.turn || generation !== this.selection || sessionId !== this.state.sessionId) return false;
      // An ambiguous timeout/disconnect may already have been accepted. Keep
      // the local text and recover server state; never automatically resend it.
      this.patch({ running: false, status: '' });
      this.fail(error);
      const code = typeof error === 'object' && error ? (error as { code?: number }).code : undefined;
      if (code === 4200 || code === 4000) this.patch({ items: previous });
      else if (submitted && this.connection === 'open') await this.open(this.state.storedId);
      return false;
    } finally { if (turn === this.turn) this.preparingSkill = false; }
  }

  async stop() {
    if (this.preparingSkill) {
      this.preparingSkill = false;
      ++this.turn;
      this.patch({ running: false, status: '' });
      return;
    }
    try {
      this.patch({ status: '正在停止' });
      const result = await this.client.request<{ interrupted?: boolean; status: string }>('session.interrupt', {
        session_id: this.state.sessionId,
      });
      if (result.status === 'not_interrupted') this.patch({ running: false, status: '' });
    } catch (error) { this.fail(error); }
  }

  async rename(title: string): Promise<boolean> {
    if (!title.trim() || this.state.running || this.state.busy || this.connection !== 'open') return false;
    const generation = this.selection;
    this.patch({ busy: true, error: '' });
    try {
      const result = await this.client.request<{ title: string }>('session.title', {
        session_id: this.state.sessionId, title: title.trim(),
      });
      if (!this.disposed && generation === this.selection) {
        this.patch({ info: { ...this.state.info, title: result.title } });
        await this.refresh();
      }
      return true;
    } catch (error) { this.fail(error); return false; }
    finally { if (generation === this.selection) this.patch({ busy: false }); }
  }

  async compressContext(focus: string): Promise<Record<string, unknown> | undefined> {
    if (this.state.running || this.state.busy || this.connection !== 'open') return;
    const sessionId = this.state.sessionId;
    const generation = this.selection;
    this.patch({ busy: true, error: '', status: '正在压缩上下文' });
    try {
      const result = await this.client.request<Record<string, unknown>>('session.compress', {
        session_id: sessionId, focus_topic: focus,
      }, 180_000);
      if (this.disposed || generation !== this.selection) return;
      if (result.status === 'pending') {
        this.patch({ running: true, status: '压缩结果未知，请重新连接以恢复后端状态' });
        return result;
      }
      if (result.info) {
        const info = { ...this.state.info, ...result.info as SessionSnapshot['info'] };
        const storedId = info.stored_session_id || this.state.storedId;
        localStorage.setItem('miniclaw.selected', storedId);
        this.patch({ info, storedId });
      }
      await this.reconcile(sessionId, generation);
      this.patch({ status: '' });
      return result;
    } catch (error) {
      this.fail(error);
      // A timed-out compression may still be running. Require reattachment
      // before submitting another turn rather than automatically retrying it.
      this.patch({ running: true, status: '压缩结果未知，请重新连接以恢复后端状态' });
      return;
    } finally { if (generation === this.selection) this.patch({ busy: false }); }
  }

  private async reconcile(sessionId: string, generation: number) {
    const turn = this.turn;
    try {
      const storedId = this.state.storedId;
      const result = await this.client.request<{ messages: HistoryRow[] }>('session.history', { session_id: sessionId });
      if (this.disposed || generation !== this.selection || turn !== this.turn || this.state.running) return;
      // A new empty session may exist only in the live gateway until its first
      // persisted message. Fetch durable tool bodies only when replay has tools.
      const items = await this.restoreItems(result.messages, storedId);
      if (this.disposed || generation !== this.selection || turn !== this.turn || this.state.running) return;
      this.patch({ items });
      await this.refresh();
    } catch (error) {
      if (generation === this.selection && turn === this.turn) this.fail(error);
    }
  }

  private async restoreItems(messages: HistoryRow[], storedId: string) {
    const [toolRows, displays] = await Promise.all([
      messages.some(row => row.role === 'tool') ? storedToolRows(storedId) : Promise.resolve([]),
      messages.some(row => row.role === 'user') ? readApi<Record<string, TurnDisplay>>(`/api/miniclaw/turns?owner=${encodeURIComponent(storedId)}`) : Promise.resolve({} as Record<string, TurnDisplay>),
    ]);
    return withCreatorContexts(historyItems(withToolResults(messages, toolRows)).map(item => {
      const display = displays[item.id.replace('row-', '')];
      return item.kind === 'user' && display ? { ...item, text: visibleUserText(display.text), attachments: display.attachments, skill: display.skill, creator_context: display.creator_context,studio_refs:display.studio_refs } : item;
    }));
  }

  private event(event: GatewayEvent) {
    if (this.disposed || event.session_id !== this.state.sessionId) return;
    const p = (event.payload ?? {}) as Record<string, unknown>;
    const handlers: Record<string, () => void> = {
      'session.info': () => this.patch({ info: { ...this.state.info, ...p } }),
      'session.title': () => {
        this.patch({ info: { ...this.state.info, title: String(p.title ?? '') } });
        void this.refresh().catch(error => this.fail(error));
      },
      'message.start': () => this.patch({ running: true, status: '正在思考' }),
      'message.delta': () => this.patch({ items: assistantText(this.state.items, String(p.text ?? ''), true), status: '正在回复' }),
      'message.interim': () => {
        const items = assistantText(this.state.items, String(p.text ?? ''), false);
        this.patch({ items: finishItems(items, 'done') });
      },
      'tool.start': () => this.patch({
        status: '正在执行工具',
        items: [...this.state.items, {
          id: String(p.tool_id), kind: 'tool', text: '', name: String(p.name),
          args: p.args ?? p.args_text, status: 'running',
        }],
      }),
      'tool.complete': () => this.patch({ items: this.state.items.map(item => item.id === p.tool_id ? {
        ...item, result: p.result ?? p.result_text ?? p.summary,
        status: resultFailed(p.result ?? p.result_text) ? 'error' : 'done',
      } : item) }),
      'status.update': () => { this.patch({ status: String(p.text ?? '') }); if(p.kind === 'clarification') void this.refreshClarifications(); },
      'error': () => this.patch({ error: String(p.message ?? '后端执行失败'), running: false }),
      'message.complete': () => {
        const outcome = p.status === 'error' ? 'error' : p.status === 'interrupted' ? 'interrupted' : 'done';
        const text = String(p.text ?? '');
        const completedItems = outcome !== 'done' && !text ? this.state.items : assistantText(this.state.items, text, false);
        this.patch({
          items: finishItems(completedItems, outcome),
          running: false, status: outcome === 'interrupted' ? '已停止' : '',
          error: outcome === 'error' ? chatFailure(p) : String(p.error ?? p.warning ?? ''),
        });
        // Completed history is authoritative for tool ordering and durable ids.
        // Preserve partial/error bubbles when the turn was not committed.
        if (outcome === 'done') void this.reconcile(this.state.sessionId, this.selection);
        void this.refreshClarifications();
      },
    };
    handlers[event.type]?.();
  }

  dispose() {
    this.disposed = true;
    this.cancelReconnect();
    if (typeof window !== 'undefined') {
      window.removeEventListener?.('online', this.wakeConnection);
      window.removeEventListener?.('pageshow', this.wakeConnection);
    }
    if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', this.wakeConnection);
    if(this.clarificationPoll) clearInterval(this.clarificationPoll);
    this.client.close(); this.listeners.clear();
  }
}
