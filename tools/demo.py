#!/usr/bin/env python3
"""Record a demo GIF of the real app against the fake iLink server.

    python3 tools/demo.py            # writes preview/demo.gif + frames
"""

from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PIL import Image                                    # noqa: E402

from tests.fake_server import FakeILink                  # noqa: E402
from wz import keys, model, ui                           # noqa: E402
from wz.app import App                                   # noqa: E402
from wz.ime import load as load_ime                      # noqa: E402
from wz.sim import MemoryDisplay, NullKeys               # noqa: E402

CHAR_CODES = {v: k for k, v in keys.CHARS.items()}
SHIFT_CODES = {v: k for k, v in keys.SHIFTED.items()}


def type_ascii(app, text):
    for ch in text:
        if ch in CHAR_CODES:
            app.handle_key(CHAR_CODES[ch], 1)
        elif ch in SHIFT_CODES:
            app.handle_key(keys.KEY_LEFTSHIFT, 1)
            app.handle_key(SHIFT_CODES[ch], 1)
            app.handle_key(keys.KEY_LEFTSHIFT, 0)


def main() -> int:
    fake = FakeILink()
    tmp = os.path.join(ROOT, "tests", ".tmp", "demo")
    os.makedirs(tmp, exist_ok=True)
    state_path = os.path.join(tmp, "state.json")
    if os.path.exists(state_path):
        os.unlink(state_path)          # every recording starts logged out
    store = model.Store(state_path)
    app = App(store, ui.UI(), MemoryDisplay(), NullKeys(),
              ime=load_ime(os.path.join(ROOT, "assets", "ime.db")),
              host=fake.base)
    frames, paths = [], []

    def shot(name, hold=1.4):
        app.tick()
        img = app.draw()
        for _ in range(int(hold / 0.25)):
            frames.append(img.copy())
        out = os.path.join(ROOT, "preview", name + ".png")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        img.save(out)
        paths.append(out)

    def wait(cond, timeout=10.0):
        end = time.time() + timeout
        while time.time() < end:
            app.tick()
            if cond():
                return True
            time.sleep(0.02)
        return False

    try:
        app.tick()
        wait(lambda: bool(app.qr_url), 6)
        shot("demo-login", 2.2)

        fake.qr_status = "confirmed"
        wait(lambda: app.logged_in, 10)
        shot("demo-friends-empty", 1.2)

        fake.push("wxid_xiaoming", "在吗？今晚一起吃饭", "ctx-xm")
        time.sleep(0.05)
        fake.push("wxid_alice", "The build passed on the device 🎉", "ctx-al")
        wait(lambda: len(store.friends) >= 2, 8)
        store.friends["wxid_xiaoming"].name = "小明"
        store.friends["wxid_alice"].name = "Alice"
        shot("demo-friends", 2.2)

        app.sel_uid = "wxid_xiaoming"
        app.key_friends(keys.KEY_ENTER)
        shot("demo-chat", 1.6)

        type_ascii(app, "jintiantianqi")
        app.handle_key(keys.KEY_TAB, 1)
        shot("demo-ime", 2.0)

        app.key_chat(keys.KEY_ENTER)
        wait(lambda: bool(fake.sent), 6)
        shot("demo-sent", 2.0)

        app.key_chat(keys.KEY_ESC)
        app.key_friends(keys.KEY_F2)
        wait(lambda: bool(app.invite_url), 6)
        shot("demo-invite", 2.2)
    finally:
        app.stop()
        fake.close()

    os.makedirs(os.path.join(ROOT, "preview"), exist_ok=True)
    gif = os.path.join(ROOT, "preview", "demo.gif")
    pal = [f.convert("P", palette=Image.ADAPTIVE, colors=64) for f in frames]
    pal[0].save(gif, save_all=True, append_images=pal[1:], duration=250, loop=0,
                optimize=True)
    print("frames：%d   GIF：%s（%.1f KB）" % (len(frames), gif,
                                             os.path.getsize(gif) / 1024.0))
    for p in paths:
        print("  " + p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
