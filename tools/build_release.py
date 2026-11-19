#!/usr/bin/env python3
"""Build every release artifact.

  * installable .deb (also used by the AppStore)
  * GitHub source archives (tar.gz + zip)
  * AppStore submission bundle (meta.json, screenshots, icon, release manifest)
  * SHA256SUMS + release notes + one-line installer

Usage:
    python tools/build_release.py
    python tools/build_release.py --owner myname --repo my-repo --version 1.1.0
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools import build_deb  # noqa: E402

DIST = os.path.join(ROOT, "dist")
RELEASE_TAG = "v%s"


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_config() -> dict:
    with open(os.path.join(ROOT, "release.json"), encoding="utf-8") as fh:
        return json.load(fh)


def write_app_builder(cfg: dict, ver: str) -> dict:
    data = {
        "package_name": cfg["package_name"],
        "version": ver,
        "app_name": cfg["app_name"],
        "bin_name": cfg["package_name"],
        "description": "WeChat iLink client with offline pinyin input",
        "store": {
            "summary": cfg["summary"][:80],
            "description": (
                "WeChat Zero brings WeChat iLink chat to the M5Stack Cardputer Zero. "
                "Scan a QR code to log in, reply to incoming WeChat messages, and invite "
                "a friend by showing a second QR: once they confirm, the device can send "
                "them messages proactively. A built-in offline pinyin IME (77k entries) "
                "handles Chinese input on the 46-key keyboard, with multiple conversation "
                "channels, unread badges, remarks and persisted history."
            ),
            "categories": cfg["categories"],
            "screenshots": [
                "packaging/screenshots/screenshot-0.png",
                "packaging/screenshots/screenshot-1.png",
                "packaging/screenshots/screenshot-2.png",
                "packaging/screenshots/screenshot-3.png",
            ],
            "icon": "packaging/icon-256.png",
            "license": cfg["license"],
            "source_repo": "https://github.com/%s/%s" % (cfg["github_owner"], cfg["github_repo"]),
            "author": {"github": cfg["github_owner"],
                       "display_name": cfg["author_display"]},
            "share_code": cfg["share_code"],
            "permissions": {
                "camera": False, "microphone": False, "imu": False,
                "network": True, "additional_hardware": False,
                "background_service": False, "external_display": False,
            },
            "locales": {
                "zh-CN": {
                    "title": cfg["title_zh"],
                    "summary": cfg["summary_zh"][:80],
                }
            },
        },
    }
    with open(os.path.join(ROOT, "app-builder.json"), "w", encoding="utf-8",
              newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return data


def copy_screenshots() -> list[str]:
    src = os.path.join(ROOT, "preview")
    picks = [
        ("device-23-invite.png", "screenshot-0.png"),
        ("device-24-invited-chat.png", "screenshot-1.png"),
        ("device-25-proactive-sent.png", "screenshot-2.png"),
        ("chat-ime.png", "screenshot-3.png"),
    ]
    out_dir = os.path.join(ROOT, "packaging", "screenshots")
    os.makedirs(out_dir, exist_ok=True)
    names = []
    for source, target in picks:
        full = os.path.join(src, source)
        if not os.path.exists(full):
            continue
        shutil.copyfile(full, os.path.join(out_dir, target))
        names.append(target)
    return names


def make_source_archives(cfg: dict, ver: str, out_dir: str) -> list[str]:
    prefix = "wechat-zero-%s" % ver
    tar_path = os.path.join(out_dir, "wechat-zero-%s-source.tar.gz" % ver)
    zip_path = os.path.join(out_dir, "wechat-zero-%s-source.zip" % ver)
    skip_dirs = {".git", "dist", "__pycache__", ".tmp"}
    skip_files = {"state.json"}

    def include(rel: str) -> bool:
        parts = rel.replace("\\", "/").split("/")
        if any(p in skip_dirs for p in parts):
            return False
        if os.path.basename(rel) in skip_files or rel.endswith(".pyc"):
            return False
        return True

    files = []
    for base, dirs, names in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if d not in skip_dirs)
        for f in sorted(names):
            full = os.path.join(base, f)
            rel = os.path.relpath(full, ROOT)
            if include(rel):
                files.append((full, rel.replace("\\", "/")))

    with tarfile.open(tar_path, "w:gz", format=tarfile.GNU_FORMAT) as tar:
        for full, rel in files:
            info = tar.gettarinfo(full, arcname="%s/%s" % (prefix, rel))
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            info.mtime = int(os.path.getmtime(full))
            with open(full, "rb") as fh:
                tar.addfile(info, fh)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for full, rel in files:
            z.write(full, "%s/%s" % (prefix, rel))
    return [tar_path, zip_path]


def make_store_bundle(cfg: dict, ver: str, deb: dict, out_dir: str) -> str:
    store = os.path.join(out_dir, "store")
    os.makedirs(os.path.join(store, "screenshots"), exist_ok=True)
    screenshots = copy_screenshots()
    for name in screenshots:
        shutil.copyfile(os.path.join(ROOT, "packaging", "screenshots", name),
                        os.path.join(store, "screenshots", name))
    shutil.copyfile(os.path.join(ROOT, "packaging", "icon-256.png"),
                    os.path.join(store, "wechat-zero_icon.png"))
    shutil.copyfile(deb["path"], os.path.join(store, os.path.basename(deb["path"])))

    now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    meta = {
        "title": cfg["app_name"],
        "summary": cfg["summary"],
        "description": (
            "WeChat Zero is a native WeChat iLink client for the M5Stack Cardputer Zero. "
            "Scan the login QR with your own WeChat, then reply to friends who message the "
            "bot. Press F2 to show an invite QR: a friend scans it, confirms on their phone, "
            "and the device gets a dedicated channel it can proactively message. Includes "
            "an offline pinyin IME, unread badges, remarks, and persisted history."
        ),
        "categories": cfg["categories"],
        "license": cfg["license"],
        "share_code": cfg["share_code"],
        "source_repo": "https://github.com/%s/%s" % (cfg["github_owner"], cfg["github_repo"]),
        "permissions": {
            "additional_hardware": False, "background_service": False,
            "camera": False, "external_display": False, "imu": False,
            "microphone": False, "network": True,
        },
        "author": {"display_name": cfg["author_display"],
                   "github": cfg["github_owner"]},
        "screenshots": ["screenshots/%s" % n for n in screenshots],
        "icon": "wechat-zero_icon.png",
        "published_at": now,
        "updated_at": now,
    }
    with open(os.path.join(store, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    manifest = {
        "filename": os.path.basename(deb["path"]),
        "url": "https://github.com/%s/%s/releases/download/%s/%s" % (
            cfg["github_owner"], cfg["github_repo"], RELEASE_TAG % ver,
            os.path.basename(deb["path"])),
        "sha256": deb["sha256"],
        "size": deb["size"],
        "package": cfg["package_name"],
        "version": ver,
        "architecture": "all",
        "uploaded_by": cfg["github_owner"],
        "uploader_email": cfg["author_email"],
    }
    name = "%s_%s_all.deb.release.json" % (cfg["package_name"], ver)
    with open(os.path.join(store, name), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return store


def make_get_sh(cfg: dict, ver: str, out_dir: str) -> str:
    path = os.path.join(out_dir, "get.sh")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("""#!/bin/sh
