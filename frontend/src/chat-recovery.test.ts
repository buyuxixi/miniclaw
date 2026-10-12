// @vitest-environment jsdom
import {expect, test, vi} from 'vitest';
import {ChatController} from './chat-controller';

const callbacks = vi.hoisted(() => ({event: undefined as undefined | ((event: unknown) => void)}));
const rpc = vi.hoisted(() => vi.fn());
vi.mock('./gateway', () => ({gatewayUrl: async () => '/api/ws', JsonRpcGatewayClient: class {
  onAny(fn: (event: unknown) => void) { callbacks.event = fn; }
  onState() {} close() {} request = rpc;
}}));
vi.mock('./management-api', () => ({readApi: vi.fn(async () => ({}))}));

test('progress and billing failure preserve partial output and never resend', () => {
  const chat = new ChatController();
  chat.state = {...chat.state, sessionId: 'live', items: [{id: 'reply', kind: 'assistant', text: '已分析第一部分', status: 'running'}]};
  rpc.mockClear();
  callbacks.event?.({type: 'status.update', session_id: 'live', payload: {text: '正在切换备用模型 qwen-plus'}});
  expect(chat.state.status).toContain('备用模型');
  callbacks.event?.({type: 'message.complete', session_id: 'live', payload: {status: 'error', text: '', error: 'HTTP 402 vendor body', error_surface: {code: 'billing'}}});
  expect(chat.state.error).toContain('额度');
  expect(chat.state.error).toContain('先核对');
  expect(chat.state.error).not.toContain('vendor');
  expect(chat.state.items.some(item => item.text.includes('已分析第一部分'))).toBe(true);
  expect(rpc.mock.calls.every(([method]) => method !== 'prompt.submit')).toBe(true);
  expect(chat.state.running).toBe(false);
  chat.dispose();
});

test('reconnection restores the same friendly error and retained partial answer', async () => {
  rpc.mockResolvedValue({session_id: 'live', stored_session_id: 'chat', info: {}, messages: [],
    inflight: {assistant: '半段回复', error: 'SDK read timeout', error_surface: {code: 'timeout'}}});
  const chat = new ChatController();
  await chat.open('chat');
  expect(chat.state.error).toContain('超时');
  expect(chat.state.items.some(item => item.text.includes('半段回复'))).toBe(true);
  expect(rpc.mock.calls.every(([method]) => method !== 'prompt.submit')).toBe(true);
  chat.dispose();
});
