import { lazy, Suspense, useState } from "react";
import { App } from "./App";
import type { ChatController } from "./chat-controller";
import type { Attachment } from "./attachments";
const CanvasApp = lazy(() => import("./CanvasApp"));

export function AppShell({ controller }: { controller: ChatController }) {
  const [module, setModule] = useState<"chat" | "canvas">(() =>
    localStorage.getItem("miniclaw.module") === "canvas" ? "canvas" : "chat",
  );
  const [canvasLoaded, setCanvasLoaded] = useState(module === "canvas");
  const [initialImport, setInitialImport] = useState<{
    attachment: Attachment;
    session: string;
    nonce: number;
  }>();
  const [suggestion, setSuggestion] = useState<{
    attachment: Attachment;
    nonce: number;
  }>();
  const [settingsNonce, setSettingsNonce] = useState(0);
  function show(value: "chat" | "canvas") {
    setModule(value);
    localStorage.setItem("miniclaw.module", value);
    if (value === "canvas") setCanvasLoaded(true);
  }
  return (
    <>
      <div className="app-surface" hidden={module !== "chat"}>
        <App
          controller={controller}
          onCanvas={(attachment) => {
            if (attachment)
              setInitialImport({
                attachment,
                session: controller.state.sessionId,
                nonce: Date.now(),
              });
            show("canvas");
          }}
          externalSuggestion={suggestion}
          settingsNonce={settingsNonce}
        />
      </div>
      {canvasLoaded && (
        <div className="app-surface" hidden={module !== "canvas"}>
          <Suspense
            fallback={<div style={{ padding: 40 }}>正在打开图片工作区…</div>}
          >
            <CanvasApp
              controller={controller}
              active={module === "canvas"}
              initialImport={initialImport}
              onChat={() => show("chat")}
              onUse={(attachment) => {
                setSuggestion({ attachment, nonce: Date.now() });
                show("chat");
              }}
              onSettings={() => {
                show("chat");
                setSettingsNonce(Date.now());
              }}
            />
          </Suspense>
        </div>
      )}
    </>
  );
}
