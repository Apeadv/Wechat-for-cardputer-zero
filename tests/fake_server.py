"""A local stand-in for WeChat's iLink bot endpoints.

Supports several bot accounts (one per QR) so the invite flow can be tested:
each ``get_bot_qrcode`` call creates a bot whose owner comes from
``self.owners`` (or defaults to the first login owner).
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeILink:
    def __init__(self):
        self.qr_status = "wait"
        self.base_url = ""
        self.messages = []
        self.sent = []
        self.requests = []
        self.owners = ["wxid_owner"]
        self.bots = {}               # token -> {"bot_id","owner"}
        self.qr = {}                 # qr code -> {"token","bot_id","owner"}
        self.current_qr = ""
        self.lock = threading.Lock()
        self.next_mid = 100
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.base_url = "http://127.0.0.1:%d" % self.port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    # ---------------------------------------------------------------- helpers
    @property
    def base(self) -> str:
        return self.base_url

    def push(self, uid: str, text: str, ctx: str = "ctx-1", mid: str | None = None):
        with self.lock:
            self.next_mid += 1
            self.messages.append({
                "message_type": 1,
                "from_user_id": uid,
                "context_token": ctx,
                "message_id": int(mid) if mid else self.next_mid,
                "item_list": [{"type": 1, "text_item": {"text": text}}],
            })
            return self.next_mid

    def take(self):
        with self.lock:
            out, self.messages = self.messages, []
            return out

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def _new_bot(self):
        n = len(self.bots) + 1
        owner = self.owners.pop(0) if self.owners else "wxid_owner"
        bot_id = "bot-%d" % (len(self.bots) + 1)
        token = "tok-%d" % (len(self.bots) + 1)
        self.bots[token] = {"bot_id": bot_id, "owner": owner}
        code = "qr-%d" % (len(self.qr) + 1)
        self.qr[code] = {"token": token, "bot_id": bot_id, "owner": owner}
        self.current_qr = code
        return code

    # ---------------------------------------------------------------- handler
    def _handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *args):
                pass

            def _send(self, obj, status=200):
                raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                fake.requests.append(("GET", self.path, dict(self.headers), b""))
                if self.path.startswith("/ilink/bot/get_bot_qrcode"):
                    code = fake._new_bot()
                    self._send({"qrcode": code,
                                "qrcode_img_content": "https://weixin.qq.com/x/" + code,
                                "ret": 0})
                elif self.path.startswith("/ilink/bot/get_qrcode_status"):
                    code = self.path.split("qrcode=", 1)[-1].split("&", 1)[0]
                    info = fake.qr.get(code)
                    if not info:
                        self._send({"status": "expired", "ret": 0})
                        return
                    if fake.qr_status == "confirmed":
                        fake.current_qr = code
                        self._send({"status": "confirmed",
                                    "bot_token": info["token"],
                                    "ilink_bot_id": info["bot_id"],
                                    "ilink_user_id": info["owner"],
                                    "baseurl": fake.base_url,
                                    "ret": 0})
                    elif fake.qr_status == "expired":
                        self._send({"status": "expired", "ret": 0})
                    else:
                        self._send({"status": "wait", "ret": 0})
                else:
                    self._send({"ret": -1, "errmsg": "not found"}, 404)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                fake.requests.append(("POST", self.path, dict(self.headers), body))
                auth = self.headers.get("Authorization", "")
                token = auth[7:] if auth.startswith("Bearer ") else ""
                if token not in fake.bots:
                    self._send({"ret": -2, "errmsg": "unauthorized"}, 401)
                    return
                if self.path.startswith("/ilink/bot/getupdates"):
                    try:
                        payload = json.loads(body or b"{}")
                    except ValueError:
                        payload = {}
                    assert "get_updates_buf" in payload, payload
                    self._send({"ret": 0, "errcode": 0,
                                "get_updates_buf": "buf-%d" % int(time.time() * 1000),
                                "msgs": fake.take()})
                elif self.path.startswith("/ilink/bot/sendmessage"):
                    try:
                        payload = json.loads(body or b"{}")
                    except ValueError:
                        payload = {}
                    msg = payload.get("msg") or {}
                    fake.sent.append(payload)
                    if not msg.get("to_user_id"):
                        self._send({"ret": -3, "errmsg": "no target"})
                    else:
                        self._send({"ret": 0})
                else:
                    self._send({"ret": -1, "errmsg": "not found"}, 404)

        return Handler
