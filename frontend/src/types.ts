export interface HistoryRow {
  role: string;
  text?: string | null;
  content?: unknown;
  name?: string;
  args?: Record<string, unknown>;
  tool_call_id?: string;
  row_id?: number;
  id?: number;
  display_kind?: string;
}

export interface ChatItem {
  id: string;
  kind: 'user' | 'assistant' | 'tool';
  text: string;
  name?: string;
  args?: unknown;
  result?: unknown;
  status?: 'running' | 'done' | 'error' | 'interrupted' | 'unavailable';
}

export interface SessionRow {
  id: string;
  title: string;
  preview: string;
  message_count: number;
}

export interface SessionInfo {
  tools?: Record<string, string[]>;
  skills?: Record<string, string[]>;
  provider?: string;
  usage?: { input?: number; output?: number; calls?: number; compressions?: number; cost_usd?: number | null; cost_status?: string };
  model?: string;
  title?: string;
  credential_warning?: string;
  running?: boolean;
  stored_session_id?: string;
}

export interface SessionSnapshot {
  session_id: string;
  stored_session_id?: string;
  session_key?: string;
  messages: HistoryRow[];
  info: SessionInfo;
  running?: boolean;
  inflight?: { user?: string; assistant?: string; streaming?: boolean; error?: string };
}

export interface ChatState {
  sessions: SessionRow[];
  sessionId: string;
  storedId: string;
  items: ChatItem[];
  info: SessionInfo;
  running: boolean;
  busy: boolean;
  status: string;
  error: string;
}
