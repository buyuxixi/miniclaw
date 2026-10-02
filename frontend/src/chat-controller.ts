import { JsonRpcGatewayClient, gatewayUrl, type ConnectionState, type GatewayEvent } from './gateway';
import { assistantText, finishItems, historyItems, resultFailed, storedSessionId, withToolResults } from './transcript';
import { storedToolRows } from './history-api';
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
      if (saved && this.state.sessions.some(row => row.id === saved)) await this.open(saved, true);
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

  async send(text: string): Promise<boolean> {
    if (!text.trim() || this.state.running || this.state.busy || !this.state.sessionId || this.connection !== 'open') return false;
    const previous = this.state.items;
    const sessionId = this.state.sessionId;
    ++this.turn;
    this.patch({
      items: [...previous, { id: crypto.randomUUID(), kind: 'user', text }],
      running: true, error: '', status: '正在提交',
    });
    try {
      await this.client.request('prompt.submit', { session_id: sessionId, text });
      return true;
    } catch (error) {
      // An ambiguous timeout/disconnect may already have been accepted. Keep
      // the local text and recover server state; never automatically resend it.
      this.patch({ running: false });
      this.fail(error);
      if (this.connection === 'open') await this.open(this.state.storedId);
      return false;
    }
  }

  async stop() {
    try {
      this.patch({ status: '正在停止' });
      const result = await this.client.request<{ interrupted?: boolean; status: string }>('session.interrupt', {
        session_id: this.state.sessionId,
      });
      if (result.status === 'not_interrupted') this.patch({ running: false, status: '' });
    } catch (error) { this.fail(error); }
  }

  private async reconcile(sessionId: string, generation: number) {
    const turn = this.turn;
    try {
      const storedId = this.state.storedId;
      const [result, toolRows] = await Promise.all([
        this.client.request<{ messages: HistoryRow[] }>('session.history', { session_id: sessionId }),
        storedToolRows(storedId),
      ]);
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
