/* One display-name rule for the spatial studio and its linked Chat. */
globalThis.shortStudioName = function (name, notes = [], shots = []) {
  const clean = (value) =>
    String(value || "")
      .replace(/\s*[·-]\s*(创作方案|创意方案|方案)\s*$/, "")
      .trim();
  const readable = (value) =>
    value &&
    !/^[a-f\d]{24,}(?:\.[a-z\d]+)?$/i.test(value) &&
    !/^\d{4}[-/]\d/.test(value);
  const candidates = [
    clean(name),
    ...notes.map((n) => clean(n.title)),
    ...shots.map((s) => clean(s.name)),
  ];
  return candidates.find(readable) || "未命名画布";
};

// Both React and the canvas use these routes; old query links remain readable.
globalThis.studioWorkspaceId = function () {
  const match = (location.pathname || "").match(/^\/p\/([^/]+)\/?$/);
  return match
    ? decodeURIComponent(match[1])
    : new URLSearchParams(location.search).get("workspace");
};
globalThis.studioChatHref = function (
  session = "",
  workspace = "",
  target = "",
) {
  const params = new URLSearchParams();
  if (workspace) params.set("workspace", workspace);
  if (target) params.set("target", target);
  return (
    (session ? "/c/" + encodeURIComponent(session) : "/") +
    (params.size ? "?" + params : "")
  );
};
globalThis.studioCanvasHref = function (workspace, focus = "") {
  return (
    "/p/" +
    encodeURIComponent(workspace) +
    (focus ? "?focus=" + encodeURIComponent(focus) : "")
  );
};
globalThis.studioAssetName = function (asset, index = 0) {
  const name = String(asset?.name || "").trim();
  return !name || /^[a-f\d]{24,}(?:\.[a-z\d]+)?$/i.test(name)
    ? "图片 " + (index + 1)
    : name;
};
globalThis.studioNotePreview = function (text) {
  return String(text || "")
    .replace(/```[\s\S]*?```/g, "")
    .replace(/^\s*#{1,6}\s+/gm, "")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .trim();
};
