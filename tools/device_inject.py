#!/usr/bin/env python3
"""Inject keystrokes through /dev/uinput (root) for on-device UI tests.

    python3 device_inject.py "jintiantianqi" TAB ENTER
    python3 device_inject.py ESC

Tokens: ENTER ESC TAB BACKSPACE UP DOWN, or literal ASCII text.
"""

import fcntl
import os
import struct
import sys
import time

UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
EV_SYN, EV_KEY = 0, 1

SPECIAL = {
    "ENTER": 28, "ESC": 1, "TAB": 15, "BACKSPACE": 14,
    "UP": 103, "DOWN": 108, "LEFT": 105, "RIGHT": 106, "SPACE": 57,
    "DEL": 111, "F1": 59, "F2": 60, "F3": 61, "F5": 63, "F8": 66,
}
CHARS = {
    "q": 16, "w": 17, "e": 18, "r": 19, "t": 20, "y": 21, "u": 22, "i": 23,
    "o": 24, "p": 25, "a": 30, "s": 31, "d": 32, "f": 33, "g": 34, "h": 35,
    "j": 36, "k": 37, "l": 38, "z": 44, "x": 45, "c": 46, "v": 47, "b": 48,
    "n": 49, "m": 50, "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7,
    "7": 8, "8": 9, "9": 10, "0": 11, ",": 51, ".": 52, "-": 12,
    "=": 13, ";": 39, "'": 40, "/": 53, "_": 12,
}


def tokens(argv):
    out = []
    for arg in argv:
        if arg.upper() in SPECIAL:
            out.append(SPECIAL[arg.upper()])
            continue
        for ch in arg:
            if ch.lower() in CHARS:
                out.append(CHARS[ch.lower()])
            elif ch == " ":
                out.append(57)
    return out


def main():
    codes = tokens(sys.argv[1:])
    if not codes:
        print("no keys")
        return 1
    fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_SYN)
    for c in sorted(set(codes)):
        fcntl.ioctl(fd, UI_SET_KEYBIT, c)
    buf = bytearray(1116)
    name = b"wz-test-kbd"
    buf[0:len(name)] = name
    struct.pack_into("HHHH", buf, 80, 3, 0x1, 0x2, 1)
    os.write(fd, bytes(buf))
    fcntl.ioctl(fd, UI_DEV_CREATE)
    time.sleep(1.0)

    def emit(t, c, v):
        now = time.time()
        os.write(fd, struct.pack("llHHi", int(now), int((now % 1) * 1e6), t, c, v))

    try:
        for c in codes:
            emit(EV_KEY, c, 1)
            emit(EV_SYN, 0, 0)
            time.sleep(0.03)
            emit(EV_KEY, c, 0)
            emit(EV_SYN, 0, 0)
            time.sleep(0.09)
        time.sleep(0.3)
    finally:
        fcntl.ioctl(fd, UI_DEV_DESTROY)
        os.close(fd)
    print("injected", len(codes), "keys")
    return 0


if __name__ == "__main__":
    sys.exit(main())
