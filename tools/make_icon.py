"""Generate the WorkRoom logo bitmaps from the same geometry as favicon.svg.

The feather is the mark: the app is a room for writing and shipping work. One
source of truth matters here — the web favicon, the taskbar icon and the
controller window must not drift apart, so the shape is defined once in
``SHAPE`` and every output is rendered from it.

Run from the project root:
    tools/.venv/Scripts/python.exe tools/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "workroom" / "static" / "workroom"

BASE = 256
INK = "#f0f3f7"
SHAFT = "#8d97a3"
BG = "#242b33"
EDGE = "#3d4652"
CUT = (168, 177, 188)


def _cubic(p0, c1, c2, p1, steps=16):
    points = []
    for index in range(steps + 1):
        t = index / steps
        u = 1 - t
        x = u**3 * p0[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t**3 * p1[0]
        y = u**3 * p0[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t**3 * p1[1]
        points.append((x, y))
    return points


def _feather_outline(scale: float):
    """Same two curves as the SVG path, in the 32×32 coordinate space."""
    left = _cubic((9, 23.5), (10.2, 15.6), (15.8, 9.8), (23.2, 8.2))
    right = _cubic((23.2, 8.2), (22.6, 16.2), (16.8, 21.8), (9, 23.5))
    return [(x * scale, y * scale) for x, y in left + right[1:]]


def render(size: int) -> Image.Image:
    scale = size / 32
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        (0, 0, size - 1, size - 1),
        radius=max(1, round(8 * scale)),
        fill=BG,
        outline=EDGE,
        width=max(1, round(0.6 * scale)),
    )
    draw.polygon(_feather_outline(scale), fill=INK)

    # 羽枝：必须垂直于羽轴朝两侧伸出。第一版画成了与羽轴平行，
    # 结果全被羽轴压住，整片看着像叶子。
    shaft_start = (8.4, 24.2)
    shaft_end = (23.4, 8.2)
    reach = 1.28
    for step in range(4):
        t = 0.26 + step * 0.14
        cx = shaft_start[0] + (shaft_end[0] - shaft_start[0]) * t
        cy = shaft_start[1] + (shaft_end[1] - shaft_start[1]) * t
        for sign in (-1, 1):
            draw.line(
                [
                    ((cx + sign * 0.35) * scale, (cy + sign * 0.35) * scale),
                    ((cx + sign * reach) * scale, (cy + sign * reach) * scale),
                ],
                fill=CUT,
                width=max(1, round(0.62 * scale)),
            )

    draw.line(
        [(shaft_start[0] * scale, shaft_start[1] * scale),
         (shaft_end[0] * scale, shaft_end[1] * scale)],
        fill=SHAFT,
        width=max(1, round(0.8 * scale)),
    )
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    large = render(BASE)
    large.save(OUT / "logo.png")
    large.save(
        OUT / "app.ico",
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    for size in (16, 32, 48):
        render(size).save(OUT / f"logo-{size}.png")
    print("logo.png / app.ico / logo-{16,32,48}.png 已写入", OUT)


if __name__ == "__main__":
    main()
