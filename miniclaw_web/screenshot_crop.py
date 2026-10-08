"""Conservative black-gutter suggestion, never a product detector or an auto-crop."""
from PIL import Image


def suggest(image):
    width, height = image.size
    if height < width * 1.8:
        return None
    sample = image.convert('RGB').resize((160, height), Image.Resampling.BOX)
    pixels = sample.load()
    rows = [sum(max(pixels[x, y]) > 3 for x in range(160)) >= 112
            for y in range(height)]
    # Bridge tiny compression/noise gaps; do not bridge large dark regions.
    start = None
    for y, active in enumerate(rows + [True]):
        if not active and start is None:
            start = y
        elif active and start is not None:
            if y - start <= 6:
                rows[start:y] = [True] * (y - start)
            start = None
    spans, start = [], None
    for y, active in enumerate(rows + [False]):
        if active and start is None:
            start = y
        elif not active and start is not None:
            if width * .5 <= y - start <= width * 1.7 and start >= height * .12 and height - y >= height * .1:
                spans.append((start, y))
            start = None
    if not spans:
        return None
    spans.sort(key=lambda span: span[1] - span[0], reverse=True)
    if len(spans) > 1 and spans[1][1] - spans[1][0] >= (spans[0][1] - spans[0][0]) * .8:
        return None
    top, bottom = max(spans, key=lambda span: span[1] - span[0])
    # Require empty gutters immediately above and below the proposed photograph.
    gap = max(8, round(width * .03))
    if any(rows[max(0, top-gap):top]) or any(rows[bottom:min(height, bottom+gap)]):
        return None
    return {'x': 0, 'y': top, 'width': width, 'height': bottom-top}
