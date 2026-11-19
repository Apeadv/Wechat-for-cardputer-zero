import os
import sys
import time
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from wz import keys, model, ui                       # noqa: E402
from wz.app import App                               # noqa: E402
from wz.ime import load as load_ime                  # noqa: E402
from wz.sim import MemoryDisplay, NullKeys           # noqa: E402
from tests.fake_server import FakeILink              # noqa: E402

CHAR_CODES = {v: k for k, v in keys.CHARS.items()}
SHIFT_CODES = {v: k for k, v in keys.SHIFTED.items()}


def type_ascii(app, text):
    for ch in text:
        code = CHAR_CODES.get(ch)
        if code is not None:
            app.handle_key(code, 1)
            continue
        code = SHIFT_CODES.get(ch)
        if code is not None:
            app.handle_key(keys.KEY_LEFTSHIFT, 1)
            app.handle_key(code, 1)
            app.handle_key(keys.KEY_LEFTSHIFT, 0)


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeILink()
        base = os.path.join(HERE, ".tmp")
        self.dir = os.path.join(base, "flow-" + uuid.uuid4().hex)
        os.makedirs(self.dir, exist_ok=True)
        self.state_path = os.path.join(self.dir, "state.json")
        self.store = model.Store(self.state_path)
        self.display = MemoryDisplay()
        self.app = App(self.store, ui.UI(), self.display, NullKeys(),
                       ime=load_ime(os.path.join(ROOT, "assets", "ime.db")),
                       host=self.fake.base)
        self.app.tick()

    def tearDown(self):
        self.app.stop()
        self.fake.close()

    def wait(self, cond, timeout=10.0, app=None):
        target = app or self.app
        end = time.time() + timeout
        while time.time() < end:
            target.tick()
            if cond():
                return True
            time.sleep(0.02)
        return False

    def login(self):
        self.assertTrue(self.wait(lambda: bool(self.app.qr_url), 6),
                        "QR never arrived: %s" % self.app.login_note)
        self.fake.qr_status = "confirmed"
        self.assertTrue(self.wait(lambda: self.app.logged_in, 10),
                        "login never completed")
        self.assertEqual(self.app.screen, "friends")
        self.assertEqual(self.store.primary.token, "tok-1")
        self.assertEqual(self.store.primary.owner, "wxid_owner")

    def invite_friend(self, owner="wxid_friend"):
        self.fake.owners.append(owner)
        before = len(self.store.accounts)
        self.app.key_friends(keys.KEY_F2)
        self.assertEqual(self.app.screen, "invite")
        self.assertTrue(self.wait(lambda: bool(self.app.invite_url), 8))
        self.assertTrue(self.wait(
            lambda: len(self.store.accounts) == before + 1 and self.app.screen == "chat",
            12), "invite never completed: %s" % self.app.invite_note)
        friend = self.store.friends[owner]
        acc = self.store.account(friend.account)
        self.assertIsNotNone(acc)
        self.assertEqual(acc.owner, owner)
        return friend, acc

    # ------------------------------------------------------------------
    def test_login_then_receive_and_reply(self):
        self.login()
        self.fake.push("wxid_bob", "你好呀")
        self.assertTrue(self.wait(lambda: "wxid_bob" in self.store.friends, 8))
        bob = self.store.friends["wxid_bob"]
        self.assertEqual(bob.unread, 1)
        self.assertEqual(bob.ctx, "ctx-1")
        self.assertEqual(bob.account, "main")

        self.app.sel_uid = "wxid_bob"
        self.app.key_friends(keys.KEY_ENTER)
        self.assertEqual(self.app.screen, "chat")
        self.assertEqual(bob.unread, 0)

        type_ascii(self.app, "jintiantianqi")
        time.sleep(0.9)
        self.app.tick()
        self.assertEqual(self.app.input, "jintiantianqi",
                         "idle typing must not auto-convert")
        self.app.handle_key(keys.KEY_TAB, 1)
        self.assertIn("今天", self.app.input, "IME did not convert: %r" % self.app.input)

        text = self.app.input
        self.app.key_chat(keys.KEY_ENTER)
        self.assertTrue(self.wait(lambda: bool(self.fake.sent), 8))
        msg = self.fake.sent[-1]["msg"]
        self.assertEqual(msg["to_user_id"], "wxid_bob")
        self.assertEqual(msg["context_token"], "ctx-1")
        self.assertEqual(msg["item_list"][0]["text_item"]["text"], text)
        self.assertEqual(self.app.input, "")

    def test_invite_then_proactive_message(self):
        self.login()
        friend, acc = self.invite_friend()
        self.assertTrue(acc.id.startswith("bot-"))
        self.assertEqual(self.store.primary.token, "tok-1")
        self.assertEqual(acc.token, "tok-2")
        self.assertEqual(self.app.channel_text(friend), "专属通道")

        self.app.input = "扫码后第一条"
        self.app.key_chat(keys.KEY_ENTER)
        self.assertTrue(self.wait(lambda: bool(self.fake.sent), 8))
        msg = self.fake.sent[-1]["msg"]
        self.assertEqual(msg["to_user_id"], "wxid_friend")
        self.assertNotIn("context_token", msg)
        self.assertEqual(msg["item_list"][0]["text_item"]["text"], "扫码后第一条")
        self.assertIn("Bearer tok-2", self.fake.requests[-1][2]["Authorization"])

        # once the friend writes, the context token is used for follow-ups
        self.fake.push("wxid_friend", "收到", "ctx-friend")
        self.assertTrue(self.wait(lambda: friend.ctx == "ctx-friend", 8))
        self.app.input = "第二条"
        self.app.key_chat(keys.KEY_ENTER)
        self.assertTrue(self.wait(lambda: len(self.fake.sent) >= 2, 8))
        self.assertEqual(self.fake.sent[-1]["msg"]["context_token"], "ctx-friend")

    def test_multiple_friends_unread_and_order(self):
        self.login()
        self.fake.push("wxid_bob", "第一条")
        self.assertTrue(self.wait(lambda: "wxid_bob" in self.store.friends, 8))
        time.sleep(0.05)
        self.fake.push("wxid_carol", "来自 carol")
        self.assertTrue(self.wait(lambda: "wxid_carol" in self.store.friends, 8))
        order = [f.uid for f in self.store.sorted_friends()]
        self.assertEqual(order[0], "wxid_carol")
        self.assertEqual(self.store.friends["wxid_carol"].unread, 1)
        self.assertEqual(self.store.total_unread(), 2)

        self.app.key_friends(keys.KEY_UP)
        self.app.key_friends(keys.KEY_DOWN)
        self.app.sel_uid = "wxid_carol"
        self.app.key_friends(keys.KEY_ENTER)
        self.assertEqual(self.store.active, "wxid_carol")
        self.assertEqual(self.store.friends["wxid_carol"].unread, 0)
        self.app.key_chat(keys.KEY_ESC)
        self.assertEqual(self.app.screen, "friends")
        self.assertEqual(self.store.total_unread(), 1)

    def test_invited_friend_can_be_renamed(self):
        self.login()
        friend, _ = self.invite_friend()
        self.app.key_chat(keys.KEY_F3)
        self.assertEqual(self.app.screen, "rename")
        self.app.input = ""
        type_ascii(self.app, "xiaoming")
        time.sleep(0.9)
        self.app.tick()
        self.assertEqual(self.app.input, "xiaoming")
        self.app.handle_key(keys.KEY_TAB, 1)
        converted = self.app.input
        self.assertTrue(any("\u4e00" <= c <= "\u9fff" for c in converted),
                        "pinyin was not converted: %r" % converted)
        self.app.key_rename(keys.KEY_ENTER)
        self.assertEqual(self.store.friends[friend.uid].name, converted)

    def test_rename_keeps_the_chat_draft(self):
        self.login()
        self.fake.push("wxid_bob", "hi")
        self.assertTrue(self.wait(lambda: "wxid_bob" in self.store.friends, 8))
        self.app.open_chat("wxid_bob")
        self.app.input = "还没发出去的话"
        self.app.key_chat(keys.KEY_F3)
        self.assertEqual(self.app.screen, "rename")
        self.app.key_rename(keys.KEY_ESC)
        self.assertEqual(self.app.screen, "chat")
        self.assertEqual(self.app.input, "还没发出去的话")

    def test_auth_loss_returns_to_login(self):
        self.login()
        del self.fake.bots["tok-1"]
        self.assertTrue(self.wait(lambda: self.app.screen == "login", 10),
                        "auth loss was not detected")
        self.assertEqual(self.store.primary.token, "")
        self.assertTrue(self.wait(lambda: bool(self.app.qr_url), 8))

    def test_invite_auth_loss_keeps_friend(self):
        self.login()
        friend, acc = self.invite_friend()
        del self.fake.bots[acc.token]
        self.assertTrue(self.wait(lambda: acc.token == "", 10))
        self.assertEqual(self.store.friends[friend.uid].ctx, "")
        self.assertEqual(self.app.screen, "chat")

    def test_manual_relogin(self):
        self.login()
        self.app.key_friends(keys.KEY_F5)
        self.assertEqual(self.app.screen, "confirm_logout")
        self.app.key_logout(keys.KEY_ENTER)
        self.assertEqual(self.store.primary.token, "")
        self.assertEqual(self.app.screen, "login")
        self.assertTrue(self.wait(lambda: bool(self.app.qr_url), 8))

    def test_restart_with_saved_token_keeps_receiving(self):
        self.login()
        self.app.stop()
        store = model.Store(self.state_path)
        self.assertEqual(store.primary.token, "tok-1")
        app2 = App(store, ui.UI(), MemoryDisplay(), NullKeys(),
                   ime=load_ime(os.path.join(ROOT, "assets", "ime.db")),
                   host=self.fake.base)
        try:
            self.assertTrue(self.wait(lambda: app2.net_ok.get("main") is True, 10, app2))
            self.fake.push("wxid_zoe", "after restart")
            self.assertTrue(self.wait(lambda: "wxid_zoe" in store.friends, 8, app2))
        finally:
            app2.stop()


if __name__ == "__main__":
    unittest.main()
