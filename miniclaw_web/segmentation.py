"""Explicitly prepared, local SAM inference. No geometric fallback."""

import importlib.util
import io
import os
import threading
from PIL import Image

_lock = threading.RLock()
_session = None
_status = {"state": "unprepared", "backend": "SAM · ONNX CPU", "error": None}


def status():
    with _lock:
        return {**_status, "installed": importlib.util.find_spec("rembg") is not None}


def prepare(home):
    global _session
    with _lock:
        if _status["state"] in ("preparing", "ready"):
            return status()
        if importlib.util.find_spec("rembg") is None:
            _status.update(
                state="error", error="请运行scripts/setup-canvas.ps1安装本地分割依赖"
            )
            return status()
        _status.update(state="preparing", error=None)

    def load():
        global _session
        try:
            os.environ["U2NET_HOME"] = str(home / "models" / "sam")
            from rembg import new_session

            session = new_session(
                "sam", sam_quant=True, providers=["CPUExecutionProvider"]
            )
            with _lock:
                _session = session
                _status.update(state="ready", error=None)
        except Exception:
            with _lock:
                _status.update(
                    state="error",
                    error="SAM准备失败，请检查模型下载与本地依赖；框选和笔刷仍可用",
                )

    threading.Thread(target=load, daemon=True, name="sam-prepare").start()
    return status()


def segment(raw, point, home):
    with _lock:
        if _session is None or _status["state"] != "ready":
            raise ValueError("请先准备SAM模型，等待状态显示就绪")
        from rembg import remove

        try:
            result = remove(
                raw,
                session=_session,
                only_mask=True,
                sam_prompt=[{"type": "point", "data": point, "label": 1}],
            )
            mask = Image.open(io.BytesIO(result)).convert("L")
            with Image.open(io.BytesIO(raw)) as source:
                if mask.size != source.size:
                    raise ValueError("SAM蒙版尺寸不一致")
            if not mask.getbbox():
                raise ValueError("未识别到该物体，请换一个点或使用笔刷")
            return mask
        except ValueError:
            raise
        except Exception:
            raise ValueError("SAM识别失败，请使用框选或笔刷") from None
