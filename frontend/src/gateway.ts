// Reuse the pinned harness client: framing, heartbeat, RPC correlation and
// reconnect replay stay aligned with Hermes, without a second Agent loop.
export { JsonRpcGatewayClient } from '../../hermes-agent/apps/shared/src/json-rpc-gateway';
export type { ConnectionState, GatewayEvent } from '../../hermes-agent/apps/shared/src/json-rpc-gateway';

declare global {
  interface Window {
    __HERMES_SESSION_TOKEN__?: string;
    __HERMES_AUTH_REQUIRED__?: boolean;
    __HERMES_BASE_PATH__?: string;
  }
}

export async function gatewayUrl(refreshToken = false): Promise<string> {
  if (window.__HERMES_AUTH_REQUIRED__) {
    throw new Error('当前版本用于本机单人运行；远端登录适配尚未完成。');
  }
  let token = window.__HERMES_SESSION_TOKEN__;
  if (refreshToken) {
    // Hermes mints a fresh loopback session token on every process start.
    // Re-read its supported HTML handshake before reconnecting an old page.
    const base = window.__HERMES_BASE_PATH__ ?? '';
    const response = await fetch(`${base}/`, { cache: 'no-store', signal: AbortSignal.timeout(15_000) });
    if (!response.ok) throw new Error(`读取本机连接凭据失败（HTTP ${response.status}）`);
    const html = await response.text();
    token = html.match(/window\.__HERMES_SESSION_TOKEN__="([^"]+)"/)?.[1];
    if (token) window.__HERMES_SESSION_TOKEN__ = token;
  }
  if (!token) throw new Error('缺少本机连接凭据，请通过 miniclaw 启动脚本打开页面。');
  const url = new URL(`${window.__HERMES_BASE_PATH__ ?? ''}/api/ws`, location.href);
  url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  url.searchParams.set('token', token);
  return url.toString();
}