# Install / upgrade WeChat Zero on a Cardputer Zero.
set -eu
REPO="${REPO:-%s/%s}"
VERSION="${VERSION:-%s}"
URL="https://github.com/$REPO/releases/download/v$VERSION/wechat-zero_${VERSION}_all.deb"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
echo "Downloading $URL"
curl -fL --retry 3 -o "$TMP/wechat-zero.deb" "$URL"
sudo apt install -y "$TMP/wechat-zero.deb"
systemctl --user restart APPLaunch 2>/dev/null || true
echo "Installed. Open APPLaunch -> 微信"
""" % (cfg["github_owner"], cfg["github_repo"], ver))
    os.chmod(path, 0o755)
    return path


def release_notes(cfg: dict, ver: str) -> str:
    return """# WeChat Zero v{ver}

WeChat iLink client for the **M5Stack Cardputer Zero**, with offline pinyin input,
QR friend invites and multiple conversation channels.

## Changes

- **IME**: removed the 0.7 s idle auto-convert. Typing pinyin no longer turns into
  Chinese on its own; press **Tab** to convert (Enter still converts a trailing
  pinyin tail before sending).
- Added the official `msg/notifystart` / `msg/notifystop` lifecycle calls and
  `bot_agent`, so a freshly invited channel becomes ready to send.
