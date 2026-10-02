import { JsonRpcGatewayClient, gatewayUrl, type ConnectionState, type GatewayEvent } from './gateway';
import { assistantText, finishItems, historyItems, resultFailed, storedSessionId, withToolResults } from './transcript';
import { storedToolRows } from './history-api';
import { prepareSkillPrompt } from './skill-prompt';
import type { ChatState, HistoryRow, SessionRow, SessionSnapshot } from './types';

const blank = (): ChatState => ({
  sessions: [], sessionId: '', storedId: '', items: [], info: {},
  running: false, busy: false, status: '', error: '',
});

export class ChatController {
  readonly client = new JsonRpcGatewayClient({ requestTimeoutMs: 30_000 });
  state = blank();
  connection: ConnectionState = 'idle';
  private listeners = new Set<() => void>();
  private selection = 0;
  private turn = 0;
  private preparingSkill = false;
  private disposed = false;

  constructor() {
    this.client.onAny(event => this.event(event));
    this.client.onState(state => {
      this.connection = state;
      if (state === 'closed' || state === 'error') {
        this.patch({ busy: false, error: '连接已断开。重新连接后会从后端恢复会话；消息不会自动重发。' });
      } else this.notify();
    });
  }

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  private notify() { for (const listener of this.listeners) listener(); }
  private patch(next: Partial<ChatState>) { this.state = { ...this.state, ...next }; this.notify(); }
  private fail(error: unknown) {
    if (!this.disposed) this.patch({ error: error instanceof Error ? error.message : String(error), busy: false });
  }

  async connect() {
    this.patch({ busy: true, error: '' });
    try {
      await this.client.connect(await gatewayUrl(this.connection === 'closed' || this.connection === 'error'));
      await this.refresh();
      if (this.disposed) return;
      const saved = this.state.storedId || localStorage.getItem('miniclaw.selected');
      // A selected older session can be outside the recent sidebar window.
      // Resume by its durable id rather than silently replacing it on reload.
      if (saved) await this.open(saved, true);
      else { this.patch({ busy: false }); await this.newSession(); }
    } catch (error) { this.fail(error); }
  }

  async refresh() {
    const result = await this.client.request<{ sessions: SessionRow[] }>('session.list', { limit: 100 });
    if (!this.disposed) this.patch({ sessions: result.sessions });
  }

  private applySnapshot(snapshot: SessionSnapshot) {
    let items = historyItems(snapshot.messages ?? []);
    const running = Boolean(snapshot.running ?? snapshot.info.running ?? snapshot.inflight?.streaming);
    if (snapshot.inflight?.assistant) items = assistantText(items, snapshot.inflight.assistant, false);
    const storedId = storedSessionId(snapshot);
    localStorage.setItem('miniclaw.selected', storedId);
    this.patch({
      sessionId: snapshot.session_id, storedId, info: snapshot.info, items, running,
      busy: false, status: running ? '正在继续执行' : '',
      error: snapshot.inflight?.error ?? snapshot.info.credential_warning ?? '',
    });
  }

  async newSession() {
    if (this.state.running || this.state.busy) return;
    const generation = ++this.selection;
    this.patch({ busy: true, error: '', status: '' });
    try {
      const snapshot = await this.client.request<SessionSnapshot>('session.create', {
        source: 'desktop', follow_profile_config: true,
      });
      if (!this.disposed && generation === this.selection) this.applySnapshot(snapshot);
    } catch (error) { this.fail(error); }
  }

  async open(storedId: string, recovering = false) {
    if (this.state.running && !recovering) return;
    const generation = ++this.selection;
    this.patch({ busy: true, error: '' });
    try {
      const snapshot = await this.client.request<SessionSnapshot>('session.resume', {
        session_id: storedId, source: 'desktop', eager_build: true,
      });
      if (!this.disposed && generation === this.selection) {
        this.applySnapshot(snapshot);
        if (!this.state.running) await this.reconcile(snapshot.session_id, generation);
      }
    } catch (error) { if (generation === this.selection) this.fail(error); }
  }

  async send(text: string, skill?: string): Promise<boolean> {
    if (!text.trim() || this.state.running || this.state.busy || !this.state.sessionId || this.connection !== 'open') return false;
    const previous = this.state.items;
    const sessionId = this.state.sessionId;
    const turn = ++this.turn;
    this.preparingSkill = Boolean(skill);
    let submitted = false;
    this.patch({ running: true, error: '', status: skill ? '正在加载技能' : '正在提交' });
    try {
      const prompt = skill ? await prepareSkillPrompt(this.client, sessionId, skill, text, () => turn === this.turn && sessionId === this.state.sessionId, Object.values(this.state.info.tools ?? {}).flat()) : { text, display: text };
      if (turn !== this.turn || !this.state.running || this.connection !== 'open' || sessionId !== this.state.sessionId) return false;
      this.preparingSkill = false;
      this.patch({ items: [...previous, { id: crypto.randomUUID(), kind: 'user', text: prompt.display }], status: '正在提交' });
      submitted = true;
      await this.client.request('prompt.submit', { session_id: sessionId, text: prompt.text });
      return true;
    } catch (error) {
      if (turn !== this.turn || sessionId !== this.state.sessionId) return false;
      // An ambiguous timeout/disconnect may already have been accepted. Keep
      // the local text and recover server state; never automatically resend it.
      this.patch({ running: false, status: '' });
      this.fail(error);
      if (submitted && this.connection === 'open') await this.open(this.state.storedId);
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
      const toolRows = result.messages.some(row => row.role === 'tool') ? await storedToolRows(storedId) : [];
      if (this.disposed || generation !== this.selection || turn !== this.turn || this.state.running) return;
      this.patch({ items: historyItems(withToolResults(result.messages, toolRows)) });
      await this.refresh();
    } catch (error) {
      if (generation === this.selection && turn === this.turn) this.fail(error);
    }
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
      'status.update': () => this.patch({ status: String(p.text ?? '') }),
      'error': () => this.patch({ error: String(p.message ?? '后端执行失败'), running: false }),
      'message.complete': () => {
        const outcome = p.status === 'error' ? 'error' : p.status === 'interrupted' ? 'interrupted' : 'done';
        this.patch({
          items: finishItems(assistantText(this.state.items, String(p.text ?? ''), false), outcome),
          running: false, status: outcome === 'interrupted' ? '已停止' : '',
          error: String(p.error ?? p.warning ?? (outcome === 'error' ? p.failure_reason ?? '本轮执行失败' : '')),
        });
        // Completed history is authoritative for tool ordering and durable ids.
        // Preserve partial/error bubbles when the turn was not committed.
        if (outcome === 'done') void this.reconcile(this.state.sessionId, this.selection);
      },
    };
    handlers[event.type]?.();
  }

  dispose() { this.disposed = true; this.client.close(); this.listeners.clear(); }
}
