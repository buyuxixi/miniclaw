"""Actual authenticated HTTP/WebSocket canvas boundary, using fictional artwork.

Default is offline/local editing. --sam downloads official weights and runs CPU
point segmentation. --model makes one configured chat-model call, never a paid
DashScope request. --cloud makes exactly one paid image call, without retries.
"""

import argparse
import base64
import copy
import io
import json
import re
import sys
import time
import uuid
from pathlib import Path
import httpx
from PIL import Image, ImageDraw
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from miniclaw_web.canvas_document import blank, layer_base, png

BASE = "http://127.0.0.1:9120"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sam", action="store_true")
    parser.add_argument("--model", action="store_true")
    parser.add_argument("--cloud", action="store_true")
    args = parser.parse_args()
    token = re.search(
        r'__HERMES_SESSION_TOKEN__="([^"]+)"', httpx.get(BASE, trust_env=False).text
    ).group(1)
    api = httpx.Client(
        base_url=BASE,
        headers={"X-Hermes-Session-Token": token},
        timeout=90,
        trust_env=False,
    )

    def request(method, path, **kw):
        r = api.request(method, path, **kw)
        if r.status_code >= 400:
            raise RuntimeError(
                f"{path}: HTTP {r.status_code}: {r.json().get('detail')}"
            )
        return r.json()

    project = request(
        "POST",
        "/api/miniclaw/canvas/projects",
        json={"name": "画布 API 验收 " + time.strftime("%m-%d %H:%M")},
    )
    p = "/api/miniclaw/canvas/projects/" + project["id"]
    image = Image.new("RGB", (480, 320), (185, 190, 200))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((160, 65, 320, 270), 28, fill=(70, 100, 140))
    draw.rectangle((190, 138, 290, 183), fill=(230, 230, 225))
    draw.text((205, 150), "DEMO", fill=(40, 45, 50))
    raw = png(image)
    asset = request(
        "POST",
        p + "/assets",
        json={"name": "canvas-demo.png", "data": base64.b64encode(raw).decode()},
    )
    doc = blank(480, 320)
    layer = layer_base("image", "演示瓶子", 480, 320, asset_id=asset["id"])
    doc["layers"] = [layer]
    project = request(
        "PUT",
        p + "/document",
        json={"revision": project["revision"], "document": doc, "label": "导入演示图"},
    )
    report = {
        "project": project["id"],
        "source": asset["id"],
        "sam_requested": args.sam,
        "model_called": args.model,
        "dashscope_called": args.cloud,
    }
    sel = request(
        "POST",
        p + "/selection",
        json={
            "revision": project["revision"],
            "layer_id": layer["id"],
            "mode": "rectangle",
            "points": [[190, 138], [290, 183]],
        },
    )
    mask = Image.open(io.BytesIO(base64.b64decode(sel["mask"]))).convert("L")
    assert mask.getpixel((240, 160)) == 255 and mask.getpixel((5, 5)) == 0
    edited = request(
        "POST",
        p + "/masked",
        json={
            "revision": project["revision"],
            "layer_id": layer["id"],
            "operation": "extract",
            "params": {},
        },
    )
    assert len(edited["document"]["layers"]) == 2
    assert (
        api.get(f"/api/miniclaw/attachments/{asset['id']}?owner=wrong").status_code
        == 404
    )
    bytes_ = api.get(p + "/export").content
    assert Image.open(io.BytesIO(bytes_)).size == (480, 320)
    stale = api.put(
        p + "/document", json={"revision": project["revision"], "document": doc}
    )
    assert stale.status_code == 409
    project = request(
        "POST", p + "/restore", json={"revision": edited["revision"], "seq": 1}
    )
    assert project["revision"] > edited["revision"] and project["document"] == doc
    report.update(
        owned_download=True,
        cas_rejected=True,
        undo_revision=project["revision"],
        export_size=[480, 320],
    )
    if args.sam:
        request("POST", "/api/miniclaw/canvas/sam/prepare", json={})
        deadline = time.time() + 180
        while time.time() < deadline:
            caps = request("GET", "/api/miniclaw/canvas/capabilities")["sam"]
            if caps["state"] in ("ready", "error"):
                break
            time.sleep(1)
        if caps["state"] != "ready":
            raise RuntimeError("SAM not ready: " + str(caps))
        sel = request(
            "POST",
            p + "/segment",
            json={
                "revision": project["revision"],
                "layer_id": layer["id"],
                "point": [240, 220],
            },
        )
        mask = Image.open(io.BytesIO(base64.b64decode(sel["mask"]))).convert("L")
        assert mask.size == (480, 320) and mask.getbbox()
        report.update(
            sam_real_inference=True,
            sam_box=list(mask.getbbox()),
            sam_backend=caps["backend"],
        )
        (ROOT / ".codex/verification/canvas-sam-mask.png").write_bytes(
            base64.b64decode(sel["mask"])
        )
    if args.cloud:
        selection = request(
            "POST",
            p + "/selection",
            json={
                "revision": project["revision"],
                "layer_id": layer["id"],
                "mode": "rectangle",
                "points": [[190, 138], [290, 183]],
            },
        )
        job = request(
            "POST",
            p + "/jobs",
            json={
                "revision": project["revision"],
                "layer_id": layer["id"],
                "selection_id": selection["id"],
                "prompt": "Remove the DEMO text on the light label. Keep the rest of the product unchanged.",
                "request_id": uuid.uuid4().hex,
                "region": True,
                "feather": 2,
            },
        )
        deadline = time.time() + 150
        while time.time() < deadline:
            job = next(j for j in request("GET", p + "/jobs") if j["id"] == job["id"])
            if job["state"] not in ("running", "queued"):
                break
            time.sleep(1)
        if job["state"] != "succeeded":
            raise RuntimeError("Cloud candidate failed: " + str(job.get("error")))
        result = api.get(
            f"/api/miniclaw/attachments/{job['output']['id']}?owner=project-{project['id']}"
        ).content
        pixels = Image.open(io.BytesIO(result)).convert("RGBA")
        source = Image.open(io.BytesIO(raw)).convert("RGBA")
        for y in range(320):
            for x in range(480):
                if not 190 <= x <= 290 or not 138 <= y <= 183:
                    assert pixels.getpixel((x, y)) == source.getpixel((x, y))
        assert request("GET", p)["revision"] == project["revision"]
        project = request(
            "POST",
            p + "/jobs/" + job["id"] + "/adopt",
            json={"revision": project["revision"]},
        )
        report.update(
            cloud_candidate=job["id"],
            outside_pixels_equal=True,
            adopted_revision=project["revision"],
        )
    if args.model:
        original = [
            g["id"]
            for g in request("GET", "/api/miniclaw/tools")["groups"]
            if g["enabled"]
        ]
        try:
            request(
                "PUT",
                "/api/miniclaw/tools",
                json={"enabled": sorted(set(original + ["miniclaw-canvas"]))},
            )
            with connect("ws://127.0.0.1:9120/api/ws?token=" + token) as ws:
                events = []

                def receive():
                    frames = [
                        json.loads(line) for line in ws.recv(timeout=90).splitlines()
                    ]
                    events.extend(
                        f["params"] for f in frames if f.get("method") == "event"
                    )
                    return frames

                def rpc(method, params):
                    rid = uuid.uuid4().hex
                    ws.send(
                        json.dumps(
                            {
                                "jsonrpc": "2.0",
                                "id": rid,
                                "method": method,
                                "params": params,
                            }
                        )
                    )
                    while True:
                        for frame in receive():
                            if frame.get("id") == rid:
                                if frame.get("error"):
                                    raise RuntimeError(frame["error"]["message"])
                                return frame["result"]

                snapshot = rpc(
                    "session.create",
                    {"source": "desktop", "follow_profile_config": True},
                )
                sid = snapshot["session_id"]
                for _ in range(100):
                    if request(
                        "GET",
                        "/api/miniclaw/session-capabilities",
                        params={"session_id": sid},
                    )["ready"]:
                        break
                    time.sleep(0.2)
                project = request(
                    "PATCH",
                    p,
                    json={"revision": project["revision"], "session_id": sid},
                )
                request(
                    "POST",
                    p + "/selection",
                    json={
                        "revision": project["revision"],
                        "layer_id": layer["id"],
                        "mode": "rectangle",
                        "points": [[190, 138], [290, 183]],
                    },
                )
                rpc(
                    "miniclaw.turn.submit",
                    {
                        "session_id": sid,
                        "skill": "canvas-editor",
                        "text": "请先读取画布摘要，然后把当前选区提取为独立图层。只进行本地提取，不要调用百炼。完成后简短报告。",
                        "canvas_context": {
                            "project_id": project["id"],
                            "revision": project["revision"],
                            "layer_id": layer["id"],
                        },
                    },
                )
                deadline = time.time() + 180
                while time.time() < deadline:
                    receive()
                    if any(
                        e.get("session_id") == sid
                        and e.get("type") == "message.complete"
                        for e in events
                    ):
                        break
                after = request("GET", p)
                assert len(after["document"]["layers"]) == 2
                report.update(
                    model_project=project["id"],
                    model_extracted=True,
                    model_revision=after["revision"],
                )
                rpc("session.close", {"session_id": sid})
        finally:
            request("PUT", "/api/miniclaw/tools", json={"enabled": original})
    report["status"] = "passed"
    suffix = (
        "-sam"
        if args.sam
        else "-model"
        if args.model
        else "-cloud"
        if args.cloud
        else ""
    )
    (ROOT / f".codex/verification/canvas-live{suffix}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
