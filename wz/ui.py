"""320x170 framebuffer UI for the Cardputer Zero.

Layout is tuned against Noto Sans CJK's real font metrics (size 8: 10+3 px,
size 11: 13+4 px, size 12: 14+4 px).  Every text baseline gets enough vertical
room so nothing is clipped at the panel edge or overlaps the next row.
"""

from __future__ import annotations

import os
import re

from PIL import Image, ImageDraw, ImageFont

from . import model
from .ime import CJK_RE

W, H = 320, 170
HEADER_H = 18
FOOT_H = 15
ROW_H = 26
INPUT_H = 26
CAND_H = 16
LINE_H = 16
PAD = 5

FONT_CANDIDATES = (
    os.environ.get("WECHAT_ZERO_FONT", ""),
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
)

BG = (16, 19, 23)
HEADER_BG = (27, 32, 39)
PANEL = (32, 38, 46)
TEXT = (233, 236, 239)
DIM = (140, 148, 157)
FAINT = (96, 104, 112)
ACCENT = (7, 193, 96)
CYAN = (86, 204, 242)
RED = (250, 81, 81)
YELLOW = (255, 200, 90)
SEL_BG = (40, 49, 59)
ME_TEXT = (150, 240, 185)

AVATARS = ((70, 120, 180), (150, 90, 160), (60, 150, 130),
           (190, 120, 60), (110, 110, 190), (180, 80, 100))

EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D]+")


def clean(text: str) -> str:
    """Replace emoji runs with a label: the panel font has no colour emoji."""
    return EMOJI_RE.sub("[表情]", text or "")


def clip(draw, text: str, font, max_w: int) -> str:
    if draw.textlength(text, font=font) <= max_w:
        return text
    out = text
    while out and draw.textlength(out + "…", font=font) > max_w:
        out = out[:-1]
    return out + "…"


