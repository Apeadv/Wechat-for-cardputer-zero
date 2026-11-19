#!/usr/bin/env python3
"""Capture the Cardputer Zero panel (RGB565) to PNG.  Runs on the device."""

import os
import sys

import numpy as np
from PIL import Image

W, H = 320, 170
path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/screen.png"
fd = os.open("/dev/fb0", os.O_RDONLY)
try:
    raw = os.read(fd, W * H * 2)
finally:
    os.close(fd)
a = np.frombuffer(raw, dtype="<u2").reshape(H, W)
r = ((a >> 11) & 0x1F).astype(np.uint32) * 255 // 31
g = ((a >> 5) & 0x3F).astype(np.uint32) * 255 // 63
b = (a & 0x1F).astype(np.uint32) * 255 // 31
img = np.dstack([r, g, b]).astype(np.uint8)
Image.fromarray(img, "RGB").save(path)
print("saved", path)
