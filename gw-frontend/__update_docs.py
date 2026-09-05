import re

path = 'E:/常用文件/科研项目/中科院国家天文台__中国科学院大学生创新实践训练计划/0722组会/引力波天文数据平台技术详解_v4.6_2026-07-22.md'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

changes = []

# 1. Update version header
old = '> **文档版本**：v3.3（对应系统 v4.12，Aladin CSP WASM 修复 + 首页卡片图标 100% 填充 + 首页卡片滚动动画 + Aladin 诊断增强）\n> **撰写日期**：2026-07-22'
new = '> **文档版本**：v3.4（对应系统 v4.13，Aladin CSP WASM 修复 + 首页卡片图标 100% 填充 + 首页卡片滚动动画重复触发 + Multi-band 默认 Aladin + Firefly iframe 回退 + WebSocket 300s 超时 + X-Forwarded 头）\n> **撰写日期**：2026-07-23'
if old in content:
    content = content.replace(old, new)
    changes.append('1. Header updated')
else:
    changes.append('1. FAILED')

# 2. Add v4.12 scroll animation note in section 4.2
old = '**v4.8 卡片交互重设计**：默认状态仅显示居中图标'
new = '**v4.12 滚动动画重复触发**：IntersectionObserver 不再调用 disconnect()，改为 setCardsVisible(entry.isIntersecting) toggle，确保每次滚入/滚出都触发卡片上滑动画。CSS 使用 .landing-cards-grid + .landing-cards-visible 双类控制（opacity 0->1 + translateY 60px->0），每个卡片通过 nth-child 错开 transition-delay（0-300ms）。Hover 时 transition-delay: 0s !important 防止 nth-child 延迟泄漏到交互。\n\n**v4.8 卡片交互重设计**：默认状态仅显示居中图标'
if old in content:
    content = content.replace(old, new)
    changes.append('2. Scroll animation added')
else:
    changes.append('2. FAILED')

# 3. Add v4.13 notes in section 4.4
old = '**三栏联动**：'
new = '**v4.13 Multi-band 查看器优化**：Multi-band 面板默认显示 Aladin 天球查看器（useState<ViewerType>("aladin")）。Firefly 新增 iframe 回退模式：JS API 初始化失败时自动降级为独立 firefly-viewer.html 页面（iframe 嵌入），避免 JS 冲突导致的 "loading image rendering" 卡死。Firefly 颜色表/拉伸/网格控件在两种模式中均可使用（iframe 模式通过 iframeKey 强制重新挂载触发更新）。\n\n**三栏联动**：'
if old in content:
    content = content.replace(old, new)
    changes.append('3. Multi-band notes added')
else:
    changes.append('3. FAILED')

# 4. Add nginx v4.13 changes in section 9.2
old = '**v4.7 WASM MIME 类型修复**：将 `location /js/*.wasm`（前缀匹配，`*` 字面量）改为 `location ~* \.wasm$`（正则匹配），确保所有 `.wasm` 文件正确获得 `application/wasm` MIME 类型。'

new = '''**v4.13 Firefly WebSocket 超时 + X-Forwarded 头修复**：
- WebSocket 超时：Firefly /firefly/ location 添加 proxy_read_timeout 300s 和 proxy_send_timeout 300s，修复 nginx 默认 60s 超时导致 Firefly WebSocket 异常关闭（CLOSED_ABNORMALLY）
- X-Forwarded 头：添加 X-Forwarded-For、X-Forwarded-Host、X-Forwarded-Proto、X-Forwarded-Port 代理头，确保 Firefly Tomcat 服务器生成正确的对外 URL（而非 Docker 内部主机名）
- Aladin WASM CSP：服务器级 script-src 添加 wasm-unsafe-eval，connect-src 添加 data:（Aladin Lite v3 通过 fetch(data:application/wasm;base64,...) 加载 WebAssembly）

**v4.12 首页图标 WebP 透明通道修复**：将首页 4 个图标从 PNG 转为 WebP（RGBA 模式，保留 alpha 通道），使用 object-fit: cover + width: 100% + height: 100% 充满卡片方框，添加 mask-image: radial-gradient(...) 边缘柔化。

**v4.7 WASM MIME 类型修复**：将 `location /js/*.wasm`（前缀匹配，`*` 字面量）改为 `location ~* \.wasm$`（正则匹配），确保所有 `.wasm` 文件正确获得 `application/wasm` MIME 类型。'''

if old in content:
    content = content.replace(old, new)
    changes.append('4. Nginx changes added')
else:
    changes.append('4. FAILED')

# 5. Update known issues
old = '| **Firefly 本地容器** | ✅ 已确认 | Firefly 运行在本地 `ipac/firefly:latest` Docker 容器，前端通过 Nginx `/firefly/` 代理连接，FITS 从 `gw-backend:8093` 加载，全程不需要外网 |'
new = '| **Firefly JS API + iframe 回退** | ✅ v4.13 | Firefly JS API 初始化失败时自动降级为独立 firefly-viewer.html 页面（iframe 嵌入）。Nginx WebSocket 超时延长至 300s（修复 CLOSED_ABNORMALLY），添加 X-Forwarded 代理头确保 Tomcat 生成正确 URL。颜色表/拉伸/网格控件在两种模式中均可使用 |'
if old in content:
    content = content.replace(old, new)
    changes.append('5. Firefly issue updated')
else:
    changes.append('5. FAILED')

# 6. Update Aladin issue
old = '| **Aladin CSP 修复** | ✅ v4.8 | Nginx CSP connect-src/img-src/frame-src 已添加 CDS 域名白名单（aladin.cds.unistra.fr、alasky.cds.unistra.fr、alaskybis.cds.unistra.fr）；修复 add_header 继承 Bug（location = /index.html 和 location / 显式添加安全头）；Aladin 天球查看器可正常加载 HiPS 巡天瓦片 |'
new = '| **Aladin CSP + WASM 修复** | ✅ v4.13 | Nginx CSP script-src 添加 wasm-unsafe-eval（WebAssembly），connect-src 添加 data:（WASM data URL 加载）；修复 add_header 继承 Bug；CDS 域名白名单；修复正则转义 (?!\/) 防止 SyntaxError；使用 CDN aladin.js 替代本地文件 |\n| **Multi-band 默认 Aladin** | ✅ v4.13 | Error Analysis 页面 Multi-band Observation Data 默认显示 Aladin 天球查看器，用户可手动切换到 Firefly |'
if old in content:
    content = content.replace(old, new)
    changes.append('6. Aladin issue updated')
else:
    changes.append('6. FAILED')

# 7. Add landing animation to known issues
old = '| **Pipeline 安全** | ✅ v4.11 | 全部端点路径遍历防护、survey 参数输入消毒、LLM 代理超时和错误处理完善 |'
new = '| **Pipeline 安全** | ✅ v4.11 | 全部端点路径遍历防护、survey 参数输入消毒、LLM 代理超时和错误处理完善 |\n| **首页滚动动画重复** | ✅ v4.12 | IntersectionObserver 移除 disconnect()，改为 toggle 模式，确保每次滚入/滚出都触发卡片上滑动画。CSS nth-child 错开延迟 + hover 时 transition-delay: 0s !important 防止延迟泄漏 |'
if old in content:
    content = content.replace(old, new)
    changes.append('7. Landing animation added')
else:
    changes.append('7. FAILED')

# 8. Update footer version
content = content.replace('GravitationalWave v4.10', 'GravitationalWave v4.13')

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

for c in changes:
    print(c)
print('DONE')
