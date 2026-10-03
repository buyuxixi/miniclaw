"""Versioned business documents and a renderer independent of the browser stage."""

import copy
import io
import math
import re
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


def number(value, low, high):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not low <= value <= high
    ):
        raise ValueError(f"数值须在{low}到{high}之间")
    return value


def color(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", value
    ):
        raise ValueError("颜色须为十六进制颜色")
    return value


def identifier():
    return uuid.uuid4().hex


def blank(width=1200, height=800):
    return dict(
        schema_version=1, width=width, height=height, background="#ffffff00", layers=[]
    )


def validate(document, asset):
    if (
        not isinstance(document, dict)
        or set(document)
        != {"schema_version", "width", "height", "background", "layers"}
        or document["schema_version"] != 1
    ):
        raise ValueError("画布文档版本或字段无效")
    result = copy.deepcopy(document)
    for key in ("width", "height"):
        value = number(result[key], 16, 4096)
        if int(value) != value:
            raise ValueError("画布尺寸须为整数")
        result[key] = int(value)
    color(result["background"])
    if not isinstance(result["layers"], list) or len(result["layers"]) > 40:
        raise ValueError("最多40个图层")
    seen = set()
    common = {
        "id",
        "kind",
        "name",
        "x",
        "y",
        "width",
        "height",
        "scale_x",
        "scale_y",
        "rotation",
        "opacity",
        "visible",
        "locked",
    }
    for layer in result["layers"]:
        if not isinstance(layer, dict):
            raise ValueError("图层无效")
        kind = layer.get("kind")
        extras = {
            "image": {"asset_id"},
            "text": {"text", "font_size", "fill"},
            "shape": {"shape", "fill"},
        }.get(kind)
        if extras is None or set(layer) != common | extras:
            raise ValueError("图层字段无效")
        if (
            not isinstance(layer["id"], str)
            or not re.fullmatch("[a-f0-9]{32}", layer["id"])
            or layer["id"] in seen
        ):
            raise ValueError("图层ID无效或重复")
        seen.add(layer["id"])
        if not isinstance(layer["name"], str) or not 1 <= len(layer["name"]) <= 100:
            raise ValueError("图层名称最长100字")
        for key in ("x", "y"):
            number(layer[key], -8192, 8192)
        for key in ("width", "height"):
            number(layer[key], 1, 4096)
        for key in ("scale_x", "scale_y"):
            number(layer[key], 0.02, 20)
        number(layer["rotation"], -36000, 36000)
        number(layer["opacity"], 0, 1)
        if type(layer["visible"]) is not bool or type(layer["locked"]) is not bool:
            raise ValueError("显隐与锁定须为布尔值")
        if kind == "image":
            record = asset(layer["asset_id"])
            if record["kind"] != "image":
                raise ValueError("素材不是图片")
            with Image.open(record["path"]) as image:
                if image.size != (layer["width"], layer["height"]):
                    raise ValueError("图片图层尺寸须与素材一致；缩放使用scale")
        elif kind == "text":
            if not isinstance(layer["text"], str) or len(layer["text"]) > 2000:
                raise ValueError("文字最多2000字")
            number(layer["font_size"], 8, 256)
            color(layer["fill"])
        else:
            if layer["shape"] not in ("rectangle", "ellipse"):
                raise ValueError("形状不支持")
            color(layer["fill"])
    return result


def layer_base(kind, name, width, height, **extra):
    return {
        **dict(
            id=identifier(),
            kind=kind,
            name=name,
            x=0,
            y=0,
            width=width,
            height=height,
            scale_x=1,
            scale_y=1,
            rotation=0,
            opacity=1,
            visible=True,
            locked=False,
        ),
        **extra,
    }


def affine(layer):
    angle = math.radians(layer["rotation"])
    c, s = math.cos(angle), math.sin(angle)
    return (
        c * layer["scale_x"],
        -s * layer["scale_y"],
        layer["x"],
        s * layer["scale_x"],
        c * layer["scale_y"],
        layer["y"],
    )


def inverse(layer):
    a, b, x, c, d, y = affine(layer)
    det = a * d - b * c
    return (
        d / det,
        -b / det,
        (b * y - d * x) / det,
        -c / det,
        a / det,
        (c * x - a * y) / det,
    )


def png(image):
    stream = io.BytesIO()
    image.save(stream, "PNG")
    return stream.getvalue()


def font_path():
    for path in (
        "C:/Windows/Fonts/msyh.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(path).is_file():
            return path
    return None


def pixels(layer, asset):
    size = (round(layer["width"]), round(layer["height"]))
    if layer["kind"] == "image":
        with Image.open(asset(layer["asset_id"])["path"]) as image:
            return ImageOps.exif_transpose(image).convert("RGBA")
    image = Image.new("RGBA", size)
    draw = ImageDraw.Draw(image)
    if layer["kind"] == "shape":
        method = draw.rectangle if layer["shape"] == "rectangle" else draw.ellipse
        method((0, 0, size[0] - 1, size[1] - 1), fill=layer["fill"])
    else:
        font = (
            ImageFont.truetype(font_path(), round(layer["font_size"]))
            if font_path()
            else ImageFont.load_default()
        )
        # Business text uses explicit newlines rather than browser-dependent wrapping.
        ascent, descent = font.getmetrics()
        line_height = layer["font_size"] * 1.35
        baseline = (ascent - descent) / 2 + line_height / 2
        for index, line in enumerate(layer["text"].split("\n")):
            draw.text(
                (0, baseline + index * line_height),
                line,
                font=font,
                fill=layer["fill"],
                anchor="ls",
            )
    return image


def render(document, asset):
    image = Image.new(
        "RGBA", (document["width"], document["height"]), document["background"]
    )
    for layer in document["layers"]:
        if not layer["visible"]:
            continue
        source = pixels(layer, asset)
        if layer["opacity"] != 1:
            source.putalpha(
                source.getchannel("A").point(lambda a: round(a * layer["opacity"]))
            )
        transformed = source.transform(
            image.size, Image.Transform.AFFINE, inverse(layer), Image.Resampling.BICUBIC
        )
        image.alpha_composite(transformed)
    return image


def ensure_unlocked(previous, document):
    by_id = {layer["id"]: layer for layer in document["layers"]}
    for old in previous["layers"]:
        if not old["locked"]:
            continue
        new = by_id.get(old["id"])
        # Unlocking is its own edit; the same write cannot also move/delete it.
        if new is None or {**new, "locked": True} != old:
            raise ValueError("请先解锁图层，再编辑或调整层级")
