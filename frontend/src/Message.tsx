import Markdown from "react-markdown";
import { useState } from "react";
import remarkGfm from "remark-gfm";
import type { ChatItem } from "./types";
import { Icon } from "./Icon";
import { AttachmentCard } from "./AttachmentCard";
import { ArtifactDownload } from "./ArtifactDownload";
import { ImageJobCard } from "./ImageJobCard";
import type { ChatImageCanvasTarget } from './ChatImageCanvasAction';
import type { Attachment } from "./attachments";
import { skillDetails } from './skill-readiness';
import { briefDisplay, parseBrief, spokenMain, type BriefCandidate } from './creator-candidates';
import {clarification} from './director-conversation';
import {DirectorQuestions} from './DirectorQuestions';
import {StudioReferences} from './StudioReferences';
import {documentToolLabel} from './tool-label';

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
  canvasTarget,
  onAnswer,
  answerDisabled=false,
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
  canvasTarget?: ChatImageCanvasTarget;
  onAnswer?: (answer:string)=>Promise<boolean>;
  answerDisabled?:boolean;
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
              {item.name === 'miniclaw_document_query' ? documentToolLabel(item.name,item.args,item.result)
                : item.name === 'miniclaw_canvas_propose' ? '制定修图方案'
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
            <ImageJobCard owner={owner} result={item.result} onEdit={onEdit} canvasTarget={canvasTarget} />
          )}
      </>
    );
  const skillPrefix = item.skill ? `/${item.skill}` : '';
  const question=item.kind==='assistant'?clarification(item.text):null;
  const replyText=question?.body??(item.kind==='assistant'&&item.status==='running'?item.text.replace(/```studio-question[\s\S]*$/,''):item.text);
  const userText = skillPrefix && item.text.startsWith(skillPrefix) &&
    (item.text.length === skillPrefix.length || /\s/.test(item.text[skillPrefix.length]))
    ? item.text.slice(skillPrefix.length).replace(/^\r?\n|^ /, '') : item.text;
  const attachmentCards = !!item.attachments?.length && (
    <div className={`attachments${item.kind === 'user' ? ' user-attachments' : ''}`}>
      {item.attachments!.map(a => <AttachmentCard key={a.id} attachment={a} owner={owner} canvasTarget={canvasTarget} variant={item.kind === 'user' ? 'tile' : 'row'}
        onEdit={onEdit && a.kind === 'image' ? () => onEdit(a) : undefined} />)}
    </div>
  );
  return (
    <article className={`message ${item.kind}`}>
      <div className="message-label">
        {item.kind === "assistant" ? <span className="reply-mark" aria-label="miniclaw">m</span> : "你"}
      </div>
      {item.kind === 'user' ? (
        <div className="user-message-content">
          {attachmentCards}
          {!!item.studio_refs?.length&&<StudioReferences items={item.studio_refs}/>}
          {(userText || item.skill) && <div className="message-body">
            {item.skill && <div className="message-skill" title={`/${item.skill}`}><Icon name="skills" size={14} />{skillDetails({name:item.skill,description:''}).title}</div>}
            {userText && <p>{userText}</p>}
          </div>}
        </div>
      ) : (
        <div className="message-body">
          <Markdown
            remarkPlugins={[remarkGfm]}
            skipHtml
            components={{
              a: (props) => <a {...props} target="_blank" rel="noreferrer" />,
              img: () => <span>请在附件或修图结果卡片中查看图片。</span>,
            }}
          >
            {briefDisplay(replyText)}
          </Markdown>
          {question&&onAnswer&&<DirectorQuestions questions={question.questions} disabled={answerDisabled||item.status==='running'} onAnswer={onAnswer}/>}
          {question&&!onAnswer&&question.questions.map((q,i)=><section key={i}><p><strong>{q.title}</strong></p><p>{q.options.join(' / ')}</p></section>)}
        </div>
      )}
      {item.kind !== 'user' && attachmentCards}
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
