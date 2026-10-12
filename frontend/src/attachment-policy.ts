export const MAX_ATTACHMENTS = 10;
export const ATTACHMENT_ACCEPT = '.png,.jpg,.jpeg,.webp,.pdf,.docx,.csv,.xlsx,.txt,.md,.markdown,.srt';
export function validateAttachmentFile(file: File): void {
  const image = /\.(png|jpe?g|webp)$/i.test(file.name);
  if (!/\.(png|jpe?g|webp|pdf|docx|csv|xlsx|txt|md|markdown|srt)$/i.test(file.name)) throw new Error('支持图片、PDF、Word（DOCX）、CSV、Excel（XLSX）、TXT、Markdown和SRT');
  if (!file.size || file.size > (image ? 5 : 50) * 1024 * 1024) throw new Error('文件不能为空；图片最大5 MiB，文档和文本最大50 MiB');
}
export function fileSize(bytes: number): string {
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MiB` : `${(bytes / 1024).toFixed(1)} KiB`;
}
