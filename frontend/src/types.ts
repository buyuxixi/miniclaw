import type { Attachment } from './attachments';
import type {StudioReference} from './StudioReferences';
import type { CreatorTurn } from './creator-api';
export interface HistoryRow {
  role: string;
  text?: string | null;
  content?: unknown;
  name?: string;
  args?: Record<string, unknown> | string;
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
  attachments?: Attachment[];
  studio_refs?: StudioReference[];
  skill?: string;
  creator_context?: CreatorTurn;
}

export interface SessionRow {
  id: string;
  title: string;
  preview: string;
  message_count: number;
  archived?: boolean;
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
  inflight?: { user?: string; assistant?: string; streaming?: boolean; error?: string; error_surface?: {code?: string} };
}

export interface ChatState {
  clarifications?: ClarificationRequest[];
  sessions: SessionRow[];
  sessionId: string;
  storedId: string;
  items: ChatItem[];
  info: SessionInfo;
  running: boolean;
  busy: boolean;
  workspaceConnecting?: boolean;
  openingId?: string;
  status: string;
  error: string;
}

export interface ClarificationRequest {
  id: string;
  task_id: string;
  status: 'pending' | 'answered' | 'timed_out' | 'canceled' | 'superseded' | 'blocked';
  version: number;
  deadline: number;
  task_status?: string;
  reason?: string;
  questions: {id: string; question: string; choices: string[]; multi_select: boolean}[];
  answers?: Record<string, string | string[]>;
}
