const preserved = '已收到的回复和已完成的操作会保留；收费或写入操作如结果未知，请先核对任务记录。';
const reasons: Record<string, string> = {
  billing: '模型账户额度或余额不足。请检查额度或配置可用备用服务后继续。',
  auth: '模型服务鉴权失败。请检查对应服务的 Key、地域和权限。',
  auth_permanent: '模型服务鉴权失败。请检查对应服务的 Key、地域和权限。',
  rate_limit: '模型服务持续限流。自动恢复已停止，请稍后继续。',
  timeout: '模型服务响应超时。自动恢复已停止，请稍后继续。',
  context_overflow: '对话超出模型上下文容量。请压缩对话或减少附件后继续。',
  format_error: '模型请求参数不被服务接受。请调整模型配置或输入后继续。',
  model_not_found: '配置的模型不可用。请检查模型名称和服务权限。',
};

/** Render structured failures; never expose a provider exception as the only recovery guidance. */
export function chatFailure(payload: {error?: unknown; failure_reason?: unknown; error_surface?: unknown}): string {
  const error = typeof payload.error === 'string' ? payload.error : '';
  // The hosted backend already supplies detailed Chinese recovery instructions.
  if (error.includes('已收到的回复和已完成的操作会保留')) return error;
  const surface = payload.error_surface as {code?: string} | undefined;
  const code = surface?.code ?? String(payload.failure_reason ?? '');
  if (reasons[code]) return reasons[code] + preserved;
  if (error && /[\u4e00-\u9fff]/.test(error)) return error;
  return '本轮未能完成，自动恢复已停止。请检查服务状态后继续。' + preserved;
}
