import os
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from wz import model, ui                             # noqa: E402
from wz.app import App                               # noqa: E402
from wz.sim import MemoryDisplay, NullKeys           # noqa: E402


class UIFixture(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.join(HERE, ".tmp", "ui-" + str(os.getpid()))
        os.makedirs(self.dir, exist_ok=True)
        self.store = model.Store(os.path.join(self.dir, "state.json"))
        self.store.set_primary("tok", "ilinkai.weixin.qq.com", "https",
                               "wxid_owner", "我")
        self.store.uin = "AAAA"
        self.friend = self.store.friend("wxid_xiaoming", account="main")
        self.friend.name = "小明"
        self.store.incoming("wxid_xiaoming", "在吗？晚上一起吃饭 😄", "ctx", "1")
        self.store.outgoing("wxid_xiaoming", "好啊，七点见")
        self.store.active = "wxid_xiaoming"
        self.app = App(self.store, ui.UI(), MemoryDisplay(), NullKeys())
        self.app.ime = None

    def tearDown(self):
        self.app.stop()


class RenderTest(UIFixture):
    def test_screens_render(self):
        shots = {}
        self.app.screen = "login"
        self.app.qr_url = "https://weixin.qq.com/x/abc"
        self.app.login_state = "wait"
        shots["login"] = self.app.draw()

        self.app.screen = "friends"
        shots["friends"] = self.app.draw()

        self.app.screen = "chat"
        self.app.input = "hello"
        shots["chat"] = self.app.draw()

        self.app.screen = "invite"
        self.app.invite_url = "https://weixin.qq.com/x/invite"
        self.app.invite_state = "wait"
        shots["invite"] = self.app.draw()

        self.app.screen = "help"
        shots["help"] = self.app.draw()

        for name, img in shots.items():
            self.assertEqual(img.size, (ui.W, ui.H), name)
            self.assertEqual(img.mode, "RGB", name)

    def test_qr_has_dark_modules_on_white(self):
        self.app.screen = "login"
        self.app.qr_url = "https://weixin.qq.com/x/abc"
        img = self.app.draw()
        # QR box is drawn on a white card at (6,18)-(136,148)
        dark = 0
        for x in range(10, 130, 2):
            for y in range(24, 140, 2):
                r, g, b = img.getpixel((x, y))
                if r < 60 and g < 60 and b < 60:
                    dark += 1
        self.assertGreater(dark, 60)
        r, g, b = img.getpixel((6, 18))
        self.assertGreater(r, 200)

    def test_emoji_is_sanitised(self):
        self.assertEqual(ui.clean("hi 😄👍"), "hi [表情]")
        self.assertEqual(ui.clean("纯中文"), "纯中文")

    def test_clip(self):
        from PIL import Image, ImageDraw
        d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        f = ui.UI().font(12)
        out = ui.clip(d, "这是一段很长的中文文本", f, 30)
        self.assertLessEqual(d.textlength(out, font=f), 40)
        self.assertTrue(out.endswith("…"))

    def test_rgb565_packing(self):
        from PIL import Image
        from wz.fb import pack_rgb565
        img = Image.new("RGB", (2, 1))
        img.putpixel((0, 0), (255, 0, 0))
        img.putpixel((1, 0), (0, 255, 0))
        self.assertEqual(pack_rgb565(img), bytes([0x00, 0xF8, 0xE0, 0x07]))

    def test_friend_rows_show_unread(self):
        self.store.friend("wxid_bob", account="main")
        self.store.friend("wxid_bob").name = "Bob"
        self.store.incoming("wxid_bob", "yo", "c", "2")
        self.app.screen = "friends"
        img = self.app.draw()
        # unread badge is red-ish somewhere on the right side
        red = sum(1 for x in range(270, 316) for y in range(18, 90)
                  if img.getpixel((x, y))[0] > 180 and img.getpixel((x, y))[1] < 120)
        self.assertGreater(red, 20)


if __name__ == "__main__":
    unittest.main()
