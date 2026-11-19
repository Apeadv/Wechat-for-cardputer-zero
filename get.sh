#!/bin/sh
# Install / upgrade WeChat Zero on a Cardputer Zero.
set -eu
REPO="${REPO:-gywan94/wechat-zero}"
VERSION="${VERSION:-1.1.0}"
URL="https://github.com/$REPO/releases/download/v$VERSION/wechat-zero_${VERSION}_all.deb"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
echo "Downloading $URL"
curl -fL --retry 3 -o "$TMP/wechat-zero.deb" "$URL"
sudo apt install -y "$TMP/wechat-zero.deb"
systemctl --user restart APPLaunch 2>/dev/null || true
echo "Installed. Open APPLaunch -> 微信"
