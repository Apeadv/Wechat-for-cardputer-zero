"""Multi-account, multi-friend conversation store.

Two kinds of relationships are supported:

* **Primary account** - the bot whose login QR *you* scanned.  Friends who
  message this bot can be replied to (their ``context_token`` is required).
* **Invite account** - a bot created by an invite QR that a friend scanned
  (the official "connect this OpenClaw to someone else's WeChat" flow).  That
  friend becomes the bot's owner, so we can message them proactively even
  before they write anything.

Every account has its own token, host, poll cursor and transcript routing.
"""

from __future__ import annotations

import json
import os
import time

MAX_MESSAGES = 120
MAX_SEEN = 400
STATE_VERSION = 2


def now() -> float:
    return time.time()


def short_id(uid: str) -> str:
    uid = uid or ""
    if uid.startswith("wxid_"):
        uid = uid[5:]
    if "@" in uid:
        uid = uid.split("@", 1)[0]
    return uid[:10] if len(uid) > 10 else uid or "未知"


def fmt_time(ts: float) -> str:
    if not ts:
        return ""
    lt = time.localtime(ts)
    today = time.localtime()
    if (lt.tm_year, lt.tm_yday) == (today.tm_year, today.tm_yday):
        return time.strftime("%H:%M", lt)
    if lt.tm_year == today.tm_year:
        return time.strftime("%m-%d", lt)
    return time.strftime("%y-%m-%d", lt)


class Account:
    """One iLink bot identity (one token / one owner)."""

    def __init__(self, aid: str, token: str = "", host: str = "",
                 scheme: str = "https", cursor: str = "", owner: str = "",
                 name: str = "", kind: str = "invite"):
        self.id = aid
        self.token = token
        self.host = host
        self.scheme = scheme or "https"
        self.cursor = cursor
        self.owner = owner
        self.name = name
        self.kind = kind          # "main" | "invite"

    def to_dict(self) -> dict:
        return {"id": self.id, "token": self.token, "host": self.host,
                "scheme": self.scheme, "cursor": self.cursor,
                "owner": self.owner, "name": self.name, "kind": self.kind}

    @classmethod
    def from_dict(cls, d: dict) -> "Account":
        return cls(str(d.get("id") or "main"), str(d.get("token") or ""),
                   str(d.get("host") or ""), str(d.get("scheme") or "https"),
                   str(d.get("cursor") or ""), str(d.get("owner") or ""),
                   str(d.get("name") or ""), str(d.get("kind") or "invite"))


class Message:
    __slots__ = ("who", "text", "ts", "mid", "state")

    def __init__(self, who: str, text: str, ts: float = 0.0,
                 mid: str = "", state: str = ""):
        self.who = who          # "me" | "them" | "sys"
        self.text = text
        self.ts = ts or now()
        self.mid = mid
        self.state = state      # "", "sending", "failed"

    def to_dict(self) -> dict:
        d = {"who": self.who, "text": self.text, "ts": round(self.ts, 3)}
        if self.mid:
            d["mid"] = self.mid
        if self.state:
            d["state"] = self.state
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Message":
        return cls(str(d.get("who") or "them"), str(d.get("text") or ""),
                   float(d.get("ts") or 0), str(d.get("mid") or ""),
                   str(d.get("state") or ""))


