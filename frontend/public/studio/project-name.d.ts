declare global {
  var shortStudioName: (name?: string, notes?: {title?: string}[], shots?: {name?: string}[]) => string;
  var studioWorkspaceId: () => string | null;
  var studioChatHref: (session?: string, workspace?: string, target?: string) => string;
  var studioCanvasHref: (workspace: string, focus?: string) => string;
  var studioAssetName: (asset: {name?: string}, index?: number) => string;
  var studioNotePreview: (text?: string) => string;
}
export {};
