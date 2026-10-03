"""Real pixels, durable history and revision/ownership guards; no paid services."""

import base64
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "hermes-agent")]
from PIL import Image
from miniclaw_web.canvas import Canvas, Conflict
from miniclaw_web.canvas_document import blank, layer_base, png, render, inverse, affine
from miniclaw_web.store import Store
from miniclaw_web.attachments import upload


class Held:
    def __init__(self):
        self.calls = []

    def submit(self, f, *args):
        self.calls.append((f, args))
        return Future()

    def run(self):
        f, args = self.calls.pop(0)
        f(*args)


class CanvasTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.held = Held()
        self.canvas = Canvas(self.store, self.held)
        self.project = self.canvas.create("测试画布")
        self.id = self.project["id"]
        image = Image.new("RGBA", (80, 60), (80, 120, 160, 180))
        image.putpixel((0, 0), (200, 20, 20, 0))
        self.raw = png(image)
        self.asset = self.canvas.add_asset(self.id, self.raw, "original.png")
        self.layer = layer_base("image", "原图", 80, 60, asset_id=self.asset["id"])
        self.doc = blank(160, 120)
        self.doc["layers"] = [self.layer]
        self.project = self.canvas.save(self.id, 0, self.doc, "导入")

    def tearDown(self):
        self.temp.cleanup()

    def select(self, mode="rectangle", points=None, **kwargs):
        return self.canvas.select(
            self.id,
            self.project["revision"],
            self.layer["id"],
            mode,
            points or [[10, 10], [30, 30]],
            **kwargs,
        )

    def test_project_reopens_without_chat_and_revision_never_rolls_back(self):
        reopened = Canvas(Store(self.temp.name), Held())
        self.assertEqual(reopened.get(self.id)["document"], self.doc)
        restored = reopened.restore(self.id, 1, 0)
        self.assertEqual(restored["revision"], 2)
        self.assertEqual(restored["cursor"], 0)
        with self.assertRaises(Conflict):
            reopened.save(self.id, 1, self.doc)
        redone = reopened.restore(self.id, 2, 1)
        self.assertEqual(redone["revision"], 3)
        self.assertEqual(redone["document"], self.doc)

    def test_history_branch_drops_redo_and_old_selection(self):
        self.select()
        restored = self.canvas.restore(self.id, 1, 0)
        self.assertIsNone(self.canvas.selection(self.id))
        doc = blank(200, 150)
        saved = self.canvas.save(self.id, restored["revision"], doc, "新分支")
        self.assertEqual(saved["revision"], 3)
        self.assertEqual([h["seq"] for h in self.canvas.history(self.id)], [1, 0])
        self.assertEqual(self.canvas.get(self.id)["document"], doc)

    def test_foreign_assets_bad_document_nan_and_locked_layers_are_rejected(self):
        other = self.canvas.create()
        foreign = self.canvas.add_asset(other["id"], self.raw, "foreign.png")
        for patch_layer in (
            {"asset_id": foreign["id"]},
            {"x": float("nan")},
            {"scale_x": -1},
            {"unexpected": True},
            {"width": 81},
        ):
            doc = copy.deepcopy(self.doc)
            doc["layers"][0].update(patch_layer)
            with self.assertRaises(ValueError):
                self.canvas.save(self.id, 1, doc)
        doc = copy.deepcopy(self.doc)
        doc["layers"][0]["locked"] = True
        self.canvas.save(self.id, 1, doc)
        doc["layers"][0]["x"] = 20
        with self.assertRaises(ValueError):
            self.canvas.save(self.id, 2, doc)
        doc["layers"][0]["locked"] = False
        with self.assertRaises(ValueError):
            self.canvas.save(self.id, 2, doc)

    def test_masked_adjust_preserves_every_pixel_outside_selection_and_source(self):
        self.select()
        out = self.canvas.masked(
            self.id, 1, self.layer["id"], "adjust", {"brightness": 0.5}
        )
        edited = Image.open(
            self.canvas.asset(self.id, out["document"]["layers"][0]["asset_id"])["path"]
        ).convert("RGBA")
        source = Image.open(io.BytesIO(self.raw)).convert("RGBA")
        for y in range(60):
            for x in range(80):
                if not 10 <= x <= 30 or not 10 <= y <= 30:
                    self.assertEqual(edited.getpixel((x, y)), source.getpixel((x, y)))
        self.assertNotEqual(edited.getpixel((20, 20)), source.getpixel((20, 20)))
        self.assertEqual(
            Path(self.canvas.asset(self.id, self.asset["id"])["path"]).read_bytes(),
            self.raw,
        )

    def test_selection_inverse_transform_rotate_nonuniform_and_brush_subtract(self):
        doc = copy.deepcopy(self.doc)
        doc["layers"][0].update(x=100, y=20, scale_x=2, scale_y=1, rotation=90)
        self.project = self.canvas.save(self.id, 1, doc)
        # Source (10,10)..(20,20) maps to canvas (90,40)..(80,60).
        selection = self.select(points=[[80, 40], [90, 60]])
        mask = Image.open(io.BytesIO(base64.b64decode(selection["mask"]))).convert("L")
        self.assertEqual(mask.getpixel((15, 15)), 255)
        self.assertEqual(mask.getpixel((0, 0)), 0)
        self.canvas.select(
            self.id,
            2,
            self.layer["id"],
            "brush",
            [[85, 50]],
            radius=2,
            combine="subtract",
        )
        mask = Image.open(
            io.BytesIO(base64.b64decode(self.canvas.selection(self.id)["mask"]))
        ).convert("L")
        self.assertEqual(mask.getpixel((15, 15)), 0)

    def test_erase_and_extract_alpha_lasso_invert_and_selection_revision(self):
        self.select("lasso", [[10, 10], [30, 10], [20, 30]])
        out = self.canvas.masked(self.id, 1, self.layer["id"], "extract", {})
        self.assertEqual(len(out["document"]["layers"]), 2)
        cut = Image.open(
            self.canvas.asset(self.id, out["document"]["layers"][1]["asset_id"])["path"]
        ).convert("RGBA")
        self.assertEqual(cut.size, (21, 21))
        self.assertEqual(cut.getpixel((10, 5))[3], 180)
        self.assertEqual(cut.getpixel((0, 20))[3], 0)
        self.project = out
        self.select()
        self.canvas.select(self.id, 2, self.layer["id"], "invert")
        out = self.canvas.masked(self.id, 2, self.layer["id"], "erase", {})
        erased = Image.open(
            self.canvas.asset(self.id, out["document"]["layers"][0]["asset_id"])["path"]
        ).convert("RGBA")
        self.assertEqual(erased.getpixel((20, 20))[3], 180)
        self.assertEqual(erased.getpixel((60, 50))[3], 0)
        with self.assertRaises(Conflict):
            self.canvas.select(self.id, 1, self.layer["id"], "brush", [[20, 20]])

    def test_renderer_shape_rotation_transparency_and_chinese_text(self):
        doc = blank(200, 160)
        doc["layers"] = [
            layer_base(
                "shape",
                "形状",
                40,
                20,
                x=70,
                y=20,
                rotation=90,
                shape="rectangle",
                fill="#ff0000",
            )
        ]
        image = render(doc, lambda _: None)
        self.assertEqual(image.getpixel((60, 30)), (255, 0, 0, 255))
        self.assertEqual(image.getpixel((10, 10))[3], 0)
        doc["layers"].append(
            layer_base(
                "text",
                "中文",
                180,
                60,
                x=10,
                y=90,
                text="中文画布",
                font_size=24,
                fill="#223344",
            )
        )
        self.assertTrue(render(doc, lambda _: None).crop((0, 90, 200, 150)).getbbox())

    def job(self, **kwargs):
        return self.canvas.submit(
            self.id,
            1,
            self.layer["id"],
            "remove selected spot",
            kwargs.get("request", "same-request-01"),
            True,
            kwargs.get("feather", 4),
        )

    def test_ai_is_idempotent_masked_candidate_and_cannot_overwrite_later_edit(self):
        self.select()
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "fixture-key"}):
            job = self.job()
            self.assertEqual(self.job()["id"], job["id"])
            self.assertEqual(len(self.held.calls), 1)
            with self.assertRaises(ValueError):
                self.job(feather=3)
        doc = copy.deepcopy(self.doc)
        doc["layers"][0]["x"] = 5
        self.canvas.save(self.id, 1, doc)
        with patch(
            "miniclaw_web.canvas.edit_image",
            return_value=(png(Image.new("RGBA", (64, 64), "red")), "fixture"),
        ):
            self.held.run()
        completed = self.canvas.jobs(self.id)[0]
        self.assertEqual(completed["state"], "succeeded")
        self.assertEqual(self.canvas.get(self.id)["document"], doc)
        image = Image.open(
            self.canvas.asset(self.id, completed["output"]["id"])["path"]
        ).convert("RGBA")
        source = Image.open(io.BytesIO(self.raw)).convert("RGBA")
        for y in range(60):
            for x in range(80):
                if not 10 <= x <= 30 or not 10 <= y <= 30:
                    self.assertEqual(image.getpixel((x, y)), source.getpixel((x, y)))
        with self.assertRaises(Conflict):
            self.canvas.adopt(self.id, 2, job["id"])

    def test_cancel_and_restart_never_resurrect_or_repeat_cloud_task(self):
        self.select()
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "fixture-key"}):
            job = self.job()
        self.canvas.cancel(self.id, job["id"])
        with patch("miniclaw_web.canvas.edit_image") as provider:
            self.held.run()
            provider.assert_not_called()
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "fixture-key"}):
            self.job(request="new-request-02")
        reopened = Canvas(Store(self.temp.name), Held())
        self.assertEqual(reopened.jobs(self.id)[0]["state"], "failed")
        self.assertEqual(reopened.executor.calls, [])

    def test_archive_restore_and_limits(self):
        p = self.canvas.metadata(self.id, 1, archived=True)
        self.assertEqual(len(self.canvas.list(True)), 1)
        with self.assertRaises(ValueError):
            self.canvas.select(
                self.id, p["revision"], self.layer["id"], "brush", [[10, 10]]
            )
        self.canvas.metadata(self.id, p["revision"], archived=False)
        with self.assertRaises(ValueError):
            self.canvas.select(
                self.id, 3, self.layer["id"], "brush", [[float("inf"), 1]]
            )

    def test_frozen_selection_id_checks_actual_mask_and_idempotency_contract(self):
        old = self.select()
        new = self.select(points=[[40, 30], [50, 40]])
        self.assertNotEqual(old["id"], new["id"])
        with self.assertRaises(Conflict):
            self.canvas.masked(self.id, 1, self.layer["id"], "erase", {}, old["id"])
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "fixture-key"}):
            with self.assertRaises(Conflict):
                self.canvas.submit(
                    self.id,
                    1,
                    self.layer["id"],
                    "edit",
                    "selection-request-01",
                    True,
                    0,
                    old["id"],
                )
            job = self.canvas.submit(
                self.id,
                1,
                self.layer["id"],
                "edit",
                "selection-request-01",
                True,
                0,
                new["id"],
            )
            self.assertEqual(
                self.canvas.submit(
                    self.id,
                    1,
                    self.layer["id"],
                    "edit",
                    "selection-request-01",
                    True,
                    0,
                    new["id"],
                )["id"],
                job["id"],
            )
            with self.assertRaises(ValueError):
                self.canvas.submit(
                    self.id,
                    1,
                    self.layer["id"],
                    "edit",
                    "selection-request-01",
                    True,
                    0,
                    old["id"],
                )

    def test_visible_old_asset_and_old_job_remain_addressable_after_list_limits(self):
        for _ in range(201):
            self.canvas.add_asset(self.id, self.raw, "history.png")
        self.assertIn(self.asset["id"], {a["id"] for a in self.canvas.assets(self.id)})
        with self.store.connect() as db:
            for index in range(35):
                db.execute(
                    "INSERT INTO canvas_jobs VALUES (?,?,?)",
                    (
                        str(index),
                        self.id,
                        json.dumps(
                            {"id": str(index), "project": self.id, "state": "canceled"}
                        ),
                    ),
                )
        self.assertEqual(len(self.canvas.jobs(self.id)), 30)
        self.assertEqual(self.canvas.job(self.id, "0")["state"], "canceled")
        other = self.canvas.create()
        with self.assertRaises(ValueError):
            self.canvas.job(other["id"], "0")


if __name__ == "__main__":
    unittest.main()
