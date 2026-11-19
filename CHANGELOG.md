# Changelog

## 1.1.0 — 2026-11-19

### Input method
- **Removed idle auto-conversion.** Typing pinyin no longer turns into Chinese after
  a pause; press **Tab** to convert. `Enter` still converts a trailing pinyin tail
  before sending, and `1/2/3` / `0` select and page candidates.

### iLink reliability
- Added the official `msg/notifystart` and `msg/notifystop` lifecycle calls and
  `base_info.bot_agent`, so a freshly invited channel can send immediately.
- Use the official numeric `iLink-App-ClientVersion` and `X-WECHAT-UIN` format.
- Handle `scaned_but_redirect`, `binded_redirect` and `need_verifycode` QR states.
- Reject self-scanned invite QR codes (one WeChat cannot own two bot channels),
  clean up dead self-invite channels and keep transcripts readable.
- Send failures now show the server reason and are logged to
  `~/.config/wechat-zero/app.log` (no tokens).

### Multi-friend channels
- One bot channel per invited friend, with per-channel polling, cursors and
  proactive sends; friends who message the main bot keep using `context_token`.
- Orphaned channels are marked instead of silently falling back to the main bot.

### Release engineering
- `tools/build_deb.py`: pure-Python `.deb` builder (works on Windows).
- `tools/build_release.py`: `.deb`, GitHub source archives, AppStore bundle,
  checksums, release notes and `get.sh`.
- `app-builder.json`, AppStore screenshots/icon, GitHub Actions release workflow.

## 1.0.0 — 2026-11-18

- Initial Cardputer Zero port of `gywan94/cardputer-wechat`.
- 320×170 UI, QR login, text send/receive, multi-friend store, offline pinyin IME,
  unread badges, remarks, persistent state, APPLaunch entry.
