#!/usr/bin/env python3
"""Generate APPLaunch / AppStore icons (80, 128, 256 px) from one design."""

import os
import sys

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from wz.ui import UI, ACCENT  # noqa: E402


def draw(size: int):
    ui = UI()
    scale = size / 128.0
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def s(v: float) -> float:
        return v * scale

    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=s(28),
                        fill=ACCENT + (255,))
    d.rounded_rectangle([s(20), s(24), s(108), s(88)], radius=s(18),
                        fill=(255, 255, 255, 255))
    d.polygon([(s(42), s(84)), (s(38), s(106)), (s(64), s(88))],
              fill=(255, 255, 255, 255))
    f = ui.font(max(12, int(44 * scale)))
    text = "微"
    tw = d.textlength(text, font=f)
    d.text(((size - tw) / 2, s(30)), text, font=f, fill=(6, 150, 74, 255))
    return img


def main() -> int:
    targets = (
        (80, os.path.join(ROOT, "packaging", "icon-80.png")),
        (128, os.path.join(ROOT, "assets", "icon-128.png")),
        (256, os.path.join(ROOT, "packaging", "icon-256.png")),
    )
    for size, out in targets:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        draw(size).save(out)
        print("wrote", out, (size, size))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
