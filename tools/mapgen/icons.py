#!/usr/bin/env python3
"""icons.py - plain pictograms for the stations of a map's package, drawn here (no operator's logo in them):
  stop.png     the stop sign: a yellow H on a green disc (the German Haltestellenzeichen, as OMSI 2's own stops show)
  sbahn.png    a white S on a green disc
  ubahn.png    a white U on a blue square
Needs Pillow; without it (or a bold font) the package simply has no icons and the stations are not drawn."""
import os

S = 4          # drawn four times larger and reduced: smooth edges
N = 96         # the pictures are 96 x 96 px, straight alpha
FONTS = [r"C:\Windows\Fonts\arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"]


def _pict(letter, shape, fill, ink, font_path, ring=(255, 255, 255)):
    from PIL import Image, ImageDraw, ImageFont
    n = N * S
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    m, w = 2 * S, 6 * S
    box = (m, m, n - m, n - m)
    if shape == "disc":
        d.ellipse(box, fill=ring + (255,))
        d.ellipse((m + w, m + w, n - m - w, n - m - w), fill=fill + (255,))
    else:
        d.rounded_rectangle(box, radius=8 * S, fill=ring + (255,))
        d.rounded_rectangle((m + w, m + w, n - m - w, n - m - w), radius=5 * S, fill=fill + (255,))
    f = ImageFont.truetype(font_path, int(n * 0.62))
    l, t, r, b = d.textbbox((0, 0), letter, font=f)
    d.text(((n - (r - l)) / 2 - l, (n - (b - t)) / 2 - t), letter, font=f, fill=ink + (255,))
    return im.resize((N, N), Image.LANCZOS)


def make_icons(folder):
    """Writes the three pictograms into `folder`; returns False when it could not (no Pillow or no font)."""
    try:
        import PIL  # noqa: F401
    except ImportError:
        return False
    font = next((f for f in FONTS if os.path.isfile(f)), None)
    if not font:
        return False
    os.makedirs(folder, exist_ok=True)
    _pict("H", "disc", (0, 131, 62), (255, 216, 0), font).save(os.path.join(folder, "stop.png"))
    _pict("S", "disc", (0, 138, 78), (255, 255, 255), font).save(os.path.join(folder, "sbahn.png"))
    _pict("U", "square", (0, 100, 168), (255, 255, 255), font).save(os.path.join(folder, "ubahn.png"))
    return True
