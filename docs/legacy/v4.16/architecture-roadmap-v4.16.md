# GravitationalWave Platform — 长期架构规划与遗留问题路线图

> **版本**：v4.16 | **日期**：2026-07-24
> **触发**：5 项架构遗留问题系统性评估
> **状态**：规划阶段，待评审

---

## 目录

1. [现状总结](#1-现状总结)
2. [问题一：AI 模型路线规划](#2-问题一ai-模型路线规划)
3. [问题二：分布式扩展方案](#3-问题二分布式扩展方案)
4. [问题三：监控告警体系](#4-问题三监控告警体系)
5. [问题四：标准化天文数据 SDK](#5-问题四标准化天文数据-sdk)
6. [问题五：安全体系完善](#6-问题五安全体系完善)
7. [分阶段实施路线图](#7-分阶段实施路线图)
8. [算力与成本估算](#8-算力与成本估算)

---

## 1. 现状总结

### 1.1 代码库扫描结果

| 层级 | 技术栈 | 代码量（估算） | 关键发现 |
|------|--------|---------------|---------|
| 前端 | React 18 + TypeScript + Vite | ~35 文件 | 坐标验证逻辑与后端 Java 重复 |
| 后端 | Spring Boot + Java | ~55 文件 | 已有 RateLimiter 接口 + Bucket4j 实现；零 ML 代码 |
| Pipeline | FastAPI + Python + Astropy | ~8 文件 | FITS 处理完善，但纯算法（无 DL） |
| MCP Server | Python | ~5 文件 | 轻薄代理层 |
| 数据库 | MongoDB 6.0 + ES 7.17 | — | 单节点，无副本集 |
| 反向代理 | Nginx 1.19 | — | 单 upstream，无负载均衡池 |

### 1.2 已有但未充分利用的基础设施

| 组件 | 当前用途 | 可扩展方向 |
|------|---------|-----------|
| `RateLimiter` 接口 (Java) | IP 限流 60 req/min | 已有 `RedisRateLimiter` 骨架，加 Redis 即可支持分布式限流 |
| `InMemoryRateLimiter` (Bucket4j) | 单机令牌桶 | 切换到 Redis 后端支持多实例 |
| `job_queue.py` (Python) | 内存异步任务 | 替换为 Celery + Redis 支持持久化和分布式 |
| `ThreadPoolExecutor` (Pipeline) | CPU 密集型 FITS 操作 | 已在用，需配合水平扩展 |
| `/pipeline/stats` 端点 | p50/p99 耗时统计 | 替换为 Prometheus metrics 导出 |
| `timing_middleware` (FastAPI) | 请求耗时头 | 同上，接入 Prometheus |

---

## 2. 问题一：AI 模型路线规划

### 2.1 现状诊断

**当前代码库中没有任何深度学习代码**。搜索确认：
- 后端：无 PyTorch/TensorFlow/ONNX 依赖
- Pipeline：使用传统算法（DAOStarFinder 点源检测、image segmentation 展源检测）
- 前端 `AIFloatingButton.tsx:24` 的描述文字 "Auto-classify anomaly types using trained CNNs" 仅为 UI 占位文案
- LLM 能力仅通过 DeepSeek API 代理实现

### 2.2 分阶段路线图

#### Phase 1：基础设施（1-2 个月，可在当前单机上完成）

**目标**：搭建模型训练与推理的最小可用基础设施

| 任务 | 技术选型 | 产出 |
|------|---------|------|
| GPU 环境搭建 | CUDA 12.4 + cuDNN，在宿主机或独立 GPU 服务器 | GPU 可用性确认 |
| 模型注册与版本管理 | MLflow (自托管 Docker) | 实验追踪、模型版本管理 |
| 训练数据准备 | 基于现有 FITS 文件标注异常类型 | 标注数据集 ≥500 样本 |
| 推理服务容器化 | BentoML 或 Triton Inference Server | 独立 `gw-inference` 容器 |

**为什么 MLflow 而不是 Wandb/Neptune？**
- MLflow 可完全自托管在 Docker 中，不需要外部 SaaS 依赖
- 与现有 7 容器 Docker Compose 架构一致
- Python API 与 FastAPI/Pipeline 天然兼容

#### Phase 2：异常检测模型（2-3 个月）

**目标**：实现首个可用的深度学习异常检测

| 里程碑 | 方法 | 训练数据 | 预期指标 |
|--------|------|---------|---------|
| M1: 监督分类器 | ResNet-18 微调，4 类异常（spike/dip/pattern-break/WCS-mismatch） | 标注 FITS 切图 500+ | Accuracy ≥ 85%, F1 ≥ 0.80 |
| M2: 无监督异常检测 | 自编码器 (AE) + 重构误差 | 正常 FITS 切图 2000+ | AUC ≥ 0.90 |
| M3: 混合流水线 | AE 初筛 → ResNet 分类 → 人工复核 | M1+M2 联合 | 减少误报 70% |

**新增 Pipeline API**：

```python
# POST /pipeline/anomaly/detect
{
    "filename": "AliCPT_RA_159.6_Dec_44.8.fits",
    "anomalies": [
        {
            "type": "DEAD_PIX",
            "confidence": 0.94,
            "pixel_region": {"x": [120,135], "y": [200,210]},
            "snr_impact": 0.12
        }
    ],
    "inference_time_ms": 45,
    "model_version": "resnet18-anomaly-v1.2"
}
```

#### Phase 3：多信使关联（3-4 个月）

**目标**：GW 事件触发后自动查询多波段数据，计算关联概率

| 能力 | 实现 | 依赖 |
|------|------|------|
| GW 事件接入 | 订阅 GCN/TreasureMap 低延迟警报流 | Kafka/WebSocket 客户端 |
| 空间交叉匹配 | HEALPix 概率天空图 + 多波段星表交叉匹配 | Astropy, HEALPy |
| 关联概率排序 | 贝叶斯假设检验 | 自定义概率模型 |
| 自动触发流水线 | GW 警报 → 查询可用波段 → 下载/检索 FITS → 异常检测 → 报告 | Phase 2 模型 + 任务队列 |

#### Phase 4：LLM 增强（持续）

- **短期**（已实现）：DeepSeek API 代理，系统提示词限定天文领域
- **中期**：RAG 增强 — 论文/星表文档向量化（ChromaDB），LLM 回答时检索相关文献
- **长期**（可选）：LLaMA-Factory 对开源基座做天文领域 SFT，部署到自有 GPU

### 2.3 算力需求

| 阶段 | GPU 需求 | 内存 | 存储 | 备注 |
|------|---------|------|------|------|
| Phase 1 | 1× RTX 3090/4090 (24GB) | 32GB | 500GB SSD | 训练+推理 |
| Phase 2 | 1× RTX 3090/4090 | 32GB | 1TB SSD | +数据集 |
| Phase 3 | 同上 | 同上 | 同上 | 无额外算力需求 |
| Phase 4 (RAG) | 无需 GPU | 16GB | 200GB | 向量数据库 |
| Phase 4 (SFT) | 4× A100 (40GB) 或云 GPU | 128GB | 2TB | 仅在决定做领域微调时需要 |

**成本估算**：
- 自有 GPU 工作站：一次性 ~2-3 万元（RTX 4090）
- 云 GPU 按需（AutoDL）：~5-10 元/小时，Phase 2 训练约 200 GPU 小时 ≈ 1000-2000 元
- MLflow + 模型服务容器：在现有 Docker 宿主机上运行，零额外成本

---

## 3. 问题二：分布式扩展方案

### 3.1 现状诊断

```
当前架构：全部单机 Docker Compose
┌─────────────────────────────────────────┐
│  Docker Host (单机)                      │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐   │
│  │Nginx │ │Front │ │Back  │ │Pipe  │   │
│  │:80   │ │:3000 │ │:8093 │ │:8200 │   │
│  └──────┘ └──────┘ └──────┘ └──────┘   │
│  ┌──────┐ ┌──────┐ ┌──────┐            │
│  │Mongo │ │  ES  │ │MCP   │            │
│  │:27017│ │:9200 │ │:8100 │            │
│  └──────┘ └──────┘ └──────┘            │
│  所有组件共享 gw-net/gw-db 网桥         │
└─────────────────────────────────────────┘
```

**关键瓶颈**：
1. **限流**：`InMemoryRateLimiter` — 多实例时计数器不共享
2. **任务队列**：`job_queue.py` — 内存字典，重启丢失所有任务
3. **缓存**：Pipeline thumbnail 缓存是本地磁盘，多实例不共享
4. **数据库**：MongoDB/ES 单节点，无高可用，无读扩展
5. **会话**：后端 JWT 无状态，天然支持多实例（这是好消息）

### 3.2 三阶段扩展方案

#### 阶段 A：引入中间件（立即可做，2-4 周）

**目标**：不增加服务器，引入必要中间件

| 变更 | 方案 | 影响 |
|------|------|------|
| 引入 Redis | 新增 `gw-redis` 容器（Redis 7 Alpine） | docker-compose.yml +1 服务 |
| 限流切换到 Redis | 激活已有 `RedisRateLimiter`，`spring.profiles.active=redis` | 一行配置 |
| 任务队列持久化 | `job_queue.py` → Celery + Redis broker | ~200 行变更 |
| MongoDB 副本集 | 本地 3 节点副本集（同一 Docker） | 增加高可用 |
| Nginx upstream 池 | 为 backend/pipeline 配置 `upstream` 块 | 仅配置文件 |

**docker-compose.yml 新增**：

```yaml
  redis:
    image: redis:7-alpine
    container_name: gw-redis
    command: redis-server --appendonly yes --maxmemory 256mb --maxmemory-policy allkeys-lru
    volumes:
      - ./docker-data/redis-data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5
    networks:
      - gw-db
    restart: on-failure
```

#### 阶段 B：水平扩展应用层（需要时，1-2 周）

**触发条件**：API 响应 p99 > 2s 或并发 > 50

| 组件 | 扩展方式 | 实例数 |
|------|---------|--------|
| gw-backend | `docker compose up --scale gw-backend=3` | 3 |
| gw-pipeline | 同上 | 2-3 |
| gw-frontend | 同上 | 2 |

**Nginx upstream 示例**：

```nginx
upstream backend_pool {
    server gw-backend:8093 max_fails=3 fail_timeout=30s;
    resolver 127.0.0.11 valid=30s;  # Docker DNS
}
```

#### 阶段 C：K3s 迁移（生产级，1-2 个月）

**触发条件**：需要跨多台物理机 / 自动扩缩容 / 灰度发布

选择 **K3s**（而非完整 K8s）的理由：
- 单二进制安装，内存 ~512MB
- 自带 traefik ingress、local-path 存储
- 与标准 K8s API 完全兼容，未来可迁移云 K8s
- 支持 HPA + KEDA（基于 Redis 队列长度自动扩缩）

---

## 4. 问题三：监控告警体系

### 4.1 现状诊断

| 监控维度 | 当前状态 | 差距 |
|---------|---------|------|
| 容器 CPU/内存 | ❌ 无 | **完全缺失** |
| API 响应耗时 | ⚠️ Pipeline `/stats` 有 p50/p99 | 仅 Pipeline，无 Backend |
| ES 查询延迟 | ❌ 无 | **完全缺失** |
| LLM Token 消耗 | ❌ 无 | **完全缺失** |
| 服务存活 | ⚠️ Docker healthcheck | 有健康检查，无告警通知 |
| 日志聚合 | ❌ 无 | 各容器独立 JSON 日志 |
| 告警通知 | ❌ 无 | **完全缺失** |

### 4.2 推荐方案：Prometheus + Grafana + AlertManager

#### 架构图

```
gw-backend:8093 ──┐
 (micrometer)      │
gw-pipeline:8200 ──┤
 (prometheus_client)│
gw-frontend:80 ────┤
 (nginx-exporter)  │    scrape        ┌─────────────┐
                   └────────────────→ │ Prometheus   │
MongoDB ← exporter ─────────────────→│ :9090        │
ES ← exporter ──────────────────────→│              │
                                      └──────┬──────┘
                                             │
                         ┌───────────────────┼────────────
                         │                   │            │
                   ┌─────▼──────┐   ┌───────▼──────┐
                   │  Grafana    │   │ AlertManager  │
                   │  :3000      │   │ :9093         │
                   └────────────┘   └───────┬──────┘
                                            │ 钉钉/邮件
```

#### 实施步骤

**Step 1：指标暴露（每个服务 10-30 分钟）**

| 服务 | 方案 | 工作量 |
|------|------|--------|
| gw-backend (Spring Boot) | `micrometer-registry-prometheus` + `/actuator/prometheus` | 5 分钟 |
| gw-pipeline (FastAPI) | `prometheus_client` + 中间件 | 15 分钟 |
| gw-frontend (Nginx) | `nginx-prometheus-exporter` sidecar 容器 | 10 分钟 |
| MongoDB | `mongodb-exporter` sidecar | 10 分钟 |
| Elasticsearch | `elasticsearch-exporter` sidecar | 10 分钟 |

**Step 2：核心告警规则**

```yaml
groups:
  - name: gw-platform
    rules:
      - alert: ContainerDown
        expr: absent(container_last_seen{name=~"gw-.*"})
        for: 1m
        labels: { severity: critical }
        annotations: { summary: "{{ $labels.name }} is down" }

      - alert: HighCPU
        expr: rate(container_cpu_usage_seconds_total{name=~"gw-.*"}[5m]) > 0.9
        for: 5m
        labels: { severity: warning }

      - alert: HighMemory
        expr: container_memory_usage_bytes{name=~"gw-.*"} / container_spec_memory_limit_bytes{name=~"gw-.*"} > 0.85
        for: 5m
        labels: { severity: warning }

      - alert: HighLatency
        expr: histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m])) > 2
        for: 5m
        labels: { severity: warning }
        annotations: { summary: "p99 latency > 2s on {{ $labels.route }}" }

      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m]) > 0.05
        for: 5m
        labels: { severity: critical }

      - alert: ESQuerySlow
        expr: elasticsearch_indices_search_query_time_seconds / elasticsearch_indices_search_query_total > 1
        for: 5m
        labels: { severity: warning }

      - alert: LLMTokenSpike
        expr: rate(llm_tokens_total[1h]) * 3600 > 100000
        for: 1h
        labels: { severity: info }
        annotations: { summary: "LLM token usage spike" }
```

### 4.3 轻量替代方案

**Netdata**（单行安装，零配置，适合快速启动）：
```bash
docker run -d --name=netdata --pid=host --network=host \
  --cap-add SYS_PTRACE netdata/netdata
```
- 自带 1000+ 告警、预配置面板
- 适合作为临时方案，需求明确后再迁移 Prometheus

---

## 5. 问题四：标准化天文数据 SDK

### 5.1 代码重复诊断

通过代码扫描确认的**逻辑重复**：

| 功能 | Backend (Java) | Pipeline (Python) | Frontend (TypeScript) | 重复度 |
|------|---------------|-------------------|----------------------|--------|
| 坐标验证 | `CoordinateValidator.java:19-41` | — | `useCoordinateValidation.ts:17-53` | **Java ⇄ TS 重复** |
| FITS 读取/验证 | — | `fits_core.py:18-73` | — | 仅 Pipeline |
| WCS 坐标转换 | — | `fits_core.py:149-221` | 通过 API 调用 | 仅 Pipeline |
| 百分位拉伸 | — | server.py 中 4 处重复 | — | **Pipeline 内部重复** |
| DSS2 文件名解析 | — | server.py 中 3 处正则重复 | — | **Pipeline 内部重复** |
| FITS 路径安全处理 | — | server.py `_safe_path()` | `util/url.ts` | 逻辑分散 |

### 5.2 统一 SDK 设计

**原则**：
1. **Python 为权威源** — 所有天文算法以 Python 实现为准（Astropy 生态最完善）
2. **TypeScript 为展示层** — 前端不实现天文算法，校验规则从 OpenAPI schema 生成
3. **Java 为业务层** — 后端不实现天文算法，调用 Pipeline API

**SDK 结构**：

```
gw-astrosdk/                          # 独立 Python 包，可 pip install
├── pyproject.toml
├── gw_astrosdk/
│   ├── coordinates.py                # 坐标验证、格式转换、交叉匹配
│   ├── fits.py                       # FITS I/O、完整性检查、WCS 操作
│   ├── photometry.py                 # 孔径测光、百分位拉伸、SNR
│   ├── surveys.py                    # 巡天数据常量（DSS2/LEGACY/2MASS/WISE…）
│   ├── visualization.py              # 拉伸方法（percentile/asinh/log）、RGB 合成
│   └── constants.py                  # RA/Dec 范围常量
└── tests/
```

**关键接口示例**：

```python
# coordinates.py
def validate_ra(ra: float) -> tuple[bool, str | None]: ...
def validate_dec(dec: float) -> tuple[bool, str | None]: ...
def sexagesimal_to_decimal(ra_str: str, dec_str: str) -> tuple[float, float]: ...
def angular_separation(ra1, dec1, ra2, dec2) -> float: ...

# fits.py
def read_fits_safe(filepath: Path) -> dict: ...
def stretch_percentile(data: np.ndarray, q_low=5, q_high=99.5) -> np.ndarray: ...
def stretch_asinh(data: np.ndarray, q_low=1, q_high=99) -> np.ndarray: ...

# surveys.py
class Survey(Enum):
    DSS2 = "DSS2"
    LEGACY = "LEGACY"
    TWOMASS = "2MASS"
    # ...
SURVEY_BANDS = { Survey.DSS2: ["DSS2-Blue", "DSS2-Green", "DSS2-Red"], ... }
```

**立即可做的消除重复（不等 SDK 完成）**：
1. Pipeline 内部：抽取 `_stretch_data(data, method, q_low, q_high)` 统一拉伸函数
2. DSS2 文件名解析：抽取 `_parse_dss2_filename(name)` 单一正则函数
3. 前端：从 Pipeline OpenAPI schema 自动生成 TypeScript 类型（`openapi-typescript`）

---

## 6. 问题五：安全体系完善

### 6.1 现状诊断

| 安全维度 | 当前状态 | 差距 |
|---------|---------|------|
| JWT 认证 | ✅ `AuthInterceptor` + `JwtUtil` | 基本完善 |
| IP 限流 | ✅ `RateLimitInterceptor` + Bucket4j | 单机内存，需 Redis 支持分布式 |
| 登录防爆破 | ❌ 无 | **完全缺失** |
| API 审计日志 | ❌ 无 | **完全缺失** |
| 敏感操作留痕 | ❌ 无 | 批量导出、删除数据无记录 |
| HTTPS | ✅ Nginx 双端口 | OK |
| 网络隔离 | ✅ gw-net / gw-db 分段 | OK |
| 生产端口屏蔽 | ✅ docker-compose.prod.yml | OK |
| CORS / CSP | ✅ Nginx 层 | OK |

### 6.2 安全加固方案

#### Phase A：登录防爆破（1 天）

**登录接口特殊限流**：5 次 / 15 分钟

```java
// AuthController.java — 账号锁定机制
private final Map<String, LoginAttempt> attempts = new ConcurrentHashMap<>();

public LoginResponse login(LoginRequest req) {
    LoginAttempt attempt = attempts.computeIfAbsent(req.getUsername(), k -> new LoginAttempt());
    
    if (attempt.isLocked()) {
        throw ApiException.tooManyRequests(
            "Account locked. Try again in " + attempt.remainingLockMinutes() + " minutes");
    }
    
    if (!authenticate(req)) {
        attempt.fail();  // failures++ ; if >= 5, lock 30 min
        throw ApiException.unauthorized(
            "Invalid credentials (" + attempt.remainingAttempts() + " attempts left)");
    }
    
    attempt.reset();
    // ... issue JWT
}
```

#### Phase B：API 审计日志（2-3 天）

**新增 `AuditLogInterceptor`**，记录所有写操作到 MongoDB `audit_logs` 集合：

```json
{
    "timestamp": "2026-07-24T16:30:00.123Z",
    "user_id": "user-123",
    "ip": "192.168.1.100",
    "method": "DELETE",
    "path": "/api/app/gravitationalwave/error/delete",
    "status_code": 200,
    "duration_ms": 45,
    "operation_type": "DELETE_ERROR_RECORD",
    "resource_id": "abc-123"
}
```

- 敏感操作（POST/PUT/DELETE）全量记录
- GET 请求采样记录（1%）
- TTL 索引 90 天自动过期

#### Phase C：敏感操作二次确认 + 留痕（1-2 天）

| 操作 | 目标 |
|------|------|
| 删除异常记录 | 前端二次确认对话框 + 审计日志 |
| 批量导出 FITS (>10 文件) | 记录导出操作，写审计日志 |
| 删除 Collection | 二次确认 + 审计日志 |
| 删除评论 | 审计日志（已确认操作人） |

---

## 7. 分阶段实施路线图

```
2026 Q3 (7-9月)                2026 Q4 (10-12月)             2027 Q1 (1-3月)
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────────┐
│ 🔴 紧急安全加固  │    │ 🟡 分布式扩展    │    │ 🟢 AI 模型落地       │
│                 │    │                 │    │                     │
│ • 登录防爆破    │    │ • Redis 引入     │    │ • 异常检测 ResNet   │
│ • 审计日志      │    │ • 限流切换 Redis │    │ • 训练数据标注      │
│ • Pipeline 内部 │    │ • Celery 任务队列│    │ • 推理服务容器      │
│   重复消除      │    │ • MongoDB 副本集 │    │ • MLflow 实验追踪   │
│                 │    │                 │    │                     │
├─────────────────┤    ├─────────────────┤    ├─────────────────────┤
│ 🔴 监控体系     │    │ 🟡 SDK 标准化   │    │ 🟢 多信使关联        │
│                 │    │                 │    │                     │
│ • Prometheus    │    │ • gw-astrosdk   │    │ • GCN 警报接入      │
│ • Grafana 面板  │    │ • Pipeline 重构 │    │ • HEALPix 交叉匹配  │
│ • 核心告警规则  │    │ • OpenAPI → TS  │    │ • 关联概率排序      │
│ • 钉钉通知      │    │   类型生成      │    │                     │
└─────────────────┘    └─────────────────┘    └─────────────────────┘
      2-3 周                 4-6 周                   8-12 周

2027 Q2+ (4月+)
┌──────────────────────────┐
│ 🔵 生产级 K3s 迁移       │
│                          │
│ • Docker Compose → K3s   │
│ • K8s ConfigMap/Secrets  │
│ • HPA 自动扩缩容         │
│ • MongoDB Atlas 云数据库 │
│                          │
│ 🔵 LLM 增强              │
│ • RAG 文献检索           │
│ • 领域 SFT（可选）       │
└──────────────────────────┘
      4-8 周
```

### 优先级矩阵

```
                    高影响
                      │
       ┌──────────────┼──────────────┐
       │  登录防爆破   │  Prometheus   │
       │  审计日志     │  告警体系      │
       │  SDK 消除重复 │  Redis 限流    │
 低 ───┼──────────────┼──────────────┼─── 高
 成本  │  Celery 队列  │  ML 异常检测   │   成本
       │  SDK 开发     │  K3s 迁移      │
       │  RAG 增强     │  多信使关联    │
       │  GPT 微调     │  MongoDB 副本集 │
       └──────────────┼──────────────┘
                      │
                    低影响

→ 优先做左上角（低成本高影响）：监控告警、安全加固
→ 其次做右上角（高成本高影响）：ML 模型、分布式
→ 最后做左下角（低成本低影响）：RAG、微调
```

---

## 8. 算力与成本估算

### 8.1 当前配置（已知）

| 资源 | docker-compose.yml 限制 | 合计 |
|------|------------------------|------|
| CPU | 3.0 (backend) + 2.0 (pipeline+firefly+ES) + 1.5 (mongo) + 1.0 (mcp+frontend) | **12.5 cores** |
| Memory | 2G (backend+firefly) + 1.5G (ES) + 1G (mongo+pipeline) + 512M (mcp) + 256M (frontend) | **8.3 GB** |

### 8.2 各阶段新增资源

| 阶段 | 新增容器 | 额外 CPU | 额外 Memory | 额外 Disk |
|------|---------|---------|-------------|-----------|
| 安全加固 (Q3) | 无 | 0 | 0 | +50MB（审计日志） |
| 监控告警 (Q3) | Prometheus, Grafana, exporters ×5 | +1.0 core | +1GB | +10GB（指标，30天） |
| 分布式 (Q4) | Redis, Celery worker ×2 | +1.5 core | +1.5GB | +5GB |
| AI 模型 (Q1) | MLflow, gw-inference (GPU) | +2.0 core + GPU | +4GB | +50GB（模型+数据集） |
| K3s (Q2) | K3s overhead | +0.5 core | +512MB | 0 |
| **全部** | **+12 容器** | **+5.0 cores + GPU** | **+7GB** | **+65GB** |

### 8.3 硬件建议

| 方案 | 配置 | 预算 | 适用 |
|------|------|------|------|
| **最低**（仅 Q3 安全+监控） | 当前机器 + 8GB RAM | ¥0 | 安全加固 + 基础监控 |
| **推荐**（Q3-Q4 全部） | 16 核 + 64GB RAM + 1TB SSD | ~¥8,000 | 安全 + 监控 + 分布式 + SDK |
| **完整**（含 AI） | 16 核 + 64GB RAM + 1TB SSD + RTX 4090 24GB | ~¥20,000 | 全部功能 |
| **云方案** | AutoDL A100 按需 + 云 MongoDB/ES | ~¥500-2000/月 | 无需硬件投资 |

---

## 附录 A：技术选型对照表

| 组件 | 推荐 | 备选 | 选择理由 |
|------|------|------|---------|
| 指标收集 | Prometheus | Netdata/Datadog | 开源标准，生态最广 |
| 可视化 | Grafana | Kibana | 插件最丰富，告警统一管理 |
| 日志聚合 | Loki | ELK Stack | 轻量，与 Prometheus 无缝集成 |
| 任务队列 | Celery + Redis | RabbitMQ/Kafka | Redis 已有，Celery 文档丰富 |
| 分布式限流 | Redis (已有接口) | Nginx rate limit | 与现有 Java RateLimiter 接口一致 |
| 模型管理 | MLflow | Wandb/Neptune | 自托管，零外部依赖 |
| 推理服务 | BentoML | Triton/TorchServe | 简单，Python-native |
| 容器编排 | K3s | K8s/Docker Swarm | 轻量，科研场景最适 |
| 向量数据库 | ChromaDB | Milvus/Weaviate | 零配置，Python-native |

---

## 附录 B：相关文件索引

| 文件 | 内容 | 问题关联 |
|------|------|---------|
| `gw-backend/.../CoordinateValidator.java` | 坐标验证（Java） | 问题四 |
| `gw-backend/.../RateLimiter.java` | 限流接口 | 问题二、五 |
| `gw-backend/.../AuthInterceptor.java` | JWT 鉴权 | 问题五 |
| `gw-backend/.../InMemoryRateLimiter.java` | Bucket4j 令牌桶 | 问题二 |
| `gw-pipeline/fits_core.py` | FITS/WCS 核心 | 问题四 |
| `gw-pipeline/server.py` | 全部 API + 重复拉伸逻辑 | 问题一、三、四 |
| `gw-pipeline/source_extraction.py` | 源检测算法（纯传统） | 问题一 |
| `gw-pipeline/job_queue.py` | 内存任务队列 | 问题二 |
| `gw-frontend/.../useCoordinateValidation.ts` | 坐标验证（TS，与 Java 重复） | 问题四 |
| `gw-frontend/.../AIFloatingButton.tsx:24` | 异常检测 UI 占位文案 | 问题一 |
| `docker-compose.yml` | 容器编排 | 问题二、三 |
