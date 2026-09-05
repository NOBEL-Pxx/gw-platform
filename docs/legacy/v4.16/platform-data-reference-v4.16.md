# GravitationalWave Platform — 代码统计与数据清单（v4.16 实测）

## 1. 代码行数精确统计

以下为 `wc -l` 实测值（2026-07-24，含空行和注释）：

| 模块 | 语言 | 行数 | 文件数 |
|------|------|------|--------|
| **gw-backend** | Java | 4,126 | 55 |
| **gw-pipeline** | Python | 3,266 | 8 |
| **gw-mcp-server** | Python | 828 | 5 |
| **gw-frontend** | TypeScript/TSX | 5,152 | 38 |
| **gw-frontend** | CSS | 752 | 1 |
| **Scripts** | Bash/PowerShell | 1,877 | 15 |
| **Docker/Config** | YAML/Dockerfile | 426 | 5 |
| **Nginx** | conf/template | 609 | 7 |
| **Static HTML** | HTML | 136 | 2 |
| **合计** | — | **17,172** | **136** |

> **注意**：之前的 ~6,360 估算仅统计了部分源文件。实测总行数为 17,172 行。

**不含**：`node_modules`（~200MB）、`docker-data`（运行时数据）、`sample_data`（FITS 文件）、Python `__pycache__`。

## 2. 数据清单（实测验证）

### Elasticsearch（2026-07-24 实测）

| 索引 | 文档数 | 说明 |
|------|--------|------|
| `alicptabnormal` | **180** | 异常观测数据（AliCPT 巡天） |
| `errorlist` | **12** | 异常报告列表（聚合） |
| `errordetail` | **48** | 异常详情（含日志内容、FITS 路径） |

### MongoDB（2026-07-24 实测）

| 集合 | 文档数 | 说明 |
|------|--------|------|
| `comments` | 43 | 5 条 demo + 38 条用户创建 |
| `users` | 12 | 注册用户 |
| `favorites` | 1 | 用户收藏 |
| `collections` | 0 | 用户集合（功能已实现，无数据） |
| `collectionItems` | 0 | 集合条目 |
| `audit_logs` | 0 | 审计日志（v4.16 新增，尚无数据） |

### FITS 文件

| 巡天 | 文件数 | 可用 | 备注 |
|------|--------|------|------|
| DSS2 | 36 | ✅ 36 | R/G/B 三通道，12 个坐标组 |
| LEGACY | 48 | ❌ 0 | 全部全零数据（legacysurvey.org 导出错误） |
| 2MASS | 24 | ✅ 24 | J/H/K 三波段 |
| allWISE | 12 | ✅ 12 | W1/W2/W4 波段 |
| NVSS | 12 | ✅ 12 | 射电巡天 |
| FIRST | 12 | ✅ 12 | 射电巡天 |
| **合计** | **144** | **108 可用** | 5 个有效巡天 |

### 前端页面

| 路由 | 页面 | 数据来源 |
|------|------|---------|
| `/search` | FITS 搜索 | ES `alicptabnormal` (180 docs) |
| `/index` | 异常分析 | ES `errorlist` (12) + `errordetail` (48) |
| `/pipeline` | 科学计算 | FITS 文件 + Pipeline API |
| `/assistant` | AI 对话 | DeepSeek API |
| `/compare` | 数据对比 | Pipeline `/photometry` |
| `/favorites` | 收藏 | MongoDB `favorites` |
| `/collections` | 集合 | MongoDB `collections` |
| `/settings` | 设置 | 静态信息 |
| `/login` | 登录 | MongoDB `users` |
| `/landing` | 首页 | 静态内容 |

## 3. 分页与数据量级说明

**消除歧义**：`page_size=-1` 是后端的 "返回全部" 信号，后端内部转为 `size=1000`（SearchService.java:100）。这不是说实际有 1000 条数据。

| 场景 | 实际数据量 | page_size=-1 行为 |
|------|-----------|------------------|
| `/geoSearch` | 180 条 | 返回全部 180 条（<1000，一次性返回） |
| `/error` | 12 条 | 返回全部 12 条 |
| `/error/{id}` | 48 条 | 返回全部 48 条 |
| `/comments` | 43 条 | 返回全部 43 条 |

**前端已修复**（v4.16）：当 `total_count ≤ page_size` 时，分页组件显示 "X results (all shown)"，不再混淆用户。