- Friend invites are blocked for your own WeChat (one WeChat cannot own two bot
  channels); dead self-invite channels are cleaned up and logged.
- Send errors now show the server reason and are written to
  `~/.config/wechat-zero/app.log`.
- Release engineering: `.deb`, GitHub archives, AppStore bundle, `get.sh`.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/{owner}/{repo}/main/get.sh | sh
```

or download `wechat-zero_{ver}_all.deb` and run:

```bash
sudo apt install ./wechat-zero_{ver}_all.deb
systemctl --user restart APPLaunch
```

Then open **APPLaunch → 微信**.

## Notes

- Scan the first QR with **your own** WeChat.
- Press **F2** to invite a friend; the friend must scan with **their** phone and
  confirm. Do not scan the invite QR yourself.
- The iLink API allows text only, and roughly 7 messages per 5 minutes per channel.

Source: https://github.com/{owner}/{repo}
""".format(owner=cfg["github_owner"], repo=cfg["github_repo"], ver=ver)


def build(out_dir: str = "", cfg: dict | None = None, ver: str | None = None) -> dict:
    cfg = cfg or load_config()
    ver = ver or open(os.path.join(ROOT, "VERSION"), encoding="utf-8").read().strip()
    out_dir = out_dir or DIST
    os.makedirs(out_dir, exist_ok=True)
    github_dir = os.path.join(out_dir, "github")
    os.makedirs(github_dir, exist_ok=True)

    write_app_builder(cfg, ver)
    copy_screenshots()
    deb = build_deb.build(out_dir, release=cfg)
    sources = make_source_archives(cfg, ver, github_dir)
    store = make_store_bundle(cfg, ver, deb, out_dir)
    get_sh = make_get_sh(cfg, ver, github_dir)

    notes = release_notes(cfg, ver)
    notes_path = os.path.join(github_dir, "RELEASE_NOTES.md")
    with open(notes_path, "w", encoding="utf-8") as fh:
        fh.write(notes)

    shutil.copyfile(deb["path"], os.path.join(github_dir, os.path.basename(deb["path"])))
    shutil.copyfile(os.path.join(ROOT, "packaging", "icon-256.png"),
                    os.path.join(github_dir, "icon-256.png"))
    store_zip = os.path.join(github_dir, "wechat-zero-%s-store.zip" % ver)
    with zipfile.ZipFile(store_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for base, _dirs, names in os.walk(store):
            for n in names:
                full = os.path.join(base, n)
                z.write(full, os.path.relpath(full, store))
    checks = []
    for path in ([os.path.join(github_dir, os.path.basename(deb["path"]))]
                 + sources + [store_zip, get_sh]):
        checks.append("%s  %s" % (sha256(path), os.path.basename(path)))
    with open(os.path.join(github_dir, "SHA256SUMS"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(checks) + "\n")
    return {"deb": deb, "sources": sources, "store": store,
            "github": github_dir, "get_sh": get_sh,
            "notes": notes_path, "checksums": os.path.join(github_dir, "SHA256SUMS")}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="")
    parser.add_argument("--owner", default="")
    parser.add_argument("--repo", default="")
    parser.add_argument("--version", default="")
    args = parser.parse_args()
    cfg = load_config()
    if args.owner:
        cfg["github_owner"] = args.owner
    if args.repo:
        cfg["github_repo"] = args.repo
    info = build(args.out, cfg, args.version or None)
    print("deb     :", info["deb"]["path"], "%.1f KB" % (info["deb"]["size"] / 1024))
    for p in info["sources"]:
        print("source  :", p, "%.1f KB" % (os.path.getsize(p) / 1024))
    print("store   :", info["store"])
    print("github  :", info["github"])
    print("get.sh  :", info["get_sh"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