class UI:
    def __init__(self):
        self.font_path = ""
        for path in FONT_CANDIDATES:
            if path and os.path.exists(path):
                self.font_path = path
                break
        self._fonts: dict[int, ImageFont.FreeTypeFont] = {}
        self._wrap_cache: dict[tuple, list] = {}
        self.blink_on = True

    def font(self, size: int):
        f = self._fonts.get(size)
        if f is None:
            if self.font_path:
                try:
                    f = ImageFont.truetype(self.font_path, size)
                except OSError:
                    f = ImageFont.load_default()
            else:
                f = ImageFont.load_default()
            self._fonts[size] = f
        return f

    def wrap(self, draw, text: str, font, max_w: int) -> list:
        text = clean(text)
        key = (text, max_w, id(font))
        hit = self._wrap_cache.get(key)
        if hit is not None:
            return hit
        lines, cur = [], ""
        for ch in text:
            if ch == "\n":
                lines.append(cur)
                cur = ""
                continue
            trial = cur + ch
            if draw.textlength(trial, font=font) > max_w and cur:
                lines.append(cur)
                cur = ch
            else:
                cur = trial
        lines.append(cur)
        if len(self._wrap_cache) > 600:
            self._wrap_cache.clear()
        self._wrap_cache[key] = lines
        return lines

    # ------------------------------------------------------------------ header
    def header(self, d, title: str, right: str = "", badge: int = 0,
               color=None) -> None:
        d.rectangle([0, 0, W, HEADER_H - 1], fill=HEADER_BG)
        d.rectangle([0, HEADER_H - 1, W, HEADER_H - 1], fill=(48, 56, 66))
        f = self.font(11)
        x = PAD
        d.text((x, 1), clip(d, title, f, 180), font=f, fill=color or ACCENT)
        x += min(d.textlength(title, font=f), 180)
        if badge > 0:
            self._badge(d, int(x) + 6, 3, badge)
        if right:
            fs = self.font(9)
            tw = d.textlength(right, font=fs)
            d.text((W - PAD - tw, 3), right, font=fs, fill=DIM)

    def _badge(self, d, x: int, y: int, count: int) -> None:
        fs = self.font(8)
        text = "99+" if count > 99 else str(count)
        tw = d.textlength(text, font=fs)
        w = max(14, tw + 6)
        d.rounded_rectangle([x, y, x + w, y + 12], radius=6, fill=RED)
        d.text((x + (w - tw) / 2, y - 1), text, font=fs, fill=(255, 255, 255))

    # ------------------------------------------------------------------ login
    def login(self, d, qr: str, state: str, note: str) -> None:
        d.rectangle([0, 0, W, H], fill=BG)
        self.header(d, "微信 iLink", "未登录" if state != "confirmed" else "已登录")
        box_x, box_y, box = 6, 19, 148
        d.rectangle([box_x - 2, box_y - 2, box_x + box + 2, box_y + box + 2],
                    fill=(245, 246, 248))
        if qr:
            self._qr(d, qr, box_x, box_y, box)
        else:
            d.rectangle([box_x, box_y, box_x + box, box_y + box], fill=(28, 32, 38))
            fs = self.font(10)
            msg = "获取二维码…" if state == "loading" else "无二维码"
            tw = d.textlength(msg, font=fs)
            d.text((box_x + (box - tw) / 2, box_y + box / 2 - 8), msg,
                   font=fs, fill=DIM)

        x = box_x + box + 8
        f11, f9, f8 = self.font(11), self.font(9), self.font(8)
        d.text((x, 20), "扫码登录", font=f11, fill=TEXT)
        d.text((x, 40), "① 微信扫码", font=f9, fill=DIM)
        d.text((x, 54), "② 确认授权", font=f9, fill=DIM)
        d.text((x, 68), "③ 自动登录", font=f9, fill=DIM)

        if state == "wait":
            label, col = "等待扫码…", YELLOW
        elif state == "confirmed":
            label, col = "登录成功", ACCENT
        elif state == "expired":
            label, col = "二维码过期", RED
        elif state == "error":
            label, col = "登录失败", RED
        else:
            label, col = "准备中…", DIM
        d.text((x, 92), label, font=self.font(10), fill=col)
        if note:
            d.text((x, 108), clip(d, note, f8, W - x - 6), font=f8, fill=FAINT)
        d.text((x, 138), "Enter 重取二维码", font=f8, fill=FAINT)
        d.text((x, 152), "Esc 退出", font=f8, fill=FAINT)

    def _qr(self, d, payload: str, x: int, y: int, box: int) -> None:
        try:
            from vendor import qrcodegen
        except ImportError:                     # running from the source tree
            import sys
            sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
            from vendor import qrcodegen
        try:
            code = qrcodegen.QrCode.encode_text(payload, qrcodegen.QrCode.Ecc.LOW)
        except Exception:
            try:
                code = qrcodegen.QrCode.encode_text(payload, qrcodegen.QrCode.Ecc.MEDIUM)
            except Exception:
                f = self.font(10)
                d.text((x + 8, y + box / 2 - 7), "二维码内容过长", font=f,
                       fill=(40, 40, 40))
                return
        n = code.get_size()
        quiet = 3
        scale = max(1, box // (n + quiet * 2))
        side = (n + quiet * 2) * scale
        ox = x + (box - side) // 2 + quiet * scale
        oy = y + (box - side) // 2 + quiet * scale
        for yy in range(n):
            run = -1
            for xx in range(n + 1):
                dark = xx < n and code.get_module(xx, yy)
                if dark and run < 0:
                    run = xx
                elif not dark and run >= 0:
                    d.rectangle([ox + run * scale, oy + yy * scale,
                                 ox + xx * scale - 1, oy + (yy + 1) * scale - 1],
                                fill=(0, 0, 0))
                    run = -1

    # ------------------------------------------------------------------ friends
    def friends(self, d, app) -> None:
        d.rectangle([0, 0, W, H], fill=BG)
        friends = app.store.sorted_friends()
        self.header(d, "微信", app.status_text(), app.store.total_unread())

        top = HEADER_H + 1
        bottom = H - FOOT_H
        visible = max(1, (bottom - top) // ROW_H)
        if app.sel < app.list_scroll:
            app.list_scroll = app.sel
        if app.sel >= app.list_scroll + visible:
            app.list_scroll = app.sel - visible + 1
        shown = friends[app.list_scroll:app.list_scroll + visible]

        if not friends:
            d.text((PAD, top + 10), "还没有聊天对象。", font=self.font(10), fill=DIM)
            d.text((PAD, top + 28), "按 F2 生成邀请二维码，好友扫码后",
                   font=self.font(9), fill=FAINT)
            d.text((PAD, top + 43), "就能主动给他发消息。",
                   font=self.font(9), fill=FAINT)

        for i, friend in enumerate(shown):
            idx = app.list_scroll + i
            y = top + i * ROW_H
            selected = idx == app.sel
            if selected:
                d.rectangle([0, y, W, y + ROW_H - 1], fill=SEL_BG)
                d.rectangle([0, y, 3, y + ROW_H - 1], fill=ACCENT)
            name = friend.display_name()
            color = AVATARS[sum(ord(c) for c in friend.uid) % len(AVATARS)]
            d.rounded_rectangle([7, y + 4, 25, y + 22], radius=4, fill=color)
            initial = name[:1] or "?"
            fi = self.font(10)
            tw = d.textlength(initial, font=fi)
            d.text((16 - tw / 2, y + 6), initial, font=fi, fill=(255, 255, 255))

            f11 = self.font(11)
            bold = friend.unread > 0
            d.text((31, y + 1), clip(d, name, f11, 168), font=f11,
                   fill=TEXT if bold else (200, 206, 213))
            f8 = self.font(8)
            d.text((31, y + 15), clip(d, clean(friend.preview()), f8, 200),
                   font=f8, fill=DIM if not bold else (186, 194, 202))
            if friend.unread:
                self._badge(d, W - 8 - 22, y + 6, friend.unread)
            else:
                t = model.fmt_time(friend.last_ts)
                d.text((W - PAD - d.textlength(t, font=f8), y + 2), t,
                       font=f8, fill=FAINT)

        d.rectangle([0, H - FOOT_H, W, H], fill=HEADER_BG)
        f8 = self.font(8)
        d.text((PAD, H - 13),
               "Enter 开 F2 邀请 F3 备注 Del 删 F1 帮助 F5 重登",
               font=f8, fill=FAINT)
        if len(friends) > visible:
            pos = "%d/%d" % (app.sel + 1, len(friends))
            d.text((W - PAD - d.textlength(pos, font=f8), H - 13),
                   pos, font=f8, fill=DIM)

    # ------------------------------------------------------------------ chat
    def chat(self, d, app) -> None:
        d.rectangle([0, 0, W, H], fill=BG)
        friend = app.active_friend()
        if friend is None:
            self.friends(d, app)
            return
        self.header(d, friend.display_name(), app.channel_text(friend), 0)

        bar_h = CAND_H + INPUT_H
        body_top = HEADER_H + 1
        body_bottom = H - bar_h
        lines = []
        with app.lock:
            messages = list(friend.messages)
        for msg in messages:
            if msg.who == "me":
                prefix, color = "我: ", ME_TEXT
            elif msg.who == "sys":
                prefix, color = "· ", YELLOW
            else:
                prefix, color = "", TEXT
            for ln in self.wrap(d, prefix + msg.text, self.font(11), W - 10):
                lines.append((ln, color))
        max_lines = max(1, (body_bottom - body_top) // LINE_H)
        app.scroll = max(0, min(app.scroll, max(0, len(lines) - max_lines)))
        start = max(0, len(lines) - max_lines - app.scroll)
        y = body_top + 1
        for text, color in lines[start:start + max_lines]:
            d.text((PAD, y), text, font=self.font(11), fill=color)
            y += LINE_H

        if not messages:
            d.text((PAD, body_top + 4), "对方发来的消息会显示在这里。",
                   font=self.font(9), fill=FAINT)
            d.text((PAD, body_top + 20), "输入拼音，按 Tab 变汉字。",
                   font=self.font(9), fill=(110, 118, 126))

        self._input_bar(d, app, friend, bar_h)

    def _input_bar(self, d, app, friend, bar_h: int) -> None:
        top = H - bar_h
        d.rectangle([0, top, W, H], fill=(22, 26, 32))
        d.line([0, top, W, top], fill=(48, 56, 66))
        f10 = self.font(10)
        f8 = self.font(8)
        cand_top = top + 1
        input_top = top + CAND_H

        if app.conv:
            page = app.conv.get("page", 0)
            shown = app.conv["cands"][page * 3:(page + 1) * 3]
            x = PAD
            for i, cand in enumerate(shown, start=1):
                label = "%d %s" % (i, cand)
                room = W - 44 - x
                if room < 18:
                    break
                d.text((x, cand_top), clip(d, label, f10, room), font=f10, fill=YELLOW)
                x += min(d.textlength(label, font=f10), room) + 8
            pages = max(1, (len(app.conv["cands"]) + 2) // 3)
            if pages > 1:
                tip = "%d/%d 0翻" % (page + 1, pages)
                d.text((W - PAD - d.textlength(tip, font=f10), cand_top), tip,
                       font=f10, fill=FAINT)
        else:
            tip = "拼音 → Tab 转汉字 · 1/2/3 选词 · 0 翻页"
            d.text((PAD, cand_top), tip, font=f10, fill=FAINT)
            if app.pinyin_tail():
                more = "Tab 转"
                d.text((W - PAD - d.textlength(more, font=f10), cand_top), more,
                       font=f10, fill=DIM)

        fy = input_top + 3
        f12 = self.font(12)
        d.text((PAD, fy), ">", font=f12, fill=ACCENT)
        width = W - 2 * PAD - 18
        show = app.input
        while show and d.textlength(show, font=f12) > width:
            show = show[1:]
        d.text((PAD + 14, fy), show, font=f12, fill=TEXT)
        cx = PAD + 14 + d.textlength(show, font=f12) + 1
        if app.blink_on:
            d.line([cx, fy + 1, cx, fy + 13], fill=ACCENT)
        if app.conv:
            pass
        elif app.ime is None:
            d.text((W - PAD - d.textlength("无输入法", font=f8), fy + 2),
                   "无输入法", font=f8, fill=RED)

    # ------------------------------------------------------------------ invite
    def invite(self, d, qr: str, state: str, note: str) -> None:
        d.rectangle([0, 0, W, H], fill=BG)
        self.header(d, "邀请好友", "等待扫码" if state != "confirmed" else "已连接")
        box_x, box_y, box = 6, 19, 148
        d.rectangle([box_x - 2, box_y - 2, box_x + box + 2, box_y + box + 2],
                    fill=(245, 246, 248))
        if qr:
            self._qr(d, qr, box_x, box_y, box)
        else:
            d.rectangle([box_x, box_y, box_x + box, box_y + box], fill=(28, 32, 38))
            f = self.font(10)
            msg = "获取二维码…" if state == "loading" else "无二维码"
            tw = d.textlength(msg, font=f)
            d.text((box_x + (box - tw) / 2, box_y + box / 2 - 8), msg,
                   font=f, fill=DIM)

        x = box_x + box + 8
        f11, f9, f8 = self.font(11), self.font(9), self.font(8)
        d.text((x, 20), "好友扫码", font=f11, fill=TEXT)
        d.text((x, 40), "① 微信扫码", font=f9, fill=DIM)
        d.text((x, 54), "② 确认授权", font=f9, fill=DIM)
        d.text((x, 68), "③ 自动连接", font=f9, fill=DIM)

        if state == "wait":
            label, col = "等待好友扫码…", YELLOW
        elif state == "confirmed":
            label, col = "已连接", ACCENT
        elif state == "expired":
            label, col = "二维码过期", RED
        elif state == "error":
            label, col = "获取失败", RED
        else:
            label, col = "准备中…", DIM
        d.text((x, 92), label, font=self.font(10), fill=col)
        if note:
            d.text((x, 108), clip(d, note, f8, W - x - 6), font=f8, fill=FAINT)
        d.text((x, 124), "务必让好友扫，", font=f8, fill=FAINT)
        d.text((x, 136), "自己的微信会失效", font=f8, fill=(230, 150, 120))
        d.text((x, 154), "Enter 重取 Esc 返回", font=f8, fill=FAINT)

    # ------------------------------------------------------------------ dialogs
    def dialog(self, d, title: str, prompt: str, text: str, hint: str) -> None:
        self._dim(d)
        pw, ph = 284, 96
        x, y = (W - pw) // 2, (H - ph) // 2
        d.rounded_rectangle([x, y, x + pw, y + ph], radius=8, fill=PANEL,
                            outline=(70, 80, 92))
        d.text((x + 12, y + 8), title, font=self.font(11), fill=ACCENT)
        d.text((x + 12, y + 27), prompt, font=self.font(9), fill=DIM)
        box = [x + 12, y + 43, x + pw - 12, y + 67]
        d.rounded_rectangle(box, radius=4, fill=(20, 24, 30),
                            outline=(60, 68, 80))
        f11 = self.font(11)
        show = text
        while show and d.textlength(show, font=f11) > box[2] - box[0] - 12:
            show = show[1:]
        d.text((box[0] + 6, y + 48), show, font=f11, fill=TEXT)
        cx = box[0] + 6 + d.textlength(show, font=f11) + 1
        if self.blink_on:
            d.line([cx, y + 50, cx, y + 64], fill=ACCENT)
        d.text((x + 12, y + 78), hint, font=self.font(8), fill=FAINT)

    def help(self, d, app) -> None:
        self._dim(d)
        pw, ph = 304, 148
        x, y = (W - pw) // 2, (H - ph) // 2
        d.rounded_rectangle([x, y, x + pw, y + ph], radius=8, fill=PANEL,
                            outline=(70, 80, 92))
        d.text((x + 12, y + 7), "微信 · 按键说明", font=self.font(11), fill=ACCENT)
        rows = [
            ("好友列表", "↑↓ 选择 · Enter 打开 · F2 邀请好友 · F3 备注"),
            ("", "Del / F8 删除 · F5 重新扫码 · Esc 退出"),
            ("邀请好友", "好友微信扫码确认后，可直接发消息给他"),
            ("聊天", "Enter 发送 · ↑↓ 翻看 · Esc 返回"),
            ("中文输入", "输入拼音 · Tab 转汉字 · Enter 发送"),
            ("", "1/2/3 选词 · 0 翻页 · Esc 取消拼音"),
            ("登录", "Enter 刷新二维码 · 扫码后自动进入"),
        ]
        f9 = self.font(9)
        yy = y + 26
        for head, body in rows:
            if head:
                d.text((x + 12, yy), head, font=f9, fill=CYAN)
            d.text((x + 62, yy), body, font=f9, fill=TEXT if head else DIM)
            yy += 16
        d.text((x + 12, y + ph - 16), "任意键返回", font=self.font(8), fill=FAINT)

    def _dim(self, d) -> None:
        d.rectangle([0, 0, W, H], fill=(8, 10, 13))

    # ------------------------------------------------------------------ toast
    def toast(self, d, text: str, screen: str = "") -> None:
        if not text:
            return
        f = self.font(9)
        text = clean(text)
        tw = d.textlength(text, font=f)
        w = min(W - 20, tw + 16)
        x = (W - w) / 2
        if screen == "chat":
            y = H - INPUT_H - CAND_H - 22
        elif screen in ("friends",):
            y = H - FOOT_H - 22
        else:
            y = H - 54
        d.rounded_rectangle([x, y, x + w, y + 17], radius=6, fill=(52, 60, 70))
        d.text((x + 8, y + 1), clip(d, text, f, int(w) - 16), font=f, fill=TEXT)

    # ------------------------------------------------------------------ entry
    def draw(self, app) -> Image.Image:
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)
        if app.screen == "login":
            self.login(d, app.qr_url, app.login_state, app.login_note)
        elif app.screen == "friends":
            self.friends(d, app)
        elif app.screen == "chat":
            self.chat(d, app)
        elif app.screen == "invite":
            self.invite(d, app.invite_url, app.invite_state, app.invite_note)
        elif app.screen == "rename":
            self.friends(d, app)
            self.dialog(d, "备注名", "给这位好友起个名字（可用拼音输入）",
                        app.input, "Enter 保存 · Esc 取消")
        elif app.screen == "confirm_delete":
            self.friends(d, app)
            self.dialog(d, "删除好友", "删除后聊天记录也会一起清掉",
                        "", "Enter 确认 · Esc 取消")
        elif app.screen == "confirm_logout":
            self.friends(d, app)
            self.dialog(d, "重新扫码登录", "会清除本机登录凭证，聊天记录保留",
                        "", "Enter 确认 · Esc 取消")
        elif app.screen == "help":
            self.help(d, app)
        self.toast(d, app.toast, app.screen)
        return img
