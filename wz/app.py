"""Application state machine: login / invite / friend list / chat.

Each WeChat relationship is backed by one iLink *account* (bot token):

* the primary account is the bot you scanned at login;
* an invite account is a bot a friend scanned, which makes that friend the
  bot's owner -- and lets us message them proactively.

Network workers only push immutable events into a queue; all store mutations
happen on the UI thread.
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import time

from . import ilink, model
from .ime import CJK_RE, is_single_syllable, looks_like_pinyin

DRAW_INTERVAL = 0.2
SAVE_INTERVAL = 3.0


def printable(ch: str) -> bool:
    return ch.isprintable() and ch not in "\n\r\t"


class LoginWorker(threading.Thread):
    def __init__(self, app, gen: int):
        super().__init__(daemon=True, name="wz-login")
        self.app, self.gen = app, gen

    def run(self) -> None:
        try:
            self._run()
        finally:
            if self.app._login_worker is self:
                self.app._login_worker = None

    def _run(self) -> None:
        app, gen, ev = self.app, self.gen, self.app.events
        ev.put(("login_state", gen, "loading"))
        client = app.new_client()
        try:
            qr = client.start_login()
        except Exception as exc:
            ev.put(("login_error", gen, str(exc)))
            return
        ev.put(("qr", gen, qr))
        while not app.stop_event.is_set() and gen == app.login_gen:
            if app.stop_event.wait(2.5):
                return
            if gen != app.login_gen:
                return
            try:
                status = client.poll_login(qr["code"])
            except ilink.ILinkError as exc:
                ev.put(("login_error", gen, str(exc)))
                continue
            state = status.get("status")
            if state == "scaned_but_redirect":
                if status.get("redirect"):
                    client.host = status["redirect"]
                ev.put(("login_wait", gen))
                continue
            if state in ("binded_redirect", "need_verifycode", "verify_code_blocked"):
                ev.put(("login_error", gen, "该微信已绑定过机器人，或需要配对数字"))
                return
            if state == "confirmed":
                ev.put(("login_ok", gen, status))
                return
            if state == "expired":
                ev.put(("login_expired", gen))
                return
            ev.put(("login_wait", gen))


class InviteWorker(threading.Thread):
    def __init__(self, app, gen: int):
        super().__init__(daemon=True, name="wz-invite")
        self.app, self.gen = app, gen

    def run(self) -> None:
        try:
            self._run()
        finally:
            if self.app._invite_worker is self:
                self.app._invite_worker = None

    def _run(self) -> None:
        app, gen, ev = self.app, self.gen, self.app.events
        ev.put(("invite_state", gen, "loading"))
        client = app.new_client()
        try:
            qr = client.start_login()
        except Exception as exc:
            ev.put(("invite_error", gen, str(exc)))
            return
        ev.put(("invite_qr", gen, qr))
        while not app.stop_event.is_set() and gen == app.invite_gen:
            if app.stop_event.wait(2.5):
                return
            if gen != app.invite_gen:
                return
            try:
                status = client.poll_login(qr["code"])
            except ilink.ILinkError as exc:
                ev.put(("invite_error", gen, str(exc)))
                continue
            state = status.get("status")
            if state == "scaned_but_redirect":
                if status.get("redirect"):
                    client.host = status["redirect"]
                ev.put(("invite_wait", gen))
                continue
            if state in ("binded_redirect", "need_verifycode", "verify_code_blocked"):
                ev.put(("invite_error", gen, "这个微信已绑定过机器人，或需要配对数字"))
                return
            if state == "confirmed":
                ev.put(("invite_ok", gen, status))
                return
            if state == "expired":
                ev.put(("invite_expired", gen))
                return
            ev.put(("invite_wait", gen))


class PollWorker(threading.Thread):
    def __init__(self, app, aid: str, gen: int):
        super().__init__(daemon=True, name="wz-poll-%s" % aid)
        self.app, self.aid, self.gen = app, aid, gen

    def run(self) -> None:
        app, ev, aid = self.app, self.app.events, self.aid
        fails = 0
        try:
            while not app.stop_event.is_set():
                if self.gen != app.poll_gen.get(aid, 0):
                    return
                acc = app.store.account(aid)
                if acc is None or not acc.token:
                    return
                try:
                    client = app.client_for(acc)
                    if not app.notified.get(aid):
                        try:
                            client.notify_start()
                        except Exception:
                            pass
                        app.notified[aid] = True
                    data = client.get_updates(acc.cursor, timeout=45)
                    errcode = int(data.get("errcode", 0) or 0)
                    if errcode == -14:
                        ev.put(("auth_lost", aid))
                        return
                    ret = int(data.get("ret", 0) or 0)
                    if ret != 0:
                        raise ilink.ILinkError("ret=%s %s" % (ret, data.get("errmsg") or ""))
                    cursor = str(data.get("get_updates_buf") or acc.cursor)
                    msgs = ilink.extract_messages(data)
                    ev.put(("updates", aid, cursor, msgs))
                    ev.put(("net_ok", aid, True))
                    fails = 0
                    if not msgs:
                        app.stop_event.wait(0.3)
                except ilink.ILinkError as exc:
                    text = str(exc)
                    if "401" in text or "403" in text:
                        ev.put(("auth_lost", aid))
                        return
                    ev.put(("net_ok", aid, False, text))
                    fails += 1
                    app.stop_event.wait(min(30.0, 2.0 * fails))
                except Exception as exc:
                    ev.put(("net_ok", aid, False, str(exc)))
                    fails += 1
                    app.stop_event.wait(min(30.0, 2.0 * fails))
        finally:
            app.notified.pop(aid, None)
            if app.poll_workers.get(aid) is self:
                app.poll_workers.pop(aid, None)


class App:
    def __init__(self, store: model.Store, ui, display, keys,
                 client: ilink.ILinkClient | None = None, ime=None,
                 host: str = ""):
        self.store = store
        self.ui = ui
        self.display = display
        self.keys = keys
        if not store.uin:
            store.uin = ilink.new_uin()
            store.dirty = True
        self.ime = ime
        self._external_client = client
        self.default_host = host

        self.lock = threading.RLock()
        self.events = queue.Queue()
        self.stop_event = threading.Event()

        self.screen = "friends" if self.logged_in else "login"
        self.help_back = "friends"
        self.sel = 0
        self.sel_uid = store.active or ""
        self.list_scroll = 0
        self.scroll = 0

        self.input = ""
        self.conv = None
        self.dialog_text = ""
        self.confirm_uid = ""
        self.draft = None
        self.rename_uid = ""
        self.rename_back = "friends"

        self.qr_url = ""
        self.qr_code = ""
        self.login_state = "idle" if self.logged_in else "loading"
        self.login_note = ""
        self.login_gen = 0
        self.login_retry_at = 0.0

        self.invite_url = ""
        self.invite_code = ""
        self.invite_state = "idle"
        self.invite_note = ""
        self.invite_gen = 0

        self.net_ok: dict[str, bool | None] = {}
        self.net_note = ""
        self.clients: dict[str, ilink.ILinkClient] = {}
        self.poll_gen: dict[str, int] = {}
        self.notified: dict[str, bool] = {}
        self.poll_workers: dict[str, threading.Thread] = {}

        self.toast = ""
        self.toast_until = 0.0
        self.blink_on = True
        self.blink_ts = 0.0
        self.running = True
        self.busy = 0

        self.shift = False
        self.last_draw = 0.0
        self.last_save = 0.0
        self._login_worker = None
        self._invite_worker = None
        self._cleanup_broken_invites()

    def log(self, text: str) -> None:
        path = os.path.join(os.path.dirname(self.store.path) or ".", "app.log")
        try:
            if os.path.exists(path) and os.path.getsize(path) > 200_000:
                os.replace(path, path + ".1")
            with open(path, "a", encoding="utf-8") as fh:
                fh.write("%s %s\n" % (time.strftime("%m-%d %H:%M:%S"), text))
        except OSError:
            pass

    def _cleanup_broken_invites(self) -> None:
        """Drop dead invite channels; keep transcripts readable."""
        for f in list(self.store.friends.values()):
            if f.account and f.account not in self.store.accounts:
                f.account = ""
                f.ctx = ""
                self.store.dirty = True
                self.log("orphan friend %s -> no channel" % f.uid)
        primary = self.store.primary
        if primary is None or not primary.owner:
            return
        for acc in list(self.store.accounts.values()):
            if acc.kind != "invite" or acc.token or acc.owner != primary.owner:
                continue
            for f in list(self.store.friends.values()):
                if f.account != acc.id:
                    continue
                if not any(m.who in ("me", "them") for m in f.messages):
                    self.store.remove(f.uid)
            self.store.drop_account(acc.id)
            self.log("cleanup self-invite %s" % acc.id)

    # ------------------------------------------------------------------ basics
    @property
    def logged_in(self) -> bool:
        acc = self.store.primary
        return bool(acc and acc.token)

    def status_text(self) -> str:
        acc = self.store.primary
        if acc is None or not acc.token:
            return "未登录"
        state = self.net_ok.get(acc.id)
        if state is None:
            return "连接中"
        return "在线" if state else "离线"

    def active_friend(self):
        return self.store.friends.get(self.store.active)

    def selected_friend(self):
        friends = self.store.sorted_friends()
        if not friends:
            return None
        self.sync_selection()
        return friends[min(self.sel, len(friends) - 1)]

    def sync_selection(self) -> None:
        friends = self.store.sorted_friends()
        if not friends:
            self.sel, self.sel_uid = 0, ""
            return
        uids = [f.uid for f in friends]
        if self.sel_uid not in uids:
            self.sel_uid = uids[0]
        self.sel = uids.index(self.sel_uid)

    def toast_now(self, text: str, secs: float = 2.2) -> None:
        self.toast = text
        self.toast_until = time.time() + secs

    def beep(self) -> None:
        try:
            sys.stdout.write("\a")
            sys.stdout.flush()
        except Exception:
            pass

    def channel_text(self, friend) -> str:
        acc = self.store.account(friend.account) if friend.account else None
        if acc is None:
            if friend.ctx and self.store.primary and self.store.primary.token:
                return "可回复"
            return "通道未登录"
        if not acc.token:
            return "通道未登录"
        if friend.uid == acc.owner:
            return "专属通道"
        return "可回复" if friend.ctx else "等对方发消息"

    # ------------------------------------------------------------------ clients
    def new_client(self) -> ilink.ILinkClient:
        """A token-less client for QR login / invite (uses primary host)."""
        primary = self.store.primary
        host = (primary.host if primary else "") or self.default_host
        scheme = primary.scheme if primary else "https"
        if host.startswith("http://"):
            scheme = "http"
        return ilink.ILinkClient(host or ilink.DEFAULT_HOST, "", self.store.uin,
                                 scheme=scheme)

    def client_for(self, acc: model.Account) -> ilink.ILinkClient:
        cached = self.clients.get(acc.id)
        if (cached is None or cached.token != acc.token
                or cached.host != acc.host or cached.scheme != acc.scheme):
            cached = ilink.ILinkClient(acc.host or ilink.DEFAULT_HOST,
                                       acc.token, self.store.uin,
                                       scheme=acc.scheme)
            self.clients[acc.id] = cached
        return cached

    def start_poll(self, aid: str) -> None:
        acc = self.store.account(aid)
        if acc is None or not acc.token:
            return
        gen = self.poll_gen.get(aid, 0) + 1
        self.poll_gen[aid] = gen
        self.net_ok.setdefault(aid, None)
        worker = PollWorker(self, aid, gen)
        self.poll_workers[aid] = worker
        worker.start()

    # ------------------------------------------------------------------ input
    def pinyin_tail(self) -> str:
        import re
        m = re.search(r"[a-z]+$", self.input)
        return m.group(0) if m else ""

    def handle_char(self, ch: str) -> None:
        if self.conv:
            self.conv = None
        if len(self.input) < 300:
            self.input += ch

    def convert(self, force: bool = False) -> bool:
        if self.ime is None or self.screen not in ("chat", "rename"):
            return False
        tail = self.pinyin_tail()
        if not tail:
            return False
        base = self.input[:len(self.input) - len(tail)]
        if not force:
            cn_context = bool(CJK_RE.search(self.input))
            if not (looks_like_pinyin(tail) or (cn_context and is_single_syllable(tail))):
                return False
        try:
            cands = self.ime.candidates(tail, 9)
        except Exception:
            cands = []
        if not cands:
            return False
        self.input = base + cands[0]
        self.conv = {"cands": cands, "start": len(base), "pinyin": tail, "page": 0}
        return True

    def pick(self, index: int) -> None:
        if not self.conv:
            return
        idx = self.conv.get("page", 0) * 3 + index
        cands = self.conv["cands"]
        if 0 <= idx < len(cands):
            self.input = self.input[:self.conv["start"]] + cands[idx]
        self.conv = None

    def next_page(self) -> None:
        if not self.conv:
            return
        pages = max(1, (len(self.conv["cands"]) + 2) // 3)
        self.conv["page"] = (self.conv.get("page", 0) + 1) % pages

    def cancel_conv(self) -> None:
        if not self.conv:
            return
        self.input = self.input[:self.conv["start"]] + self.conv["pinyin"]
        self.conv = None

    # ------------------------------------------------------------------ login
    def start_login(self, force: bool = False) -> None:
        if self.logged_in and not force:
            return
        self.login_gen += 1
        self.qr_url, self.qr_code = "", ""
        self.login_state = "loading"
        self.login_note = ""
        self.screen = "login"
        worker = LoginWorker(self, self.login_gen)
        self._login_worker = worker
        worker.start()

    def logout(self, note: str = "") -> None:
        for acc in self.store.accounts.values():
            acc.token = ""
        self.clients.clear()
        self.poll_gen = {k: v + 1 for k, v in self.poll_gen.items()}
        self.net_ok.clear()
        self.store.dirty = True
        self.screen = "login"
        self.qr_url = ""
        self.login_state = "loading"
        if note:
            self.toast_now(note)

    # ------------------------------------------------------------------ invite
    def start_invite(self) -> None:
        self.invite_gen += 1
        self.invite_url, self.invite_code = "", ""
        self.invite_state = "loading"
        self.invite_note = ""
        self.screen = "invite"
        worker = InviteWorker(self, self.invite_gen)
        self._invite_worker = worker
        worker.start()

    def cancel_invite(self) -> None:
        self.invite_gen += 1
        self.screen = "friends"

    # ------------------------------------------------------------------ send
    def _send_worker(self, aid, uid, text, ctx, msg) -> None:
        try:
            acc = self.store.account(aid)
            if acc is None or not acc.token:
                raise ilink.ILinkError("通道未登录")
            res = self.client_for(acc).send_text(uid, text, ctx)
            ret = int(res.get("ret", 0) or 0)
            err = str(res.get("errmsg") or "") if ret else ""
            if ret == -14:
                self.events.put(("auth_lost", aid))
            self.events.put(("sent", aid, msg, uid, ret == 0, err
                             + ("（会话已过期）" if ret == -14 else "")))
        except Exception as exc:
            self.events.put(("sent", aid, msg, uid, False, str(exc)))

    def send_current(self) -> None:
        friend = self.active_friend()
        if friend is None:
            return
        text = self.input.strip()
        if not text:
            return
        tail = self.pinyin_tail()
        if tail and (looks_like_pinyin(tail)
                     or (CJK_RE.search(text) and is_single_syllable(tail))):
            self.convert(force=True)
            text = self.input.strip()

        acc = self.store.account(friend.account) if friend.account else None
        if acc is None and friend.ctx:
            acc = self.store.primary
        if acc is None or not acc.token:
            self.toast_now("通道未登录")
            self.store.system(friend.uid, "这个好友的专属通道未登录，请重新邀请。")
            return
        proactive = friend.uid == acc.owner
        if not friend.ctx and not proactive:
            self.toast_now("对方还没发来消息")
            self.store.system(friend.uid, "对方还没有发来消息，微信不允许主动发起会话。")
            return
        msg = self.store.outgoing(friend.uid, text)
        self.input, self.conv, self.scroll = "", None, 0
        self.busy += 1
        threading.Thread(target=self._send_worker,
                         args=(acc.id, friend.uid, text,
                               friend.ctx if not proactive else "", msg),
                         daemon=True).start()

    # ------------------------------------------------------------------ events
    def handle_event(self, ev) -> None:
        kind = ev[0]
        if kind == "qr":
            gen, qr = ev[1], ev[2]
            if gen != self.login_gen:
                return
            self.qr_url, self.qr_code = qr["url"], qr["code"]
            self.login_state, self.login_note = "wait", ""
        elif kind == "login_state":
            if ev[1] == self.login_gen:
                self.login_state = ev[2]
        elif kind == "login_wait":
            if ev[1] == self.login_gen:
                self.login_state = "wait"
        elif kind == "login_error":
            if ev[1] == self.login_gen:
                self.login_state, self.login_note = "error", ev[2][:40]
                self.login_retry_at = time.time() + 8
        elif kind == "login_expired":
            if ev[1] == self.login_gen:
                self.login_state, self.login_note = "expired", "正在重新获取…"
                self.login_retry_at = time.time() + 4
        elif kind == "login_ok":
            if ev[1] != self.login_gen:
                return
            self.apply_login(ev[2])
        elif kind == "invite_state":
            if ev[1] == self.invite_gen:
                self.invite_state = ev[2]
        elif kind == "invite_wait":
            if ev[1] == self.invite_gen:
                self.invite_state = "wait"
        elif kind == "invite_qr":
            if ev[1] == self.invite_gen:
                self.invite_url, self.invite_code = ev[2]["url"], ev[2]["code"]
                self.invite_state, self.invite_note = "wait", ""
        elif kind == "invite_error":
            if ev[1] == self.invite_gen:
                self.invite_state, self.invite_note = "error", ev[2][:40]
        elif kind == "invite_expired":
            if ev[1] == self.invite_gen:
                self.invite_state, self.invite_note = "expired", "按 Enter 重新获取"
        elif kind == "invite_ok":
            if ev[1] != self.invite_gen:
                return
            self.apply_invite(ev[2])
        elif kind == "updates":
            aid, cursor, msgs = ev[1], ev[2], ev[3]
            acc = self.store.account(aid)
            if acc is not None and cursor != acc.cursor:
                acc.cursor = cursor
                self.store.dirty = True
            self.apply_messages(aid, msgs)
        elif kind == "net_ok":
            aid = ev[1]
            self.net_ok[aid] = bool(ev[2])
            if len(ev) > 3:
                self.net_note = ev[3]
        elif kind == "auth_lost":
            self.on_auth_lost(ev[1])
        elif kind == "sent":
            aid, msg, uid, ok, err = ev[1], ev[2], ev[3], ev[4], ev[5]
            self.busy = max(0, self.busy - 1)
            if ok:
                msg.state = ""
                self.toast_now("已发送")
            else:
                msg.state = "failed"
                self.log("send failed aid=%s ret_err=%s" % (aid, err or "unknown"))
                self.store.system(uid, "发送失败：%s" % (err or "未知错误"))
                self.toast_now("发送失败")
            self.store.dirty = True

    def apply_login(self, status: dict) -> None:
        token = status.get("token", "")
        host = status.get("host", "")
        scheme = status.get("scheme", "https")
        if not token:
            return
        acc = self.store.set_primary(token, host, scheme,
                                     status.get("owner", ""))
        self.client_for(acc)
        self.store.dirty = True
        self.store.save(force=True)
        self.login_state = "confirmed"
        self.screen = "friends"
        self.net_ok[acc.id] = None
        self.toast_now("登录成功")
        self._cleanup_broken_invites()
        self.start_poll(acc.id)

    def apply_invite(self, status: dict) -> None:
        token = status.get("token", "")
        host = status.get("host", "")
        scheme = status.get("scheme", "https")
        owner = status.get("owner", "")
        if not token or not owner:
            self.invite_state, self.invite_note = "error", "没有拿到好友身份"
            return
        primary = self.store.primary
        if primary is not None and primary.owner and owner == primary.owner:
            self.invite_state = "error"
            self.invite_note = "这是你自己的微信，请让好友扫码"
            return
        acc = self.store.add_account(status.get("bot_id", ""), token, host,
                                     scheme, owner,
                                     "好友%d" % (len(self.store.accounts) + 1))
        friend = self.store.friend(owner, account=acc.id)
        assert friend is not None
        if not friend.name:
            friend.name = "好友%d" % len(self.store.accounts)
        self.store.active = owner
        self.sel_uid = owner
        self.store.mark_read(owner)
        self.store.dirty = True
        self.store.save(force=True)
        self.net_ok[acc.id] = None
        self.start_poll(acc.id)
        self.toast_now("好友已连接，可以主动发消息")
        self.screen = "chat"
        self.scroll, self.input, self.conv = 0, "", None

    def on_auth_lost(self, aid: str) -> None:
        acc = self.store.account(aid)
        if acc is None:
            return
        acc.token = ""
        self.clients.pop(aid, None)
        self.net_ok[aid] = False
        self.store.dirty = True
        self.log("auth lost aid=%s kind=%s" % (aid, acc.kind))
        if aid == self.store.primary_id:
            self.qr_url = ""
            self.login_state = "loading"
            self.screen = "login"
            self.start_login(force=True)
            self.toast_now("登录已失效，请重新扫码")
            return
        self.toast_now("好友通道失效：别用自己的微信扫邀请码", 4.0)
        for f in self.store.friends.values():
            if f.account == aid:
                self.store.system(
                    f.uid,
                    "通道失效。常见原因：用自己的微信扫了邀请码——"
                    "一个微信只能绑一条 bot 通道。请让好友用他的手机扫。")

    def apply_messages(self, aid: str, msgs) -> None:
        for item in msgs:
            uid, text = item["uid"], item["text"]
            mid, ctx = item["mid"], item["ctx"]
            if self.store.is_duplicate(uid, mid):
                continue
            viewed = (self.screen == "chat" and self.store.active == uid)
            friend = self.store.incoming(uid, text, ctx, mid, viewed=viewed,
                                         account=aid)
            if viewed:
                self.scroll = 0
            else:
                self.beep()
                if self.screen == "friends":
                    short = text.replace("\n", " ").strip()
                    if len(short) > 18:
                        short = short[:18] + "…"
                    self.toast_now("%s：%s" % (friend.display_name(), short), 1.6)

    # ------------------------------------------------------------------ keys
    def handle_key(self, code: int, value: int) -> None:
        from . import keys as K
        if code in (K.KEY_LEFTSHIFT, K.KEY_RIGHTSHIFT):
            self.shift = value != 0
            return
        if value == 0:
            return
        repeatable = code in (K.KEY_UP, K.KEY_DOWN)
        if value == 2 and not repeatable:
            return
        if self.screen == "help":
            self.screen = self.help_back
            return
        if self.screen == "login":
            self.key_login(code)
        elif self.screen == "invite":
            self.key_invite(code)
        elif self.screen == "friends":
            self.key_friends(code)
        elif self.screen == "chat":
            self.key_chat(code)
        elif self.screen == "rename":
            self.key_rename(code)
        elif self.screen == "confirm_delete":
            self.key_confirm(code)
        elif self.screen == "confirm_logout":
            self.key_logout(code)

    def key_login(self, code: int) -> None:
        from . import keys as K
        if code == K.KEY_ESC:
            self.running = False
        elif code == K.KEY_ENTER:
            self.start_login(force=True)

    def key_invite(self, code: int) -> None:
        from . import keys as K
        if code == K.KEY_ESC:
            self.cancel_invite()
        elif code == K.KEY_ENTER:
            self.start_invite()

    def key_friends(self, code: int) -> None:
        from . import keys as K
        friends = self.store.sorted_friends()
        if code == K.KEY_ESC:
            self.running = False
        elif code == K.KEY_UP:
            if friends:
                self.sel = (self.sel - 1) % len(friends)
                self.sel_uid = friends[self.sel].uid
        elif code == K.KEY_DOWN:
            if friends:
                self.sel = (self.sel + 1) % len(friends)
                self.sel_uid = friends[self.sel].uid
        elif code == K.KEY_ENTER:
            if friends:
                self.open_chat(friends[self.sel].uid)
        elif code == K.KEY_F1:
            self.help_back, self.screen = "friends", "help"
        elif code == K.KEY_F2:
            self.start_invite()
        elif code == K.KEY_F3:
            friend = self.selected_friend()
            if friend:
                self.draft = None
                self.input, self.conv = friend.name, None
                self.rename_uid = friend.uid
                self.rename_back = "friends"
                self.screen = "rename"
        elif code in (K.KEY_DELETE, K.KEY_F8):
            friend = self.selected_friend()
            if friend:
                self.confirm_uid = friend.uid
                self.screen = "confirm_delete"
        elif code == K.KEY_F5:
            self.screen = "confirm_logout"

    def open_chat(self, uid: str) -> None:
        self.store.active = uid
        self.sel_uid = uid
        self.store.mark_read(uid)
        self.store.dirty = True
        self.screen = "chat"
        self.scroll, self.input, self.conv = 0, "", None
        self.toast = ""

    def key_chat(self, code: int) -> None:
        from . import keys as K
        if self.conv:
            if code in (2, 3, 4):
                self.pick({2: 0, 3: 1, 4: 2}[code])
                return
            if code == 11:
                self.next_page()
                return
        if code == K.KEY_ESC:
            if self.conv:
                self.cancel_conv()
            else:
                self.screen = "friends"
                self.scroll = 0
        elif code == K.KEY_ENTER:
            if self.input.strip():
                self.send_current()
        elif code == K.KEY_BACKSPACE:
            if self.conv:
                self.conv = None
            self.input = self.input[:-1]
        elif code == K.KEY_TAB:
            self.convert(force=True)
        elif code == K.KEY_F1:
            self.help_back, self.screen = "chat", "help"
        elif code == K.KEY_F2:
            self.start_invite()
        elif code == K.KEY_F3:
            friend = self.active_friend()
            if friend:
                self.draft = (self.input, self.conv)
                self.input, self.conv = friend.name, None
                self.rename_uid = friend.uid
                self.rename_back = "chat"
                self.screen = "rename"
        elif code == K.KEY_UP:
            self.scroll += 3
        elif code == K.KEY_DOWN:
            self.scroll = max(0, self.scroll - 3)
        else:
            ch = K.SHIFTED.get(code) if self.shift else K.CHARS.get(code)
            if ch and self.shift and ch.isalpha():
                ch = ch.upper()
            if ch and printable(ch):
                self.handle_char(ch)

    def key_rename(self, code: int) -> None:
        from . import keys as K
        if self.conv:
            if code in (2, 3, 4):
                self.pick({2: 0, 3: 1, 4: 2}[code])
                return
            if code == 11:
                self.next_page()
                return
        if code == K.KEY_ESC:
            if self.conv:
                self.cancel_conv()
            else:
                self.leave_rename()
        elif code == K.KEY_ENTER:
            friend = self.store.friends.get(self.rename_uid)
            if friend:
                friend.name = self.input.strip()[:20]
                self.store.dirty = True
                self.toast_now("已保存备注名")
            self.leave_rename()
        elif code == K.KEY_BACKSPACE:
            if self.conv:
                self.conv = None
            self.input = self.input[:-1]
        elif code == K.KEY_TAB:
            self.convert(force=True)
        else:
            ch = K.SHIFTED.get(code) if self.shift else K.CHARS.get(code)
            if ch and self.shift and ch.isalpha():
                ch = ch.upper()
            if ch and printable(ch):
                self.handle_char(ch)

    def leave_rename(self) -> None:
        back, draft = self.rename_back, self.draft
        self.screen = back
        self.rename_uid = ""
        self.draft = None
        if back == "chat" and draft is not None:
            self.input, self.conv = draft
        else:
            self.conv = None

    def key_confirm(self, code: int) -> None:
        from . import keys as K
        if code == K.KEY_ESC:
            self.screen = "friends"
        elif code == K.KEY_ENTER:
            if self.confirm_uid:
                self.store.remove(self.confirm_uid)
                self.toast_now("已删除")
                if self.sel_uid == self.confirm_uid:
                    self.sel_uid = ""
            self.confirm_uid = ""
            self.screen = "friends"

    def key_logout(self, code: int) -> None:
        from . import keys as K
        if code == K.KEY_ENTER:
            self.logout("已退出登录")
            self.start_login(force=True)
        else:
            self.screen = "friends"

    # ------------------------------------------------------------------ loop
    def tick(self) -> None:
        now = time.time()
        while True:
            try:
                ev = self.events.get_nowait()
            except queue.Empty:
                break
            try:
                self.handle_event(ev)
            except Exception as exc:
                self.net_note = "事件错误：%s" % exc

        if not self.logged_in and self.screen == "login" and self._login_worker is None:
            if not self.login_retry_at or now >= self.login_retry_at:
                self.login_retry_at = 0.0
                self.start_login()

        for acc in self.store.active_accounts():
            worker = self.poll_workers.get(acc.id)
            if worker is None or not worker.is_alive():
                self.start_poll(acc.id)

        if now - self.blink_ts > 0.5:
            self.blink_ts = now
            self.blink_on = not self.blink_on
            self.ui.blink_on = self.blink_on

        if self.toast and now > self.toast_until:
            self.toast = ""

        if self.store.dirty and now - self.last_save > SAVE_INTERVAL:
            self.last_save = now
            self.store.save()

        if now - self.last_draw >= DRAW_INTERVAL:
            self.last_draw = now
            self.sync_selection()
            self.display.show(self.ui.draw(self))

    def run(self, max_seconds: float | None = None) -> int:
        started = time.time()
        try:
            while self.running and not self.stop_event.is_set():
                for code, value in self.keys.poll():
                    self.handle_key(code, value)
                self.tick()
                if max_seconds and time.time() - started > max_seconds:
                    break
                time.sleep(0.01)
        finally:
            self.stop()
        return 0

    def stop(self) -> None:
        self.running = False
        self.stop_event.set()
        self.login_gen += 1
        self.invite_gen += 1
        self.poll_gen = {k: v + 1 for k, v in self.poll_gen.items()}
        try:
            self.store.save(force=True)
        except Exception:
            pass

    # ------------------------------------------------------------------ previews
    def draw(self):
        self.ui.blink_on = self.blink_on
        self.sync_selection()
        return self.ui.draw(self)
