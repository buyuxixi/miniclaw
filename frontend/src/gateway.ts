// Reuse Hermes framing, RPC correlation and reconnect replay. The browser
// heartbeat accounts for suspended/throttled timers before declaring a loss.
import {JsonRpcGatewayClient as HermesGatewayClient, type GatewayClientOptions} from '../../hermes-agent/apps/shared/src/json-rpc-gateway';
import {DEFAULT_HEARTBEAT_DEADLINE_MS, DEFAULT_HEARTBEAT_INTERVAL_MS} from '../../hermes-agent/apps/shared/src/json-rpc-channel';
export type { ConnectionState, GatewayEvent } from '../../hermes-agent/apps/shared/src/json-rpc-gateway';

export class JsonRpcGatewayClient extends HermesGatewayClient {
  private heartbeatTimer?: ReturnType<typeof setInterval>;
  private probe?: AbortController;
  private lastAlive = 0;
  private lastTick = 0;
  private readonly interval: number;
  private readonly deadline: number;

  constructor(options: GatewayClientOptions = {}) {
    super({...options, heartbeatIntervalMs: 0});
    this.interval = options.heartbeatIntervalMs ?? DEFAULT_HEARTBEAT_INTERVAL_MS;
    this.deadline = options.heartbeatDeadlineMs ?? DEFAULT_HEARTBEAT_DEADLINE_MS;
    this.onState(state => { if (state !== 'open') this.stopBrowserHeartbeat(); });
    this.onAny(() => { this.lastAlive = Date.now(); });
    this.on('gateway.ready', event => {
      if (event.payload?.heartbeat === true) this.startBrowserHeartbeat();
    });
  }

  private startBrowserHeartbeat() {
    this.stopBrowserHeartbeat();
    if (this.interval <= 0 || this.deadline <= 0) return;
    this.lastAlive = this.lastTick = Date.now();
    this.heartbeatTimer = setInterval(() => {
      const now = Date.now();
      // Time spent with a paused event loop is not time spent waiting for a
      // probe. Give the backend a fresh response window and send a new probe.
      if (now - this.lastTick >= this.deadline) this.resetProbe();
      this.lastTick = now;
      if (now - this.lastAlive >= this.deadline) {
        this.invalidate('连接心跳未响应');
        return;
      }
      this.sendProbe();
    }, this.interval);
    if (typeof window !== 'undefined') {
      window.addEventListener?.('pageshow', this.wakeHeartbeat);
      window.addEventListener?.('online', this.wakeHeartbeat);
    }
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', this.wakeHeartbeat);
  }

  private wakeHeartbeat = () => {
    if ((typeof document !== 'undefined' && document.visibilityState === 'hidden') || this.connectionState !== 'open') return;
    this.resetProbe();
    this.lastTick = Date.now();
    this.sendProbe();
  };

  private resetProbe() {
    const previous = this.probe;
    this.probe = undefined;
    previous?.abort();
    this.lastAlive = Date.now();
  }

  private sendProbe() {
    if (this.probe || this.connectionState !== 'open') return;
    const probe = new AbortController();
    this.probe = probe;
    // The browser-aware timer owns the deadline; a second wall-clock RPC
    // timeout would incorrectly expire the probe during browser suspension.
    void this.request('gateway.ping', {}, 0, probe.signal).then(() => {
      if (this.probe === probe) this.lastAlive = Date.now();
    }, () => {
      if (this.probe === probe) this.invalidate('连接探测失败');
    }).finally(() => { if (this.probe === probe) this.probe = undefined; });
  }

  private stopBrowserHeartbeat() {
    if (this.heartbeatTimer !== undefined) clearInterval(this.heartbeatTimer);
    this.heartbeatTimer = undefined;
    const previous = this.probe;
    this.probe = undefined;
    previous?.abort();
    if (typeof window !== 'undefined') {
      window.removeEventListener?.('pageshow', this.wakeHeartbeat);
      window.removeEventListener?.('online', this.wakeHeartbeat);
    }
    if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', this.wakeHeartbeat);
  }
}

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
