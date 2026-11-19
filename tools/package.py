#!/usr/bin/env python3
"""Build the distributable tarball: dist/wechat-zero-<version>.tar.gz.

The archive is self-contained: `tar xzf ... && sudo bash install.sh` on the
device.  Executable bits are set explicitly because the archive may be built on
Windows, where the source files are not executable.
"""

from __future__ import annotations

import argparse
import os
import tarfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION = "1.1.0"
INCLUDE_FILES = ("wechat.py", "install.sh", "README.md", "VERSION", "LICENSE", "CHANGELOG.md")
INCLUDE_DIRS = ("wz", "vendor", "assets", "bin", "packaging")
EXEC_FILES = ("install.sh", "bin/wechat-zero")
SKIP_DIRS = {"__pycache__", ".tmp", ".git"}


def build(out_dir: str = "") -> str:
    out_dir = out_dir or os.path.join(ROOT, "dist")
    os.makedirs(out_dir, exist_ok=True)
    name = "wechat-zero-%s.tar.gz" % VERSION
    path = os.path.join(out_dir, name)
    prefix = "wechat-zero-%s" % VERSION
    with tarfile.open(path, "w:gz") as tar:
        def add(src: str, rel: str) -> None:
            arc = os.path.join(prefix, rel).replace("\\", "/")
            info = tar.gettarinfo(src, arcname=arc)
            if rel in EXEC_FILES:
                info.mode = 0o755
            if info.isfile():
                with open(src, "rb") as fh:
                    tar.addfile(info, fh)
            else:
                tar.addfile(info)

        for rel in INCLUDE_FILES:
            src = os.path.join(ROOT, rel)
            if os.path.exists(src):
                add(src, rel)
        for top in INCLUDE_DIRS:
            src = os.path.join(ROOT, top)
            if not os.path.isdir(src):
                continue
            for base, dirs, files in os.walk(src):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                for f in sorted(files):
                    full = os.path.join(base, f)
                    rel = os.path.relpath(full, ROOT).replace("\\", "/")
                    if f.endswith(".pyc"):
                        continue
                    add(full, rel)
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    path = build(args.out)
    print("%s  %.1f KB  %s" % (path, os.path.getsize(path) / 1024.0,
                               time.strftime("%Y-%m-%d %H:%M:%S")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
