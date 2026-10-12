/* Preserve the original spatial canvas; project commands and Hermes own results. */
let workspaceTokenRefresh = null;
async function refreshWorkspaceToken(rejectedToken) {
  if (window.WORKSPACE_TOKEN !== rejectedToken) return;
  if (!workspaceTokenRefresh)
    workspaceTokenRefresh = (async () => {
      const response = await fetch("/studio/index.html", {
        cache: "no-store",
        signal: AbortSignal.timeout(15000),
      });
      if (!response.ok) throw Error("连接恢复失败，请重试保存");
      const match = (await response.text()).match(
        /window\.WORKSPACE_TOKEN\s*=\s*("(?:[^"\\]|\\.)*")/,
      );
      const token = match ? JSON.parse(match[1]) : "";
      if (!token || token === "__WORKSPACE_TOKEN__")
        throw Error("连接恢复失败，请刷新页面后重试");
      window.WORKSPACE_TOKEN = token;
      window.__HERMES_SESSION_TOKEN__ = token;
    })().finally(() => {
      workspaceTokenRefresh = null;
    });
  await workspaceTokenRefresh;
}
function withStudioIntegration(app) {
  const init = app.init,
    showProject = app.showProject,
    openEdit = app.openEdit,
    closeFullEditor = app.closeFullEditor,
    refreshProjectChanges = app.refreshProjectChanges,
    loadSharedProject = app.loadSharedProject;
  Object.assign(app, {
    directorReady: false,
    editorComparing: false,
    directorGoal: "",
    adoptRequest: null,
    cloudBudget: { limit: 0, reserved: 0 },
    cloudCalls: 0,
    compareBasis: null,
    adoptShot: null,
    previewBefore: "",
    previewUrls: [],
    workspaceList: [],
    sharedChatId: null,
    contentVersions: [],
    contentVersionTargets: [],
    versionPage: 0,
    versionTotal: 0,
    versionRequest: 0,
    versionTarget: "",
    versionsBusy: false,
    versionQuery: "",
    compareZoom: false,
    chatOpening: false,
    pendingChatHref: "",
  });
  Object.defineProperties(
    app,
    Object.getOwnPropertyDescriptors({
      init() {
        init.call(this);
        if (typeof BroadcastChannel !== "undefined") {
          const connect = () => {
            this._studioChannel?.close();
            try {
              this._studioChannel = new BroadcastChannel("miniclaw-studio");
              this._studioChannel.addEventListener("message", (event) => {
                if (event.data?.workspace === this.workspaceId && event.data?.type === "asset-added")
                  void this.refreshProjectChanges("项目素材");
              });
            } catch {
              this._studioChannel = null;
            }
          };
          connect();
          window.addEventListener("pagehide", () => this._studioChannel?.close());
          window.addEventListener("pageshow", (event) => { if (event.persisted) connect(); });
        }
        window.addEventListener("message", (e) => {
          if (
            e.origin !== location.origin ||
            e.source !== this.$refs.director?.contentWindow ||
            e.data?.workspace !== this.workspaceId
          )
            return;
          if (["miniclaw.director.adopted", "miniclaw.director.changed"].includes(e.data.type))
            void this.refreshProjectChanges("助手");
          if (e.data.type === "miniclaw.director.precision")
            void this.openDirectorPrecision(e.data.target);
          if (
            [
              "miniclaw.director.compare",
              "miniclaw.director.compare-retained",
            ].includes(e.data.type)
          ) {
            const m = e.data;
            this.editAssetId = m.target.object;
            this.editSource = this.assets.find((a) => a.id === m.target.object);
            if (!this.editSource || this.editSource.file !== m.target.source) {
              this.notify("素材已有变化，请重新比较");
              return;
            }
            this.editSource = JSON.parse(JSON.stringify(this.editSource));
            this.editorReturnTarget = this.getTarget(this.selection) ? this.selection : m.target.object;
            this.editorProject = m.candidate.project;
            this.previewUrls.forEach(URL.revokeObjectURL);
            this.previewUrls = [];
            this.previewBefore = m.candidate.before_output || "";
            this.editorCandidate = m.candidate;
            if (m.candidate.after) {
              this.previewUrls = [
                URL.createObjectURL(m.candidate.before),
                URL.createObjectURL(m.candidate.after),
              ];
              this.previewBefore = this.previewUrls[0];
              this.editorCandidate = {
                ...m.candidate,
                output: this.previewUrls[1],
              };
            }
            this.editorUrl = "";
            this.editorLoading = false;
            this.editorFailure = "";
            this.compareBasis = m.basis;
            this.adoptShot = m.target.shot;
            this.adoptRequest = null;
            this.fullEditor = true;
            if (m.type === "miniclaw.director.compare-retained")
              void this.refreshEditorComparison();
          }
        });
      },
      async loadSharedProject() {
        await loadSharedProject.call(this);
        if (this.projectReady) {
          if (!this.shots.some((s) => s.id === this.active))
            this.active = this.shots[0]?.id || "";
          if (!this.getTarget(this.selection)) {
            this.selection = this.active;
            this.selectedIds = this.selection ? [this.selection] : [];
          }
          if (this.quote?.targetId && !this.getTarget(this.quote.targetId))
            this.quote = null;
        }
        void this.loadWorkspaceList();
        const raw = localStorage.getItem("studio-adopt:" + this.workspaceId);
        if (raw && this.projectReady) {
          try {
            await this.projectApi("/commands", JSON.parse(raw));
            localStorage.removeItem("studio-adopt:" + this.workspaceId);
            await loadSharedProject.call(this);
            this.notify("上次采用已恢复");
          } catch (e) {
            this.projectError = "上次采用的结果仍保留：" + e.message;
          }
        }
      },
      async refreshProjectChanges(source = "助手") {
        const revision = this.projectRevision;
        await refreshProjectChanges.call(this, source);
        if (revision === this.projectRevision) return;
        if (!this.shots.some((s) => s.id === this.active)) this.active = this.shots[0]?.id || "";
        if (!this.getTarget(this.selection)) {
          this.selection = this.active;
          this.selectedIds = this.selection ? [this.selection] : [];
        } else {
          this.selectedIds = this.selectedIds.filter((id) => this.getTarget(id));
        }
        if (this.quote?.targetId && !this.getTarget(this.quote.targetId)) this.quote = null;
        this.syncDirectorTarget?.();
        void this.refreshVideo?.();
      },
      get shot() {
        return (
          this.shots.find((s) => s.id === this.active) ||
          this.shots[0] || {
            id: "",
            name: "新片段",
            mode: "first",
            first: "",
            refs: [],
            prompt: "",
            x: 360,
            y: 360,
          }
        );
      },
      async loadWorkspaceList() {
        try {
          const r = await fetch("/api/workspaces", {
            headers: { "X-Hermes-Session-Token": window.WORKSPACE_TOKEN },
            signal: AbortSignal.timeout(15000),
          });
          if (r.ok) this.workspaceList = await r.json();
        } catch {}
      },
      async openFullChat(event) {
        event.preventDefault();
        if (this.chatOpening) return;
        this.pendingChatHref = event.currentTarget.href;
        await this.continueToChat();
      },
      sourceChatHref(object) {
        const node = typeof object === "string"
          ? this.assets.find((a) => a.id === object) || this.notes.find((n) => n.id === object) || this.shots.find((s) => s.id === object) || this.videoJobs?.find((j) => "video-" + j.id === object)
          : object;
        if (!node) return "";
        const source = node.source && typeof node.source === "object" ? node.source : {};
        const owner = this.sharedChatId || source.sessionId || "";
        const target = node.shot || node.id;
        const href = studioChatHref(owner, this.workspaceId, target);
        // Only genuine message provenance can produce a message anchor. Other
        // source ids refer to assets or jobs, not to a Hermes message.
        const messageId = String(source.messageId ?? "");
        const message = /^\d+$/.test(messageId) ? "row-" + Number(messageId) : /^row-\d+$/.test(messageId) ? messageId : "";
        if (message && Number.isSafeInteger(Number(message.slice(4))) && (!source.sessionId || source.sessionId === owner)) {
          const params = new URLSearchParams(href.split("?")[1] || "");
          params.set("message", message);
          return href.split("?")[0] + "?" + params;
        }
        return href;
      },
      get selectionSourceHref() {
        return this.sourceChatHref(this.selection);
      },
      async openSelectionSource(event) {
        event?.preventDefault();
        const href = this.selectionSourceHref;
        if (!href || this.chatOpening) return;
        this.pendingChatHref = href;
        await this.continueToChat();
      },
      async continueToChat() {
        if (this.chatOpening || !this.pendingChatHref) return;
        this.chatOpening = true;
        try {
          if (!this.projectReady) throw Error("项目尚未读取完成，请稍后重试");
          await this.flushProject();
          location.href = this.pendingChatHref;
          this.pendingChatHref = "";
        } catch (e) {
          this.projectError = "打开完整对话前保存未完成：" + e.message;
        } finally {
          this.chatOpening = false;
        }
      },
      async retryProjectSave() {
        if (!this.projectReady) {
          await this.loadSharedProject();
          return;
        }
        if (this.projectConflict) {
          await this.showProject();
          return;
        }
        if (this.pendingChatHref) {
          await this.continueToChat();
          return;
        }
        this.persist();
        try {
          await this.flushProject();
          this.notify("项目已保存");
        } catch (e) {
          this.projectError = e.message;
        }
      },
      async openEdit() {
        this.compareBasis = null;
        this.adoptShot = null;
        this.adoptRequest = null;
        this.previewBefore = "";
        await openEdit.call(this);
      },
      closeFullEditor() {
        if (this.editorApplying) return;
        this.compareZoom = false;
        this.previewUrls.forEach(URL.revokeObjectURL);
        this.previewUrls = [];
        this.previewBefore = "";
        closeFullEditor.call(this);
        this.$refs.director?.contentWindow.postMessage(
          { type: "miniclaw.director.refresh", workspace: this.workspaceId },
          location.origin,
        );
      },
      async continueFullPrecision() {
        if (this.editorApplying) return;
        this.editorApplying = true;
        try {
          const c = this.editorCandidate;
          if (c && (c.plan || c.job || c.comparison || c.legacyComparison)) {
            await this.applyEditorPreview(c);
          }
          if (this.editorUrl) {
            this.editorCandidate = null;
            const url = new URL(this.editorUrl, location.origin);
            this.editorToken = crypto.randomUUID();
            url.searchParams.set("nonce", this.editorToken);
            this.editorUrl = url.pathname + url.search;
            return;
          }
          const target = {
            object: this.editAssetId,
            source: this.editSource.file,
            project: this.editorProject,
            shot: this.adoptShot,
          };
          this.editorApplying = false;
          this.closeFullEditor();
          await this.openDirectorPrecision(target);
        } catch (e) {
          this.editorFailure = e.message;
        } finally {
          this.editorApplying = false;
        }
      },
      async openDirectorPrecision(target) {
        try {
          if (!target || typeof target.object !== "string" || typeof target.source !== "string" || typeof target.project !== "string")
            throw Error("修图目标暂不可用，请重新选择素材");
          await this.flushProject();
          const asset = this.assets.find((a) => a.id === target.object);
          if (!asset || asset.file !== target.source)
            throw Error("原素材已有变化，请重新选择");
          this.editSource = JSON.parse(JSON.stringify(asset));
          this.editAssetId = asset.id;
          this.editorReturnTarget = this.getTarget(this.selection) ? this.selection : asset.id;
          this.adoptShot = target.shot || null;
          this.compareBasis = this.projectRevision;
          this.editorToken = crypto.randomUUID();
          this.editorProject = target.project;
          this.editorCandidate = null;
          this.adoptRequest = null;
          this.editorFailure = "";
          this.editorLoading = true;
          this.fullEditor = true;
          this.editorUrl =
            "/editor/precision-workspace.html?project=" +
            target.project +
            "&nonce=" +
            this.editorToken +
            "&workspace=" +
            this.workspaceId +
            "&label=" +
            encodeURIComponent(asset.name);
        } catch (e) {
          this.projectError = e.message;
        }
      },
      get affectedClips() {
        return this.adoptShot
          ? this.shots.filter((s) => s.id === this.adoptShot)
          : this.shots.filter((s) =>
              s.mode === "first"
                ? s.first === this.editAssetId
                : s.refs.includes(this.editAssetId),
            );
      },
      async showProject() {
        this.cloudBudgetMessage = "";
        this.cloudBudgetError = "";
        await showProject.call(this);
        try {
          const [budget, link] = await Promise.all([
            this.projectApi("/budget"),
            this.projectApi("/chat"),
          ]);
          this.cloudBudget = budget;
          this.cloudCalls = this.cloudBudget.limit;
          this.sharedChatId = link.chat_id;
          await this.loadContentVersions();
        } catch (e) {
          this.projectError = e.message;
        }
      },
      async loadContentVersions(more = false) {
        const request = ++this.versionRequest;
        this.versionsBusy = true;
        try {
          const result = await this.projectApi(
            "/versions?page=" +
              (more ? this.versionPage + 1 : 1) +
              "&target=" +
              encodeURIComponent(this.versionTarget),
          );
          if (request !== this.versionRequest) return;
          this.contentVersions = more
            ? [
                ...this.contentVersions,
                ...result.items.filter(
                  (v) => !this.contentVersions.some((old) => old.id === v.id),
                ),
              ]
            : result.items;
          this.contentVersionTargets = result.targets;
          this.versionPage = result.page;
          this.versionTotal = result.total;
        } catch (e) {
          if (request === this.versionRequest) this.projectError = e.message;
        } finally {
          if (request === this.versionRequest) this.versionsBusy = false;
        }
      },
      get visibleContentVersions() {
        return this.contentVersions.filter(
          (v) => !this.versionTarget || v.target === this.versionTarget,
        );
      },
      get versionTargets() {
        return [...new Set(this.contentVersionTargets.map((v) => v.id))].map(
          (id) => {
            const v = this.contentVersionTargets.find((v) => v.id === id),
              asset = this.assets.find((a) => a.id === id),
              kind = v.kind;
            let name =
              asset?.name ||
              this.shots.find((s) => s.id === id)?.name ||
              this.notes.find((n) => n.id === id)?.title ||
              { facts: "共同要求", narration: "口播文案", render: "成片" }[id];
            if (asset && /^[a-f0-9]{24,}\./i.test(name))
              name = "产品素材 " + (this.assets.indexOf(asset) + 1);
            return {
              id,
              kind,
              file: asset?.file,
              name:
                name ||
                ({
                  image: "已移除的图片",
                  prompt: "已移除的镜头",
                  note: "已移除的备注",
                }[kind] || "历史内容") +
                  " · " +
                  id.slice(-6),
            };
          },
        );
      },
      get searchedVersionTargets() {
        const q = this.versionQuery.trim().toLowerCase();
        return this.versionTargets.filter((t) =>
          (t.name + " " + t.id).toLowerCase().includes(q),
        );
      },
      versionKind(kind, target) {
        if (target === "narration") return "口播文案";
        if (target === "facts") return "共同要求";
        return (
          {
            image: "图片",
            prompt: "镜头要求",
            note: "创意备注",
            facts: "共同要求",
            narration: "口播文案",
            video: "视频",
            render: "成片",
          }[kind] || "内容"
        );
      },
      versionAvailable(v) {
        return (
          ["facts", "narration"].includes(v.target) ||
          this.assets.some((a) => a.id === v.target) ||
          this.shots.some((s) => s.id === v.target) ||
          this.notes.some((n) => n.id === v.target)
        );
      },
      versionLabel(v) {
        return (
          this.versionTargets.find((t) => t.id === v.target)?.name || v.target
        );
      },
      async restoreContentVersion(v) {
        if (this.versionsBusy) return;
        if (v.kind === "video" || v.kind === "render") {
          if (v.kind === "video") {
            this.reviewVideoId = v.data.id;
            this.panel = "video-review";
            void this.refreshVideo();
            return;
          }
          location.href = "/studio/media/render/" + v.data.id + "?download=1";
          return;
        }
        this.versionsBusy = true;
        try {
          await this.flushProject();
          const record = await this.projectApi("/versions/restore", {
            request_id: crypto.randomUUID(),
            revision: this.projectRevision,
            version_id: v.id,
          });
          for (const [key, value] of Object.entries(record.state))
            this[key] = value;
          this.projectRevision = record.revision;
          this.projectEvents = record.events;
          this._ack = JSON.stringify(this.projectSnapshot());
          this.persist();
          await this.loadContentVersions();
          this.notify("已恢复历史版本");
        } catch (e) {
          this.projectError = e.message;
        } finally {
          this.versionsBusy = false;
        }
      },
      cloudBudgetSaving: false,
      cloudBudgetError: "",
      cloudBudgetMessage: "",
      get cloudBudgetMaximum() {
        return Number.isInteger(this.cloudBudget.max_calls)
          ? this.cloudBudget.max_calls
          : 10;
      },
      get cloudBudgetHelp() {
        return this.cloudBudget.max_calls === undefined
          ? "当前后台仍限制 10 次；需重启 miniclaw 后台后才能调高。"
          : "支持 0–" +
              this.cloudBudgetMaximum +
              " 次；已预留 " +
              this.cloudBudget.reserved +
              " 次，调高上限可继续生成。失败或未知任务仍计入次数。";
      },
      async saveCloudBudget() {
        if (this.cloudBudgetSaving) return;
        this.cloudBudgetError = "";
        this.cloudBudgetMessage = "";
        const calls = this.cloudCalls;
        if (!Number.isInteger(calls) || calls < 0 || calls > 1000) {
          this.cloudBudgetError = "请输入0至1000的整数";
          return;
        }
        if (calls > this.cloudBudgetMaximum) {
          this.cloudBudgetError =
            this.cloudBudget.max_calls === undefined
              ? "当前后台仍限制10次，请重启 miniclaw 后台后再保存。"
              : "上限不能超过 " + this.cloudBudgetMaximum + " 次";
          return;
        }
        this.cloudBudgetSaving = true;
        try {
          this.cloudBudget = await this.projectApi("/budget", { calls });
          this.cloudCalls = this.cloudBudget.limit;
          this.cloudBudgetMessage =
            "已保存，可再生成 " + this.cloudBudget.remaining + " 次";
        } catch (e) {
          this.cloudBudgetError = e.message;
        } finally {
          this.cloudBudgetSaving = false;
        }
      },
      displayFile(file) {
        return typeof file === "string" &&
          file.startsWith("/api/precision/projects/")
          ? file.replace("/api/precision/projects/", "/studio/media/")
          : file;
      },
      async editApi(path = "", body) {
        const token = window.WORKSPACE_TOKEN || "",
          payload = body ? JSON.stringify(body) : undefined;
        const send = () =>
          fetch("/api/precision" + path, {
            method: body ? "POST" : "GET",
            headers: {
              "Content-Type": "application/json",
              "X-Hermes-Session-Token": window.WORKSPACE_TOKEN || "",
            },
            body: payload,
            signal: AbortSignal.timeout(30000),
            cache: "no-store",
          });
        let response = await send();
        if (response.status === 401) {
          await refreshWorkspaceToken(token);
          response = await send();
        }
        const data = await response.json();
        if (!response.ok) {
          const error = new Error(data.detail || "图片连接失败");
          error.status = response.status;
          throw error;
        }
        return data;
      },
      async projectApi(path = "", body) {
        const token = window.WORKSPACE_TOKEN || "",
          payload = body ? JSON.stringify(body) : undefined;
        const send = () =>
          fetch("/api/workspaces/" + this.workspaceId + path, {
            method: body ? "POST" : "GET",
            headers: {
              "Content-Type": "application/json",
              "X-Hermes-Session-Token": window.WORKSPACE_TOKEN || "",
            },
            body: payload,
            signal: AbortSignal.timeout(30000),
            cache: "no-store",
          });
        let response = await send();
        if (response.status === 401) {
          await refreshWorkspaceToken(token);
          response = await send();
        }
        const data = await response.json();
        if (!response.ok) {
          const error = new Error(data.detail || "项目读取失败");
          error.status = response.status;
          throw error;
        }
        return data;
      },
      comparisonRequest(c) {
        const item = c.comparison || c.plan || c.job;
        return {
          revision: c.revision,
          kind: c.comparison ? "comparison" : c.plan ? "plan" : "job",
          id: item.id,
        };
      },
      get canRefreshComparison() {
        return !!(
          this.editorCandidate?.job ||
          this.editorCandidate?.comparison ||
          this.editorCandidate?.legacyComparison
        );
      },
      async workingApi(path, body, method = "POST", binary = false) {
        const token = window.WORKSPACE_TOKEN || "",
          payload = body ? JSON.stringify(body) : undefined;
        const send = () =>
          fetch("/api/miniclaw/canvas" + path, {
            method: body ? method : "GET",
            headers: {
              "Content-Type": "application/json",
              "X-Hermes-Session-Token": window.WORKSPACE_TOKEN || "",
            },
            body: payload,
            signal: AbortSignal.timeout(30000),
            cache: "no-store",
          });
        let response = await send();
        if (response.status === 401) {
          await refreshWorkspaceToken(token);
          response = await send();
        }
        if (!response.ok) {
          const data = await response.json();
          const error = new Error(data.detail || "图片保存连接失败");
          error.status = response.status;
          throw error;
        }
        return binary ? response.blob() : response.json();
      },
      async legacyJobComparison(latest, id) {
        const job = await this.workingApi(
          "/projects/" + this.editorProject + "/jobs/" + id,
        );
        if (
          job.state !== "succeeded" ||
          !job.output ||
          job.review?.decision === "reject"
        )
          throw Error("此结果暂不可采用，请先核对修图任务");
        const document = JSON.parse(JSON.stringify(latest.document)),
          layer = document.layers.find((l) => l.id === job.layer_id);
        if (!layer || layer.kind !== "image" || layer.locked || !layer.visible)
          throw Error("原图层不可编辑，请先在精修中检查；候选仍保留");
        layer.asset_id = job.output.id;
        const [before, after] = await Promise.all([
          this.workingApi(
            "/projects/" + this.editorProject + "/preview",
            { revision: latest.revision, document: latest.document },
            "POST",
            true,
          ),
          this.workingApi(
            "/projects/" + this.editorProject + "/preview",
            { revision: latest.revision, document },
            "POST",
            true,
          ),
        ]);
        const urls = [URL.createObjectURL(before), URL.createObjectURL(after)];
        return {
          project: this.editorProject,
          revision: latest.revision,
          output: urls[1],
          before_output: urls[0],
          previewUrls: urls,
          legacyComparison: { document, job: id, output: job.output.id },
        };
      },
      async applyEditorPreview(c) {
        if (!c.legacyComparison)
          return this.editApi(
            "/full/" + this.editorProject + "/apply-preview",
            this.comparisonRequest(c),
          );
        const path = "/projects/" + this.editorProject,
          basis = c.legacyComparison;
        const job = await this.workingApi(path + "/jobs/" + basis.job);
        if (
          job.state !== "succeeded" ||
          job.output?.id !== basis.output ||
          job.review?.decision === "reject"
        )
          throw Error("修图结果状态已变化，请重新核对");
        const current = await this.workingApi(path);
        if (current.revision === c.revision)
          return this.workingApi(
            path + "/document",
            {
              revision: c.revision,
              document: basis.document,
              label: "采用已比较的修图结果",
            },
            "PUT",
          );
        if (
          current.revision === c.revision + 1 &&
          JSON.stringify(current.document) === JSON.stringify(basis.document)
        )
          return current;
        const error = new Error("工作图已变化，候选已保留，请重新比较");
        error.status = 409;
        throw error;
      },
      async refreshEditorComparison() {
        if (this.editorApplying || !this.canRefreshComparison) return;
        this.editorApplying = true;
        this.editorComparing = true;
        try {
          await this.flushProject();
          const record = await this.projectApi("");
          const asset = record.state.assets.find(
            (a) => a.id === this.editAssetId,
          );
          if (!asset || asset.file !== this.editSource.file)
            throw Error("画布原图已改变，请返回画布重新选择；修图结果仍保留");
          const latest = await this.workingApi(
            "/projects/" + this.editorProject,
          );
          const job =
            this.editorCandidate.comparison?.job ||
            this.editorCandidate.legacyComparison?.job ||
            this.editorCandidate.job.id;
          let candidate;
          try {
            candidate = await this.editApi(
              "/full/" + this.editorProject + "/compare-job",
              { revision: latest.revision, job },
            );
          } catch (e) {
            if (![404, 405].includes(e.status)) throw e;
            candidate = await this.legacyJobComparison(latest, job);
          }
          this.previewUrls.forEach(URL.revokeObjectURL);
          this.previewUrls = candidate.previewUrls || [];
          this.previewBefore = candidate.before_output;
          this.editorCandidate = candidate;
          this.compareBasis = record.revision;
          this.adoptRequest = null;
          this.editorFailure = "";
          this.notify("比较已更新，请核对后采用");
        } catch (e) {
          this.editorFailure = e.message;
        } finally {
          this.editorApplying = false;
          this.editorComparing = false;
        }
      },
      async adoptFullEditor() {
        if (!this.editorCandidate || this.editorApplying) return;
        this.editorApplying = true;
        this.editorFailure = "";
        try {
          await this.flushProject();
          const canvasBasis = JSON.stringify(this.projectSnapshot());
          if (
            !this.adoptRequest &&
            (this.editorCandidate.plan ||
              this.editorCandidate.job ||
              this.editorCandidate.comparison ||
              this.editorCandidate.legacyComparison)
          ) {
            const c = this.editorCandidate;
            const updated = await this.applyEditorPreview(c);
            const output = await this.editApi(
              "/full/" + this.editorProject + "/preview",
              { revision: updated.revision },
            );
            this.editorCandidate = { ...output };
          }
          if (JSON.stringify(this.projectSnapshot()) !== canvasBasis)
            throw Error("画布有新的编辑，请先保存并重新比较后采用");
          if (!this.adoptRequest)
            this.adoptRequest = {
              request_id: crypto.randomUUID(),
              revision: this.compareBasis ?? this.projectRevision,
              action: "adopt",
              args: {
                object: this.editAssetId,
                source: this.editSource.file,
                project: this.editorProject,
                revision: this.editorCandidate.revision,
                asset: this.editorCandidate.output_id,
                ...(this.adoptShot ? { shot: this.adoptShot } : {}),
              },
            };
          localStorage.setItem(
            "studio-adopt:" + this.workspaceId,
            JSON.stringify(this.adoptRequest),
          );
          const record = await this.projectApi("/commands", this.adoptRequest);
          if (JSON.stringify(this.projectSnapshot()) !== canvasBasis || record.revision < this.projectRevision) {
            this.cacheDraft();
            this.projectConflict = true;
            this.projectError = "精修结果已保存到项目，当前画布的新编辑仍保留；请备份后读取最新版本。";
            this.projectChangeNotice = { status: "conflict", message: this.projectError, revision: record.revision, changes: (record.events || []).slice(-6) };
            clearTimeout(this._projectTimer);
            throw Error(this.projectError);
          }
          this._pendingRequest = null;
          this.adoptRequest = null;
          localStorage.removeItem("studio-adopt:" + this.workspaceId);
          for (const [key, value] of Object.entries(record.state))
            this[key] = value;
          this.projectRevision = record.revision;
          this.projectEvents = record.events;
          this._ack = JSON.stringify(this.projectSnapshot());
          const changedShot = this.shots.find((s) => s.id === this.adoptShot),
            changedInputs = changedShot
              ? changedShot.mode === "first"
                ? [changedShot.first]
                : changedShot.refs
              : [];
          const adoptedAsset =
            changedShot &&
            this.assets.find(
              (a) =>
                changedInputs.includes(a.id) &&
                a.editProject === this.editorProject &&
                a.file === this.editorCandidate.output,
            );
          const adoptedShot = this.adoptShot;
          this.editorApplying = false;
          this.closeFullEditor();
          this.persist();
          this.notify("图片已采用 · 关联片段待检查");
          if (adoptedAsset)
            this.$refs.director?.contentWindow.postMessage(
              {
                type: "miniclaw.director.image",
                workspace: this.workspaceId,
                target: adoptedShot,
                asset: adoptedAsset.id,
              },
              location.origin,
            );
          this.syncDirectorTarget();
        } catch (e) {
          this.editorFailure = e.message;
        } finally {
          this.editorApplying = false;
        }
      },
      async restoreEditOriginal() {
        const asset = this.asset;
        if (!asset?.originalFile) return;
        try {
          await this.flushProject();
          const record = await this.projectApi("/commands", {
            request_id: crypto.randomUUID(),
            revision: this.projectRevision,
            action: "restore",
            args: { object: asset.id, source: asset.file },
          });
          for (const [key, value] of Object.entries(record.state))
            this[key] = value;
          this.projectRevision = record.revision;
          this.projectEvents = record.events;
          this._ack = JSON.stringify(this.projectSnapshot());
          this.persist();
          this.notify("已恢复原图 · 关联片段待检查");
        } catch (e) {
          this.projectError = e.message;
        }
      },
    }),
  );
  return app;
}
