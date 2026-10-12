/* Actual project identity and model results, layered onto the existing canvas. */
function withStudioProduction(app) {
  const load = app.loadSharedProject,
    init = app.init,
    objects = app.objects,
    getTarget = app.getTarget,
    appProject = app.showProject,
    move = app.dragMove,
    end = app.dragEnd,
    start = app.dragStart,
    remember = app.remember,
    remove = app.removeNodes,
    keydown = app.keydown,
    addShot = app.addShot;
  let moveFrame = null,
    lastMove = null,
    panPreview = null,
    nodePreview = null,
    dragDiagnostics = { frames: 0, pathWrites: 0, commits: 0, samples: [] };
  const now = () =>
    typeof performance === "undefined" ? Date.now() : performance.now();
  const paintNodes = (self, event) => {
    const d = self.drag;
    if (!d || !nodePreview) return;
    const started = now(),
      dx = (event.clientX - d.x) / self.zoom,
      dy = (event.clientY - d.y) / self.zoom;
    nodePreview.point = event;
    for (const item of nodePreview.items)
      if (item.element)
        item.element.style.transform = "translate(" + dx + "px," + dy + "px)";
    const ports = new Map(nodePreview.ports);
    for (const item of d.items)
      for (const side of ["in", "out"]) {
        const key = item.id + ":" + side,
          p = ports.get(key);
        if (p) ports.set(key, { x: p.x + dx, y: p.y + dy });
      }
    const nodes = nodePreview.nodes.map((n) =>
      nodePreview.ids.has(n.id) ? { ...n, x: n.x + dx, y: n.y + dy } : n,
    );
    for (const edge of nodePreview.edges) {
      const path = self.edgeGeometry(edge, { ports, nodes }).path;
      for (const element of edge.elements) {
        element.setAttribute("d", path);
        dragDiagnostics.pathWrites++;
      }
    }
    for (const control of nodePreview.controls)
      control.style.visibility = "hidden";
    dragDiagnostics.frames++;
    dragDiagnostics.samples.push(now() - started);
    if (dragDiagnostics.samples.length > 120) dragDiagnostics.samples.shift();
  };
  const previewMove = (self, point) => {
    if (self.drag.kind === "pan") paintPan(self, point);
    else if (self.drag.kind === "nodes" && nodePreview) paintNodes(self, point);
    else move.call(self, point);
  };
  const paintPan = (self, event) => {
    const d = self.drag;
    if (!d) return;
    panPreview = {
      x: d.ox + event.clientX - d.x,
      y: d.oy + event.clientY - d.y,
    };
    const world = self.$refs.world?.querySelector(".world");
    if (world)
      world.style.transform =
        "translate(" +
        panPreview.x +
        "px," +
        panPreview.y +
        "px) scale(" +
        self.zoom +
        ")";
  };
  Object.assign(app, {
    connectionDraft: null,
    selectedEdge: null,
    dragClick: false,
    projectTab: "overview",
    audit: { entries: [], estimate_cny: 0, unestimated_count: 0, notice: "" },
    auditError: "",
    projectName: "正在读取项目…",
    productionLoading: true,
    videoJobs: [],
    videoRenders: [],
    videoProvider: { configured: false },
    videoBusy: false,
    videoError: "",
    reviewVideoId: "",
    videoRequests: {},
  });
  Object.defineProperties(
    app,
    Object.getOwnPropertyDescriptors({
      get dragDiagnostics() {
        return { ...dragDiagnostics, samples: [...dragDiagnostics.samples] };
      },
      init() {
        if (!studioWorkspaceId()) {
          location.replace("/projects");
          return;
        }
        init.call(this);
        this._videoTimer = setInterval(() => {
          if (this.projectReady) {
            void this.refreshVideo();
            if (this.assistant || this.projectChangeNotice?.status === "pending" || !this._studioChannel)
              void this.refreshProjectChanges?.(this.assistant ? "助手" : "项目");
          }
        }, 5000);
      },
      async loadSharedProject() {
        try {
          await load.call(this);
          if (!this.projectReady) return;
          this.productionLoading = false;
          if (!this._initialFocus) {
            this._initialFocus = true;
            this.history = [];
            const focus = new URLSearchParams(location.search).get("focus");
            this.$nextTick(() =>
              requestAnimationFrame(() => {
                this.fit();
                const target = focus || this.selection || this.active;
                if (target && this.getTarget(target)) {
                  this.choose(target);
                  if (focus) this.focusObject(target);
                  else if (this.zoom < 0.6) this.readableView();
                }
              }),
            );
          }
          // Project content is usable before auxiliary metadata and task lists arrive.
          await Promise.allSettled([
            this.projectApi("/info").then((info) => {
              this.projectName = shortStudioName(
                info?.name,
                this.notes,
                this.shots,
              );
              this.sharedChatId=info?.chat_id||null;
            }),
            this.refreshVideo(),
          ]);
        } catch (e) {
          this.projectError = e.message;
        } finally {
          this.productionLoading = false;
        }
      },
      readableView() {
        const items = this.objects(),
          world = this.$refs.world;
        if (!items.length || !world) return;
        const left = Math.min(...items.map((n) => n.x)),
          right = Math.max(...items.map((n) => n.x + n.w)),
          top = Math.min(...items.map((n) => n.y));
        this.zoom = world.clientHeight >= 750 ? 0.61 : 0.55;
        this.pan = {
          x:
            Math.max(90, (world.clientWidth - (right - left) * this.zoom) / 2) -
            left * this.zoom,
          y: 80 - top * this.zoom,
        };
      },
      dragMove(event) {
        if (!this.drag) return;
        lastMove = { clientX: event.clientX, clientY: event.clientY };
        if (moveFrame !== null) return;
        moveFrame = requestAnimationFrame(() => {
          moveFrame = null;
          const point = lastMove;
          lastMove = null;
          if (this.drag && point) previewMove(this, point);
        });
      },
      dragStart(event, id) {
        if (this.connectionDraft || event.target.closest(".node-port")) return;
        const video = event.target.closest("video");
        if (video && event.clientY >= video.getBoundingClientRect().bottom - 32)
          return;
        this.selectedEdge = null;
        if (id && event.target.closest(".asset-image,.plan-content")) {
          const original = event.target;
          start.call(
            this,
            {
              button: event.button,
              clientX: event.clientX,
              clientY: event.clientY,
              shiftKey: event.shiftKey,
              pointerId: event.pointerId,
              currentTarget: event.currentTarget,
              target: {
                closest: (selector) =>
                  selector === "button,input,textarea,select,a"
                    ? null
                    : original.closest(selector),
              },
              preventDefault: () => event.preventDefault(),
            },
            id,
          );
          event.preventDefault();
        } else start.call(this, event, id);
        const world = this.$refs.world;
        if (this.drag?.kind === "nodes" && world?.querySelectorAll) {
          dragDiagnostics = {
            frames: 0,
            pathWrites: 0,
            commits: 0,
            samples: [],
          };
          const ids = new Set(this.drag.items.map((n) => n.id)),
            elements = [...world.querySelectorAll("[data-object-id]")],
            groups = [...world.querySelectorAll("[data-edge-id]")],
            ports = new Map(),
            nodes = this.objects();
          for (const n of nodes)
            for (const side of ["in", "out"])
              ports.set(n.id + ":" + side, this.portPoint(n.id, side));
          nodePreview = {
            ids,
            nodes,
            ports,
            point: null,
            controls: [this.$refs.composer, this.$refs.contextToolbar].filter(
              Boolean,
            ),
            items: this.drag.items.map((n) => ({
              element: elements.find((el) => el.dataset.objectId === n.id),
            })),
            edges: this.canvasEdges()
              .filter((e) => ids.has(e.from) || ids.has(e.to))
              .map((e) => ({
                ...e,
                elements: [
                  ...(groups
                    .find((g) => g.dataset.edgeId === e.id)
                    ?.querySelectorAll("path") || []),
                ],
              })),
          };
        }
      },
      dragEnd() {
        if (moveFrame !== null) {
          cancelAnimationFrame(moveFrame);
          moveFrame = null;
        }
        if (lastMove && this.drag) previewMove(this, lastMove);
        lastMove = null;
        if (nodePreview) {
          if (nodePreview.point && this.drag) {
            move.call(this, nodePreview.point);
            dragDiagnostics.commits++;
          }
          for (const item of nodePreview.items)
            if (item.element) item.element.style.removeProperty("transform");
          for (const control of nodePreview.controls)
            control.style.removeProperty("visibility");
          nodePreview = null;
        }
        if (panPreview) {
          this.pan = panPreview;
          panPreview = null;
        }
        const d = this.drag;
        this.dragClick =
          !!d &&
          (d.kind === "pan"
            ? Math.hypot(this.pan.x - d.ox, this.pan.y - d.oy) > 4
            : d.kind === "marquee"
              ? Math.max(this.marquee.w, this.marquee.h) * this.zoom > 4
              : !!d.moved);
        end.call(this);
        if (this.$refs.world?.dataset && dragDiagnostics.frames)
          this.$refs.world.dataset.dragDiagnostics =
            JSON.stringify(dragDiagnostics);
        if (this.dragClick) setTimeout(() => (this.dragClick = false), 0);
      },
      getTarget(id) {
        if (id === "narration")
          return this.narrationNode.removed ? undefined : this.narrationNode;
        if (id.startsWith("video-")) {
          const job = this.videoJobs.find((j) => "video-" + j.id === id);
          if (!job || this.canvasLayout[id]?.hidden) return;
          return this.canvasLayout[id] || this.videoPosition(job);
        }
        return id === "candidate" ? undefined : getTarget.call(this, id);
      },
      remember() {
        remember.call(this);
        this.history.at(-1).canvasLayout = JSON.parse(
          JSON.stringify(this.canvasLayout),
        );
      },
      removeNodes(ids = this.selectedIds) {
        const videos = ids.filter(
          (id) => id.startsWith("video-") && this.getTarget(id),
        );
        if (!videos.length) {
          remove.call(this, ids);
          return;
        }
        this.remember();
        const other = ids.filter((id) => !videos.includes(id));
        if (other.length) {
          remove.call(this, other);
          this.history.splice(-2, 1);
        }
        for (const id of videos) this.getTarget(id).hidden = true;
        this.selection = "";
        this.selectedIds = [];
        this.persist();
        this.toastUndo = true;
        this.notify("结果已从画布收起，任务与已采用视频保留");
      },
      get selectionName() {
        if (this.selectedIds.length > 1)
          return this.selectedIds.length + " 个对象";
        if (this.selection === "narration") return "口播稿";
        return (
          this.assets.find((a) => a.id === this.selection)?.name ||
          this.shots.find((s) => s.id === this.selection)?.name ||
          this.notes.find((n) => n.id === this.selection)?.title ||
          (this.videoJobs.find((j) => "video-" + j.id === this.selection)
            ?.name || "") + " · 视频结果"
        );
      },
      addNarration() {
        this.remember();
        this.narrationNode = {
          ...this.narrationNode,
          ...this.freePosition(60, 400, 300, 110),
          removed: false,
        };
        this.narration = "";
        this.voice = false;
        this.choose("narration");
        this.persist();
        this.panel = "script";
        this.addMenu = false;
      },
      addShot() {
        addShot.call(this);
        this.shot.videoProvider = this.videoProvider.provider || "minimax";
        this.persist();
      },
      removeNarration() {
        if (this.narrationNode.removed) return;
        this.remember();
        this.narrationNode = { ...this.narrationNode, removed: true };
        this.voice = false;
        this.selectedIds = this.selectedIds.filter((id) => id !== "narration");
        if (this.selection === "narration") this.selection = this.active;
        this.persist();
        this.toastUndo = true;
        this.notify("口播节点已移除，可以撤销");
      },
      auditAmount(job) {
        return job?.estimate_cny == null
          ? "无法估算"
          : "预估 ¥" + Number(job.estimate_cny).toFixed(3).replace(/0$/, "");
      },
      assetAudit(id) {
        return this.audit.entries.find(
          (j) => j.kind === "image" && j.objects?.includes(id),
        );
      },
      async showAudit() {
        this.projectTab = "audit";
        await this.showProject();
      },
      async refreshAudit() {
        try {
          this.audit = await this.projectApi("/audit");
          this.auditError = "";
        } catch (e) {
          this.auditError = e.message;
        }
      },
      async showProject() {
        await appProject.call(this);
        await this.refreshAudit();
      },
      exportAudit() {
        const link = document.createElement("a"),
          url = URL.createObjectURL(
            new Blob([JSON.stringify(this.audit, null, 2)], {
              type: "application/json",
            }),
          );
        link.href = url;
        link.download = this.projectName + "-生成审计.json";
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      },
      objects() {
        return objects
          .call(this)
          .filter((n) => n.id !== "candidate")
          .map((n) =>
            n === this.narrationNode
              ? { ...n, id: "narration", w: 300, h: 110 }
              : this.shots.some((s) => s.id === n.id)
                ? { ...n, h: 360 }
                : n,
          )
          .concat(
            this.visibleVideoJobs.map((j) => ({
              ...this.videoPosition(j),
              id: "video-" + j.id,
              w: 380,
              h: 400,
            })),
          );
      },
      get visibleVideoJobs() {
        return this.videoJobs.filter(
          (j) => !this.canvasLayout["video-" + j.id]?.hidden,
        );
      },
      defaultVideoPosition(job) {
        const shot = this.shots.find((s) => s.id === job.shot);
        return {
          x: shot?.x ?? 500,
          y:
            (shot?.y ?? 40) +
            430 +
            this.videoJobs.filter((j) => j.shot === job.shot).indexOf(job) *
              430,
        };
      },
      videoPosition(job) {
        return (
          this.canvasLayout["video-" + job.id] ??
          (this.canvasLayout["video-" + job.id] =
            this.defaultVideoPosition(job))
        );
      },
      organizeLayout() {
        this.remember();
        this.clearCanvasSelection();
        let noteY = 40,
          imageY = 40,
          shotY = 40;
        const size = this.mediaSize(),
          imageX =
            60 +
            Math.max(
              190,
              this.narrationNode.removed ? 0 : 300,
              ...this.notes.map((n) => n.w || 360),
            ) +
            180,
          shotX = imageX + Math.max(250, ...this.assets.map((a) => a.w)) + 180,
          resultX = shotX + size.w + 180;
        for (const n of this.notes) {
          Object.assign(n, { x: 60, y: noteY });
          noteY += (n.h || 280) + 90;
        }
        for (const a of this.assets) {
          Object.assign(a, { x: imageX, y: imageY });
          imageY += a.h + 34 + 90;
        }
        for (const s of this.shots) {
          Object.assign(s, { x: shotX, y: shotY });
          const jobs = this.visibleVideoJobs.filter((j) => j.shot === s.id);
          jobs.forEach((j, i) => {
            this.canvasLayout["video-" + j.id] = {
              ...this.canvasLayout["video-" + j.id],
              x: resultX,
              y: shotY + i * (size.h + 124),
            };
          });
          shotY += Math.max(1, jobs.length) * (size.h + 124);
        }
        if (!this.narrationNode.removed)
          Object.assign(this.narrationNode, { x: 60, y: noteY });
        this.persist();
        this.fit();
        if (this.zoom < 0.55 && this.$refs.world.clientWidth >= 700) {
          const nodes = this.objects();
          this.zoom = 0.55;
          this.pan = {
            x: 100 - Math.min(...nodes.map((n) => n.x)) * 0.55,
            y: 100 - Math.min(...nodes.map((n) => n.y)) * 0.55,
          };
        }
        this.notify("已整理，可撤销 · 全览查看全部");
      },
      canvasEdges() {
        const edges = [],
          assets = new Set(this.assets.map((a) => a.id)),
          notes = new Set(this.notes.map((n) => n.id));
        for (const s of this.shots) {
          for (const id of s.mode === "first" ? [s.first] : s.refs) {
            if (assets.has(id))
              edges.push({
                id: id + ">" + s.id,
                from: id,
                to: s.id,
                kind: "image",
                label: s.mode === "first" ? "首帧" : "参考图",
                editable: true,
              });
          }
          if (notes.has(s.briefSource))
            edges.push({
              id: s.briefSource + ">" + s.id,
              from: s.briefSource,
              to: s.id,
              kind: "brief",
              label: "创意依据",
              editable: true,
            });
          for (const j of this.visibleVideoJobs.filter((j) => j.shot === s.id))
            edges.push({
              id: s.id + ">video-" + j.id,
              from: s.id,
              to: "video-" + j.id,
              kind: "result",
              label: "生成结果",
              editable: false,
            });
        }
        const scene = { nodes: this.objects() };
        return edges.map((e) => ({ ...e, ...this.edgeGeometry(e, scene) }));
      },
      portPoint(id, side) {
        const n =
          this.assets.find((a) => a.id === id) ||
          this.shots.find((s) => s.id === id) ||
          this.notes.find((n) => n.id === id) ||
          this.getTarget(id);
        if (!n) return { x: 0, y: 0 };
        return {
          x: n.x + (side === "out" ? n.w || 380 : 0),
          y: n.y + (id.startsWith("video-") ? 32 : 100),
        };
      },
      edgeGeometry(edge) {
        const a = this.portPoint(edge.from, "out"),
          b = this.portPoint(edge.to, edge.kind === "result" ? "out" : "in");
        if (edge.kind === "result") {
          const lane = Math.max(a.x, b.x) + 90,
            end = b.x + 12 / this.zoom,
            nodes = this.objects(),
            obstacles = nodes.filter(
              (n) => n.id !== edge.from && n.id !== edge.to,
            );
          const blocked = Array.from({ length: 25 }, (_, i) => {
            const t = i / 24,
              u = 1 - t;
            return {
              x:
                u * u * u * a.x +
                3 * u * u * t * lane +
                3 * u * t * t * lane +
                t * t * t * end,
              y:
                u * u * u * a.y +
                3 * u * u * t * a.y +
                3 * u * t * t * b.y +
                t * t * t * b.y,
            };
          }).some((p) =>
            obstacles.some(
              (n) =>
                p.x >= n.x - 8 / this.zoom &&
                p.x <= n.x + n.w + 8 / this.zoom &&
                p.y >= n.y - 8 / this.zoom &&
                p.y <= n.y + n.h + 8 / this.zoom,
            ),
          );
          if (blocked) {
            const index = Math.max(
                0,
                this.visibleVideoJobs.findIndex(
                  (j) => "video-" + j.id === edge.to,
                ),
              ),
              outer =
                Math.max(...nodes.map((n) => n.x + n.w)) + 50 + index * 24,
              top = Math.min(...nodes.map((n) => n.y)) - 100 - index * 24,
              escape = a.x + 24;
            return {
              path:
                "M " +
                a.x +
                " " +
                a.y +
                " L " +
                escape +
                " " +
                a.y +
                " L " +
                escape +
                " " +
                top +
                " L " +
                outer +
                " " +
                top +
                " L " +
                outer +
                " " +
                b.y +
                " L " +
                end +
                " " +
                b.y,
              lx: outer - 12,
              ly: (top + b.y) / 2,
            };
          }
          return {
            path:
              "M " +
              a.x +
              " " +
              a.y +
              " C " +
              lane +
              " " +
              a.y +
              ", " +
              lane +
              " " +
              b.y +
              ", " +
              end +
              " " +
              b.y,
            lx: lane - 12,
            ly: (a.y + b.y) / 2,
          };
        }
        const sources = this.assets.concat(this.notes),
          index = Math.max(
            0,
            sources.findIndex((n) => n.id === edge.from),
          ),
          lane = Math.min(a.y, b.y) - 145 - index * 26,
          left = a.x + 24,
          right = b.x - 24;
        return {
          path:
            "M " +
            a.x +
            " " +
            a.y +
            " L " +
            left +
            " " +
            a.y +
            " L " +
            left +
            " " +
            lane +
            " L " +
            right +
            " " +
            lane +
            " L " +
            right +
            " " +
            b.y +
            " L " +
            (b.x - 12 / this.zoom) +
            " " +
            b.y,
          lx: (left + right) / 2,
          ly: lane - 8,
        };
      },
      edgeActive(e) {
        return (
          this.selectedEdge?.id === e.id ||
          this.selectedIds.includes(e.from) ||
          this.selectedIds.includes(e.to)
        );
      },
      edgeDescription(e) {
        const from =
          this.assets.find((a) => a.id === e.from)?.name ||
          this.notes.find((n) => n.id === e.from)?.title ||
          this.shots.find((s) => s.id === e.from)?.name ||
          "来源";
        const to =
          this.shots.find((s) => s.id === e.to)?.name ||
          this.videoJobs.find((j) => "video-" + j.id === e.to)?.name +
            " · 结果";
        return from + " → " + to + " · " + e.label;
      },
      selectEdge(e) {
        this.selectedEdge = e;
        this.selection = "";
        this.selectedIds = [];
      },
      showInputConnection(id) {
        const edge = this.canvasEdges().find((e) => e.to === id && e.editable);
        if (edge) this.selectEdge(edge);
        else this.notify("从图片或创意备注的右侧端口拖入");
      },
      disconnectEdge(e = this.selectedEdge) {
        if (!e?.editable) return;
        const shot = this.shots.find((s) => s.id === e.to);
        if (!shot) return;
        this.remember();
        if (e.kind === "brief") {
          shot.briefSource = null;
          shot.creativeBrief = "";
        } else if (shot.mode === "first") {
          shot.first = "";
        } else {
          shot.refs = shot.refs.filter((id) => id !== e.from);
        }
        shot.dirty = true;
        this.saved = this.saved.filter((s) => s.id !== shot.id);
        this.selectedEdge = null;
        this.persist();
        this.notify("已断开" + e.label + "连接，可撤销");
      },
      startConnection(event, id) {
        if (event.button !== 0) return;
        event.preventDefault();
        this.connectionDraft = { from: id, point: this.point(event) };
        this.selectedEdge = null;
        this.$refs.world.setPointerCapture?.(event.pointerId);
      },
      moveConnection(event) {
        if (this.connectionDraft)
          this.connectionDraft.point = this.point(event);
      },
      endConnection(event) {
        if (!this.connectionDraft) return;
        const from = this.connectionDraft.from;
        const node = document
          .elementFromPoint(event.clientX, event.clientY)
          ?.closest("[data-object-id]");
        const to = node?.dataset.objectId;
        if (to === from) return;
        this.connectionDraft = null;
        if (to) this.connectNodes(from, to);
        else this.notify("将输出端口拖到视频片段的输入端口");
      },
      connectNodes(from, to) {
        const shot = this.shots.find((s) => s.id === to),
          asset = this.assets.find((a) => a.id === from),
          note = this.notes.find((n) => n.id === from);
        if (!shot || (!asset && !note) || asset?.pending) {
          this.notify("图片或创意备注可以连接到视频片段");
          return false;
        }
        if (
          (asset &&
            (shot.mode === "first"
              ? shot.first === from
              : shot.refs.includes(from))) ||
          (note && shot.briefSource === from)
        )
          return false;
        this.remember();
        if (asset) {
          if (shot.mode === "first" && !shot.first) shot.first = from;
          else {
            shot.refs = [
              ...new Set([
                ...(shot.refs || []),
                ...(shot.mode === "first" && shot.first ? [shot.first] : []),
                from,
              ]),
            ];
            shot.mode = "reference";
          }
        } else {
          shot.briefSource = from;
          shot.creativeBrief = note.text;
        }
        shot.dirty = true;
        this.saved = this.saved.filter((s) => s.id !== shot.id);
        this.active = to;
        this.choose(to);
        this.persist();
        this.notify(
          asset
            ? "已连接图片 · " +
                (shot.mode === "first" ? 1 : shot.refs.length) +
                " 张"
            : "已连接创意依据",
        );
        return true;
      },
      connectionPreview() {
        if (!this.connectionDraft) return "";
        const a = this.portPoint(this.connectionDraft.from, "out"),
          b = this.connectionDraft.point;
        return (
          "M " +
          a.x +
          " " +
          a.y +
          " C " +
          (a.x + 100) +
          " " +
          a.y +
          ", " +
          (b.x - 100) +
          " " +
          b.y +
          ", " +
          b.x +
          " " +
          b.y
        );
      },
      keydown(e) {
        if (e.key === "Escape") this.connectionDraft = null;
        if (
          this.selectedEdge &&
          ["Delete", "Backspace"].includes(e.key) &&
          !e.target.closest("input,textarea,select,video") &&
          !this.panel
        ) {
          e.preventDefault();
          this.disconnectEdge();
          return;
        }
        keydown.call(this, e);
      },
      get adoptedSeconds() {
        return (
          this.sequence.filter((s) => typeof s === "object" && s.job).length * 5
        );
      },
      get targetSeconds() {
        return (
          this.shots.reduce((n, s) => n + Number(s.duration || 5), 0) || 10
        );
      },
      get selectedVideo() {
        return this.videoJobs.find((j) => j.id === this.reviewVideoId);
      },
      get currentRender() {
        return this.videoRenders.find(
          (r) => r.state === "succeeded" && !r.stale,
        );
      },
      get videoSequence() {
        return this.sequence
          .filter((s) => typeof s === "object" && s.job)
          .map((s) => ({
            ...s,
            video: this.videoJobs.find((j) => j.id === s.job),
          }));
      },
      get selectedAssemblyClip() {
        return this.videoSequence.find((s) => s.job === this.assemblyClip) || this.videoSequence[0] || null;
      },
      get assemblySelection() {
        return this.selectedAssemblyClip?.video || null;
      },
      selectAssemblyClip(job) {
        const id = typeof job === "string" ? job : job?.job || job?.id;
        const clip = this.videoSequence.find((s) => s.job === id);
        if (!clip?.video) {
          this.notify("这个片段暂不可读，请刷新视频进度");
          return;
        }
        this.assemblyClip = clip.job;
        const shot = this.shots.find((s) => s.id === clip.video.shot);
        if (shot) {
          this.active = shot.id;
          this.choose(shot.id);
        }
      },
      locateAssemblyClip() {
        const job = this.assemblySelection;
        const id = job?.shot;
        if (!id || !this.shots.some((s) => s.id === id)) {
          this.notify("原镜头已移除，已采用的视频仍保留");
          return;
        }
        this.view = "canvas";
        this.active = id;
        this.choose(id);
        this.$nextTick(() => this.focusObject(id));
      },
      openAssemblyForShot(shot) {
        const selected = shot || this.shots.find((s) => s.id === this.selection) || this.shot;
        const id = typeof selected === "string" ? selected : selected?.id;
        const clip = this.videoSequence.find((s) => s.video?.shot === id);
        if (!clip) {
          this.notify("这个镜头还没有采用的视频，请先比较并采用");
          return;
        }
        this.selectAssemblyClip(clip.job);
        this.view = "assemble";
      },
      providerFor(shot) {
        return (
          this.videoProvider.options?.find(
            (p) =>
              p.provider ===
              (shot.videoProvider || this.videoProvider.provider),
          ) || this.videoProvider
        );
      },
      providerLabel(shot) {
        const p = this.providerFor(shot);
        return (
          (p.model || "正在读取模型") +
          " · " +
          (p.resolution || "") +
          " · " +
          (p.duration || 5) +
          "秒生成"
        );
      },
      providerPrice(shot) {
        const p = this.providerFor(shot);
        return p.reference_cny == null
          ? "费用待账单核对"
          : "参考 ¥" + Number(p.reference_cny).toFixed(2) + " / 次";
      },
      changeVideoProvider() {
        this.changed();
        this.videoError = "";
      },
      videoState(job) {
        if (job.stale) return "历史结果 · 要求已更新";
        if (this.videoAdopted(job)) return "已采用 · " + job.duration + " 秒";
        return (
          {
            queued: "等待提交",
            submitting: "正在提交",
            running: "模型生成中",
            succeeded: "生成完成 · 待核对",
            failed: "生成未完成",
            unknown: "提交结果待核对",
          }[job.state] || job.state
        );
      },
      latestShotJob(shot) {
        return this.videoJobs
          .filter((j) => j.shot === shot.id && !j.stale)
          .at(-1);
      },
      videoAdopted(job) {
        return this.sequence.some((s) => s?.job === job.id);
      },
      async refreshVideo() {
        try {
          const response = await this.projectApi("/video");
          this.videoJobs = response.jobs;
          this.videoRenders = response.renders;
          this.videoProvider = response.provider;
        } catch (e) {
          this.videoError = e.message;
        }
      },
      prepare(id) {
        this.active = id;
        this.videoError = "";
        this.panel = "plan";
        void this.refreshVideo();
      },
      nextClipAction(shot) {
        return !shot.first || shot.mode !== "first"
          ? "选首帧 →"
          : !shot.prompt.trim()
            ? "写镜头要求 →"
            : this.latestShotJob(shot)?.state === "succeeded"
              ? "查看视频结果 →"
              : "生成视频 →";
      },
      nextClip(shot) {
        const job = this.latestShotJob(shot);
        if (job?.state === "succeeded") {
          this.reviewVideoId = job.id;
          this.panel = "video-review";
        } else if (!shot.first || shot.mode !== "first" || !shot.prompt.trim())
          this.openClip(shot.id);
        else this.prepare(shot.id);
      },
      async generateVideo() {
        if (this.videoBusy) return;
        this.videoBusy = true;
        this.videoError = "";
        try {
          await this.flushProject();
          const shot = this.shot;
          const key = JSON.stringify([
            shot.id,
            shot.prompt,
            shot.first,
            shot.refs,
            shot.duration,
            shot.videoProvider,
            shot.videoModel,
            this.projectRevision,
          ]);
          const storage =
            "studio-video-request:" + this.workspaceId + ":" + shot.id;
          let pending;
          try {
            pending = JSON.parse(localStorage.getItem(storage) || "null");
          } catch {}
          if (!pending || pending.key !== key)
            pending = {
              key,
              body: {
                request_id: crypto.randomUUID(),
                revision: this.projectRevision,
                shot: shot.id,
              },
            };
          localStorage.setItem(storage, JSON.stringify(pending));
          const job = await this.projectApi("/video", pending.body);
          localStorage.removeItem(storage);
          await this.refreshVideo();
          this.reviewVideoId = job.id;
          this.panel = "video-review";
          this.notify("视频任务已提交 · 可以继续整理其他素材");
        } catch (e) {
          this.videoError = e.message;
        } finally {
          this.videoBusy = false;
        }
      },
      async adoptVideo() {
        if (this.videoBusy || !this.selectedVideo) return;
        this.videoBusy = true;
        this.videoError = "";
        try {
          await this.flushProject();
          const record = await this.projectApi("/video/adopt", {
            request_id: crypto.randomUUID(),
            revision: this.projectRevision,
            job: this.selectedVideo.id,
            ...(this.selectedVideo.stale ? { use_history: true } : {}),
          });
          for (const [key, value] of Object.entries(record.state))
            this[key] = value;
          this.projectRevision = record.revision;
          this.projectEvents = record.events;
          this._ack = JSON.stringify(this.projectSnapshot());
          this.persist();
          this.panel = "";
          this.notify("已采用 " + this.selectedVideo.name + " · 5 秒");
        } catch (e) {
          this.videoError = e.message;
        } finally {
          this.videoBusy = false;
        }
      },
      async renderVideo() {
        if (this.videoBusy) return;
        this.videoBusy = true;
        this.videoError = "";
        try {
          await this.flushProject();
          await this.projectApi("/video/render", {
            request_id: crypto.randomUUID(),
            revision: this.projectRevision,
          });
          await this.refreshVideo();
          this.notify("正在合成已采用的片段");
        } catch (e) {
          this.videoError = e.message;
        } finally {
          this.videoBusy = false;
        }
      },
      exportPlan() {
        const output = {
          project: this.projectName,
          workspace: this.workspaceId,
          requirements: this.facts,
          shots: this.shots,
          notes: this.notes,
          sequence: this.sequence,
          videoJobs: this.videoJobs.map((j) => ({
            id: j.id,
            shot: j.shot,
            state: j.state,
            model: j.model,
            stale: j.stale,
          })),
        };
        const link = document.createElement("a"),
          url = URL.createObjectURL(
            new Blob([JSON.stringify(output, null, 2)], {
              type: "application/json",
            }),
          );
        link.href = url;
        link.download = this.projectName + "-创作方案.json";
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      },
    }),
  );
  return app;
}
