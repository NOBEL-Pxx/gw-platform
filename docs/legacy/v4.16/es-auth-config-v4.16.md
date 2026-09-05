# Elasticsearch 安全认证配置模板（v4.16）

## 模式切换

### 开发模式（默认 — docker-compose.yml）

```yaml
elasticsearch:
  environment:
    - xpack.security.enabled=true       # 认证开启（最低限度保护）
    - ELASTIC_PASSWORD=${ES_PASSWORD}   # 密码从 .env 读取
  # 注：开发模式仍启用 xpack，但仅使用 Basic Auth
  # 无 TLS/HTTPS — 仅用于本地 Docker 网络
```

### 生产模式（docker-compose.prod.yml 叠加）

在已有的 `docker-compose.prod.yml` 中添加以下 ES 安全配置：

```yaml
services:
  elasticsearch:
    environment:
      # ── 生产安全加固 ──
      - xpack.security.enabled=true
      - xpack.security.transport.ssl.enabled=true
      - xpack.security.transport.ssl.verification_mode=certificate
      - xpack.security.transport.ssl.keystore.path=/usr/share/elasticsearch/config/certs/elastic-certificates.p12
      - xpack.security.transport.ssl.truststore.path=/usr/share/elasticsearch/config/certs/elastic-certificates.p12
      - xpack.security.http.ssl.enabled=true
      - xpack.security.http.ssl.keystore.path=/usr/share/elasticsearch/config/certs/elastic-certificates.p12
      # 审计日志
      - xpack.security.audit.enabled=true
      - xpack.security.audit.logfile.events.include=access_denied,authentication_failed,connection_denied
    volumes:
      - ./docker-data/es-certs:/usr/share/elasticsearch/config/certs:ro
```

### 一键启用步骤

```bash
# 1. 生成 ES 证书（仅需一次）
docker exec gw-elasticsearch bin/elasticsearch-certutil ca --out /tmp/elastic-stack-ca.p12 --pass ""
docker exec gw-elasticsearch bin/elasticsearch-certutil cert \
    --ca /tmp/elastic-stack-ca.p12 --ca-pass "" \
    --out /tmp/elastic-certificates.p12 --pass ""
docker cp gw-elasticsearch:/tmp/elastic-certificates.p12 docker-data/es-certs/

# 2. 以生产模式启动
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d elasticsearch

# 3. 验证 HTTPS 启用
curl -k -u elastic:$ES_PASSWORD https://localhost:9200/_cluster/health
```

### 开发模式快速切换（关闭认证 — 仅限本地调试）

```bash
# 临时关闭 xpack（docker-compose.override.yml）
cat > docker-compose.override.yml << 'EOF'
services:
  elasticsearch:
    environment:
      - xpack.security.enabled=false
EOF

docker compose up -d elasticsearch
# 使用后删除: rm docker-compose.override.yml
```

### 配置对照表

| 配置项 | 开发 | 生产 |
|--------|------|------|
| `xpack.security.enabled` | `true` | `true` |
| HTTP SSL/TLS | 关闭 | **开启** |
| Transport SSL | 关闭 | **开启** |
| 审计日志 | 关闭 | **开启** |
| 密码 | `.env` 文件 | `.env` 文件 (≥16字符) |
| 匿名访问 | 无 | 无 |
