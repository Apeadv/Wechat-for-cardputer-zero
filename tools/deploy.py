#!/usr/bin/env python3
"""Copy wechat-zero to a Cardputer Zero over SSH and install it.

    py tools/deploy.py --host 192.168.50.106 --user apead
    py tools/deploy.py --host 192.168.50.106 --dry-run

Uses the OpenSSH client (ssh/scp) and key auth.  If remote sudo needs a
password, put it in WECHAT_ZERO_SUDO_PASS (never on the command line).
"""

from __future__ import annotations

import argparse
import getpass
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools import package  # noqa: E402


def run(cmd, stdin_data=None, check=True):
    print("+ " + " ".join(cmd))
    proc = subprocess.run(cmd, input=stdin_data, text=True)
    if check and proc.returncode != 0:
        raise SystemExit("命令失败（exit %d）：%s" % (proc.returncode, " ".join(cmd)))
    return proc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="192.168.50.106")
    parser.add_argument("--user", default="apead")
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--key", default=os.path.expanduser("~/.ssh/id_ed25519_cardputer"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    tar = package.build()
    remote_tar = "/tmp/wechat-zero.tar.gz"
    install_dir = "/tmp/wechat-zero-install"
    print("包：%s（%.1f KB）" % (tar, os.path.getsize(tar) / 1024.0))

    ssh_base = ["ssh", "-p", str(args.port), "-o", "StrictHostKeyChecking=accept-new"]
    if os.path.exists(args.key):
        ssh_base += ["-i", args.key]
    ssh_base += ["%s@%s" % (args.user, args.host)]
    scp = ["scp", "-P", str(args.port), "-o", "StrictHostKeyChecking=accept-new"]
    if os.path.exists(args.key):
        scp += ["-i", args.key]
    scp += [tar, "%s@%s:%s" % (args.user, args.host, remote_tar)]

    unpack = ("rm -rf %s && mkdir -p %s && tar -xzf %s -C %s --strip-components=1"
              % (install_dir, install_dir, remote_tar, install_dir))

    if args.dry_run:
        print("\n[dry-run] 将要执行：")
        print("  " + " ".join(scp))
        print("  " + " ".join(ssh_base) + " '" + unpack + " && cd " + install_dir
              + " && sudo -n bash install.sh'")
        return 0

    run(scp)
    run(ssh_base + [unpack])

    probe = run(ssh_base + ["cd %s && sudo -n true" % install_dir], check=False)
    if probe.returncode == 0:
        run(ssh_base + ["cd %s && sudo -n bash install.sh" % install_dir])
    else:
        password = os.environ.get("WECHAT_ZERO_SUDO_PASS") or ""
        if not password:
            if sys.stdin.isatty():
                password = getpass.getpass("设备 %s 的 sudo 密码：" % args.user)
            else:
                print("远程 sudo 需要密码：设置环境变量 WECHAT_ZERO_SUDO_PASS 后重试",
                      file=sys.stderr)
                return 2
        run(ssh_base + ["cd %s && sudo -S -p '' bash install.sh" % install_dir],
            stdin_data=password + "\n")

    run(ssh_base + ["/usr/local/bin/wechat-zero --version"])
    print("\n完成。设备上从 APPLaunch 打开「微信」，或运行 wechat-zero")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