class Friend:
    def __init__(self, uid: str, name: str = "", account: str = ""):
        self.uid = uid
        self.name = name
        self.account = account
        self.ctx = ""
        self.unread = 0
        self.last_ts = 0.0
        self.messages: list[Message] = []

    def display_name(self) -> str:
        return (self.name or "").strip() or short_id(self.uid)

    def preview(self) -> str:
        for msg in reversed(self.messages):
            if msg.text:
                return msg.text.replace("\n", " ")[:40]
        return "（还没有消息）"

    def add(self, msg: Message) -> None:
        self.messages.append(msg)
        if len(self.messages) > MAX_MESSAGES:
            del self.messages[:len(self.messages) - MAX_MESSAGES]
        self.last_ts = max(self.last_ts, msg.ts)

    def to_dict(self) -> dict:
        return {
            "uid": self.uid,
            "name": self.name,
            "account": self.account,
            "ctx": self.ctx,
            "unread": self.unread,
            "last_ts": round(self.last_ts, 3),
            "messages": [m.to_dict() for m in self.messages],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Friend":
        f = cls(str(d.get("uid") or ""), str(d.get("name") or ""),
                str(d.get("account") or ""))
        f.ctx = str(d.get("ctx") or "")
        f.unread = int(d.get("unread") or 0)
        f.last_ts = float(d.get("last_ts") or 0)
        f.messages = [Message.from_dict(m) for m in d.get("messages") or []
                      if isinstance(m, dict)]
        return f


class Store:
    def __init__(self, path: str):
        self.path = path
        self.uin = ""
        self.active = ""
        self.accounts: dict[str, Account] = {}
        self.primary_id = ""
        self.friends: dict[str, Friend] = {}
        self.seen: list[str] = []
        self.dirty = False
        self.last_save = 0.0
        self.load()

    # ---------------- persistence
    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return
        self.uin = str(data.get("uin") or "")
        self.active = str(data.get("active") or "")
        self.seen = [str(x) for x in data.get("seen") or []][-MAX_SEEN:]
        for item in data.get("accounts") or []:
            if isinstance(item, dict) and item.get("id"):
                acc = Account.from_dict(item)
                self.accounts[acc.id] = acc
        self.primary_id = str(data.get("primary") or "")
        for item in data.get("friends") or []:
            if isinstance(item, dict) and item.get("uid"):
                f = Friend.from_dict(item)
                self.friends[f.uid] = f
        # migrate the 1.0 single-token state
        if not self.accounts and data.get("token"):
            acc = Account("main", str(data.get("token") or ""),
                          str(data.get("host") or ""),
                          str(data.get("scheme") or "https"),
                          str(data.get("cursor") or ""), "", "我", "main")
            self.accounts["main"] = acc
            self.primary_id = "main"
            for f in self.friends.values():
                if not f.account:
                    f.account = "main"
            self.dirty = True
        if not self.primary_id and self.accounts:
            self.primary_id = next(iter(self.accounts))

    def to_dict(self) -> dict:
        return {
            "version": STATE_VERSION,
            "uin": self.uin,
            "active": self.active,
            "primary": self.primary_id,
            "seen": self.seen[-MAX_SEEN:],
            "accounts": [a.to_dict() for a in self.accounts.values()],
            "friends": [f.to_dict() for f in self.sorted_friends()],
        }

    def save(self, force: bool = False) -> bool:
        if not (self.dirty or force):
            return False
        self.last_save = now()
        data = self.to_dict()
        folder = os.path.dirname(self.path) or "."
        tmp = self.path + ".tmp"
        try:
            os.makedirs(folder, exist_ok=True)
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=1)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        except OSError:
            try:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            except OSError:
                pass
            return False
        self.dirty = False
        return True

    # ---------------- accounts
    @property
    def primary(self) -> Account | None:
        return self.accounts.get(self.primary_id)

    def account(self, aid: str) -> Account | None:
        return self.accounts.get(aid)

    def set_primary(self, token: str, host: str, scheme: str,
                    owner: str = "", name: str = "我") -> Account:
        acc = self.accounts.get("main")
        if acc is None:
            acc = Account("main", kind="main")
            self.accounts["main"] = acc
        acc.token, acc.host, acc.scheme = token, host, scheme
        if owner:
            acc.owner = owner
        acc.name = name
        acc.kind = "main"
        self.primary_id = "main"
        self.dirty = True
        return acc

    def add_account(self, aid: str, token: str, host: str, scheme: str,
                    owner: str, name: str = "") -> Account:
        base = aid or ("acc-%d" % (len(self.accounts) + 1))
        aid = base
        n = 1
        while aid in self.accounts:
            n += 1
            aid = "%s-%d" % (base, n)
        acc = Account(aid, token, host, scheme, "", owner, name, "invite")
        self.accounts[aid] = acc
        self.dirty = True
        return acc

    def drop_account(self, aid: str) -> None:
        self.accounts.pop(aid, None)
        for f in list(self.friends.values()):
            if f.account == aid:
                f.ctx = ""
        self.dirty = True

    def active_accounts(self) -> list[Account]:
        return [a for a in self.accounts.values() if a.token]

    # ---------------- friends
    def sorted_friends(self) -> list[Friend]:
        return sorted(self.friends.values(),
                      key=lambda f: (f.last_ts, f.display_name()), reverse=True)

    def friend(self, uid: str, create: bool = True, account: str = "") -> Friend | None:
        f = self.friends.get(uid)
        if f is None and create:
            f = Friend(uid, account=account)
            self.friends[uid] = f
            self.dirty = True
        if f is not None and account and not f.account:
            f.account = account
            self.dirty = True
        return f

    def remove(self, uid: str) -> None:
        if uid in self.friends:
            del self.friends[uid]
            if self.active == uid:
                self.active = ""
            self.dirty = True

    def total_unread(self) -> int:
        return sum(f.unread for f in self.friends.values())

    def is_duplicate(self, uid: str, mid: str) -> bool:
        if not mid:
            return False
        key = uid + "#" + mid
        if key in self.seen:
            return True
        self.seen.append(key)
        if len(self.seen) > MAX_SEEN:
            del self.seen[:len(self.seen) - MAX_SEEN]
        self.dirty = True
        return False

    def incoming(self, uid: str, text: str, ctx: str, mid: str,
                 viewed: bool = False, account: str = "") -> Friend:
        friend = self.friend(uid, account=account)
        assert friend is not None
        if mid:
            friend.messages = [m for m in friend.messages if m.mid != mid]
        friend.add(Message("them", text, now(), mid=mid))
        if ctx:
            friend.ctx = ctx
        if account:
            friend.account = account
        if not viewed:
            friend.unread += 1
        self.dirty = True
        return friend

    def outgoing(self, uid: str, text: str) -> Message:
        friend = self.friend(uid)
        assert friend is not None
        msg = Message("me", text, now(), state="sending")
        friend.add(msg)
        self.dirty = True
        return msg

    def system(self, uid: str, text: str) -> None:
        friend = self.friend(uid)
        if friend is not None:
            friend.add(Message("sys", text))
            self.dirty = True

    def mark_read(self, uid: str) -> None:
        f = self.friends.get(uid)
        if f is not None and f.unread:
            f.unread = 0
            self.dirty = True

    def touch(self) -> None:
        self.dirty = True
