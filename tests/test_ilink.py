import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from wz import ilink                                  # noqa: E402
from tests.fake_server import FakeILink               # noqa: E402


class SplitTextTest(unittest.TestCase):
    def test_ascii_and_cjk(self):
        text = "你好" * 1200
        chunks = ilink.split_text(text)
        self.assertGreater(len(chunks), 1)
        self.assertEqual("".join(chunks), text)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), ilink.MAX_CHUNK_CHARS)
            self.assertLessEqual(len(chunk.encode("utf-8")), ilink.MAX_CHUNK_BYTES)

    def test_empty(self):
        self.assertEqual(ilink.split_text(""), [])


class ParseTest(unittest.TestCase):
    def test_prefix_and_unicode(self):
        obj = ilink.parse_json('noise {"ret":0,"text":"中文"}')
        self.assertEqual(obj["text"], "中文")

    def test_extract_messages(self):
        payload = {"msgs": [
            {"message_type": 1, "from_user_id": "wxid_a", "context_token": "c1",
             "message_id": 7, "item_list": [
                 {"type": 1, "text_item": {"text": "第一行"}},
                 {"type": 2},
                 {"type": 1, "text_item": {"text": "第二行"}}]},
            {"message_type": 2, "from_user_id": "wxid_b"},
            {"message_type": 1, "from_user_id": ""},
        ]}
        msgs = ilink.extract_messages(payload)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["text"], "第一行\n第二行")
        self.assertEqual(msgs[0]["uid"], "wxid_a")
        self.assertEqual(msgs[0]["ctx"], "c1")


class ClientTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeILink()
        self.client = ilink.ILinkClient(self.fake.base)

    def tearDown(self):
        self.fake.close()

    def test_host_parsing(self):
        self.assertEqual(self.client.scheme, "http")
        self.assertEqual(self.client.host, "127.0.0.1:%d" % self.fake.port)

    def test_login_flow(self):
        qr = self.client.start_login()
        self.assertTrue(qr["url"].startswith("https://weixin.qq.com/x/"))
        self.assertEqual(qr["code"], "qr-1")

        self.assertEqual(self.client.poll_login(qr["code"])["status"], "wait")
        self.fake.qr_status = "confirmed"
        res = self.client.poll_login(qr["code"])
        self.assertEqual(res["status"], "confirmed")
        self.assertEqual(res["token"], "tok-1")
        self.assertEqual(res["bot_id"], "bot-1")
        self.assertEqual(res["owner"], "wxid_owner")
        self.assertEqual(res["host"], "127.0.0.1:%d" % self.fake.port)
        self.assertEqual(res["scheme"], "http")

    def test_send_payload_and_headers(self):
        self.fake._new_bot()
        self.client.token = "tok-1"
        self.client.send_text("wxid_bob", "你好，世界", "ctx-9")
        self.assertEqual(len(self.fake.sent), 1)
        msg = self.fake.sent[0]["msg"]
        self.assertEqual(msg["to_user_id"], "wxid_bob")
        self.assertEqual(msg["context_token"], "ctx-9")
        self.assertEqual(msg["message_type"], 2)
        self.assertEqual(msg["item_list"][0]["text_item"]["text"], "你好，世界")
        self.assertTrue(msg["client_id"].startswith("aos-"))
        sent_headers = self.fake.requests[-1][2]
        headers = {k.lower(): v for k, v in sent_headers.items()}
        self.assertEqual(headers["authorization"], "Bearer tok-1")
        self.assertEqual(headers["authorizationtype"], "ilink_bot_token")
        self.assertTrue(headers["x-wechat-uin"])
        self.assertIn("AuthorizationType", sent_headers)
        self.assertIn("X-WECHAT-UIN", sent_headers)

    def test_proactive_send_without_context(self):
        self.fake._new_bot()
        self.client.token = "tok-1"
        self.client.send_text("wxid_owner", "主动问候", "")
        self.assertNotIn("context_token", self.fake.sent[0]["msg"])

    def test_long_message_chunks(self):
        self.fake._new_bot()
        self.client.token = "tok-1"
        text = "长" * 1500
        self.client.send_text("wxid_bob", text, "ctx")
        self.assertGreater(len(self.fake.sent), 1)
        joined = "".join(p["msg"]["item_list"][0]["text_item"]["text"]
                         for p in self.fake.sent)
        self.assertEqual(joined, text)

    def test_updates(self):
        self.fake._new_bot()
        self.client.token = "tok-1"
        self.fake.push("wxid_a", "hello")
        data = self.client.get_updates("")
        msgs = ilink.extract_messages(data)
        self.assertEqual(msgs[0]["text"], "hello")
        headers = {k.lower(): v for k, v in self.fake.requests[-1][2].items()}
        self.assertEqual(headers["authorization"], "Bearer tok-1")
        self.assertEqual(self.fake.requests[-1][3][:1], b"{")


if __name__ == "__main__":
    unittest.main()
