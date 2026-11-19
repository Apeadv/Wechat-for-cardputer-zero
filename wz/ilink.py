"""WeChat iLink protocol client.

Reverse engineered from gywan94/cardputer-wechat (TheProject/src/Classes/WeChatILink.cpp,
which in turn follows M5Claw's wechat_bot).  The endpoints are the official
"iLink bot" endpoints used by WeChat's own bot channel:

    GET  /ilink/bot/get_bot_qrcode?bot_type=3     -> qrcode + qrcode_img_content
    GET  /ilink/bot/get_qrcode_status?qrcode=...  -> wait / confirmed / expired
    POST /ilink/bot/getupdates                    -> long poll for messages
    POST /ilink/bot/sendmessage                   -> send text to one user

Auth is a bearer bot token obtained after the QR scan; every request also
carries X-WECHAT-UIN (base64 of 4 random bytes, fixed per install).
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import ssl
import urllib.parse
from typing import Any, Callable, Optional

DEFAULT_HOST = "ilinkai.weixin.qq.com"
CHANNEL_VERSION = "1.0.2"
BOT_AGENT = "wechat-zero/1.1.0"
# iLink-App-ClientVersion is a uint32: major<<16 | minor<<8 | patch
CLIENT_VERSION = (1 << 16) | (0 << 8) | 2
MAX_CHUNK_CHARS = 1000
MAX_CHUNK_BYTES = 2000

QR_PATH = "/ilink/bot/get_bot_qrcode?bot_type=3"
QR_STATUS_PATH = "/ilink/bot/get_qrcode_status?qrcode="
UPDATES_PATH = "/ilink/bot/getupdates"
SEND_PATH = "/ilink/bot/sendmessage"


class ILinkError(Exception):
    """Network or protocol level failure."""


Transport = Callable[[str, str, dict, Optional[bytes], float], tuple]


def http_request(method: str, url: str, headers: dict, body: Optional[bytes],
                 timeout: float) -> tuple:
    """Minimal HTTPS transport.

    http.client (instead of urllib) is used because urllib rewrites header names
    to Titlecase -- iLink's gateway is known to be picky about
    "AuthorizationType" / "X-WECHAT-UIN" spelling, and we want to keep the exact
    names the upstream firmware sends.  Certificate validation is disabled on
    purpose: the upstream client does the same and the device's CA store is old.
    """
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https":
        conn = http.client.HTTPSConnection(
            parts.hostname, parts.port or 443, timeout=timeout,
            context=ssl._create_unverified_context())
    else:
        conn = http.client.HTTPConnection(parts.hostname, parts.port or 80,
                                          timeout=timeout)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    try:
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        return resp.status, resp.read()
    except (OSError, http.client.HTTPException) as exc:
        raise ILinkError(str(exc)) from exc
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _json_start(text: str) -> int:
    """iLink answers sometimes carry a short text prefix before the JSON."""
    return text.find("{")


def parse_json(text: str) -> dict:
    idx = _json_start(text)
    if idx < 0:
        raise ILinkError("响应不是 JSON")
    try:
        obj = json.loads(text[idx:])
    except ValueError as exc:
        raise ILinkError("JSON 解析失败") from exc
    if not isinstance(obj, dict):
        raise ILinkError("响应格式不对")
    return obj


def new_uin() -> str:
    """Official format: base64 of the decimal string of a random uint32."""
    value = int.from_bytes(os.urandom(4), "big")
    return base64.b64encode(str(value).encode("ascii")).decode("ascii")


def split_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list:
    """Split a message into UTF-8 safe chunks (by characters, not bytes)."""
    if not text:
        return []
    chunks, cur, size = [], [], 0
    for ch in text:
        n = len(ch.encode("utf-8"))
        if cur and (len(cur) >= max_chars or size + n > MAX_CHUNK_BYTES):
            chunks.append("".join(cur))
            cur, size = [], 0
        cur.append(ch)
        size += n
    if cur:
        chunks.append("".join(cur))
    return chunks


def split_host(value: str) -> tuple:
    """Return (scheme, host) and accept values with or without a scheme."""
    value = (value or "").strip()
    scheme = ""
    if value.startswith("http://"):
        scheme, value = "http", value[7:]
    elif value.startswith("https://"):
        scheme, value = "https", value[8:]
    value = value.split("/", 1)[0]          # baseurl may carry a path; API is root-relative
    return scheme, value.rstrip("/")


def normalize_host(host: str) -> str:
    return split_host(host)[1]


class ILinkClient:
    def __init__(self, host: str = "", token: str = "", uin: str = "",
                 transport: Transport = http_request, scheme: str = "https"):
        auto_scheme, host = split_host(host or DEFAULT_HOST)
        self.host = host or DEFAULT_HOST
        self.token = token or ""
        self.uin = uin or new_uin()
        self.transport = transport
        self.scheme = auto_scheme or (scheme if scheme in ("http", "https") else "https")
        self.last_error = ""

    # ---------------- plumbing
    def base_url(self) -> str:
        return f"{self.scheme}://{self.host}"

    def _headers(self, auth: bool, json_body: bool) -> dict:
        headers = {
            "Accept": "application/json",
            "iLink-App-ClientVersion": str(CLIENT_VERSION),
            "User-Agent": BOT_AGENT,
        }
        if json_body:
            headers["Content-Type"] = "application/json; charset=utf-8"
        if auth and self.token:
            headers["AuthorizationType"] = "ilink_bot_token"
            headers["Authorization"] = "Bearer " + self.token
            headers["X-WECHAT-UIN"] = self.uin
        return headers

    def base_info(self) -> dict:
        return {"channel_version": CHANNEL_VERSION, "bot_agent": BOT_AGENT}

    def _request(self, method: str, path: str, payload: Optional[dict],
                 auth: bool, timeout: float) -> dict:
        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = self._headers(auth, payload is not None)
        try:
            status, raw = self.transport(method, self.base_url() + path,
                                         headers, body, timeout)
        except ILinkError:
            raise
        except Exception as exc:                      # transport bug / socket
            raise ILinkError(str(exc)) from exc
        text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        if status == 401 or status == 403:
            raise ILinkError("授权失效（401）")
        if not text.strip():
            raise ILinkError("空响应")
        return parse_json(text)

    # ---------------- login
    def start_login(self) -> dict:
        """Ask WeChat for a bot QR.  Returns {'url': <payload>, 'code': <id>}."""
        data = self._request("GET", QR_PATH, None, auth=False, timeout=20)
        url = (data.get("qrcode_img_content") or "").strip()
        code = (data.get("qrcode") or "").strip()
        if not url or not code:
            raise ILinkError("没有拿到二维码")
        return {"url": url, "code": code}

    def poll_login(self, code: str) -> dict:
        """Returns {'status': 'wait'|'confirmed'|'expired', 'token':..., 'host':...}."""
        data = self._request("GET", QR_STATUS_PATH + urllib.parse.quote(code),
                             None, auth=False, timeout=45)
        status = (data.get("status") or "wait").strip()
        out = {"status": status}
        if status == "scaned_but_redirect":
            out["redirect"] = normalize_host(data.get("redirect_host") or "")
        elif status in ("binded_redirect", "need_verifycode", "verify_code_blocked"):
            out["note"] = status
        if status == "confirmed":
            token = (data.get("bot_token") or "").strip()
            scheme, host = split_host(data.get("baseurl") or "")
            scheme = scheme or self.scheme
            if not token:
                raise ILinkError("扫码成功但没有 token")
            out["token"] = token
            out["host"] = host or self.host
            out["scheme"] = scheme
            out["bot_id"] = str(data.get("ilink_bot_id") or "").strip()
            out["owner"] = str(data.get("ilink_user_id") or "").strip()
        return out

    # ---------------- messaging
    def get_updates(self, cursor: str, timeout: float = 50) -> dict:
        payload = {
            "get_updates_buf": cursor or "",
            "base_info": self.base_info(),
        }
        return self._request("POST", UPDATES_PATH, payload, auth=True,
                             timeout=timeout)

    def notify_start(self) -> dict:
        return self._request("POST", "/ilink/bot/msg/notifystart",
                             {"base_info": self.base_info()}, auth=True,
                             timeout=10)

    def notify_stop(self) -> dict:
        return self._request("POST", "/ilink/bot/msg/notifystop",
                             {"base_info": self.base_info()}, auth=True,
                             timeout=5)

    def send_text(self, user_id: str, text: str, context_token: str) -> dict:
        if not self.token:
            raise ILinkError("还没登录")
        if not user_id:
            raise ILinkError("缺少好友 ID")
        last = {"ret": 0}
        for chunk in split_text(text):
            payload = {
                "msg": {
                    "from_user_id": "",
                    "to_user_id": user_id,
                    "client_id": _client_id(),
                    "message_type": 2,
                    "message_state": 2,
                    "item_list": [{"type": 1, "text_item": {"text": chunk}}],
                },
                "base_info": self.base_info(),
            }
            if context_token:
                payload["msg"]["context_token"] = context_token
            last = self._request("POST", SEND_PATH, payload, auth=True,
                                 timeout=45)
            if int(last.get("ret", 0) or 0) != 0:
                break
        return last


def _client_id() -> str:
    import time
    return "aos-%d-%d" % (int(time.time() * 1000), int.from_bytes(os.urandom(2), "big"))


def extract_messages(payload: dict) -> list:
    """Turn a getupdates response into a list of normalized text messages."""
    out = []
    for msg in payload.get("msgs") or []:
        try:
            if int(msg.get("message_type", 0) or 0) != 1:
                continue
            uid = (msg.get("from_user_id") or "").strip()
            if not uid:
                continue
            parts = []
            for item in msg.get("item_list") or []:
                if int(item.get("type", 0) or 0) != 1:
                    continue
                text = ((item.get("text_item") or {}).get("text") or "")
                if text:
                    parts.append(text)
            if not parts:
                continue
            out.append({
                "uid": uid,
                "text": "\n".join(parts),
                "mid": str(msg.get("message_id") or ""),
                "ctx": (msg.get("context_token") or "").strip(),
            })
        except (TypeError, ValueError):
            continue
    return out


def short_uid(uid: str) -> str:
    """Human friendly fallback name for an opaque wxid."""
    uid = uid or ""
    if uid.startswith("wxid_"):
        uid = uid[5:]
    return uid[:10] if len(uid) > 10 else uid or "未知"


AnyDict = dict[str, Any]
