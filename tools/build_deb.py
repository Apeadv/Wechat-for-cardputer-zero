#!/usr/bin/env python3
"""Build an installable Debian package for the Cardputer Zero.

Pure Python: writes the `ar` archive itself, so it works on Windows without
dpkg.  The result is a normal `.deb` that `apt install ./pkg.deb` accepts and
that the APPLaunch AppStore can publish.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tarfile
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")

APP_DIR = "/opt/wechat-zero"
LAUNCH_BIN = "/usr/share/APPLaunch/bin/wechat-zero"
DESKTOP = "/usr/share/APPLaunch/applications/wechat-zero.desktop"
ICON = "/usr/share/APPLaunch/share/images/wechat-zero.png"
DOC_DIR = "/usr/share/doc/wechat-zero"

APP_FILES = ("wechat.py", "README.md", "LICENSE", "CHANGELOG.md", "VERSION")
APP_TREES = ("wz", "vendor", "assets")


def version() -> str:
    with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as fh:
        return fh.read().strip()


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write(path: str, data: bytes, mode: int = 0o644) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    os.chmod(path, mode)


def _copy(src: str, dst: str, mode: int = 0o644) -> None:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)
    os.chmod(dst, mode)


def _stage(stage_root: str) -> None:
    # application payload
    app_root = stage_root + APP_DIR
    os.makedirs(app_root, exist_ok=True)
    for name in APP_FILES:
        src = os.path.join(ROOT, name)
        if os.path.exists(src):
            _copy(src, os.path.join(app_root, name))
    for tree in APP_TREES:
        src = os.path.join(ROOT, tree)
        if not os.path.isdir(src):
            continue
        for base, dirs, files in os.walk(src):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            rel = os.path.relpath(base, ROOT)
            os.makedirs(os.path.join(app_root, rel), exist_ok=True)
            for f in files:
                if f.endswith(".pyc"):
                    continue
                _copy(os.path.join(base, f), os.path.join(app_root, rel, f))
    # launcher (APPLaunch + PATH)
    launcher = open(os.path.join(ROOT, "bin", "wechat-zero"), "rb").read()
    _write(stage_root + LAUNCH_BIN, launcher, 0o755)
    _write(stage_root + "/usr/bin/wechat-zero", launcher, 0o755)
    _copy(os.path.join(ROOT, "packaging", "wechat-zero.desktop"),
          stage_root + DESKTOP)
    _copy(os.path.join(ROOT, "packaging", "wechat-zero.desktop"),
          stage_root + "/usr/share/applications/wechat-zero.desktop")
    icon = os.path.join(ROOT, "packaging", "icon-80.png")
    if not os.path.exists(icon):
        icon = os.path.join(ROOT, "assets", "icon-128.png")
    _copy(icon, stage_root + ICON)
    for name in ("README.md", "LICENSE", "CHANGELOG.md"):
        src = os.path.join(ROOT, name)
        if os.path.exists(src):
            _copy(src, os.path.join(stage_root + DOC_DIR, name))
    _write(stage_root + DOC_DIR + "/copyright",
           ("Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n"
            "Upstream-Name: wechat-zero\n"
            "Source: https://github.com/gywan94/wechat-zero\n\n"
            "Files: *\nCopyright: 2026 gywan94\nLicense: MIT\n").encode("utf-8"))


EXEC_ARCS = {"./postinst", "./usr/bin/wechat-zero",
             "./usr/share/APPLaunch/bin/wechat-zero"}


def _add_entry(tar: tarfile.TarFile, full: str, arc: str) -> None:
    info = tar.gettarinfo(full, arcname=arc)
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    info.mtime = 0
    info.mode = 0o755 if (info.isdir() or arc in EXEC_ARCS) else 0o644
    if info.isfile():
        with open(full, "rb") as fh:
            tar.addfile(info, fh)
    else:
        tar.addfile(info)


def _tar_from_dir(root: str, out_path: str, names: list[str] | None = None) -> None:
    with tarfile.open(out_path, "w:gz", format=tarfile.GNU_FORMAT) as tar:
        if names is not None:
            for name in names:
                _add_entry(tar, os.path.join(root, name), "./" + name)
            return
        for base, dirs, files in os.walk(root):
            dirs.sort()
            rel = os.path.relpath(base, root).replace("\\", "/")
            arc_dir = "." if rel == "." else "./" + rel
            if arc_dir != ".":
                _add_entry(tar, base, arc_dir)
            for f in sorted(files):
                full = os.path.join(base, f)
                arc = ("./" + f) if rel == "." else ("./" + rel + "/" + f)
                _add_entry(tar, full, arc)


def _md5sums(stage_root: str) -> bytes:
    lines = []
    for base, dirs, files in os.walk(stage_root):
        dirs.sort()
        for f in sorted(files):
            full = os.path.join(base, f)
            rel = os.path.relpath(full, stage_root).replace("\\", "/")
            h = hashlib.md5()
            with open(full, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            lines.append("%s  %s\n" % (h.hexdigest(), rel))
    return "".join(lines).encode("utf-8")


def _control(ver: str, installed_kb: int, release: dict) -> bytes:
    owner = release.get("github_owner", "gywan94")
    repo = release.get("github_repo", "wechat-zero")
    maintainer = "%s <%s>" % (release.get("author_display", owner),
                              release.get("author_email", owner + "@users.noreply.github.com"))
    text = """Package: {pkg}
