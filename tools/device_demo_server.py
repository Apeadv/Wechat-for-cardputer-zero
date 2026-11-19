#!/usr/bin/env python3
"""Device-side fake iLink server for an end-to-end hardware test.

Runs on the Cardputer Zero (stdlib only), prints its base URL, confirms the QR
automatically, then feeds two friends' messages.  Sent messages are mirrored to
/tmp/wz-sent.json for the host to inspect.
"""

import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fake_server import FakeILink  # noqa: E402

fake = FakeILink()
fake.owners = ["wxid_owner", "wxid_friend"]
fake.qr_status = "wait"
with open("/tmp/wz-base", "w", encoding="utf-8") as fh:
    fh.write(fake.base)
print("fake iLink on", fake.base, flush=True)


def confirm():
    time.sleep(5)
    fake.qr_status = "confirmed"


threading.Thread(target=confirm, daemon=True).start()


def feed():
    time.sleep(8)
    fake.push("wxid_xiaoming", "在吗？今晚一起吃饭", "ctx-xm")
    time.sleep(1.5)
    fake.push("wxid_alice", "The build passed on the device 🎉", "ctx-al")
    time.sleep(2)
    fake.push("wxid_xiaoming", "记得带上卡带机 😄", "ctx-xm2")


threading.Thread(target=feed, daemon=True).start()

while True:
    try:
        with open("/tmp/wz-sent.json", "w", encoding="utf-8") as fh:
            json.dump(fake.sent, fh, ensure_ascii=False)
    except OSError:
        pass
    time.sleep(0.4)
