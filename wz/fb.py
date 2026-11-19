"""Linux framebuffer output (RGB565 / RGB32) for the Cardputer Zero panel."""

from __future__ import annotations

import array
import mmap
import os
import struct
import sys

try:
    import fcntl
except ImportError:      # host development on Windows
    fcntl = None

from PIL import Image

try:                     # numpy makes RGB565 packing ~10x faster
    import numpy as _np
except Exception:        # pragma: no cover - device may not have numpy
    _np = None


def pack_rgb565(img: Image.Image) -> bytes:
    """Pack an RGB image into little-endian RGB565 (the panel's format)."""
    if _np is not None:
        arr = _np.asarray(img, dtype=_np.uint16)
        out = (((arr[:, :, 0] >> 3) << 11)
               | ((arr[:, :, 1] >> 2) << 5)
               | (arr[:, :, 2] >> 3)).astype("<u2")
        return out.tobytes()
    buf = array.array("H", [(r >> 3) << 11 | (g >> 2) << 5 | (b >> 3)
                            for (r, g, b) in img.getdata()])
    if sys.byteorder != "little":
        buf.byteswap()
    return buf.tobytes()


class FramebufferError(RuntimeError):
    pass


class Framebuffer:
    def __init__(self, path: str = ""):
        if fcntl is None:
            raise FramebufferError("帧缓冲只在 Linux 上可用")
        candidates = [path] if path else ["/dev/fb_lcd", "/dev/fb0"]
        for dev in candidates:
            try:
                fd = os.open(dev, os.O_RDWR)
            except OSError:
                continue
            try:
                var = bytearray(160)
                fix = bytearray(80)
                fcntl.ioctl(fd, 0x4600, var)      # FBIOGET_VSCREENINFO
                fcntl.ioctl(fd, 0x4602, fix)      # FBIOGET_FSCREENINFO
                xres, yres = struct.unpack_from("<2I", var, 0)
                bpp = struct.unpack_from("<I", var, 24)[0]
                line = struct.unpack_from("<I", fix, 48)[0]
                smem = struct.unpack_from("<I", fix, 24)[0] or line * yres
                if xres < 64 or yres < 64 or bpp not in (16, 32):
                    os.close(fd)
                    continue
                self.fd, self.path = fd, dev
                self.w, self.h, self.bpp = xres, yres, bpp
                self.mm = mmap.mmap(fd, smem, mmap.MAP_SHARED,
                                    mmap.PROT_READ | mmap.PROT_WRITE)
                return
            except OSError:
                try:
                    os.close(fd)
                except OSError:
                    pass
        raise FramebufferError("找不到可用的帧缓冲（/dev/fb_lcd、/dev/fb0）")

    def show(self, img: Image.Image) -> None:
        if img.size != (self.w, self.h):
            img = img.resize((self.w, self.h), Image.BILINEAR)
        rgb = img.convert("RGB")
        if self.bpp == 16:
            data = pack_rgb565(rgb)
        else:
            data = rgb.convert("RGBX").tobytes()
        self.mm.seek(0)
        self.mm.write(data)

    def clear(self) -> None:
        self.mm.seek(0)
        self.mm.write(b"\x00" * (self.w * self.h * (self.bpp // 8)))

    def close(self) -> None:
        try:
            self.mm.close()
        finally:
            try:
                os.close(self.fd)
            except OSError:
                pass
