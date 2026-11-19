#!/usr/bin/env python3
"""wechat-zero: WeChat iLink client for the M5Stack Cardputer Zero.

Runs on the device (Debian aarch64, 320x170 framebuffer, evdev keyboard) and on
a laptop for development (--selftest / --preview).

    python3 wechat.py                 # normal app
    python3 wechat.py --selftest      # check framebuffer, keyboard, font, IME
    python3 wechat.py --preview DIR   # render every screen to PNG and exit
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from wz import app as app_mod          # noqa: E402
from wz import ilink, keys as keys_mod, model, sim  # noqa: E402
from wz.ime import load as load_ime    # noqa: E402
from wz.ui import UI                   # noqa: E402

VERSION = "1.1.0"
DEFAULT_STATE = os.path.join(os.path.expanduser("~"), ".config", "wechat-zero", "state.json")
LOG_PATH = os.path.join(os.path.dirname(DEFAULT_STATE), "error.log")


def log_error(text: str) -> None:
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write("\n=== %s ===\n%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text))
    except OSError:
        pass


def default_ime_path() -> str:
    for path in ("/opt/wechat-zero/ime.db",
                 os.path.join(HERE, "assets", "ime.db")):
        if os.path.exists(path):
            return path
    return ""


def make_store(path: str) -> model.Store:
    return model.Store(path)


def make_ui() -> UI:
    return UI()


def selftest(state_path: str) -> int:
    print("wechat-zero %s" % VERSION)
    ok = True

    try:
        from wz.fb import Framebuffer
        fb = Framebuffer()
        print("framebuffer : %s %dx%d %dbpp" % (fb.path, fb.w, fb.h, fb.bpp))
        fb.close()
    except Exception as exc:
        ok = False
        print("framebuffer : 不可用（%s）" % exc)

    kbd = keys_mod.Keys()
    if kbd.available:
        print("keyboard    : %d 个输入设备" % len(kbd.devices))
    else:
        ok = False
        print("keyboard    : 未找到（需要 python3-evdev 或 /dev/input 权限）")

    ui = UI()
    if not ui.font_path:
        ok = False
        print("font        : 没找到中文字体（apt install fonts-wqy-zenhei）")
    else:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (120, 24), (0, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((2, 2), "中文测试", font=ui.font(12), fill=(255, 255, 255))
        print("font        : %s" % ui.font_path)

    ime_path = default_ime_path()
    ime = load_ime(ime_path) if ime_path else None
    if ime is None:
        ok = False
        print("ime         : 没找到 ime.db")
    else:
        sample = ime.candidates("jintiantianqi", 3)
        print("ime         : %s -> %s" % (ime_path, " / ".join(sample)))

    store = make_store(state_path)
    print("state       : %s（%d 位好友，%d 个通道，%s）" % (
        state_path, len(store.friends), len(store.accounts),
        "已登录" if store.primary and store.primary.token else "未登录"))
    print("qr encoder  : ok" if _qr_ok() else "qr encoder  : 失败")
    print("结果        : %s" % ("OK" if ok else "有问题，见上面"))
    return 0 if ok else 1


def _qr_ok() -> bool:
    try:
        from vendor import qrcodegen
        code = qrcodegen.QrCode.encode_text("https://weixin.qq.com/x/test", qrcodegen.QrCode.Ecc.LOW)
        return code.get_size() >= 21
    except Exception:
        return False


def preview(out_dir: str, state_path: str) -> int:
    """Render the main screens with sample data; no device needed."""
    from wz.sim import MemoryDisplay, NullKeys
    from wz.ime import LocalIME

    store = model.Store(state_path)
    store.set_primary("demo-token", "ilinkai.weixin.qq.com", "https",
                      "wxid_owner", "我")
    store.uin = "AAAAAAAA"
    for uid, name, msgs in (
        ("wxid_xiaoming", "小明", [("them", "在吗？晚上一起吃饭"), ("me", "好啊，几点？"),
                                  ("them", "七点，老地方见。记得带上卡带机 😄")]),
        ("wxid_25432718", "产品群小助手", [("them", "周报我已经发到群里了，麻烦看下"),
                                          ("me", "收到，我晚点回复你")]),
        ("wxid_alice", "Alice", [("them", "The build passed on the device 🎉")]),
    ):
        f = store.friend(uid, account="main")
        f.name = name
        f.last_ts = 0
        for i, (who, text) in enumerate(msgs):
            import time
            f.add(model.Message(who, text, time.time() - 60 * (len(msgs) - i)))
        f.ctx = "ctx-" + uid
    store.friend("wxid_alice").unread = 2
    store.friend("wxid_alice").ctx = ""
    store.active = "wxid_xiaoming"

    display = MemoryDisplay()
    keys = sim.NullKeys()
    ime_path = default_ime_path()
    ime = LocalIME(ime_path) if ime_path else None
    a = app_mod.App(store, UI(), display, keys, ime=ime)
    a.screen = "login"
    a.qr_url = "https://weixin.qq.com/x/demo-qr-payload-123456"
    a.login_state = "wait"
    shots = {}

    def save(name, img):
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, name + ".png")
        img.save(path)
        shots[name] = path

    save("login", a.draw())
    a.screen = "friends"
    save("friends", a.draw())
    a.screen, a.store.active = "chat", "wxid_xiaoming"
    save("chat", a.draw())
    a.input = "jintiantianqi"
    a.convert(force=True)
    save("chat-ime", a.draw())
    a.screen = "invite"
    a.invite_url = "https://weixin.qq.com/x/demo-invite-qr"
    a.invite_state = "wait"
    save("invite", a.draw())
    a.screen = "help"
    save("help", a.draw())
    for name, path in shots.items():
        print("%-10s %s" % (name, path))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="WeChat iLink client for Cardputer Zero")
    parser.add_argument("--state", default=os.environ.get("WECHAT_ZERO_STATE", DEFAULT_STATE))
    parser.add_argument("--ime", default="", help="path to ime.db")
    parser.add_argument("--font", default="", help="override CJK font path")
    parser.add_argument("--keyboard", default="", help="explicit evdev device")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--preview", default="", metavar="DIR")
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args(argv)

    if args.version:
        print(VERSION)
        return 0
    if args.selftest:
        return selftest(args.state)
    if args.preview:
        return preview(args.preview, args.state)

    os.environ.setdefault("LANG", "C.UTF-8")
    ui = UI()
    if args.font:
        ui.font_path = args.font
    store = make_store(args.state)
    ime_path = args.ime or default_ime_path()
    ime = load_ime(ime_path) if ime_path else None

    try:
        from wz.fb import Framebuffer
        display = Framebuffer()
    except Exception as exc:
        log_error("framebuffer: %s" % exc)
        print("无法打开帧缓冲：%s" % exc, file=sys.stderr)
        return 1

    try:
        a = app_mod.App(store, ui, display, keys_mod.Keys(args.keyboard),
                        ime=ime)
    except Exception:
        log_error(traceback.format_exc())
        print("wechat-zero 初始化失败，详见 %s" % LOG_PATH, file=sys.stderr)
        return 1
    try:
        return a.run()
    except Exception:
        log_error(traceback.format_exc())
        print("wechat-zero crashed; see %s" % LOG_PATH, file=sys.stderr)
        return 1
    finally:
        try:
            display.clear()
            display.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
