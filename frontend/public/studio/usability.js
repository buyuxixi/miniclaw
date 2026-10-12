/* Object operations and precision roundtrip, on the existing video canvas. */
function usableCanvas(app) {
  return baseUsableCanvas(app);
}
function baseUsableCanvas(app) {
  const copy = (value) => JSON.parse(JSON.stringify(value));
  const before = {
    init: app.init,
    remember: app.remember,
    getTarget: app.getTarget,
    objects: app.objects,
    keydown: app.keydown,
    quoteEdit: app.quoteEdit,
    directorAction: app.directorAction,
    bind: app.bind,
    isSaved: app.isSaved,
    undo: app.undo,
    askSelection: app.askSelection,
  };
  Object.assign(app, {
    workspaceId: crypto.randomUUID(),
    precision: {},
    clipEdit: null,
    editAssetId: null,
    editSource: null,
    editMeta: null,
    editReceipt: null,
    editMode: "local",
    editError: "",
    editBusy: false,
    editRetryAllowed: false,
    editScope: "whole",
    editAdjust: { brightness: 0, contrast: 0, saturation: 0 },
    editNonce: 0,
    narrationNode: {
      id: "narration",
      x: 1010,
      y: 700,
      w: 300,
      h: 95,
      removed: true,
    },
    toastUndo: false,
  });
  Object.defineProperties(
    app,
    Object.getOwnPropertyDescriptors({
      init() {
        before.init.call(this);
        this.selectedIds = this.selectedIds.filter((id) => this.getTarget(id));
        this.persist();
        this.$watch("panel", (value) => {
          if (!value) {
            this.editNonce++;
            this.editBusy = false;
          }
        });
      },
      get asset() {
        return (
          this.assets.find((a) => a.id === this.selection) ||
          this.assets[0] || { id: "", name: "图片", file: "source.png" }
        );
      },
      get shot() {
        return (
          this.shots.find((s) => s.id === this.active) ||
          this.shots[0] || {
            id: "",
            name: "视频片段",
            duration: 5,
            mode: "first",
            first: "",
            refs: [],
            prompt: "",
            x: 490,
            y: 115,
          }
        );
      },
      get editAsset() {
        return (
          this.assets.find((a) => a.id === this.editAssetId) ||
          this.editSource ||
          this.asset
        );
      },
      get quoteMissing() {
        return !!this.quote?.targetId && !this.getTarget(this.quote.targetId);
      },
      get isEditingRequest() {
        return (
          this.editBusy ||
          ["queued", "running", "unknown"].includes(this.editReceipt?.state)
        );
      },
      get clipAssets() {
        return this.assets.filter((a) => !a.pending);
      },
      isSaved(shot) {
        let plan = this.saved.find((p) => p.id === shot.id);
        return (
          !this.saveError &&
          before.isSaved.call(this, shot) &&
          !!plan?.inputs?.every(
            (input) =>
              this.assets.find((a) => a.id === input.id)?.file === input.file,
          )
        );
      },
      bind() {
        if (!this.shots.length) {
          let id = this.asset.id;
          this.addShot();
          this.openClip();
          this.clipChooseImage(id);
          return;
        }
        before.bind.call(this);
      },
      getTarget(id) {
        if (id === "candidate" && this.candidate.removed) return undefined;
        if (id === "narration")
          return this.narrationNode.removed ? undefined : this.narrationNode;
        return before.getTarget.call(this, id);
      },
      objects() {
        return before.objects
          .call(this)
          .filter((n) => n.id !== "candidate" || !this.candidate.removed)
          .concat(this.narrationNode.removed ? [] : [this.narrationNode]);
      },
      lines() {
        let paths = [];
        for (const s of this.shots)
          for (const id of s.mode === "first"
            ? s.first
              ? [s.first]
              : []
            : s.refs) {
            let asset = this.assets.find((a) => a.id === id);
            if (asset)
              paths.push(
                '<path d="' +
                  this.connection(asset, s) +
                  '" class="input-line"></path>',
              );
          }
        let s = this.shots.find((s) => s.id === "s1"),
          c = this.candidate;
        if (s && !c.removed)
          paths.push(
            '<path d="M ' +
              (s.x + 380) +
              " " +
              (s.y + 170) +
              " C " +
              (s.x + 460) +
              " " +
              (s.y + 170) +
              "," +
              (c.x - 80) +
              " " +
              (c.y + 170) +
              "," +
              c.x +
              " " +
              (c.y + 170) +
              '" class="candidate-line"></path>',
          );
        return paths.join("");
      },
      fit() {
        let e = this.$refs.world;
        if (!e) return;
        let items = this.objects();
        if (!items.length) {
          this.zoom = 1;
          this.pan = { x: 100, y: 88 };
          return;
        }
        let minX = Math.min(...items.map((n) => n.x)),
          minY = Math.min(...items.map((n) => n.y)) - 130,
          maxX = Math.max(...items.map((n) => n.x + n.w)),
          maxY = Math.max(...items.map((n) => n.y + n.h));
        const width = e.clientWidth - 180,
          height = e.clientHeight - 150;
        this.zoom = Math.max(
          0.2,
          Math.min(1, width / (maxX - minX), height / (maxY - minY)),
        );
        this.pan = {
          x: 100 + (width - (maxX - minX) * this.zoom) / 2 - minX * this.zoom,
          y: 32 + (height - (maxY - minY) * this.zoom) / 2 - minY * this.zoom,
        };
      },
      remember() {
        before.remember.call(this);
        Object.assign(this.history.at(-1), {
          narrationNode: copy(this.narrationNode),
          narration: this.narration,
          voice: this.voice,
        });
      },
      undo() {
        before.undo.call(this);
        this.selectedIds = this.selectedIds.filter((id) => this.getTarget(id));
        this.toastUndo = false;
      },
      askSelection() {
        if (this.getTarget(this.selection)) {
          before.askSelection.call(this);
          return;
        }
        this.ask("整支产品短片");
        if (!this.draft.trim())
          this.quote = { label: "整支产品短片", context: "", inputs: [] };
      },
      removeNodes(ids = this.selectedIds) {
        let selected = ids.filter((id) => this.getTarget(id));
        if (!selected.length) return;
        this.remember();
        let names = selected.map((id) =>
          id === "candidate"
            ? "视频候选"
            : id === "narration"
              ? "口播稿"
              : this.assets.find((a) => a.id === id)?.name ||
                this.shots.find((s) => s.id === id)?.name ||
                this.notes.find((n) => n.id === id)?.title,
        );
        let affected = 0,
          dirtyIds = [];
        this.assets = this.assets.filter((a) => !selected.includes(a.id));
        for (const s of this.shots) {
          if (
            selected.includes(s.first) ||
            s.refs.some((id) => selected.includes(id))
          ) {
            affected++;
            dirtyIds.push(s.id);
            s.dirty = true;
          }
          if (selected.includes(s.first)) s.first = "";
          s.refs = s.refs.filter((id) => !selected.includes(id));
          if (selected.includes(s.briefSource)) s.briefSource = null;
        }
        this.shots = this.shots.filter((s) => !selected.includes(s.id));
        this.notes = this.notes.filter((n) => !selected.includes(n.id));
        this.saved = this.saved.filter(
          (s) => !selected.includes(s.id) && !dirtyIds.includes(s.id),
        );
        if (selected.includes("candidate")) {
          this.candidate.removed = true;
          this.sequence = this.sequence.filter((id) => id !== "candidate-01");
        }
        if (selected.includes("narration")) {
          this.narrationNode.removed = true;
          this.voice = false;
        }
        if (!this.shots.some((s) => s.id === this.active))
          this.active = this.shots[0]?.id || "";
        this.selectedIds = [];
        this.selection = "";
        this.persist();
        this.toastUndo = true;
        this.toast =
          names.length === 1
            ? "已移除节点"
            : "已移除 " + names.length + " 个节点";
        clearTimeout(this._toast);
        this._toast = setTimeout(() => {
          this.toast = "";
          this.toastUndo = false;
        }, 2500);
      },
      keydown(e) {
        if (e.target.closest("input,textarea,select,video") || this.panel)
          return;
        if (
          ["Delete", "Backspace"].includes(e.key) &&
          this.selectedIds.length
        ) {
          e.preventDefault();
          this.removeNodes();
          return;
        }
        before.keydown.call(this, e);
      },
      openClip(id = this.active) {
        let shot = this.shots.find((s) => s.id === id);
        if (!shot) return;
        this.active = id;
        this.choose(id);
        this.clipEdit = copy(shot);
        let lines = shot.prompt.split("\n");
        this.clipEdit.camera =
          lines.find((l) => l.startsWith("镜头："))?.slice(3) || "";
        this.clipEdit.keep =
          lines.find((l) => l.startsWith("保持："))?.slice(3) || "";
        this.clipEdit.prompt = lines
          .filter((l) => !l.startsWith("镜头：") && !l.startsWith("保持："))
          .join("\n");
        if (!this.clipEdit.camera) {
          let camera = [
            "固定机位",
            "缓慢推近",
            "缓慢拉远",
            "从左向右移动",
          ].find((c) => this.clipEdit.prompt.startsWith(c + "。"));
          if (camera) {
            this.clipEdit.camera = camera;
            this.clipEdit.prompt = this.clipEdit.prompt
              .slice(camera.length + 1)
              .trim();
          }
        }
        this.panel = "clip";
      },
      clipChooseImage(id) {
        if (!this.clipEdit) return;
        if (this.clipEdit.mode === "first") this.clipEdit.first = id;
        else
          this.clipEdit.refs = this.clipEdit.refs.includes(id)
            ? this.clipEdit.refs.filter((x) => x !== id)
            : [...this.clipEdit.refs, id];
      },
      clipHasImage(id) {
        return (
          !!this.clipEdit &&
          (this.clipEdit.mode === "first"
            ? this.clipEdit.first === id
            : this.clipEdit.refs.includes(id))
        );
      },
      clipExample(text) {
        if (!this.clipEdit.prompt.trim()) this.clipEdit.prompt = text;
        else if (!this.clipEdit.prompt.includes(text))
          this.clipEdit.prompt += "\n" + text;
      },
      get clipPrompt() {
        if (!this.clipEdit) return "";
        return [
          this.clipEdit.prompt.trim(),
          this.clipEdit.camera ? "镜头：" + this.clipEdit.camera : "",
          this.clipEdit.keep.trim() ? "保持：" + this.clipEdit.keep.trim() : "",
        ]
          .filter(Boolean)
          .join("\n");
      },
      saveClip() {
        let shot = this.shots.find((s) => s.id === this.clipEdit?.id);
        if (!shot) return;
        this.remember();
        Object.assign(shot, {
          name: this.clipEdit.name.trim() || "视频片段",
          duration: this.clipEdit.duration,
          mode: this.clipEdit.mode,
          first: this.clipEdit.first,
          refs: [...this.clipEdit.refs],
          prompt: this.clipPrompt,
          dirty: true,
        });
        this.active = shot.id;
        this.choose(shot.id);
        if (!this.persist()) return;
        this.panel = "";
        this.notify("片段已更新");
        this.$nextTick(() => this.focusObject(shot.id));
      },
      nextClipAction(shot) {
        let has = shot.mode === "first" ? !!shot.first : !!shot.refs.length;
        return !has
          ? "选画面 →"
          : !shot.prompt.trim()
            ? "写视频要求 →"
            : "查看生成方案 →";
      },
      nextClip(shot) {
        let has = shot.mode === "first" ? !!shot.first : !!shot.refs.length;
        if (!has || !shot.prompt.trim()) this.openClip(shot.id);
        else this.prepare(shot.id);
      },
      directorAction(action) {
        if (this.quoteMissing) return;
        let id = this.quote?.targetId || this.quote?.shotId || this.active;
        if (action === "edit" && this.shots.some((s) => s.id === id)) {
          this.openClip(id);
          return;
        }
        before.directorAction.call(this, action);
      },
      async editApi(path, body) {
        let response = await fetch("/api/precision" + path, {
          method: body ? "POST" : "GET",
          headers: {
            "Content-Type": "application/json",
            "X-Workspace-Token": window.WORKSPACE_TOKEN || "",
          },
          body: body ? JSON.stringify(body) : undefined,
          signal: AbortSignal.timeout(30000),
          cache: "no-store",
        });
        let value = await response.json().catch(() => ({}));
        if (!response.ok) {
          let error = new Error(value.detail || "修图服务暂不可用，请重试连接");
          error.status = response.status;
          throw error;
        }
        return value;
      },
      async openEdit() {
        let asset = this.asset;
        if (!asset || asset.pending) return;
        this.editAssetId = asset.id;
        this.editSource = copy(asset);
        this.repair = this.edits[asset.id]?.text || "";
        this.region = this.edits[asset.id]?.region || null;
        this.editScope = this.region ? "region" : "whole";
        this.editAdjust = { brightness: 0, contrast: 0, saturation: 0 };
        this.editMode = "local";
        this.editMeta = null;
        this.editReceipt = null;
        this.editError = "";
        this.editRetryAllowed = false;
        this.editBusy = true;
        this.panel = "edit";
        let nonce = ++this.editNonce;
        try {
          let meta = await this.editApi("/open", {
            workspace: this.workspaceId,
            object_id: asset.id,
            file: asset.file,
            name: asset.name,
          });
          if (nonce !== this.editNonce) return;
          this.editMeta = meta;
          let entry = this.precision[asset.id];
          if (entry?.base === asset.file && entry.request) {
            this.editReceipt = entry.receipt || { state: "unknown" };
            this.editMode = entry.request.kind === "ai" ? "ai" : "local";
            if (entry.request.kind === "local")
              this.editAdjust = Object.fromEntries(
                Object.entries(entry.request.params).map(([k, v]) => [
                  k,
                  Math.round(v * 100),
                ]),
              );
            this.repair = entry.request.prompt || this.repair;
            await this.checkEdit();
          }
        } catch (error) {
          if (nonce === this.editNonce) this.editError = error.message;
        } finally {
          if (nonce === this.editNonce) this.editBusy = false;
        }
      },
      async reconnectEdit() {
        let id = this.editAssetId;
        this.choose(id);
        await this.openEdit();
      },
      async runEdit() {
        if (this.isEditingRequest || !this.editMeta) return;
        if (
          this.editScope === "region" &&
          (!this.region || this.region.w < 0.002 || this.region.h < 0.002)
        ) {
          this.editError = "请先拖动框选要修改的区域";
          return;
        }
        if (this.editMode === "ai" && !this.repair.trim()) {
          this.editError = "请写下想修改的地方";
          return;
        }
        if (
          this.editMode === "local" &&
          !Object.values(this.editAdjust).some((v) => Number(v) !== 0)
        ) {
          this.editError = "请先调节亮度、对比度或颜色，再预览";
          return;
        }
        let id = this.editAssetId,
          meta = this.editMeta,
          nonce = this.editNonce;
        let request = {
          request_id: crypto.randomUUID(),
          revision: meta.revision,
          source: meta.source,
          kind: this.editMode === "ai" ? "ai" : "local",
          params:
            this.editMode === "local"
              ? Object.fromEntries(
                  Object.entries(this.editAdjust).map(([k, v]) => [
                    k,
                    Number(v) / 100,
                  ]),
                )
              : {},
          region: this.editScope === "region" ? copy(this.region) : null,
          prompt: this.repair,
        };
        this.precision[id] = {
          meta: copy(meta),
          base: this.editSource.file,
          request,
          receipt: { state: "unknown" },
        };
        this.edits[id] = { text: this.repair, region: this.region };
        if (!this.persist()) {
          this.editError = this.saveError;
          return;
        }
        this.editError = "";
        this.editRetryAllowed = false;
        this.editReceipt = null;
        this.editBusy = true;
        try {
          let receipt = await this.editApi(
            "/projects/" + meta.project + "/edit",
            request,
          );
          this.acceptEditReceipt(id, receipt);
        } catch (error) {
          let rejected = [400, 409, 413].includes(error.status),
            receipt = {
              state: rejected ? "failed" : "unknown",
              error: error.message,
            };
          if (this.precision[id]?.request?.request_id === request.request_id) {
            this.precision[id].receipt = receipt;
            this.persist();
          }
          if (nonce === this.editNonce && this.editAssetId === id) {
            this.editReceipt = receipt;
            this.editError =
              error.message +
              (rejected ? "；可以重新连接并调整" : "；请查看上次修图进度");
          }
        } finally {
          if (nonce === this.editNonce && this.editAssetId === id)
            this.editBusy = false;
        }
      },
      acceptEditReceipt(id, receipt) {
        let entry = this.precision[id];
        if (!entry) return;
        entry.receipt = receipt;
        this.persist();
        if (
          this.editAssetId !== id ||
          !this.editMeta ||
          entry.base !== this.editSource?.file
        )
          return;
        this.editRetryAllowed = false;
        this.editReceipt = receipt;
        this.editMeta.revision = receipt.revision;
        this.editError =
          receipt.state === "failed"
            ? receipt.error || "修图失败，原图保留"
            : receipt.state === "unknown"
              ? "结果暂未确认，请核对原请求"
              : "";
        if (["queued", "running"].includes(receipt.state))
          setTimeout(() => {
            if (this.panel === "edit" && this.editAssetId === id)
              this.checkEdit();
          }, 1300);
      },
      async checkEdit() {
        let id = this.editAssetId,
          entry = this.precision[id];
        if (!entry?.request) return;
        const requestId = entry.request.request_id;
        try {
          let receipt = await this.editApi(
            "/projects/" + entry.meta.project + "/requests/" + requestId,
          );
          if (this.precision[id]?.request?.request_id === requestId)
            this.acceptEditReceipt(id, receipt);
        } catch (error) {
          if (this.editAssetId === id) {
            this.editError = error.message;
            this.editRetryAllowed =
              error.message === "原请求尚未受理，可重新提交同一请求";
          }
        }
      },
      async retryEdit() {
        let id = this.editAssetId,
          entry = this.precision[id];
        if (!this.editRetryAllowed || !entry?.request || this.editBusy) return;
        this.editBusy = true;
        this.editRetryAllowed = false;
        this.editError = "";
        try {
          this.acceptEditReceipt(
            id,
            await this.editApi(
              "/projects/" + entry.meta.project + "/edit",
              entry.request,
            ),
          );
        } catch (error) {
          this.editError = error.message + "；请核对原请求";
        } finally {
          this.editBusy = false;
        }
      },
      async applyEdit() {
        let id = this.editAssetId,
          asset = this.assets.find((a) => a.id === id),
          receipt = this.editReceipt;
        if (asset && receipt?.output === asset.file) {
          if (this.persist()) {
            this.panel = "";
            this.notify("精修结果已保存到画布");
          }
          return;
        }
        if (!asset || asset.file !== this.editSource.file) {
          this.editError = "画布里的图片已变化，结果仍保留，请重新打开核对";
          return;
        }
        if (this.editBusy || receipt?.state !== "succeeded" || !receipt.output)
          return;
        let nonce = this.editNonce;
        this.editBusy = true;
        this.editError = "";
        try {
          let meta = await this.editApi(
            "/projects/" + this.editMeta.project + "/apply",
            {
              request_id: receipt.request_id,
              revision: this.editMeta.revision,
            },
          );
          if (
            !this.assets.some((a) => a.id === id) ||
            asset.file !== this.editSource.file
          ) {
            this.editError = "原素材已变化，修图结果已保留";
            return;
          }
          this.remember();
          asset.originalFile = asset.originalFile || asset.file;
          asset.versions = asset.versions || [];
          asset.versions.push({
            file: receipt.output,
            request: receipt.request_id,
          });
          asset.file = receipt.output;
          this.edits[id] = {
            text: this.repair,
            region: this.region,
            applied: true,
          };
          this.precision[id].meta = meta;
          for (let s of this.shots)
            if (s.first === id || s.refs.includes(id)) s.dirty = true;
          if (!this.persist()) {
            if (nonce === this.editNonce) this.editError = this.saveError;
            return;
          }
          if (nonce === this.editNonce && this.editAssetId === id) {
            this.choose(id);
            this.panel = "";
            this.notify("精修结果已用于画布 · 原图保留");
          }
        } catch (error) {
          if (nonce === this.editNonce) this.editError = error.message;
        } finally {
          if (nonce === this.editNonce) this.editBusy = false;
        }
      },
      async restoreEditOriginal() {
        let asset = this.assets.find((a) => a.id === this.editAssetId);
        if (!asset?.originalFile) return;
        this.remember();
        asset.file = asset.originalFile;
        this.edits[asset.id] = { ...this.edits[asset.id], applied: false };
        for (let s of this.shots)
          if (s.first === asset.id || s.refs.includes(asset.id)) s.dirty = true;
        if (!this.persist()) return;
        await this.reconnectEdit();
      },
      editState() {
        return (
          {
            queued: "已排队，等待修图",
            running: "正在修图，可以关闭窗口稍后查看",
            unknown: "结果待核对，不会自动重新提交",
            succeeded: "修图完成，请对比后采用",
            failed: "修改失败，原图保留",
            canceled: "已停止接收结果",
          }[this.editReceipt?.state] || ""
        );
      },
    }),
  );
  return app;
}
