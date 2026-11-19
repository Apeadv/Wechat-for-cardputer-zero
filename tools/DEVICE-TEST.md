# 在真机上做端到端测试

不需要第二个微信账号：设备上跑一个假 iLink 服务器，再用 `/dev/uinput` 注入键盘，
就能验证「屏幕 + 键盘 + 拼音 + 邀请通道 + 主动发送」整条链路。

以下命令在电脑上执行，`HOST=192.168.50.106`、`USER=apead`。

## 1. 准备

```bash
ssh USER@HOST "python3 -c 'import PIL, evdev, numpy; print(\"ok\")'"

scp tests/fake_server.py tools/device_demo_server.py tools/capture_fb.py \
    tools/device_injectd.py USER@HOST:/tmp/
```

## 2. 起假服务器

```bash
ssh USER@HOST "setsid nohup python3 /tmp/device_demo_server.py >/tmp/wz-server.log 2>&1 < /dev/null &"
ssh USER@HOST "cat /tmp/wz-base"       # 例如 http://127.0.0.1:43015
```

假服务器默认分配两个 owner：第一次扫码是 `wxid_owner`（你），第二次是
`wxid_friend`（好友）。`fake.qr_status` 会在 5 秒后变成 `confirmed`，之后所有
新二维码也会自动确认；8/9.5/11.5 秒各推一条消息。

## 3. 预置一个指向假服务器的 state

```bash
ssh USER@HOST 'python3 - <<PY
import json
json.dump({"version": 2, "uin": "AAAA", "active": "", "primary": "main",
           "seen": [], "friends": [],
           "accounts": [{"id": "main", "token": "", "host": "127.0.0.1:43015",
                         "scheme": "http", "cursor": "", "owner": "",
                         "name": "我", "kind": "main"}]},
          open("/tmp/wz-state.json", "w"))
PY'
```

## 4. 启动应用并登录

```bash
ssh USER@HOST "cd /opt/wechat-zero && LANG=C.UTF-8 setsid nohup \
  python3 wechat.py --state /tmp/wz-state.json >/tmp/wz-app.log 2>&1 < /dev/null &"
sleep 3
ssh USER@HOST "python3 /tmp/capture_fb.py /tmp/wz-login.png"   # 登录二维码
sleep 10
ssh USER@HOST "python3 /tmp/capture_fb.py /tmp/wz-friends.png" # 好友列表 + 未读
```

## 5. 注入键盘：邀请好友

```bash
# root：常驻虚拟键盘（只需一次）
ssh USER@HOST "sudo setsid nohup python3 /tmp/device_injectd.py \
  >/tmp/wz-kbd.log 2>&1 < /dev/null &"

# F2 → 邀请二维码
ssh USER@HOST "echo F2 | sudo tee /tmp/wz-keys"
sleep 1
ssh USER@HOST "python3 /tmp/capture_fb.py /tmp/wz-invite.png"

# 假服务器会自动确认邀请；约 3 秒后进入「专属通道」
sleep 4
ssh USER@HOST "python3 /tmp/capture_fb.py /tmp/wz-invited.png"

# 打拼音 + 发送
ssh USER@HOST "echo zaijian | sudo tee /tmp/wz-keys"
sleep 2
ssh USER@HOST "echo ENTER | sudo tee /tmp/wz-keys"
sleep 2
ssh USER@HOST "python3 /tmp/capture_fb.py /tmp/wz-sent.png"
ssh USER@HOST "cat /tmp/wz-sent.json"
```

`/tmp/wz-sent.json` 里应出现**没有 `context_token`**、`to_user_id=wxid_friend` 的请求：

```json
[{"msg": {"to_user_id": "wxid_friend",
          "item_list": [{"type": 1, "text_item": {"text": "再见"}}]}}]
```

## 6. 清理

```bash
ssh USER@HOST "sudo pkill -f device_injectd; pkill -f device_demo_server; \
  pkill -f 'wechat.py'; rm -f /tmp/wz-* /tmp/device_*.py /tmp/capture_fb.py"
```

之后从 APPLaunch 打开「微信」就是正常模式（真实 iLink + 真实账号）。
