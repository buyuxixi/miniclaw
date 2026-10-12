function createCanvasState() {
  return usableCanvas({
    view: "canvas",
    notes: [],
    selectedIds: ["source"],
    tool: "select",
    marquee: null,
    addMenu: false,
    libraryOpen: true,
    library: [],
    libraryQuery: "",
    libraryBusy: false,
    libraryError: "",
    history: [],
    saveError: "",
    editedNote: null,
    viewBeforeAssistant: null,
    panel: "",
    assistant: false,
    selection: "source",
    active: "s1",
    zoom: 1,
    pan: { x: 0, y: 0 },
    drag: null,
    toast: "",
    draft: "",
    quote: null,
    messages: [],
    repair: "降低左侧背景高光，保留瓶身、胶头和包装文字。",
    region: null,
    start: null,
    angle: "侧面 45°",
    purpose: "补充产品侧面展示",
    narration: "从一滴开始，让日常多一点仪式感。",
    voice: false,
    review: "待核对",
    sequence: [],
    saved: [],
    edits: {},
    frame: "end",
    assets: [
      {
        id: "source",
        name: "FORM 01 · 原始海报",
        file: "source.png",
        x: 85,
        y: 130,
        w: 215,
        h: 330,
      },
      {
        id: "macro",
        name: "水滴细节",
        file: "macro.png",
        x: 105,
        y: 580,
        w: 215,
        h: 170,
      },
    ],
    shots: [
      {
        id: "s1",
        name: "产品登场",
        duration: 5,
        mode: "first",
        first: "source",
        refs: [],
        prompt:
          "固定机位。保持绿色瓶身、胶头和包装文字不变，只有背景水面产生细微涟漪。冷静、清透、有质感。",
        x: 490,
        y: 115,
        dirty: false,
      },
    ],
    candidate: { x: 1010, y: 145 },
    init() {
      try {
        let d = JSON.parse(localStorage.getItem("video-workspace-03"));
        if (d)
          for (let k of [
            "assets",
            "shots",
            "active",
            "selection",
            "edits",
            "narration",
            "voice",
            "review",
            "sequence",
            "saved",
            "draft",
            "quote",
            "messages",
            "candidate",
            "notes",
            "history",
            "workspaceId",
            "precision",
            "narrationNode",
            "facts",
          ])
            if (d[k] !== undefined) this[k] = d[k];
      } catch {}
      this.workspaceId = studioWorkspaceId() || this.workspaceId;
      this.selectedIds = [this.selection];
      this.$watch("draft", () => this.persist());
      this.$watch("assistant", (v) =>
        this.$nextTick(() => {
          if (v) {
            this.viewBeforeAssistant = {
              zoom: this.zoom,
              pan: { ...this.pan },
            };
            setTimeout(() => {
              if (
                this.assistant &&
                !(
                  typeof matchMedia === "function" &&
                  matchMedia("(max-width:600px)").matches
                )
              )
                this.frameDirectorView(() =>
                  this.focusObject(
                    this.directorContext?.node ||
                      this.quote?.targetId ||
                      this.quote?.shotId ||
                      this.active,
                  ),
                );
            }, 230);
          } else if (this.viewBeforeAssistant) {
            const previous = this.viewBeforeAssistant;
            this.frameDirectorView(() => {
              this.zoom = previous.zoom;
              this.pan = previous.pan;
            });
            this.viewBeforeAssistant = null;
          }
        }),
      );
      this.readTransfers();
      this.$watch("panel", (v) => {
        if (v) {
          this._focus = document.activeElement;
          this.$nextTick(() =>
            document.querySelector(".modal .close")?.focus(),
          );
        } else this._focus?.focus();
      });
      this.$nextTick(() => {
        this.fit();
        if (this.importedNote) this.focusObject(this.importedNote);
        else if (
          this.zoom < 0.55 &&
          !(
            typeof matchMedia === "function" &&
            matchMedia("(max-width:600px)").matches
          )
        )
          this.focusObject(this.selection);
      });
      let q = new URLSearchParams(location.search).get("state");
      if (["edit", "angles", "review", "plan", "script"].includes(q))
        this.panel = q;
      if (q === "assemble") this.view = "assemble";
      if (q === "assistant") this.ask("视频片段：" + this.shot.name);
      if (q === "motion-open")
        setTimeout(() => this.ask("视频片段：" + this.shot.name), 2200);
      if (q === "motion-save")
        setTimeout(() => {
          this.panel = "plan";
          this.savePlan();
        }, 2200);
    },
    get shot() {
      return this.shots.find((s) => s.id === this.active) || this.shots[0];
    },
    get asset() {
      return this.assets.find((a) => a.id === this.selection) || this.assets[0];
    },
    get adoptedSeconds() {
      return this.sequence.length * 5;
    },
    get inputs() {
      return this.shot.mode === "first"
        ? this.shot.first
          ? [this.shot.first]
          : []
        : this.shot.refs;
    },
    get ready() {
      return (
        this.inputs.length &&
        this.shot.prompt.trim() &&
        this.inputs.every((id) =>
          this.assets.some((a) => a.id === id && !a.pending),
        )
      );
    },
    isSaved(s) {
      let p = this.saved.find((x) => x.id === s.id);
      return (
        !!p &&
        ["name", "duration", "mode", "first", "refs", "prompt"].every(
          (k) => JSON.stringify(p[k]) === JSON.stringify(s[k]),
        )
      );
    },
    getAsset(id) {
      return this.assets.find((a) => a.id === id) || this.assets[0];
    },
    getTarget(id) {
      return id === "candidate"
        ? this.candidate
        : this.assets.find((a) => a.id === id) ||
            this.shots.find((s) => s.id === id) ||
            this.notes.find((n) => n.id === id);
    },
    persist() {
      let o = {};
      for (let k of [
        "assets",
        "shots",
        "active",
        "selection",
        "edits",
        "narration",
        "voice",
        "review",
        "sequence",
        "saved",
        "draft",
        "quote",
        "messages",
        "candidate",
        "notes",
        "history",
        "workspaceId",
        "precision",
        "narrationNode",
        "facts",
      ])
        o[k] = this[k];
      try {
        localStorage.setItem("video-workspace-03", JSON.stringify(o));
        this.saveError = "";
        return true;
      } catch {
        this.saveError =
          "保存未完成，当前内容仍在。释放浏览器存储空间后可重试。";
        return false;
      }
    },
    notify(t) {
      if (this.saveError) return;
      this.toast = t;
      clearTimeout(this._toast);
      this._toast = setTimeout(() => (this.toast = ""), 2500);
    },
    selectAsset(id, e) {
      this.choose(id, e);
      this.persist();
    },
    selectShot(id, e) {
      this.active = id;
      this.choose(id, e);
      this.persist();
    },
    bind() {
      if (this.asset.pending) {
        this.notify("这份素材还在等待制作");
        return;
      }
      if (this.shot.mode === "first") this.shot.first = this.asset.id;
      else if (!this.shot.refs.includes(this.asset.id))
        this.shot.refs.push(this.asset.id);
      this.changed();
      this.notify(
        "已用于「" +
          this.shot.name +
          "」 · " +
          (this.shot.mode === "first" ? "首帧" : "参考图"),
      );
    },
    changed() {
      this.shot.dirty = true;
      this.persist();
    },
    addShot() {
      this.remember();
      let id = "s" + crypto.randomUUID();
      this.shots.push({
        id,
        name: "新的片段",
        duration: 5,
        mode: "first",
        first: "",
        refs: [],
        prompt: "",
        ...this.freePosition(this.shot.x + 460, this.shot.y + 40),
        dirty: true,
      });
      this.active = id;
      this.selection = id;
      this.selectedIds = [id];
      this.persist();
      this.focusShot();
    },
    focusShot() {
      this.focusObject(this.active);
    },
    openEdit() {
      let e = this.edits[this.asset.id];
      this.repair = e?.text || "降低左侧背景高光，保留瓶身、胶头和包装文字。";
      this.region = e?.region || null;
      this.panel = "edit";
    },
    saveEdit() {
      this.remember();
      this.edits[this.asset.id] = { text: this.repair, region: this.region };
      if (!this.persist()) return;
      this.panel = "";
      this.notify("修改要求已保存 · 原图仍保留");
    },
    quoteEdit() {
      this.edits[this.asset.id] = { text: this.repair, region: this.region };
      let occupied = !!this.draft.trim();
      this.ask("素材：" + this.asset.name + (this.region ? " · 局部选区" : ""));
      if (!occupied) {
        this.draft = this.repair;
        this.quote.assetId = this.asset.id;
        this.quote.targetId = this.asset.id;
        this.quote.region = this.region;
      }
      this.panel = "";
      this.persist();
    },
    addAngle() {
      let id = "a" + Date.now();
      this.assets.push({
        id,
        name: this.angle,
        pending: true,
        purpose: this.purpose,
        target: this.active,
        source: this.asset.id,
        x: 80,
        y: 940 + (this.assets.length - 2) * 190,
        w: 260,
        h: 145,
      });
      this.persist();
      this.panel = "";
      this.fit();
      this.notify("已记录角度制作要求，等待素材结果");
    },
    ask(label) {
      if (!this.draft.trim())
        this.quote = {
          label,
          targetId: label.startsWith("素材：") ? this.asset.id : this.active,
          shotId: this.active,
          context: label.startsWith("视频片段")
            ? this.shot.prompt
            : label.includes("口播")
              ? this.narration
              : "",
          inputs: label.startsWith("视频片段")
            ? this.inputs.map((id) => this.getAsset(id).name)
            : [],
        };
      this.assistant = true;
      this.$nextTick(() => this.$refs.ask?.focus());
    },
    send() {
      if (!this.draft.trim()) return;
      this.messages.push({
        id: crypto.randomUUID(),
        text: this.draft,
        quote: JSON.parse(JSON.stringify(this.quote)),
      });
      this.draft = "";
      this.quote = null;
      this.persist();
    },
    prepare(id) {
      this.active = id;
      this.panel = "plan";
    },
    savePlan() {
      if (!this.ready) return;
      let s = JSON.parse(JSON.stringify(this.shot));
      this.saved = this.saved.filter((x) => x.id !== s.id);
      this.saved.push({
        ...s,
        inputs: this.inputs.map((id) => ({
          id,
          file: this.getAsset(id).file,
          role: s.mode === "first" ? "first_frame" : "reference_image",
        })),
      });
      this.persist();
      this.notify("已保存「" + s.name + "」的生成方案");
    },
    adopt() {
      this.review = "采用（保留外观偏差记录）";
      if (!this.sequence.includes("candidate-01"))
        this.sequence.push("candidate-01");
      this.persist();
      this.panel = "";
      this.notify("候选已加入成片 · 5 秒");
    },
    reject() {
      this.review = "不采用 · 胶头变形";
      this.sequence = this.sequence.filter((x) => x !== "candidate-01");
      this.persist();
      this.notify("不采用原因已记录");
    },
    exportPlan() {
      let o = {
        project: "FORM 01",
        targetDuration: 15,
        shots: this.saved,
        sequence: this.sequence,
        narration: this.voice ? this.narration : null,
        review: this.review,
        edits: this.edits,
        assets: this.assets,
      };
      let a = document.createElement("a"),
        u = URL.createObjectURL(
          new Blob([JSON.stringify(o, null, 2)], { type: "application/json" }),
        );
      a.href = u;
      a.download = "FORM01-video-plan.json";
      a.click();
      setTimeout(() => URL.revokeObjectURL(u), 1000);
    },
    fit() {
      let e = this.$refs.world;
      if (!e) return;
      let items = [
        ...this.assets,
        ...this.shots.map((s) => ({ ...s, w: 380, h: 580 })),
        ...this.notes,
        { ...this.candidate, w: 300, h: 610 },
      ];
      let minX = Math.min(0, ...items.map((n) => n.x)),
        minY = Math.min(0, ...items.map((n) => n.y)),
        maxX = Math.max(...items.map((n) => n.x + (n.w || 320) + 40)),
        maxY = Math.max(...items.map((n) => n.y + (n.h || 320) + 65));
      this.zoom = Math.min(
        1,
        (e.clientWidth - 160) / (maxX - minX),
        (e.clientHeight - 130) / (maxY - minY),
      );
      this.zoom = Math.max(0.2, this.zoom);
      this.pan = { x: 100 - minX * this.zoom, y: 88 - minY * this.zoom };
    },
    dragStart(e, id) {
      if (
        typeof matchMedia === "function" &&
        matchMedia("(max-width:600px)").matches
      )
        return;
      if (e.button !== 0 || e.target.closest("button,input,textarea,select,a"))
        return;
      if (id && this.tool !== "hand" && !this.spaceDown) {
        this.choose(id, e);
        if (e.shiftKey) return;
        this.remember();
        let ids = this.selectedIds.includes(id) ? this.selectedIds : [id];
        this.drag = {
          kind: "nodes",
          x: e.clientX,
          y: e.clientY,
          items: ids.map((key) => ({
            id: key,
            x: this.getTarget(key).x,
            y: this.getTarget(key).y,
          })),
          moved: false,
        };
      } else if (!id && this.tool === "select" && !this.spaceDown) {
        let p = this.point(e);
        this.marquee = { x: p.x, y: p.y, w: 0, h: 0 };
        this.drag = { kind: "marquee", start: p };
      } else
        this.drag = {
          kind: "pan",
          x: e.clientX,
          y: e.clientY,
          ox: this.pan.x,
          oy: this.pan.y,
        };
      e.currentTarget.setPointerCapture(e.pointerId);
    },
    dragMove(e) {
      let d = this.drag;
      if (!d) return;
      if (d.kind === "pan") {
        this.pan = { x: d.ox + e.clientX - d.x, y: d.oy + e.clientY - d.y };
      } else if (d.kind === "nodes") {
        d.moved = true;
        for (let n of d.items) {
          let target = this.getTarget(n.id);
          target.x = n.x + (e.clientX - d.x) / this.zoom;
          target.y = n.y + (e.clientY - d.y) / this.zoom;
        }
      } else if (d.kind === "resize") {
        let a = this.getTarget(d.id);
        a.w = Math.max(120, Math.min(700, d.w + (e.clientX - d.x) / this.zoom));
        a.h = (d.h * a.w) / d.w;
      } else {
        let p = this.point(e);
        this.marquee = {
          x: Math.min(p.x, d.start.x),
          y: Math.min(p.y, d.start.y),
          w: Math.abs(p.x - d.start.x),
          h: Math.abs(p.y - d.start.y),
        };
      }
    },
    dragEnd() {
      let d = this.drag;
      if (!d) return;
      if (d.kind === "marquee") {
        let r = this.marquee;
        this.selectedIds =
          r.w * this.zoom > 4 || r.h * this.zoom > 4
            ? this.objects()
                .filter(
                  (n) =>
                    n.x < r.x + r.w &&
                    n.x + n.w > r.x &&
                    n.y < r.y + r.h &&
                    n.y + n.h > r.y,
                )
                .map((n) => n.id)
            : [];
        this.selection = this.selectedIds[0] || "";
        if (!this.selection) this.clearCanvasSelection?.();
        this.marquee = null;
      } else if (d.kind === "nodes" && !d.moved) this.history.pop();
      this.drag = null;
      this.persist();
    },
    lines() {
      let paths = [];
      for (let s of this.shots)
        for (let id of s.mode === "first" ? (s.first ? [s.first] : []) : s.refs)
          paths.push(
            '<path d="' +
              this.connection(this.getAsset(id), s) +
              '" class="input-line"></path>',
          );
      let s = this.shots[0],
        c = this.candidate;
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
    connection(a, s) {
      return (
        "M " +
        (a.x + a.w) +
        " " +
        (a.y + 120) +
        " C " +
        (a.x + a.w + 100) +
        " " +
        (a.y + 120) +
        ", " +
        (s.x - 100) +
        " " +
        (s.y + 140) +
        ", " +
        s.x +
        " " +
        (s.y + 140)
      );
    },
    regionDown(e) {
      let b = e.currentTarget.getBoundingClientRect();
      this.start = {
        x: (e.clientX - b.left) / b.width,
        y: (e.clientY - b.top) / b.height,
      };
      this.region = { ...this.start, w: 0, h: 0 };
      e.currentTarget.setPointerCapture(e.pointerId);
    },
    regionMove(e) {
      if (!this.start) return;
      let b = e.currentTarget.getBoundingClientRect(),
        x = Math.max(0, Math.min(1, (e.clientX - b.left) / b.width)),
        y = Math.max(0, Math.min(1, (e.clientY - b.top) / b.height));
      this.region = {
        x: Math.min(x, this.start.x),
        y: Math.min(y, this.start.y),
        w: Math.abs(x - this.start.x),
        h: Math.abs(y - this.start.y),
      };
    },
    regionEnd() {
      this.start = null;
    },
    freePosition(x, y, w = 380, h = 760) {
      let objects = this.objects();
      for (let tries = 0; tries < 100; tries++) {
        if (
          !objects.some(
            (n) =>
              x < n.x + n.w + 36 &&
              x + w + 36 > n.x &&
              y < n.y + n.h + 36 &&
              y + h + 36 > n.y,
          )
        )
          return { x, y };
        x += w + 80;
      }
      return { x, y };
    },
    objects() {
      return [
        ...this.assets.map((a) => ({ ...a, h: a.h + 65 })),
        ...this.shots.map((n) => ({ ...n, w: 380, h: 570 })),
        ...this.notes,
        { ...this.candidate, id: "candidate", w: 285, h: 610 },
      ];
    },
    point(e) {
      let b = this.$refs.world.getBoundingClientRect();
      return {
        x: (e.clientX - b.left - this.pan.x) / this.zoom,
        y: (e.clientY - b.top - this.pan.y) / this.zoom,
      };
    },
    choose(id, e) {
      if (e?.shiftKey) {
        this.selectedIds = this.selectedIds.includes(id)
          ? this.selectedIds.filter((x) => x !== id)
          : [...this.selectedIds, id];
      } else if (
        !this.selectedIds.includes(id) ||
        this.selectedIds.length === 1
      )
        this.selectedIds = [id];
      this.selection = this.selectedIds.includes(id)
        ? id
        : this.selectedIds.at(-1) || id;
      let s = this.shots.find((x) => x.id === this.selection);
      if (s) this.active = id;
    },
    get selectedNote() {
      return this.notes.find((n) => n.id === this.selection);
    },
    get selectionName() {
      if (this.selectedIds.length > 1)
        return this.selectedIds.length + " 个对象";
      return (
        this.assets.find((a) => a.id === this.selection)?.name ||
        this.shots.find((s) => s.id === this.selection)?.name ||
        this.selectedNote?.title ||
        "视频候选"
      );
    },
    focusObject(id) {
      let n = this.getTarget(id),
        e = this.$refs.world;
      if (!n || !e || e.clientWidth < 1 || e.clientHeight < 1) return;
      this.view = "canvas";
      let node = e.querySelectorAll
          ? [...e.querySelectorAll("[data-object-id]")].find(
              (el) => el.dataset.objectId === id,
            )
          : null,
        w = node?.offsetWidth || n.w || 380,
        h = node?.offsetHeight || n.h || (n.creativeBrief ? 760 : 570);
      let isShot = this.shots.some((s) => s.id === id);
      this.zoom = Math.max(
        0.2,
        Math.min(
          isShot ? 0.8 : 1,
          (e.clientWidth - 190) / w,
          (e.clientHeight - (isShot ? 230 : 180)) /
            (isShot ? Math.min(h, 450) : h),
        ),
      );
      this.pan = {
        x: Math.max(100, (e.clientWidth - w * this.zoom) / 2) - n.x * this.zoom,
        y: 70 - n.y * this.zoom,
      };
      if (
        node &&
        typeof matchMedia === "function" &&
        matchMedia("(max-width:600px)").matches
      )
        node.scrollIntoView({
          block: "start",
          behavior: matchMedia("(prefers-reduced-motion:reduce)").matches
            ? "auto"
            : "smooth",
        });
    },
    zoomAt(delta, e) {
      let p = e
          ? this.point(e)
          : {
              x: (this.$refs.world.clientWidth / 2 - this.pan.x) / this.zoom,
              y: (this.$refs.world.clientHeight / 2 - this.pan.y) / this.zoom,
            },
        old = this.zoom;
      this.zoom = Math.max(0.2, Math.min(2, this.zoom + delta));
      this.pan.x -= p.x * (this.zoom - old);
      this.pan.y -= p.y * (this.zoom - old);
    },
    wheel(e) {
      if (
        typeof matchMedia === "function" &&
        matchMedia("(max-width:600px)").matches
      )
        return;
      e.preventDefault();
      if (e.ctrlKey || e.metaKey) this.zoomAt(-e.deltaY * 0.003, e);
      else {
        this.pan.x -= e.deltaX;
        this.pan.y -= e.deltaY;
      }
    },
    resizeStart(e, id) {
      this.remember();
      let n = this.getTarget(id);
      this.drag = { kind: "resize", id, x: e.clientX, w: n.w, h: n.h };
      e.currentTarget.setPointerCapture(e.pointerId);
    },
    remember() {
      this.history.push(
        JSON.parse(
          JSON.stringify({
            assets: this.assets,
            shots: this.shots,
            notes: this.notes,
            candidate: this.candidate,
            active: this.active,
            selection: this.selection,
            saved: this.saved,
            edits: this.edits,
            sequence: this.sequence,
            review: this.review,
          }),
        ),
      );
      if (this.history.length > 10) this.history.shift();
    },
    undo() {
      let old = this.history.pop();
      if (!old) return;
      for (let k of Object.keys(old)) this[k] = old[k];
      this.selectedIds = [this.selection];
      this.persist();
      this.notify("已撤销上一次画布修改");
    },
    branch(id = this.active) {
      let source = this.shots.find((s) => s.id === id);
      if (!source) return;
      this.remember();
      let item = JSON.parse(JSON.stringify(source));
      item.id = "s" + crypto.randomUUID();
      item.name = source.name + " · 新方向";
      Object.assign(item, this.freePosition(item.x + 460, item.y + 45));
      item.dirty = true;
      this.shots.push(item);
      this.active = item.id;
      this.choose(item.id);
      this.persist();
      this.focusShot();
      this.notify("新方向已建立，原片段保留");
    },
    addNote(text = "", source = null, title = "创意备注") {
      if (source && this.notes.some((n) => n.source?.id === source.id)) {
        let n = this.notes.find((n) => n.source?.id === source.id);
        this.choose(n.id);
        this.focusObject(n.id);
        this.notify("已定位到画布中的原备注");
        return n;
      }
      this.remember();
      let n = {
        id: "n" + crypto.randomUUID(),
        title,
        text,
        source,
        x: this.shot.x - 40,
        y:
          this.shot.y -
          330 -
          this.notes.filter((n) => Math.abs(n.x - (this.shot.x - 40)) < 360)
            .length *
            300,
        w: 340,
        h: 240,
      };
      this.notes.push(n);
      this.choose(n.id);
      this.addMenu = false;
      this.persist();
      this.focusObject(n.id);
      if (!text) {
        this.editedNote = n.id;
        this.panel = "note";
      }
      return n;
    },
    get note() {
      return (
        this.notes.find((n) => n.id === this.editedNote) || this.selectedNote
      );
    },
    saveNote() {
      this.persist();
      if (!this.saveError) {
        this.panel = "";
        this.notify("备注已保留在画布");
      }
    },
    noteToShot() {
      let note = this.selectedNote;
      if (!note) return;
      this.remember();
      let shot = {
        id: "s" + crypto.randomUUID(),
        name: note.title,
        creativeBrief: note.text,
        briefSource: note.id,
        duration: 5,
        mode: "first",
        first: "",
        refs: [],
        prompt: "",
        ...this.freePosition(note.x + 420, note.y + 25, 380, 760),
        dirty: true,
      };
      this.shots.push(shot);
      this.active = shot.id;
      this.choose(shot.id);
      this.persist();
      this.focusShot();
      this.notify("已从备注建立片段，请指定素材和画面运动");
    },
    readTransfers() {
      try {
        let queue = JSON.parse(
          localStorage.getItem("video-workspace-03-transfer") || "[]",
        );
        for (let item of queue)
          this.importedNote = this.addNote(
            item.text,
            item.source,
            item.title,
          ).id;
        if (!this.saveError)
          localStorage.removeItem("video-workspace-03-transfer");
      } catch {
        this.saveError = "讨论内容暂未导入，请回到创作助手 重试。";
      }
    },
    thoughtToCanvas(m) {
      this.addNote(
        m.text,
        {
          id: m.id || "discussion-" + this.messages.indexOf(m),
          type: "director",
          label: m.quote?.label || "导演讨论",
        },
        "讨论中的方案",
      );
      this.assistant = false;
      this.notify("讨论已放到画布，来源保留");
    },
    askSelection() {
      let id = this.selection,
        n = this.getTarget(id),
        occupied = !!this.draft.trim(),
        note = this.notes.find((n) => n.id === id);
      let label = note
        ? "创作方案：" + note.title
        : this.assets.some((a) => a.id === id)
          ? "素材：" + this.asset.name
          : this.shots.some((s) => s.id === id)
            ? "视频片段：" + this.shot.name
            : "视频候选：产品登场";
      this.ask(label);
      if (!occupied)
        this.quote = {
          label,
          targetId: id,
          shotId: id === "candidate" ? "s1" : this.active,
          context: note?.text || n?.prompt || "",
          inputs: [],
        };
    },
    directorAction(action) {
      let id = this.quote?.targetId || this.quote?.shotId || this.active,
        note = this.notes.find((n) => n.id === id);
      if (action === "branch") {
        if (note) {
          this.choose(id);
          this.noteToShot();
        } else
          this.branch(
            this.shots.some((s) => s.id === id) ? id : this.quote?.shotId,
          );
        return;
      }
      if (action === "edit") {
        if (note) {
          this.choose(id);
          this.editedNote = id;
          this.panel = "note";
          return;
        }
        if (id === "candidate") {
          this.panel = "review";
          return;
        }
        let a = this.assets.find((a) => a.id === id);
        if (a) {
          this.choose(id);
          this.openEdit();
        } else {
          let s = this.shots.find((s) => s.id === id);
          if (s) {
            this.active = id;
            this.panel = "prompt";
          }
        }
      }
    },
    alignSelection() {
      if (this.selectedIds.length < 2) return;
      this.remember();
      let nodes = this.selectedIds.map((id) => this.getTarget(id)),
        left = Math.min(...nodes.map((n) => n.x)),
        top = Math.min(...nodes.map((n) => n.y));
      nodes.forEach((n, i) => {
        n.x = left + i * 400;
        n.y = top;
      });
      this.persist();
      this.notify("对象已并排，输入关系保持不变");
    },
    async importImage(event) {
      let file = event.target.files?.[0];
      event.target.value = "";
      if (!file) return;
      if (
        !["image/png", "image/jpeg", "image/webp"].includes(file.type) ||
        file.size > 5 * 1024 * 1024
      ) {
        this.saveError = "请选择 5 MiB 以内的 PNG、JPEG 或 WebP 图片。";
        return;
      }
      try {
        await this.flushProject();
        const response = await fetch(
          "/api/workspaces/" +
            this.workspaceId +
            "/assets/upload?name=" +
            encodeURIComponent(file.name),
          {
            method: "POST",
            headers: {
              "Content-Type": file.type,
              "X-Hermes-Session-Token": window.WORKSPACE_TOKEN || "",
            },
            body: file,
            signal: AbortSignal.timeout(60000),
          },
        );
        const media = await response.json();
        if (!response.ok) throw Error(media.detail || "图片上传失败");
        this.placeAsset(file.name, media.file, media.width, media.height, "upload");
        this.notify("素材已加入画布");
      } catch (error) {
        this.saveError = error.message;
      }
    },
    // Adds an image node in the first free slot left of the shots, then selects it.
    placeAsset(name, file, width, height, source) {
      this.remember();
      let id = "a" + crypto.randomUUID(),
        w = 220,
        h = Math.min(420, (w * height) / width),
        x = Math.min(60, (this.shot?.x || 500) - 320),
        y = 40;
      for (let tries = 0; tries < 100; tries++) {
        let hit = this.objects().find(
          (n) =>
            x < n.x + n.w + 36 &&
            x + w + 36 > n.x &&
            y < n.y + n.h + 36 &&
            y + h + 101 > n.y,
        );
        if (!hit) break;
        y = hit.y + hit.h + 70;
      }
      this.assets.push({ id, name, file, x, y, w, h, source });
      this.choose(id);
      this.addMenu = false;
      this.persist();
      this.focusObject(id);
      return id;
    },
    // Global library (docs/redesign-log.md step 1): shared files, granted per project on use.
    async loadLibrary() {
      this.libraryBusy = true;
      this.libraryError = "";
      try {
        const response = await fetch(
          "/api/workspaces/library?q=" + encodeURIComponent(this.libraryQuery.trim()),
          { headers: { "X-Hermes-Session-Token": window.WORKSPACE_TOKEN || "" } },
        );
        const items = await response.json();
        if (!response.ok) throw Error(items.detail || "素材库读取失败");
        this.library = items.filter((i) => i.kind === "image");
      } catch (error) {
        this.libraryError = error.message;
      } finally {
        this.libraryBusy = false;
      }
    },
    async collectToLibrary(asset) {
      if (!asset?.file || this.libraryBusy) return;
      this.libraryBusy = true;
      try {
        await this.flushProject();
        const response = await fetch(
          "/api/workspaces/" + this.workspaceId + "/library",
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-Hermes-Session-Token": window.WORKSPACE_TOKEN || "",
            },
            body: JSON.stringify({
              file: asset.file,
              name: String(asset.name || "未命名素材").slice(0, 120),
            }),
          },
        );
        const item = await response.json();
        if (!response.ok) throw Error(item.detail || "收进素材库失败");
        this.notify("已收进素材库");
      } catch (error) {
        this.saveError = error.message;
      } finally {
        this.libraryBusy = false;
      }
      await this.loadLibrary();
    },
    async useLibraryItem(item) {
      if (this.libraryBusy) return;
      this.libraryBusy = true;
      try {
        const response = await fetch(
          "/api/workspaces/" + this.workspaceId + "/library/" + encodeURIComponent(item.id) + "/use",
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-Hermes-Session-Token": window.WORKSPACE_TOKEN || "",
            },
            body: "{}",
          },
        );
        const granted = await response.json();
        if (!response.ok) throw Error(granted.detail || "素材暂时无法使用");
        const image = new Image();
        image.src = granted.url;
        await image.decode();
        this.placeAsset(item.name, granted.url, image.naturalWidth, image.naturalHeight, "library");
        this.notify("已从素材库加入画布");
      } catch (error) {
        this.saveError = error.message;
      } finally {
        this.libraryBusy = false;
      }
    },
    keydown(e) {
      if (e.target.closest("input,textarea,select,video")) return;
      if (e.key === " ") {
        e.preventDefault();
        this.spaceDown = true;
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
        e.preventDefault();
        this.undo();
      }
      if (this.view === "canvas" && e.key.toLowerCase() === "h")
        this.tool = "hand";
      if (this.view === "canvas" && e.key.toLowerCase() === "v")
        this.tool = "select";
      if (this.view === "canvas" && e.key === "Home") {
        e.preventDefault();
        this.fit();
      }
    },
    trap(e) {
      if (!this.panel) return;
      let els = [
          ...document.querySelectorAll(
            ".modal button,.modal input,.modal textarea,.modal select",
          ),
        ].filter((x) => x.getClientRects().length),
        a = els[0],
        b = els.at(-1);
      if (e.shiftKey && document.activeElement === a) {
        e.preventDefault();
        b?.focus();
      } else if (!e.shiftKey && document.activeElement === b) {
        e.preventDefault();
        a?.focus();
      }
    },
  });
}
