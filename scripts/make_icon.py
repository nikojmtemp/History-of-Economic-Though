"""Draw the Stock logo: Adam Smith in profile, as a cameo.

    .venv/Scripts/python.exe scripts/make_icon.py

After James Tassie's paste medallion of 1787, the best-known likeness of Smith: the
profile in white relief on a coloured ground, here in a gold rim. (His neckcloth was
what the age called a stock.)

Writes `scripts/stock.ico` (the Windows icon, 16-256 px), `mac/stock.icns` (the Mac
icon) and `stock/web/icon.png` (the page's favicon). Drawn at 1024 px and scaled down, so every size stays crisp.
Needs Pillow (a build tool only; the game does not import it).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
S = 1024

GROUND = (58, 88, 132)  # Wedgwood-ish blue
GROUND_DEEP = (36, 58, 92)
RELIEF = (246, 241, 230)
RELIEF_SHADE = (205, 198, 184)
LINE = (150, 142, 128)
GOLD, GOLD_DARK, GOLD_LIGHT = (212, 166, 62), (140, 102, 30), (246, 216, 130)
RIBBON = (30, 27, 22)

Point = tuple[float, float]

# The profile, facing right, clockwise from the crown (1024 px canvas).
PROFILE: list[Point] = [
    (492, 244),
    (588, 252),
    (640, 292),  # the crown and the front of the wig
    (662, 338),
    (676, 384),
    (668, 404),  # the forehead, the brow, the bridge of the nose
    (700, 450),
    (730, 500),
    (748, 528),
    (740, 544),  # the long, strong nose and its tip
    (712, 546),
    (706, 562),
    (716, 574),
    (700, 584),  # under the nose, the upper lip
    (712, 596),
    (694, 612),  # the lower lip, the crease of the chin
    (708, 640),
    (696, 668),
    (664, 688),
    (632, 696),  # the chin and the jowl
    (612, 714),
    (634, 740),
    (666, 760),
    (678, 800),
    (664, 832),  # the throat, the stock and its frill
    (690, 880),
    (704, 932),  # the coat
    (330, 932),
    (332, 862),
    (372, 806),  # the back of the coat and the shoulder
    (420, 752),
    (446, 716),
    (404, 694),
    (366, 664),  # the nape, the queue
    (330, 604),
    (314, 530),
    (320, 446),
    (350, 360),
    (408, 284),  # the full back of the wig
]


def _catmull(points: list[Point], steps: int = 14) -> list[Point]:
    """A smooth closed curve through `points`."""

    out: list[Point] = []
    n = len(points)
    for i in range(n):
        p0, p1, p2, p3 = points[i - 1], points[i], points[(i + 1) % n], points[(i + 2) % n]
        for k in range(steps):
            t = k / steps
            t2, t3 = t * t, t * t * t
            out.append(
                tuple(  # type: ignore[arg-type]
                    0.5
                    * (
                        2 * p1[j]
                        + (-p0[j] + p2[j]) * t
                        + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * t2
                        + (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * t3
                    )
                    for j in (0, 1)
                )
            )
    return out


def _quad(a: Point, m: Point, b: Point, steps: int = 16) -> list[Point]:
    """A quadratic curve from `a` to `b`, bent toward `m`."""

    return [
        (
            (1 - t) ** 2 * a[0] + 2 * (1 - t) * t * m[0] + t * t * b[0],
            (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * m[1] + t * t * b[1],
        )
        for t in (k / steps for k in range(steps + 1))
    ]


def _stroke(d: ImageDraw.ImageDraw, pts: list[Point], width: int, fill: tuple[int, ...]) -> None:
    d.line(pts, fill=fill, width=width, joint="curve")
    r = width / 2
    for x, y in (pts[0], pts[-1]):
        d.ellipse((x - r, y - r, x + r, y + r), fill=fill)


def draw() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    c, R = S // 2, 470

    # a soft shadow, the gold rim, the blue ground with a little depth toward the edge
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse((c - R + 6, c - R + 22, c + R + 6, c + R + 22), fill=(0, 0, 0, 120))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)))
    d = ImageDraw.Draw(img)
    d.ellipse((c - R, c - R, c + R, c + R), fill=GOLD_DARK)
    d.ellipse((c - R + 10, c - R + 10, c + R - 10, c + R - 10), fill=GOLD)
    d.arc((c - R + 22, c - R + 22, c + R - 22, c + R - 22), 200, 290, fill=GOLD_LIGHT, width=14)
    g = R - 52
    d.ellipse((c - g - 6, c - g - 6, c + g + 6, c + g + 6), fill=GOLD_DARK)
    d.ellipse((c - g, c - g, c + g, c + g), fill=GROUND_DEEP)
    d.ellipse((c - g + 26, c - g + 26, c + g - 26, c + g - 26), fill=GROUND)

    # the profile, in relief: a shadow cast down and left, then the white paste
    outline = _catmull(PROFILE)
    relief = Image.new("L", (S, S), 0)
    ImageDraw.Draw(relief).polygon(outline, fill=255)
    ground_mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(ground_mask).ellipse((c - g, c - g, c + g, c + g), fill=255)
    relief = ImageChops.multiply(relief, ground_mask)  # the bust is cut off by the medallion's edge
    cast = relief.filter(ImageFilter.GaussianBlur(10)).transform(
        (S, S), Image.Transform.AFFINE, (1, 0, 10, 0, 1, -14)
    )
    img.paste(Image.new("RGBA", (S, S), (10, 20, 40, 150)), (0, 0), ImageChops.multiply(cast, ground_mask))
    img.paste(Image.new("RGBA", (S, S), RELIEF_SHADE), (0, 0), relief)
    lit = relief.filter(ImageFilter.GaussianBlur(3)).transform(
        (S, S), Image.Transform.AFFINE, (1, 0, 8, 0, 1, 8)
    )
    img.paste(Image.new("RGBA", (S, S), RELIEF), (0, 0), ImageChops.multiply(lit, relief))

    d = ImageDraw.Draw(img)
    # the wig: hair swept back from the brow to the queue, two rolled curls over the ear
    for (x0, y0), (xm, ym), (x1, y1) in (
        ((604, 276), (500, 266), (392, 320)),
        ((636, 318), (520, 316), (360, 400)),
        ((652, 360), (540, 372), (378, 470)),
    ):
        _stroke(d, _quad((x0, y0), (xm, ym), (x1, y1)), 6, LINE)
    for cy in (500, 564):
        d.ellipse((404, cy - 32, 540, cy + 32), fill=RELIEF_SHADE)
        d.ellipse((414, cy - 26, 534, cy + 22), fill=RELIEF)
        d.arc((428, cy - 16, 518, cy + 20), 150, 390, fill=LINE, width=7)
    # the ribbon tying the queue
    d.polygon([(378, 680), (320, 654), (330, 722)], fill=RIBBON)
    d.polygon([(378, 680), (346, 750), (394, 742)], fill=RIBBON)
    d.ellipse((362, 664, 394, 696), fill=RIBBON)
    # the face: brow, eye, nostril, mouth
    _stroke(d, _quad((610, 398), (636, 386), (664, 394)), 7, LINE)
    _stroke(d, _quad((628, 418), (644, 428), (660, 420)), 7, LINE)
    d.ellipse((638, 410, 652, 422), fill=LINE)
    _stroke(d, _quad((706, 532), (716, 538), (724, 536)), 6, LINE)
    _stroke(d, [(686, 582), (702, 582)], 6, LINE)
    # the stock: the neckcloth's folds; the coat's lapel
    for y in (744, 770):
        _stroke(d, _quad((612, y), (636, y + 2), (660, y + 12)), 6, LINE)
    _stroke(d, _quad((590, 826), (604, 880), (632, 928)), 8, LINE)
    return img


def main() -> None:
    img = draw()
    # classic bitmaps, not PNG, inside the .ico: every part of Windows can read them
    img.save(
        ROOT / "scripts" / "stock.ico",
        sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)],
        bitmap_format="bmp",
    )
    img.save(ROOT / "mac" / "stock.icns")  # the Mac app's icon, every size from one drawing
    img.resize((256, 256), Image.Resampling.LANCZOS).save(ROOT / "stock" / "web" / "icon.png")
    img.resize((512, 512), Image.Resampling.LANCZOS).save(ROOT / ".pyinstaller" / "icon-preview.png")


if __name__ == "__main__":
    (ROOT / ".pyinstaller").mkdir(exist_ok=True)
    main()
