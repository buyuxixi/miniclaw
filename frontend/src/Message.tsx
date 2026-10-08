import Markdown from "react-markdown";
import { useState } from "react";
import remarkGfm from "remark-gfm";
import type { ChatItem } from "./types";
import { Icon } from "./Icon";
import { AttachmentCard } from "./AttachmentCard";
import { ArtifactDownload } from "./ArtifactDownload";
import { ImageJobCard } from "./ImageJobCard";
import type { Attachment } from "./attachments";
import { briefDisplay, parseBrief, spokenMain, type BriefCandidate } from './creator-candidates';

function pretty(value: unknown) {
  if (typeof value === "string") {
    try {
      return JSON.stringify(JSON.parse(value), null, 2);
    } catch {
      return value;
    }
  }
  return JSON.stringify(value, null, 2) ?? "";
}

export function Message({
  item,
  owner,
  onReuse,
  onEdit,
  onAdopt,
  onAdoptBrief,
  onSaveIdea,
  saveIdeaLabel='放到项目画布',
  currentMain,
}: {
  item: ChatItem;
  owner: string;
  onReuse: (text: string) => void;
  onEdit?: (image: Attachment) => void;
  onAdopt?: (text: string, item: string) => void;
  onAdoptBrief?: (fields: BriefCandidate, item: string) => void;
  onSaveIdea?: (item: string) => Promise<void>;
  saveIdeaLabel?: string;
  currentMain?: string;
}) {
  const [copyStatus, setCopyStatus] = useState("");
  const [savingIdea,setSavingIdea]=useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(item.text);
      setCopyStatus("已复制");
    } catch {
      setCopyStatus("复制失败，请选中文字复制");
    }
  }
  if (item.kind === "tool")
    return (
      <>
        <details className={`tool-card ${item.status}`}>
          <summary>
            <span className="tool-chevron"><Icon name="chevron" size={14} /></span>
            <span className="tool-icon">
              <Icon name={item.name==='miniclaw_list_files'?'folder':item.name?.includes('canvas')?'image':'activity'} size={15} />
            </span>
            <span>
              {item.name === 'miniclaw_canvas_propose' ? '制定修图方案'
                : item.name === 'miniclaw_canvas_view' ? '读取工作图'
                : item.name === 'miniclaw_canvas_region' ? '局部修改'
                : item.name === 'miniclaw_canvas_ai' ? '生成修图候选'
                : item.name === 'miniclaw_canvas_job' ? '查询修图候选'
                : item.name === "miniclaw_edit_image"
                ? "编辑图片"
                : item.name === "miniclaw_image_list"
                  ? "查找图片版本"
                  : item.name === "miniclaw_image_status"
                    ? "查询修图进度"
                    : item.name === "miniclaw_list_files"
                      ? "查看文件目录"
                      : item.name === "miniclaw_read_file"
                        ? "读取资料"
                        : item.name === "miniclaw_save_artifact"
                          ? "保存文本产物"
                          : item.name === "miniclaw_overlay_compile"
                            ? "生成动效编排"
                            : item.name === "skill_view"
                              ? "读取技能"
                              : item.name === "skills_list"
                                ? "查找技能"
                                : item.name}
            </span>
            <span className="tool-status">
              {
                {
                  running: "执行中",
                  done: "已完成",
                  error: "执行失败",
                  interrupted: "已停止",
                  unavailable: "结果未加载",
                }[item.status ?? "unavailable"]
              }
            </span>
          </summary>
          <div className="tool-details">
            <p>
              工具 <code>{item.name}</code>
            </p>
            {item.args != null && <><p>调用参数</p><pre>{pretty(item.args)}</pre></>}
            {item.result !== undefined && (
              <>
                <p>执行结果</p>
                <pre>{pretty(item.result)}</pre>
                {[
                  "miniclaw_save_artifact",
                  "miniclaw_overlay_compile",
                ].includes(item.name ?? "") && (
                  <ArtifactDownload result={item.result} />
                )}
              </>
            )}
          </div>
        </details>
        {item.result !== undefined &&
          ["miniclaw_edit_image", "miniclaw_image_status"].includes(
            item.name ?? "",
          ) && (
            <ImageJobCard owner={owner} result={item.result} onEdit={onEdit} />
          )}
      </>
    );
  return (
    <article className={`message ${item.kind}`}>
      <div className="message-label">
        {item.kind === "assistant" ? <span className="reply-mark" aria-label="miniclaw">m</span> : "你"}
      </div>
      <div className="message-body">
        {item.kind === "user" ? (
          <p>{item.text}</p>
        ) : (
          <Markdown
            remarkPlugins={[remarkGfm]}
            skipHtml
            components={{
              a: (props) => <a {...props} target="_blank" rel="noreferrer" />,
              img: () => <span>请在附件或修图结果卡片中查看图片。</span>,
            }}
          >
            {briefDisplay(item.text)}
          </Markdown>
        )}
      </div>
      {!!item.attachments?.length && (
        <div className="attachments">
          {item.attachments.map((a) => (
            <AttachmentCard
              key={a.id}
              attachment={a}
              owner={owner}
              onEdit={
                onEdit && a.kind === "image" ? () => onEdit(a) : undefined
              }
            />
          ))}
        </div>
      )}
      {item.status === "running" && !item.text && (
        <span className="thinking">正在思考…</span>
      )}
      {item.kind === "assistant" &&
        item.text &&
        !["running", "error", "interrupted"].includes(item.status ?? "") && (
          <div className="message-actions">
            <button title="复制回复" aria-label="复制回复" onClick={() => void copy()}>
              <Icon
                name={copyStatus === "已复制" ? "check" : "copy"}
                size={14}
              />
              <span className="action-caption">复制</span>
            </button>
            {onAdopt && (currentMain?.trim() && spokenMain(item.text).trim()===currentMain.trim() ? <span className="message-adopt-state">与主稿一致</span> :
              <button onClick={() => onAdopt(spokenMain(item.text), item.id)}>
                采用为项目口播
              </button>
            )}
            {onAdoptBrief && parseBrief(item.text) && <button onClick={() => onAdoptBrief(parseBrief(item.text)!, item.id)}>采用为创作依据</button>}
            {onSaveIdea && <button disabled={savingIdea || !/^row-\d+$/.test(item.id)} onClick={()=>{setSavingIdea(true);void onSaveIdea(item.id).catch(e=>setCopyStatus(e.message)).finally(()=>setSavingIdea(false));}}>{saveIdeaLabel}</button>}
            <span role="status">{copyStatus}</span>
          </div>
        )}
      {item.kind === "user" && item.text && (
        <div className="message-actions">
          <button title="复用到输入框" aria-label="复用这条消息" onClick={() => onReuse(item.text)}>
            <Icon name="edit" size={14} />
            <span className="action-caption">复用到输入框</span>
          </button>
        </div>
      )}
    </article>
  );
}
