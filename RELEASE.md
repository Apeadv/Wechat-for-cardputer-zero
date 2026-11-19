# 发布指南（GitHub + CardputerZero AppStore）

## 0. 一次性配置

编辑仓库根目录的 `release.json`：

```json
{
  "github_owner": "你的 GitHub 用户名",
  "github_repo": "wechat-zero",
  "author_display": "显示名",
  "author_email": "you@users.noreply.github.com",
  "share_code": "WXZR",
  "package_name": "wechat-zero"
}
```

- `package_name` 是 Debian 包名，**先到先得**；已经被占用就换一个（同时换 `share_code`）。
- `share_code` 是 4 位字母/数字，AppStore 内唯一，用于快捷跳转。
- `app-builder.json` 由构建脚本自动生成，不要手工维护。

## 1. 构建

```powershell
py wechat-zero\tools\build_release.py
```

产物：

```
dist/
├── wechat-zero_1.1.0_all.deb          # 安装包（AppStore 也用它）
├── store/                              # AppStore 提交目录
│   ├── meta.json
│   ├── screenshots/screenshot-0..3.png
│   ├── wechat-zero_icon.png
│   ├── wechat-zero_1.1.0_all.deb
│   └── wechat-zero_1.1.0_all.deb.release.json
├── github/
│   ├── wechat-zero_1.1.0_all.deb
│   ├── wechat-zero-1.1.0-source.tar.gz
│   ├── wechat-zero-1.1.0-source.zip
│   ├── wechat-zero-1.1.0-store.zip
│   ├── get.sh
│   ├── RELEASE_NOTES.md
│   └── SHA256SUMS
└── wechat-zero-1.1.0.tar.gz            # 旧版设备安装包（tar + install.sh）
```

## 2. GitHub Release

### 自动（推荐）

```bash
git add .
git commit -m "release: v1.1.0"
git tag v1.1.0
git push origin main --tags
```

`.github/workflows/release.yml` 会跑测试、构建并创建 Release，附件来自 `dist/github/`。

### 手动

1. 创建 tag `v1.1.0` 和 Release；
2. 上传 `dist/github/` 里的全部文件；
3. Release 说明用 `dist/github/RELEASE_NOTES.md`。

## 3. CardputerZero AppStore

官方流程是 `czdev publish`（来自 [CardputerZero/AppBuilder](https://github.com/CardputerZero/AppBuilder)）：

```bash
# 一台有 Python 3、git、dpkg-deb 的 Linux/WSL 机器
git clone https://github.com/CardputerZero/AppBuilder.git
cd AppBuilder
./czdev login          # GitHub device flow，只需要一次
```

在你的应用仓库根目录（必须包含 `app-builder.json` 和 `dist/`）：

```bash
./path/to/AppBuilder/czdev publish --deb dist/wechat-zero_1.1.0_all.deb
```

它会：

1. 校验包名、版本、图标、截图（320×170）、分类、权限、`share_code`；
2. 把 `.deb` 上传到你 fork 的 `CardputerZero/packages` 的 `czdev-buffer` Release；
3. 自动开 PR，附上 `meta.json`、截图、图标和 release manifest。

PR 合并后，AppStore 会在下一次索引更新时显示。

### 首次发布注意

- 首次上架**不会自动合并**：需要在 PR 评论里贴一段**真机运行视频**，
  维护者看完才会 merge。
- 截图为 `packaging/screenshots/` 里的 4 张 320×170 PNG。
- 如果只想改商店文案/截图（不升版本）：`czdev publish --meta-only`。
- 手动提交时，`dist/store/` 已经是 PR 需要的目录结构；把其中的
  `*.deb.release.json` 的 `url` 换成你自己的 Release 地址即可。

## 4. 发布前检查

```bash
python -m unittest discover -s tests -p "test_*.py"
python tools/build_release.py
dpkg-deb -I dist/wechat-zero_1.1.0_all.deb
dpkg-deb -c dist/wechat-zero_1.1.0_all.deb | head
```

在真机上安装验证：

```bash
sudo apt install ./wechat-zero_1.1.0_all.deb
wechat-zero --selftest
systemctl --user restart APPLaunch
```
