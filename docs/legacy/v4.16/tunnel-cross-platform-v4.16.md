# SSH 公网隧道 — 全平台部署与自动重连指南（v4.16）

## 1. 平台脚本对照

| 平台 | 脚本 | 安装方式 |
|------|------|---------|
| **Windows** | [tunnel-daemon.ps1](C:\Users\28610\tunnel-daemon.ps1) | Startup 文件夹（用户登录自启） |
| **Windows** | [tunnel.sh](D:\AliCPT\scripts\tunnel.sh) (Git Bash) | 手动启动 |
| **Linux** | [tunnel.sh](D:\AliCPT\scripts\tunnel.sh) (bash) | systemd 服务 |
| **macOS** | [tunnel.sh](D:\AliCPT\scripts\tunnel.sh) (bash) | launchd plist |

## 2. Linux 部署（systemd 自动重启）

```bash
# 创建 systemd 服务文件
sudo cat > /etc/systemd/system/gw-tunnel.service << 'EOF'
[Unit]
Description=GW Platform SSH Tunnel
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=simple
User=your-username
WorkingDirectory=/path/to/AliCPT
ExecStart=/bin/bash /path/to/AliCPT/scripts/tunnel.sh
Restart=always
RestartSec=10
StandardOutput=append:/path/to/AliCPT/docker-data/tunnel.log
StandardError=append:/path/to/AliCPT/docker-data/tunnel.log

[Install]
WantedBy=multi-user.target
EOF

# 启用并启动
sudo systemctl daemon-reload
sudo systemctl enable gw-tunnel
sudo systemctl start gw-tunnel

# 查看状态
sudo systemctl status gw-tunnel
journalctl -u gw-tunnel -f
```

**关键特性**：
- `Restart=always` + `RestartSec=10` → 断线 10 秒后自动重连
- `After=docker.service` → 等待 Docker 就绪再启动
- `network-online.target` → 等待网络就绪

## 3. macOS 部署（launchd 自动重启）

```bash
# 创建 launchd plist
cat > ~/Library/LaunchAgents/com.gw.tunnel.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.gw.tunnel</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>/path/to/AliCPT/scripts/tunnel.sh</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/path/to/AliCPT</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/path/to/AliCPT/docker-data/tunnel.log</string>
    <key>StandardErrorPath</key>
    <string>/path/to/AliCPT/docker-data/tunnel.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
EOF

# 加载并启动
launchctl load ~/Library/LaunchAgents/com.gw.tunnel.plist
launchctl start com.gw.tunnel

# 查看状态
launchctl list | grep com.gw.tunnel
```

## 4. 断线自动重连逻辑

`tunnel.sh` 内置的重连机制（所有平台共用）：

```
主循环 (watchdog_loop):
  ┌──────────────────────────────────────────┐
  │ 1. 检查 Docker + gw-frontend 是否运行    │
  │    ↓ 否 → 等待 30s，返回步骤 1          │
  │ 2. 尝试 localhost.run（主隧道）          │
  │    ↓ 成功 → 写入 URL 文件，监控进程      │
  │    ↓ 失败/断线 → 进入步骤 3              │
  │ 3. 尝试 serveo.net（备用隧道）           │
  │    ↓ 成功 → 写入 URL 文件，监控进程      │
  │    ↓ 失败 → 进入步骤 4                    │
  │ 4. 双隧道均失败                           │
  │    ↓ 等待指数退避时间（5s→10s→20s...→5min)│
  │    ↓ 返回步骤 1                           │
  └──────────────────────────────────────────┘

重试策略: 指数退避（5s, 10s, 20s, 40s, 80s, 160s, 300s max）
监控频率: 每 30 秒检查隧道进程存活状态
URL 持久化: docker-data/public-url.txt（前端读取显示公网地址）
```

## 5. 双隧道容灾原理

```
                  ┌─────────────────┐
用户请求 ───────→ │ localhost.run   │ ← 主隧道（免费，无需注册）
                  │ (c759be6375.lhr.life)
                  └────────┬────────┘
                           │ 宕机/超时/被限流
                           ↓
                  ┌─────────────────┐
                  │ serveo.net      │ ← 备用隧道（免费，无需注册）
                  │ (gwplatform.serveo.net)
                  └─────────────────┘

两个服务完全独立，同时宕机概率极低。
```

## 6. 快速诊断

```bash
# 查看当前公网 URL
cat D:/AliCPT/docker-data/public-url.txt

# 查看隧道日志
tail -f D:/AliCPT/docker-data/tunnel-daemon.log   # Windows daemon
tail -f D:/AliCPT/docker-data/tunnel.log          # bash tunnel.sh

# 手动测试隧道连接
ssh -o StrictHostKeyChecking=no -R 80:localhost:6001 nokey@localhost.run
# 等待 5-10 秒，观察输出的 URL

# 验证公网可访问
curl -I https://<tunnel-url>
```
