"""Keyboard input: evdev on the Cardputer Zero, scripted input for the host sim."""

from __future__ import annotations

import glob
import os
import select
import time

KEY_ESC = 1
KEY_BACKSPACE = 14
KEY_TAB = 15
KEY_ENTER = 28
KEY_LEFTCTRL = 29
KEY_LEFTSHIFT = 42
KEY_RIGHTSHIFT = 54
KEY_F1 = 59
KEY_F2 = 60
KEY_F3 = 61
KEY_F4 = 62
KEY_F5 = 63
KEY_F6 = 64
KEY_F7 = 65
KEY_F8 = 66
KEY_UP = 103
KEY_DOWN = 108
KEY_DELETE = 111

CHARS = {
    16: "q", 17: "w", 18: "e", 19: "r", 20: "t", 21: "y", 22: "u", 23: "i", 24: "o", 25: "p",
    30: "a", 31: "s", 32: "d", 33: "f", 34: "g", 35: "h", 36: "j", 37: "k", 38: "l",
    44: "z", 45: "x", 46: "c", 47: "v", 48: "b", 49: "n", 50: "m",
    2: "1", 3: "2", 4: "3", 5: "4", 6: "5", 7: "6", 8: "7", 9: "8", 10: "9", 11: "0",
    57: " ", 51: ",", 52: ".", 12: "-", 13: "=", 39: ";", 40: "'", 53: "/",
    55: "*", 86: "<",
}
SHIFTED = {52: "?", 51: "!", 11: ")", 9: "(", 8: "*", 12: "_", 13: "+",
           39: ":", 40: '"', 86: ">"}


class Keys:
    """Reads every evdev device that reports key events."""

    def __init__(self, explicit: str = ""):
        self.devices = []
        self.explicit = explicit
        self.seen = set()
        self.last_scan = 0.0
        try:
            import evdev
        except ImportError:
            return
        self.evdev = evdev
        self._scan()

    def _paths(self):
        if self.explicit:
            return [self.explicit]
        return (glob.glob("/dev/input/by-path/platform-*event*")
                + sorted(glob.glob("/dev/input/event*")))

    def _scan(self) -> None:
        """Open any key-capable event device that appeared since the last scan.

        APPLaunch can start before the USB/BLE keyboard enumerates, and tests
        inject a virtual keyboard after boot, so re-scanning is needed.
        """
        if not hasattr(self, "evdev"):
            return
        self.last_scan = time.time()
        for path in self._paths():
            real = os.path.realpath(path)
            if real in self.seen:
                continue
            self.seen.add(real)
            try:
                dev = self.evdev.InputDevice(real)
                caps = dev.capabilities(absinfo=False)
                if self.evdev.ecodes.EV_KEY in caps:
                    self.devices.append(dev)
                else:
                    dev.close()
            except OSError:
                continue

    @property
    def available(self) -> bool:
        return bool(self.devices)

    def poll(self) -> list:
        out = []
        now = time.time()
        if now - self.last_scan > 2.0:
            self._scan()
        if not self.devices:
            return out
        try:
            ready, _, _ = select.select([d.fd for d in self.devices], [], [], 0)
        except (OSError, ValueError):
            return out
        for dev in self.devices:
            if dev.fd not in ready:
                continue
            try:
                for ev in dev.read():
                    if ev.type == 1:
                        out.append((ev.code, ev.value))
            except OSError:
                continue
        return out


class ScriptedKeys:
    """Deterministic keyboard for the host simulator / tests.

    Feed a list of (code, value) pairs; value 1 = press, 0 = release.  The
    helper `tap()` produces the two events.  `queue_text()` types ASCII text.
    """

    def __init__(self, events=None):
        self.events = list(events or [])
        self.available = True

    @staticmethod
    def _code_for(ch: str):
        for code, c in CHARS.items():
            if c == ch:
                return code, 0
        for code, c in SHIFTED.items():
            if c == ch:
                return code, 1
        return None

    def tap(self, code: int, shift: bool = False) -> None:
        if shift:
            self.events.append((KEY_LEFTSHIFT, 1))
        self.events.append((code, 1))
        self.events.append((code, 0))
        if shift:
            self.events.append((KEY_LEFTSHIFT, 0))

    def type_text(self, text: str) -> None:
        for ch in text:
            if ch == "\n":
                self.tap(KEY_ENTER)
            elif ch == "\t":
                self.tap(KEY_TAB)
            else:
                hit = self._code_for(ch)
                if hit:
                    self.tap(hit[0], shift=bool(hit[1]))

    def poll(self) -> list:
        out, self.events = self.events, []
        return out
