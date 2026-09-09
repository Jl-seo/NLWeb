"""
Generate the Teams app icons without an image dependency.

Teams requires a 192x192 color icon and a 32x32 outline icon (white glyph on
transparency). Both are drawn here from primitives and written as PNG with the
standard library, so the package can be rebuilt anywhere without Pillow.

    python make_icons.py
"""

import struct
import zlib
from typing import List, Tuple

ACCENT = (91, 95, 199)      # Teams-ish purple, matches manifest accentColor
WHITE = (255, 255, 255)


def write_png(path: str, pixels: List[List[Tuple[int, int, int, int]]]) -> None:
    height = len(pixels)
    width = len(pixels[0])
    raw = b"".join(
        b"\x00" + b"".join(struct.pack("BBBB", *px) for px in row) for row in pixels
    )

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(png)


def blank(size: int, color: Tuple[int, int, int, int]):
    return [[color for _ in range(size)] for _ in range(size)]


def disc(canvas, cx: float, cy: float, r: float, color) -> None:
    size = len(canvas)
    for y in range(max(0, int(cy - r)), min(size, int(cy + r) + 1)):
        for x in range(max(0, int(cx - r)), min(size, int(cx + r) + 1)):
            if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                canvas[y][x] = color


def line(canvas, x0: float, y0: float, x1: float, y1: float, width: float, color) -> None:
    steps = int(max(abs(x1 - x0), abs(y1 - y0)) * 3) + 1
    for i in range(steps + 1):
        t = i / steps
        disc(canvas, x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, width / 2, color)


def graph_glyph(canvas, scale: float, color) -> None:
    """One node fanning out to three: a change and what it reaches."""
    root = (0.28, 0.5)
    leaves = [(0.74, 0.24), (0.78, 0.5), (0.74, 0.76)]
    for lx, ly in leaves:
        line(canvas, root[0] * scale, root[1] * scale, lx * scale, ly * scale,
             scale * 0.045, color)
    disc(canvas, root[0] * scale, root[1] * scale, scale * 0.105, color)
    for lx, ly in leaves:
        disc(canvas, lx * scale, ly * scale, scale * 0.068, color)


def main() -> None:
    color_icon = blank(192, ACCENT + (255,))
    graph_glyph(color_icon, 192, WHITE + (255,))
    write_png("color.png", color_icon)

    outline_icon = blank(32, (255, 255, 255, 0))
    graph_glyph(outline_icon, 32, WHITE + (255,))
    write_png("outline.png", outline_icon)

    print("생성 완료: color.png (192x192), outline.png (32x32)")


if __name__ == "__main__":
    main()
