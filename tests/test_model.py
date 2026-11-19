import json
import os
import sys
import shutil
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from wz import model                                 # noqa: E402


class StoreTest(unittest.TestCase):
    def setUp(self):
        base = os.path.join(HERE, ".tmp")
        self.dir = os.path.join(base, "wz-" + uuid.uuid4().hex)
        os.makedirs(self.dir, exist_ok=True)
        self.path = os.path.join(self.dir, "state.json")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_roundtrip(self):
        store = model.Store(self.path)
        store.uin = "AAAA"
        store.set_primary("tok-main", "ilinkai.weixin.qq.com", "https",
                          "wxid_owner", "我")
        inv = store.add_account("bot-2", "tok-2", "ilinkai.weixin.qq.com",
                                "https", "wxid_friend", "好友")
        f = store.friend("wxid_a", account="main")
        f.name = "小明"
        store.incoming("wxid_a", "你好", "ctx-a", "11")
        store.outgoing("wxid_a", "在的")
        store.active = "wxid_a"
        store.friend("wxid_friend", account=inv.id)
        self.assertTrue(store.save(force=True))

        again = model.Store(self.path)
        self.assertEqual(again.primary.token, "tok-main")
        self.assertEqual(again.primary.owner, "wxid_owner")
        self.assertEqual(again.account("bot-2").token, "tok-2")
        self.assertEqual(again.active, "wxid_a")
        self.assertEqual(again.friends["wxid_a"].name, "小明")
        self.assertEqual(again.friends["wxid_a"].unread, 1)
        self.assertEqual(again.friends["wxid_a"].ctx, "ctx-a")
        self.assertEqual(again.friends["wxid_friend"].account, "bot-2")
        self.assertEqual([m.text for m in again.friends["wxid_a"].messages],
                         ["你好", "在的"])

    def test_secrets_file_mode(self):
        store = model.Store(self.path)
        store.set_primary("secret", "h", "https", "wxid_owner")
        store.dirty = True
        store.save()
        self.assertTrue(os.path.exists(self.path))
        if os.name != "nt":
            self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

    def test_multi_friend_ordering_and_unread(self):
        store = model.Store(self.path)
        store.incoming("wxid_a", "first", "c", "1", account="main")
        store.incoming("wxid_b", "second", "c", "2", viewed=True, account="main")
        order = [f.uid for f in store.sorted_friends()]
        self.assertEqual(order[0], "wxid_b")
        self.assertEqual(store.total_unread(), 1)
        store.mark_read("wxid_a")
        self.assertEqual(store.total_unread(), 0)

    def test_duplicate_filter(self):
        store = model.Store(self.path)
        self.assertFalse(store.is_duplicate("wxid_a", "42"))
        self.assertTrue(store.is_duplicate("wxid_a", "42"))
        self.assertFalse(store.is_duplicate("wxid_b", "42"))
        store.incoming("wxid_a", "hi", "c", "42", account="main")
        store.incoming("wxid_a", "hi", "c", "42", account="main")
        self.assertEqual(len(store.friends["wxid_a"].messages), 1)

    def test_context_updates_from_new_messages(self):
        store = model.Store(self.path)
        store.incoming("wxid_a", "one", "ctx-1", "1", account="main")
        store.incoming("wxid_a", "two", "ctx-2", "2", account="main")
        self.assertEqual(store.friends["wxid_a"].ctx, "ctx-2")

    def test_transcript_is_bounded(self):
        store = model.Store(self.path)
        for i in range(model.MAX_MESSAGES + 20):
            store.incoming("wxid_a", "m%d" % i, "c", str(i), account="main")
        self.assertEqual(len(store.friends["wxid_a"].messages),
                         model.MAX_MESSAGES)

    def test_short_id(self):
        self.assertEqual(model.short_id("wxid_1234567890abcdef"), "1234567890")
        self.assertEqual(model.short_id("bob"), "bob")

    def test_format_time(self):
        self.assertEqual(model.fmt_time(0), "")
        self.assertTrue(len(model.fmt_time(1_700_000_000)) >= 5)

    def test_migrates_v1_state(self):
        legacy = {
            "version": 1, "host": "ilinkai.weixin.qq.com", "scheme": "https",
            "token": "old-token", "uin": "AAAA", "active": "wxid_a",
            "cursor": "buf-9",
            "friends": [{"uid": "wxid_a", "name": "老友", "ctx": "c1",
                         "messages": []}],
        }
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(legacy, fh)
        store = model.Store(self.path)
        self.assertEqual(store.primary.token, "old-token")
        self.assertEqual(store.primary.cursor, "buf-9")
        self.assertEqual(store.friends["wxid_a"].account, "main")
        self.assertEqual(store.friends["wxid_a"].name, "老友")

    def test_drop_account_clears_context(self):
        store = model.Store(self.path)
        acc = store.add_account("bot-2", "tok", "h", "https", "wxid_f")
        f = store.friend("wxid_f", account=acc.id)
        f.ctx = "ctx"
        store.drop_account(acc.id)
        self.assertIsNone(store.account(acc.id))
        self.assertEqual(store.friends["wxid_f"].ctx, "")


if __name__ == "__main__":
    unittest.main()
