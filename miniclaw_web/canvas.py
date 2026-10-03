"""Profile-local image projects; immutable assets, atomic CAS and bounded history."""

import base64
import copy
import hashlib
import io
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from .attachments import public, upload
from .canvas_document import (
    affine,
    blank,
    ensure_unlocked,
    identifier,
    layer_base,
    number,
    pixels,
    png,
    render,
    validate,
)
from .images import local_edit
from .image_provider import edit_image, provider_status


class Conflict(ValueError):
    pass


class Canvas:
    def __init__(self, store, executor=None):
        self.store = store
        self.lock = threading.RLock()
        self.executor = executor or ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="canvas"
        )
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS canvas_projects (id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS canvas_history (project TEXT NOT NULL, seq INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY(project,seq));
                CREATE TABLE IF NOT EXISTS canvas_selections (project TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS canvas_jobs (id TEXT PRIMARY KEY, project TEXT NOT NULL, data TEXT NOT NULL);
            """)
            for job_id, data in db.execute(
                "SELECT id,data FROM canvas_jobs"
            ).fetchall():
                job = json.loads(data)
                if job["state"] in ("queued", "running"):
                    job.update(
                        state="failed", error="服务重启，结果未知；不会重放付费请求"
                    )
                    db.execute(
                        "UPDATE canvas_jobs SET data=? WHERE id=?",
                        (json.dumps(job), job_id),
                    )

    @staticmethod
    def owner(project):
        return "project-" + project

    def _get(self, db, project, active=True):
        row = db.execute(
            "SELECT data FROM canvas_projects WHERE id=?", (project,)
        ).fetchone()
        if not row:
            raise ValueError("图片项目不存在")
        result = json.loads(row[0])
        if active and result["archived"]:
            raise ValueError("项目已归档，请先恢复")
        return result

    def get(self, project):
        with self.store.connect() as db:
            return self._get(db, project, False)

    def asset(self, project, asset_id):
        return self.store.get("attachments", asset_id, self.owner(project))

    def list(self, archived=False):
        with self.store.connect() as db:
            rows = [
                json.loads(row[0])
                for row in db.execute("SELECT data FROM canvas_projects")
            ]
        return [
            {
                k: row[k]
                for k in ("id", "name", "revision", "updated", "archived", "chat_id")
            }
            for row in sorted(rows, key=lambda r: r["updated"], reverse=True)
            if row["archived"] == archived
        ]

    def create(self, name="未命名图片项目"):
        project = identifier()
        now = time.time()
        row = dict(
            id=project,
            name=self._name(name),
            revision=0,
            cursor=0,
            updated=now,
            archived=False,
            chat_id=None,
            document=blank(),
        )
        with self.store.connect() as db:
            db.execute(
                "INSERT INTO canvas_projects VALUES (?,?)", (project, json.dumps(row))
            )
            db.execute(
                "INSERT INTO canvas_history VALUES (?,?,?)",
                (
                    project,
                    0,
                    json.dumps(
                        dict(document=row["document"], label="创建画布", time=now)
                    ),
                ),
            )
        return row

    @staticmethod
    def _name(name):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            raise ValueError("名称需要1到100个字")
        return name.strip()

    def metadata(
        self, project, revision, name=None, archived=None, chat_id=None, link=False
    ):
        with self.lock, self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._get(db, project, False)
            self._cas(row, revision)
            if name is not None:
                row["name"] = self._name(name)
            if archived is not None:
                if type(archived) is not bool:
                    raise ValueError("归档状态无效")
                row["archived"] = archived
            if link:
                if chat_id is not None and (
                    not isinstance(chat_id, str)
                    or not re.fullmatch(r"[\w-]{1,128}", chat_id)
                ):
                    raise ValueError("聊天ID无效")
                row["chat_id"] = chat_id
            row["revision"] += 1
            row["updated"] = time.time()
            self._write(db, row)
            return row

    @staticmethod
    def _cas(row, revision):
        if type(revision) is not int or revision != row["revision"]:
            raise Conflict("项目已更新，请刷新后再操作")

    @staticmethod
    def _write(db, row):
        db.execute(
            "UPDATE canvas_projects SET data=? WHERE id=?",
            (json.dumps(row, ensure_ascii=False), row["id"]),
        )
        db.execute("DELETE FROM canvas_selections WHERE project=?", (row["id"],))

    def save(self, project, revision, document, label="编辑画布"):
        document = validate(document, lambda a: self.asset(project, a))
        label = self._name(label)
        with self.lock, self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._get(db, project)
            self._cas(row, revision)
            ensure_unlocked(row["document"], document)
            row.update(
                document=document,
                revision=row["revision"] + 1,
                cursor=row["cursor"] + 1,
                updated=time.time(),
            )
            db.execute(
                "DELETE FROM canvas_history WHERE project=? AND seq>=?",
                (project, row["cursor"]),
            )
            db.execute(
                "INSERT INTO canvas_history VALUES (?,?,?)",
                (
                    project,
                    row["cursor"],
                    json.dumps(
                        dict(document=document, label=label, time=time.time()),
                        ensure_ascii=False,
                    ),
                ),
            )
            db.execute(
                "DELETE FROM canvas_history WHERE project=? AND seq<?",
                (project, row["cursor"] - 100),
            )
            self._write(db, row)
            return row

    def history(self, project):
        with self.store.connect() as db:
            row = self._get(db, project, False)
            return [
                dict(
                    seq=seq,
                    label=json.loads(data)["label"],
                    time=json.loads(data)["time"],
                    current=seq == row["cursor"],
                )
                for seq, data in db.execute(
                    "SELECT seq,data FROM canvas_history WHERE project=? ORDER BY seq DESC",
                    (project,),
                )
            ]

    def restore(self, project, revision, seq):
        if type(seq) is not int:
            raise ValueError("版本号无效")
        with self.lock, self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._get(db, project)
            self._cas(row, revision)
            found = db.execute(
                "SELECT data FROM canvas_history WHERE project=? AND seq=?",
                (project, seq),
            ).fetchone()
            if not found:
                raise ValueError("该版本不存在")
            row.update(
                document=json.loads(found[0])["document"],
                cursor=seq,
                revision=row["revision"] + 1,
                updated=time.time(),
            )
            self._write(db, row)
            return row

    def add_asset(self, project, raw, name):
        self.get(project)
        # Normalize orientation at import. Layer geometry always describes decoded pixels.
        with Image.open(io.BytesIO(raw)) as image:
            if image.width * image.height > 16_777_216 or max(image.size) > 4096:
                raise ValueError("画布素材最长边4096，最多1677万像素")
            image = ImageOps.exif_transpose(image).convert("RGBA")
            size = image.size
            raw = png(image)
        item = upload(
            self.store,
            self.owner(project),
            Path(name).stem[:100] + ".png",
            base64.b64encode(raw).decode(),
        )
        return {**item, "width": size[0], "height": size[1]}

    def assets(self, project):
        row = self.get(project)
        records = {r["id"]: r for r in self.store.images(self.owner(project))}
        # A long edit history must not make a still-visible old layer disappear.
        for layer in row["document"]["layers"]:
            if layer["kind"] == "image" and layer["asset_id"] not in records:
                records[layer["asset_id"]] = self.asset(project, layer["asset_id"])
        result = []
        for record in records.values():
            with Image.open(record["path"]) as image:
                size = image.size
            result.append({**public(record), "width": size[0], "height": size[1]})
        return result

    def export(self, project, seq=None):
        row = self.get(project)
        document = row["document"]
        if seq is not None:
            with self.store.connect() as db:
                found = db.execute(
                    "SELECT data FROM canvas_history WHERE project=? AND seq=?",
                    (project, seq),
                ).fetchone()
            if not found:
                raise ValueError("版本不存在")
            document = json.loads(found[0])["document"]
        return png(render(document, lambda a: self.asset(project, a)))

    def _target(self, project, revision, layer_id):
        row = self.get(project)
        self._cas(row, revision)
        if row["archived"]:
            raise ValueError("项目已归档，请先恢复")
        layer = next(
            (l for l in row["document"]["layers"] if l["id"] == layer_id), None
        )
        if (
            layer is None
            or layer["kind"] != "image"
            or layer["locked"]
            or not layer["visible"]
        ):
            raise ValueError("请选择可见且未锁定的图片图层")
        return row, layer

    def _mask_store(self, project, row, layer, mask):
        source = self.asset(project, layer["asset_id"])
        record = dict(
            id=identifier(),
            revision=row["revision"],
            layer_id=layer["id"],
            asset_id=layer["asset_id"],
            source_hash=hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest(),
            mask=base64.b64encode(png(mask)).decode(),
        )
        with self.lock, self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._cas(self._get(db, project), row["revision"])
            db.execute(
                "INSERT OR REPLACE INTO canvas_selections VALUES (?,?)",
                (project, json.dumps(record)),
            )
        return self.selection(project)

    def _selection(self, project, row, layer, expected_id=None):
        with self.store.connect() as db:
            found = db.execute(
                "SELECT data FROM canvas_selections WHERE project=?", (project,)
            ).fetchone()
        if not found:
            raise ValueError("请先选择要编辑的区域")
        selection = json.loads(found[0])
        source = self.asset(project, layer["asset_id"])
        selection_id = (
            selection.get("id")
            or hashlib.sha256(selection["mask"].encode()).hexdigest()[:32]
        )
        if expected_id is not None and selection_id != expected_id:
            raise Conflict("选区已改变，请重新选择或发送消息")
        if (
            selection["revision"] != row["revision"]
            or selection["layer_id"] != layer["id"]
            or selection["asset_id"] != layer["asset_id"]
            or selection["source_hash"]
            != hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest()
        ):
            raise Conflict("选区已过期，请重新选择")
        mask = Image.open(io.BytesIO(base64.b64decode(selection["mask"]))).convert("L")
        if mask.size != (layer["width"], layer["height"]):
            raise ValueError("选区尺寸无效")
        return mask

    def selection(self, project):
        with self.store.connect() as db:
            row = self._get(db, project, False)
            found = db.execute(
                "SELECT data FROM canvas_selections WHERE project=?", (project,)
            ).fetchone()
        if not found:
            return None
        record = json.loads(found[0])
        if record["revision"] != row["revision"]:
            return None
        return {
            "id": record.get("id")
            or hashlib.sha256(record["mask"].encode()).hexdigest()[:32],
            **{k: record[k] for k in ("revision", "layer_id", "asset_id", "mask")},
        }

    def select(
        self,
        project,
        revision,
        layer_id,
        mode,
        points=None,
        radius=20,
        combine="replace",
    ):
        row, layer = self._target(project, revision, layer_id)
        if combine not in ("replace", "add", "subtract"):
            raise ValueError("选区组合方式无效")
        if mode in ("invert", "clear"):
            if mode == "clear":
                with self.lock, self.store.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    self._cas(self._get(db, project), revision)
                    db.execute(
                        "DELETE FROM canvas_selections WHERE project=?", (project,)
                    )
                return None
            return self._mask_store(
                project,
                row,
                layer,
                ImageOps.invert(self._selection(project, row, layer)),
            )
        if mode not in ("rectangle", "lasso", "brush"):
            raise ValueError("选区工具无效")
        if not isinstance(points, list) or not 1 <= len(points) <= 2048:
            raise ValueError("选区路径需要1到2048个点")
        for point in points:
            if not isinstance(point, list) or len(point) != 2:
                raise ValueError("选区坐标无效")
            for value in point:
                number(value, -8192, 8192)
        canvas = Image.new("L", (row["document"]["width"], row["document"]["height"]))
        draw = ImageDraw.Draw(canvas)
        xy = [tuple(p) for p in points]
        if mode == "rectangle":
            if len(xy) != 2:
                raise ValueError("框选需要两个角点")
            x1, y1 = xy[0]
            x2, y2 = xy[1]
            draw.rectangle(
                (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)), fill=255
            )
        elif mode == "lasso":
            if len(xy) < 3:
                raise ValueError("套索至少需要三个点")
            draw.polygon(xy, fill=255)
        else:
            radius = round(number(radius, 1, 256))
            if len(xy) > 1:
                draw.line(xy, fill=255, width=radius * 2, joint="curve")
            for x, y in xy:
                draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)
        mask = canvas.transform(
            (round(layer["width"]), round(layer["height"])),
            Image.Transform.AFFINE,
            affine(layer),
            Image.Resampling.NEAREST,
        )
        if combine != "replace":
            old = (
                self._selection(project, row, layer)
                if self.selection(project)
                else Image.new("L", mask.size)
            )
            mask = (
                ImageChops.lighter(old, mask)
                if combine == "add"
                else ImageChops.subtract(old, mask)
            )
        return self._mask_store(project, row, layer, mask)

    def masked(self, project, revision, layer_id, operation, params, selection_id=None):
        if not isinstance(params, dict) or (operation != "adjust" and params):
            raise ValueError("该操作不接受额外参数")
        row, layer = self._target(project, revision, layer_id)
        source = pixels(layer, lambda a: self.asset(project, a))
        mask = self._selection(project, row, layer, selection_id)
        if not mask.getbbox():
            raise ValueError("选区为空")
        if operation == "extract":
            result = source.copy()
            result.putalpha(ImageChops.multiply(source.getchannel("A"), mask))
            bounds = mask.getbbox()
            result = result.crop(bounds)
        elif operation == "erase":
            result = source.copy()
            result.putalpha(
                ImageChops.multiply(source.getchannel("A"), ImageOps.invert(mask))
            )
        elif operation == "adjust":
            candidate = Image.open(
                io.BytesIO(local_edit(png(source), "adjust", params))
            ).convert("RGBA")
            result = Image.composite(candidate, source, mask)
        else:
            raise ValueError("局部操作无效")
        asset = self.add_asset(project, png(result), "selection.png")
        document = copy.deepcopy(row["document"])
        target = next(l for l in document["layers"] if l["id"] == layer_id)
        if operation == "extract":
            a, b, x, c, d, y = affine(target)
            new_layer = {
                **target,
                "id": identifier(),
                "asset_id": asset["id"],
                "name": "选区提取",
                "width": asset["width"],
                "height": asset["height"],
                "x": a * bounds[0] + b * bounds[1] + x,
                "y": c * bounds[0] + d * bounds[1] + y,
            }
            document["layers"].insert(document["layers"].index(target) + 1, new_layer)
        else:
            target["asset_id"] = asset["id"]
        return self.save(
            project,
            revision,
            document,
            {"extract": "提取选区", "erase": "擦除选区", "adjust": "选区调色"}[
                operation
            ],
        )

    def local(self, project, revision, layer_id, operation, params):
        row, layer = self._target(project, revision, layer_id)
        result = local_edit(
            Path(self.asset(project, layer["asset_id"])["path"]).read_bytes(),
            operation,
            params,
        )
        asset = self.add_asset(project, result, "local-edit.png")
        document = copy.deepcopy(row["document"])
        target = next(l for l in document["layers"] if l["id"] == layer_id)
        target.update(
            asset_id=asset["id"], width=asset["width"], height=asset["height"]
        )
        return self.save(project, revision, document, "整层本地编辑")

    def segment(self, project, revision, layer_id, point, combine="replace"):
        from .segmentation import segment

        row, layer = self._target(project, revision, layer_id)
        if not isinstance(point, list) or len(point) != 2:
            raise ValueError("需要点选坐标")
        from .canvas_document import inverse

        x, y = [number(v, -8192, 8192) for v in point]
        a, b, c, d, e, f = inverse(layer)
        pixel = [a * x + b * y + c, d * x + e * y + f]
        if not (0 <= pixel[0] < layer["width"] and 0 <= pixel[1] < layer["height"]):
            raise ValueError("点击位置不在图片内")
        mask = segment(
            png(pixels(layer, lambda a: self.asset(project, a))), pixel, self.store.home
        )
        if combine in ("add", "subtract"):
            old = (
                self._selection(project, row, layer)
                if self.selection(project)
                else Image.new("L", mask.size)
            )
            mask = (
                ImageChops.lighter(old, mask)
                if combine == "add"
                else ImageChops.subtract(old, mask)
            )
        elif combine != "replace":
            raise ValueError("选区组合方式无效")
        return self._mask_store(project, row, layer, mask)

    def jobs(self, project):
        self.get(project)
        with self.store.connect() as db:
            rows = [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT data FROM canvas_jobs WHERE project=? ORDER BY rowid DESC LIMIT 30",
                    (project,),
                )
            ]
        return [
            {
                k: v
                for k, v in row.items()
                if k not in ("input_mask", "input_document", "signature")
            }
            for row in rows
        ]

    def job(self, project, job_id):
        self.get(project)
        with self.store.connect() as db:
            found = db.execute(
                "SELECT data FROM canvas_jobs WHERE project=? AND id=?",
                (project, job_id),
            ).fetchone()
        if not found:
            raise ValueError("任务不属于当前图片项目")
        return {
            k: v
            for k, v in json.loads(found[0]).items()
            if k not in ("input_mask", "input_document", "signature")
        }

    def submit(
        self,
        project,
        revision,
        layer_id,
        prompt,
        request_id,
        region=True,
        feather=0,
        selection_id=None,
    ):
        if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 2000:
            raise ValueError("修图要求需要1到2000字")
        if not isinstance(request_id, str) or not re.fullmatch(
            r"[\w-]{8,80}", request_id
        ):
            raise ValueError("请求ID无效")
        if type(region) is not bool:
            raise ValueError("区域范围无效")
        number(feather, 0, 20)
        signature = hashlib.sha256(
            json.dumps(
                [revision, layer_id, prompt, region, feather, selection_id]
            ).encode()
        ).hexdigest()
        job_id = hashlib.sha256((project + ":" + request_id).encode()).hexdigest()[:32]
        with self.lock, self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT data FROM canvas_jobs WHERE id=? AND project=?",
                (job_id, project),
            ).fetchone()
            if existing:
                job = json.loads(existing[0])
                if job["signature"] != signature:
                    raise ValueError("同一请求ID不能更换参数")
                return self.job(project, job_id)
            row, layer = self._target(project, revision, layer_id)
            mask = (
                self._selection(project, row, layer, selection_id)
                if region
                else Image.new(
                    "L", (round(layer["width"]), round(layer["height"])), 255
                )
            )
            if not mask.getbbox():
                raise ValueError("选区为空")
            if not provider_status()["configured"]:
                raise ValueError("请先配置百炼Key")
            active = [
                json.loads(r[0])
                for r in db.execute("SELECT data FROM canvas_jobs")
                if json.loads(r[0])["state"] in ("queued", "running")
            ]
            if len(active) >= 4 or any(j["project"] == project for j in active):
                raise ValueError("该项目已有修图任务，或服务繁忙")
            job = dict(
                id=job_id,
                project=project,
                revision=revision,
                layer_id=layer_id,
                source_id=layer["asset_id"],
                prompt=prompt,
                region=region,
                feather=feather,
                signature=signature,
                state="queued",
                created=time.time(),
                input_mask=base64.b64encode(png(mask)).decode(),
                input_document=row["document"],
            )
            db.execute(
                "INSERT INTO canvas_jobs VALUES (?,?,?)",
                (job_id, project, json.dumps(job)),
            )
        self.executor.submit(self._execute, job)
        return self.job(project, job_id)

    def _job_write(self, job):
        with self.store.connect() as db:
            db.execute(
                "UPDATE canvas_jobs SET data=? WHERE id=?", (json.dumps(job), job["id"])
            )

    def _execute(self, job):
        with self.lock:
            latest = self.job(job["project"], job["id"])
            if latest["state"] != "queued":
                return
            job["state"] = "running"
            self._job_write(job)
        try:
            source = Image.open(
                self.asset(job["project"], job["source_id"])["path"]
            ).convert("RGBA")
            mask = Image.open(io.BytesIO(base64.b64decode(job["input_mask"]))).convert(
                "L"
            )
            box = mask.getbbox()
            # Send the selected bounding area with some context, then composite locally.
            # Qwen edit has no native mask contract; outside pixels are protected here.
            pad = (
                max(16, round(max(box[2] - box[0], box[3] - box[1]) * 0.1))
                if job["region"]
                else 0
            )
            crop = (
                max(0, box[0] - pad),
                max(0, box[1] - pad),
                min(source.width, box[2] + pad),
                min(source.height, box[3] + pad),
            )
            raw, provider_id = edit_image(
                png(source.crop(crop)), "image/png", job["prompt"]
            )
            generated = (
                Image.open(io.BytesIO(raw))
                .convert("RGBA")
                .resize(
                    (crop[2] - crop[0], crop[3] - crop[1]), Image.Resampling.LANCZOS
                )
            )
            candidate = source.copy()
            candidate.paste(generated, crop[:2])
            support = mask.point(lambda p: 255 if p else 0)
            if job["feather"]:
                mask = ImageChops.multiply(
                    mask.filter(ImageFilter.GaussianBlur(job["feather"])), support
                )
            result = Image.composite(candidate, source, mask)
            with self.lock:
                latest = self.job(job["project"], job["id"])
                if latest["state"] != "running":
                    return
                asset = self.add_asset(job["project"], png(result), "ai-candidate.png")
                job.update(
                    state="succeeded", output=asset, provider_request_id=provider_id
                )
                self._job_write(job)
        except Exception as error:
            with self.lock:
                latest = self.job(job["project"], job["id"])
                if latest["state"] != "running":
                    return
                job.update(
                    state="failed",
                    error=str(error)
                    if isinstance(error, ValueError)
                    else "图片处理失败，原图已保留",
                )
                self._job_write(job)

    def cancel(self, project, job_id):
        with self.lock, self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT data FROM canvas_jobs WHERE id=? AND project=?",
                (job_id, project),
            ).fetchone()
            if not row:
                raise ValueError("任务不存在")
            job = json.loads(row[0])
            if job["state"] in ("queued", "running"):
                job.update(state="canceled", error="已取消接收；云端可能仍计费")
                db.execute(
                    "UPDATE canvas_jobs SET data=? WHERE id=?",
                    (json.dumps(job), job_id),
                )
        return self.jobs(project)

    def adopt(self, project, revision, job_id):
        job = self.job(project, job_id)
        if not job or job["state"] != "succeeded":
            raise ValueError("没有可采用的结果")
        row, layer = self._target(project, revision, job["layer_id"])
        if revision != job["revision"] or layer["asset_id"] != job["source_id"]:
            raise Conflict("画布已改变；候选已保留，可作为新图层导入，不能覆盖当前层")
        doc = copy.deepcopy(row["document"])
        next(l for l in doc["layers"] if l["id"] == layer["id"])["asset_id"] = job[
            "output"
        ]["id"]
        return self.save(project, revision, doc, "采用AI修图")
