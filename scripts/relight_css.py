"""Map the dark theme's hard-coded colors to the light "studio" theme.

Rules (see docs/redesign-log.md, step 2):
- Neutral or near-neutral colors invert their lightness, so dark surfaces become paper and light text becomes ink.
- Saturated colors keep their hue and are pulled into a readable mid-dark lightness on paper.
- Black with alpha stays a (softer) shadow; white with alpha becomes black with alpha (hover/overlay tints).
Run: python scripts/relight_css.py <css files...>   (idempotency is not attempted; run once on dark sources)
"""
import colorsys, re, sys
from pathlib import Path

HEX = re.compile(r'#([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})\b')


def parse(h):
    if len(h) in (3, 4): h = ''.join(c * 2 for c in h)
    rgb = tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    alpha = int(h[6:8], 16) / 255 if len(h) == 8 else None
    return rgb, alpha


def fmt(rgb, alpha):
    s = '#' + ''.join(f'{round(max(0, min(1, c)) * 255):02x}' for c in rgb)
    return s + (f'{round(alpha * 255):02x}' if alpha is not None else '')


def relight(match):
    rgb, alpha = parse(match.group(1))
    h, l, s = colorsys.rgb_to_hls(*rgb)
    if alpha is not None and alpha < 1:
        if l < 0.12: return fmt((0.1, 0.1, 0.09), alpha * 0.55)        # shadow
        if l > 0.85: return fmt((0.1, 0.1, 0.09), min(alpha, 0.08))    # white tint -> ink tint
    chroma = s * (1 - abs(2 * l - 1))
    if chroma < 0.12:
        # Neutral: invert lightness, warm it slightly toward paper, keep a little contrast headroom.
        nl = 0.97 - l * 0.86
        ns = min(s, 0.12)
        nh = 0.11 if nl > 0.6 else h
        return fmt(colorsys.hls_to_rgb(nh, nl, ns), alpha)
    # Saturated: keep hue; light pastels become mid-dark, dark tints become pale fills.
    nl = 0.38 + (1 - l) * 0.12 if l >= 0.5 else 0.9 + (0.5 - l) * 0.12
    return fmt(colorsys.hls_to_rgb(h, nl, min(1, s * 0.85)), alpha)


for name in sys.argv[1:]:
    path = Path(name)
    text = path.read_bytes().decode('utf-8')  # bytes keep the file's own CRLF/LF endings
    out = HEX.sub(relight, text).replace('color-scheme: dark', 'color-scheme: light')
    path.write_bytes(out.encode('utf-8'))
    print(path, len(HEX.findall(text)))
