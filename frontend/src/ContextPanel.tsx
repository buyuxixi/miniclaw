import { useEffect, useState } from 'react';
import type { ChatController } from './chat-controller';
import type { ChatState } from './types';

interface Breakdown {
  categories: { id: string; label: string; tokens: number }[];
  context_used: number; context_max: number; context_estimated: boolean;
  context_source: string; estimated_total: number;
  context_files?: { path: string; loaded: boolean; status: string; est_tokens: number }[];
}
const labels: Record<string, string> = { system_prompt: '系统提示词', tool_definitions: '工具定义', rules: '项目规则', skills: '技能索引', mcp: 'MCP', subagent_definitions: '子 Agent 定义', memory: '记忆', conversation: '模型会话历史' };

export function ContextPanel({ controller, chat }: { controller: ChatController; chat: ChatState }) {
  const [snapshot, setSnapshot] = useState<Breakdown>();
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [focus, setFocus] = useState('');
  const [feedback, setFeedback] = useState<Record<string, unknown>>();
  useEffect(() => { setFeedback(undefined); }, [chat.sessionId]);
  useEffect(() => {
    let active = true;
    setSnapshot(undefined); setError('');
    if (!chat.sessionId || chat.running || chat.busy || controller.connection !== 'open') return;
    void controller.client.request<Breakdown>('session.context_breakdown', { session_id: chat.sessionId })
      .then(value => { if (active) setSnapshot(value); })
      .catch(reason => { if (active) setError(String(reason)); });
    return () => { active = false; };
  }, [controller, chat.sessionId, chat.running, chat.busy, revision]);
  const blocked = chat.running || chat.busy || controller.connection !== 'open';
  async function compress() {
    setFeedback(undefined);
    const result = await controller.compressContext(focus);
    if (result) setFeedback(result);
    setRevision(value => value + 1);
  }
  const tools = Object.entries(chat.info.tools ?? {});
  return <section className="context-panel" aria-label="上下文观察">
    <div className="context-heading"><strong>上下文观察</strong><button disabled={blocked} onClick={() => setRevision(value => value + 1)}>刷新快照</button></div>
    <p>当前持久化会话：<code>{chat.storedId || '尚未保存'}</code></p>
    <p>模型：<strong>{chat.info.model || '待加载'}</strong> · Provider：{chat.info.provider || '待加载'}</p>
    {chat.info.usage && <p>会话累计：输入 {chat.info.usage.input ?? 0} · 输出 {chat.info.usage.output ?? 0} tokens · 调用 {chat.info.usage.calls ?? 0} 次 · 压缩 {chat.info.usage.compressions ?? 0} 次。{chat.info.usage.cost_usd != null ? `费用 $${chat.info.usage.cost_usd}` : '费用暂不可用'}。这些是累计值，不是本轮用量。</p>}
    <p>这是运行时快照与估算，完整模型 API 请求尚未捕获。运行时请等待本轮结束。</p>
    {error && <p role="alert">{error}</p>}
    {snapshot && <>
      <p><strong>{snapshot.context_used.toLocaleString()} / {snapshot.context_max.toLocaleString()} tokens</strong> · {snapshot.context_estimated ? '估算用量' : '后端用量'} · 来源：{snapshot.context_source}</p>
      <progress aria-label="上下文用量" value={snapshot.context_used} max={snapshot.context_max || 1} />
      <p>以下分类均为本地估算，不是各项精确计费 token。总量可能包含用量锚点与新增消息估算。</p>
      <div className="context-categories">{snapshot.categories.map(category => <div key={category.id}><span>{labels[category.id] ?? category.label}</span><strong>≈ {category.tokens.toLocaleString()}</strong></div>)}</div>
      {!snapshot.categories.length && <p>Agent 尚未构建，发送一条消息后刷新。</p>}
      <details><summary>上下文文件加载清单</summary>{snapshot.context_files?.length ? snapshot.context_files.map(file => <p key={file.path}><code>{file.path}</code> · {file.loaded ? '已加载' : '未加载'} · {file.status} · ≈ {file.est_tokens} tokens</p>) : <p>没有文件清单；不代表整个系统提示词为空。</p>}</details>
    </>}
    <details open><summary>历史怎样筛选</summary><ol>
      <li>数据库按当前会话及压缩关联链读取 active=1 或 compacted=1 的记录。</li>
      <li>模型恢复历史只保留当前会话的 active=1；界面保留归档旧正文并去重。</li>
      <li>还原 tool_calls 与工具结果，修复中断序列。空正文的工具调用不能删除。</li>
      <li>组装系统提示词、历史、本轮输入和工具 schema，必要时压缩后发送。</li>
    </ol><p>这是程序规则。当前没有按问题语义检索历史，也没有简单只取最近 N 条。</p></details>
    <details><summary>当前模型工具（session.info）</summary>{tools.length ? tools.map(([group, names]) => <p key={group}><strong>{group}</strong>：{names.join('、')}</p>) : <p>工具元信息尚未加载。</p>}<p>配置选择工具集 → 注册与环境检查 → 构建模型工具定义 → 模型选择调用 → 程序校验参数并执行。上面的名称来自后端会话信息；这不是完整 schema。</p></details>
    <details><summary>Hermes 压缩：旧历史变为摘要，近期消息保留</summary>
      <p>先清理可裁剪的工具输出，再选择可摘要区间；保护开头与近期消息，并保持工具调用配对。摘要模型提炼目标、事实、约束、进展；程序安装摘要并保存压缩状态。默认摘要是有损的。</p>
      <p>DS 窗口大，只会让自动阈值更难达到。手动压缩无需填满窗口；短会话可能无变化，或因摘要会变大而拒绝。建议在单独的教学会话积累多轮资料后试用。</p>
      <label>摘要重点（可选）<input value={focus} onChange={event => setFocus(event.target.value)} placeholder="例如：商品事实、缺少证据、未完成任务" disabled={blocked} /></label>
      <p>按钮会调用真实 Hermes 压缩，可能产生模型费用，并改变当前会话后续使用的历史。旧记录仍用于界面回看。</p>
      <button disabled={blocked} onClick={() => void compress()}>手动压缩当前会话</button>
      {feedback && <div role="status"><p>压缩返回结果（token 为估算）：</p><pre>{JSON.stringify(feedback, (key, value) => ['messages', 'info', 'usage'].includes(key) ? undefined : value, 2)}</pre></div>}
    </details>
    {chat.status.includes('压缩结果未知') && <button onClick={() => void controller.open(chat.storedId, true)}>重新附着并恢复状态</button>}
  </section>;
}