Version: {ver}
Architecture: all
Maintainer: {maint}
Installed-Size: {size}
Depends: python3 (>= 3.9), python3-pil, python3-evdev
Recommends: fonts-noto-cjk | fonts-wqy-zenhei, python3-numpy
Section: net
Priority: optional
Homepage: https://github.com/{owner}/{repo}
Description: WeChat iLink client for the M5Stack Cardputer Zero
 Chat over WeChat iLink on the Cardputer Zero, with an offline pinyin IME,
 QR login, friend invite QR codes and multiple conversation channels.
""".format(pkg=release.get("package_name", "wechat-zero"), ver=ver,
           maint=maintainer, size=installed_kb, owner=owner, repo=repo)
    return text.encode("utf-8")


def _postinst() -> bytes:
    return b"""#!/bin/sh
set -e
if [ -f /opt/wechat-zero/assets/ime.db ]; then
    python3 - <<'PY' || true
import sqlite3
con = sqlite3.connect("/opt/wechat-zero/assets/ime.db")
con.execute("CREATE INDEX IF NOT EXISTS words_py ON words(py)")
con.commit()
con.close()
PY
fi
update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
exit 0
"""


def _ar(path: str, members: list[tuple[str, bytes, int]]) -> None:
    with open(path, "wb") as fh:
        fh.write(b"!<arch>\n")
        for name, data, mode in members:
            header = ("%-16s%-12s%-6s%-6s%-8s%-10s`\n" % (
                name, "0", "0", "0", "%o" % mode, len(data))).encode("ascii")
            assert len(header) == 60, len(header)
            fh.write(header)
            fh.write(data)
            if len(data) % 2:
                fh.write(b"\n")


def build(out_dir: str = "", release: dict | None = None) -> dict:
    release = release or {}
    ver = version()
    out_dir = out_dir or DIST
    os.makedirs(out_dir, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wz-deb-", dir=out_dir) as tmp:
        stage = os.path.join(tmp, "stage")
        _stage(stage)
        installed_kb = 0
        for base, _dirs, files in os.walk(stage):
            for f in files:
                installed_kb += os.path.getsize(os.path.join(base, f))
        installed_kb = max(1, installed_kb // 1024)

        ctrl = os.path.join(tmp, "control")
        os.makedirs(ctrl)
        _write(os.path.join(ctrl, "control"), _control(ver, installed_kb, release))
        _write(os.path.join(ctrl, "postinst"), _postinst(), 0o755)
        _write(os.path.join(ctrl, "md5sums"), _md5sums(stage))
        control_tar = os.path.join(tmp, "control.tar.gz")
        data_tar = os.path.join(tmp, "data.tar.gz")
        _tar_from_dir(ctrl, control_tar, ["control", "postinst", "md5sums"])
        _tar_from_dir(stage, data_tar)

        deb = os.path.join(out_dir, "wechat-zero_%s_all.deb" % ver)
        _ar(deb, [
            ("debian-binary", b"2.0\n", 0o100644),
            ("control.tar.gz", open(control_tar, "rb").read(), 0o100644),
            ("data.tar.gz", open(data_tar, "rb").read(), 0o100644),
        ])
    return {"path": deb, "sha256": _sha256(deb), "size": os.path.getsize(deb),
            "version": ver, "architecture": "all"}


if __name__ == "__main__":
    info = build()
    print("%s  %.1f KB  sha256=%s" % (info["path"], info["size"] / 1024.0,
                                      info["sha256"]))
