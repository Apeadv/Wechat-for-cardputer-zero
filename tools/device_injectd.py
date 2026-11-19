#!/usr/bin/env python3
"""Persistent virtual keyboard for on-device tests.

Creates one uinput device at startup (so the app enumerates it), then watches
/tmp/wz-keys for lines of tokens and injects them.

    python3 device_injectd.py &          # as root
    echo "ENTER" > /tmp/wz-keys
    echo "jintiantianqi ENTER" > /tmp/wz-keys
"""

import fcntl
import os
import struct
import time

UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
EV_SYN, EV_KEY = 0, 1

SPECIAL = {
    "ENTER": 28, "ESC": 1, "TAB": 15, "BACKSPACE": 14, "UP": 103,
    "DOWN": 108, "LEFT": 105, "RIGHT": 106, "SPACE": 57, "DEL": 111,
    "F1": 59, "F2": 60, "F3": 61, "F5": 63, "F8": 66,
}
CHARS = dict(zip("qwertyuiop", range(16, 26)))
CHARS.update(dict(zip("asdfghjkl", range(30, 39))))
CHARS.update(dict(zip("zxcvbnm", range(44, 51))))
CHARS.update(dict(zip("1234567890", range(2, 12))))

KEYS = "/tmp/wz-keys"


def emit(fd, code):
    now = time.time()
    os.write(fd, struct.pack("llHHi", int(now), int((now % 1) * 1e6), EV_KEY, code, 1))
    os.write(fd, struct.pack("llHHi", int(now), int((now % 1) * 1e6) + 1000, EV_SYN, 0, 0))
    time.sleep(0.03)
    os.write(fd, struct.pack("llHHi", int(now), int((now % 1) * 1e6) + 2000, EV_KEY, code, 0))
    os.write(fd, struct.pack("llHHi", int(now), int((now % 1) * 1e6) + 3000, EV_SYN, 0, 0))
    time.sleep(0.08)


def main():
    fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_SYN)
    codes = set(SPECIAL.values()) | set(CHARS.values())
    for c in sorted(codes):
        fcntl.ioctl(fd, UI_SET_KEYBIT, c)
    buf = bytearray(1116)
    name = b"wz-test-kbd"
    buf[0:len(name)] = name
    struct.pack_into("HHHH", buf, 80, 3, 0x1, 0x2, 1)
    os.write(fd, bytes(buf))
    fcntl.ioctl(fd, UI_DEV_CREATE)
    open(KEYS, "w").close()
    print("virtual keyboard ready", flush=True)
    try:
        while True:
            try:
                lines = open(KEYS, encoding="utf-8").read().splitlines()
            except OSError:
                lines = []
            if lines:
                open(KEYS, "w").close()
                for line in lines:
                    for tok in line.split():
                        if tok.upper() in SPECIAL:
                            emit(fd, SPECIAL[tok.upper()])
                        else:
                            for ch in tok:
                                if ch.lower() in CHARS:
                                    emit(fd, CHARS[ch.lower()])
                                elif ch == " ":
                                    emit(fd, 57)
            time.sleep(0.12)
    finally:
        fcntl.ioctl(fd, UI_DEV_DESTROY)
        os.close(fd)


if __name__ == "__main__":
    main()
