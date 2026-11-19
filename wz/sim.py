"""Host-side simulator helpers: offscreen display, scripted keys, PNG snapshots.

Used by tools/preview.py and the test-suite so the whole UI can be exercised on
a laptop (no framebuffer, no keyboard, no WeChat account).
"""

from __future__ import annotations

import os

from PIL import Image


class MemoryDisplay:
    """Keeps the last frame and optionally writes every changed frame to PNG."""

    def __init__(self, out_dir: str = "", prefix: str = "frame"):
        self.out_dir = out_dir
        self.prefix = prefix
        self.frames = 0
        self.last: Image.Image | None = None
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

    def show(self, img: Image.Image) -> None:
        self.frames += 1
        self.last = img.copy()
        if self.out_dir:
            path = os.path.join(self.out_dir, "%s-%03d.png" % (self.prefix, self.frames))
            img.save(path)


class NullKeys:
    def __init__(self):
        self.available = False
        self.events = []

    def push(self, events):
        self.events.extend(events)

    def poll(self):
        out, self.events = self.events, []
        return out
