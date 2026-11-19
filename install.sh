#!/bin/sh
# Install wechat-zero on the Cardputer Zero.  Run as root from this directory:
#     sudo ./install.sh              # install, check deps, don't touch apt
#     sudo ./install.sh --with-deps  # also apt-get install python3-pil python3-evdev
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "请用 sudo 运行：sudo ./install.sh" >&2
    exit 1
fi

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PREFIX=/opt/wechat-zero
WITH_DEPS=0
for arg in "$@"; do
    case "$arg" in
        --with-deps) WITH_DEPS=1 ;;
    esac
done

# ---------------------------------------------------------------- dependencies
missing=""
python3 -c "import PIL" 2>/dev/null || missing="$missing python3-pil"
python3 -c "import evdev" 2>/dev/null || missing="$missing python3-evdev"
if [ -n "$missing" ]; then
    if [ "$WITH_DEPS" = 1 ]; then
        echo "安装依赖：$missing"
        apt-get update
        apt-get install -y --no-install-recommends $missing
    else
        echo "缺少依赖：$missing" >&2
        echo "联网时可运行：sudo ./install.sh --with-deps" >&2
        echo "手工安装：sudo apt install -y $missing" >&2
        exit 1
    fi
fi

font=0
for f in \
    /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc \
    /usr/share/fonts/truetype/wqy/wqy-zenhei.ttc \
    /usr/share/fonts/truetype/wqy/wqy-microhei.ttc; do
    [ -f "$f" ] && font=1
done
if [ "$font" = 0 ]; then
    echo "提示：没有找到中文字体，界面中文会显示方块。" >&2
    echo "      sudo apt install fonts-wqy-zenhei" >&2
fi

# ---------------------------------------------------------------- application
install -d "$PREFIX" "$PREFIX/assets"
rm -rf "$PREFIX/wz" "$PREFIX/vendor"
cp -a "$HERE/wz" "$PREFIX/wz"
cp -a "$HERE/vendor" "$PREFIX/vendor"
cp -a "$HERE/assets/." "$PREFIX/assets/"
install -m 0644 "$HERE/wechat.py" "$PREFIX/wechat.py"
install -m 0644 "$HERE/README.md" "$PREFIX/README.md" 2>/dev/null || true
install -m 0644 "$HERE/LICENSE" "$PREFIX/LICENSE" 2>/dev/null || true
install -m 0644 "$HERE/CHANGELOG.md" "$PREFIX/CHANGELOG.md" 2>/dev/null || true
find "$PREFIX" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true

# The pinyin dictionary is queried once per keystroke; an index keeps that in
# the millisecond range on the 4x A53 CPU.
if [ -f "$PREFIX/assets/ime.db" ]; then
    python3 - "$PREFIX/assets/ime.db" <<'PY'
import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
con.execute("CREATE INDEX IF NOT EXISTS words_py ON words(py)")
con.commit()
con.close()
PY
fi

# ---------------------------------------------------------------- launch entry
install -d /usr/local/bin /usr/share/APPLaunch/bin \
    /usr/share/APPLaunch/applications /usr/share/APPLaunch/share/images \
    /usr/share/applications
install -m 0755 "$HERE/bin/wechat-zero" /usr/local/bin/wechat-zero
install -m 0755 "$HERE/bin/wechat-zero" /usr/share/APPLaunch/bin/wechat-zero
install -m 0644 "$HERE/packaging/wechat-zero.desktop" \
    /usr/share/APPLaunch/applications/wechat-zero.desktop
install -m 0644 "$HERE/packaging/wechat-zero.desktop" \
    /usr/share/applications/wechat-zero.desktop
install -m 0644 "$HERE/assets/icon-128.png" \
    /usr/share/APPLaunch/share/images/wechat-zero.png

chown -R root:root "$PREFIX" /usr/local/bin/wechat-zero \
    /usr/share/APPLaunch/bin/wechat-zero \
    /usr/share/APPLaunch/applications/wechat-zero.desktop \
    /usr/share/APPLaunch/share/images/wechat-zero.png \
    /usr/share/applications/wechat-zero.desktop
update-desktop-database /usr/share/applications >/dev/null 2>&1 || true

echo "已安装：/opt/wechat-zero"
echo "启动器：/usr/share/APPLaunch/applications/wechat-zero.desktop"
echo "命令行：wechat-zero            自检：wechat-zero --selftest"
