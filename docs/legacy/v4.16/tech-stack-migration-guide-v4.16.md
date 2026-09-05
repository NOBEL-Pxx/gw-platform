# GravitationalWave Platform — 技术栈迁移与兼容性指南

> **版本**：v4.16 | **日期**：2026-07-24
> **状态**：Spring Boot 3.4.1 + Java 21 迁移已完成，ES 8.x 客户端迁移已完成。本文档记录迁移路径、兼容切换方案和旧依赖下线流程。

---

## 1. 当前技术栈基线（v4.16）

### 1.1 版本矩阵

| 组件 | 当前版本 | 旧版本（已下线） | 迁移状态 |
|------|---------|-----------------|---------|
| **Spring Boot** | 3.4.1 | 2.3.7 | ✅ 已完成 |
| **Java** | 21 (Eclipse Temurin) | 8 | ✅ 已完成 |
| **Maven** | 3.9 | 3.6 | ✅ 已完成 |
| **Elasticsearch Client** | 8.15.0 (`elasticsearch-java`) | 7.17 (`rest-high-level-client`) | ✅ 已完成 |
| **ES Server** | 7.17.28 (Docker) | — | ⚠️ 低版本服务端 |
| **Jakarta EE** | Servlet 6.0 / Mail 2.0.1 | javax.* (全部) | ✅ 已完成 |
| **JJWT** | 0.12.6 | 旧版（含 JAXB） | ✅ 已完成 |
| **Spring Security** | 仅 crypto 模块 | — | 无完整 Security |
| **Bucket4j** | 8.10.1 | — | 新增 |
| **MongoDB Driver** | Spring Boot 3.4.1 管理 | — | 自动同步 |
| **Log4j** | 2.24.0 | Logback（已排除） | ✅ 已完成 |
| **MyBatis** | 3.0.3 (Spring Boot 3.x) | 2.x | ✅ 已完成 |
| **Jackson** | Spring Boot 3.4.1 管理 | — | 自动同步 |
| **OkHttp** | 4.12.0 | — | 新增 |
| **ANTLR4** | 4.13.2 | — | ⚠️ 遗留注释 |

### 1.2 审计确认：已不存在旧依赖

| 旧组件 | 搜索结果 | 结论 |
|--------|---------|------|
| `RestHighLevelClient` | 仅在注释中提及 | ✅ 已从依赖和代码中完全移除 |
| `javax.servlet.*` | 无引用 | ✅ 已全部迁移到 `jakarta.servlet.*` |
| `javax.mail.*` | 无引用 | ✅ 已迁移到 `jakarta.mail 2.0.1` |
| JAXB (XML 绑定) | 无引用 | ✅ JJWT 0.12.6 不再需要 JAXB |
| Logback | 已从所有 starter 中排除 | ✅ 统一使用 Log4j 2.24.0 |
| `spring-boot-starter-security` | 不存在 | ✅ 仅使用 `spring-security-crypto` |

### 1.3 审计确认：仍然存在的低层依赖（正常且必需）

| 组件 | 原因 | 是否需要移除 |
|------|------|------------|
| `org.elasticsearch.client.RestClient` | ES 8.x Java Client 的低层 HTTP 传输层 | ❌ 不需要 — 这是 `ElasticsearchClient` 的依赖 |
| `org.elasticsearch.client.RestClientBuilder` | 同上 — 构建传输层 | ❌ 不需要 |
| `RestClientTransport` (`co.elastic.clients.transport.rest_client`) | ES 8.x 官方传输适配器 | ❌ 不需要 |
| `spring-boot-starter-data-elasticsearch` | Spring Data ES 自动配置（内部使用新客户端） | ⚠️ 建议移除，直接用 `elasticsearch-java` |

> **关键区分**：`RestHighLevelClient`（已移除）≠ `RestClient`（低层传输）。前者是过时的 API 客户端，后者是 ES 8.x 新客户端的 HTTP 传输层，不能移除。

---

## 2. Spring Boot 2.3→3.4 迁移路径（已执行）

### 2.1 已完成的变更

```
Phase 1: Java 版本升级
  pom.xml: <java.version>8 → 21
  Dockerfile: openjdk:8-jre → eclipse-temurin:21-jre-alpine
  Maven: 3.6 → 3.9
  compiler-plugin: source/target 1.8 → 21

Phase 2: javax → jakarta 命名空间迁移
  所有 javax.servlet.* → jakarta.servlet.*
  所有 javax.mail.* → jakarta.mail.*
  javax.persistence → jakarta.persistence (Spring Data 管理)

Phase 3: Spring Boot 3.x 适配
  spring-boot 2.3.7 → 3.4.1
  spring-boot-starter-data-elasticsearch 自动升级
  MyBatis starter 2.x → 3.0.3
  JJWT 旧版 → 0.12.6 (无 JAXB)
  Logback → Log4j 2.24.0

Phase 4: ES 客户端迁移
  rest-high-level-client 7.17 → elasticsearch-java 8.15.0
  RestHighLevelClient → ElasticsearchClient
  查询 DSL 重写 (SearchRequest → SearchRequest.Builder)
```

### 2.2 回滚兼容方案

如果需要回退到 Spring Boot 2.3.7 + Java 8 环境（例如部署到仅支持 Java 8 的服务器），执行以下步骤：

#### 方案 A：Git 分支回退（推荐）

```bash
# 查看 v4.11 标签（最后一个 Spring Boot 2.3.7 版本）
git tag -l "v4.11*"
git checkout v4.11.0

# 使用旧版 Docker Compose
cd D:/AliCPT
docker compose -f docker-compose.yml up -d
```

#### 方案 B：Maven Profile 双构建（如需同时维护两套）

在 `pom.xml` 中添加条件 profile（当前未实现，需要时创建）：

```xml
<!-- 父 pom.xml 中添加 -->
<profiles>
    <!-- 默认：Spring Boot 3.4 + Java 21（当前生产） -->
    <profile>
        <id>sb3</id>
        <activation><activeByDefault>true</activeByDefault></activation>
        <properties>
            <spring-boot.version>3.4.1</spring-boot.version>
            <java.version>21</java.version>
            <elasticsearch-client.version>8.15.0</elasticsearch-client.version>
        </properties>
    </profile>

    <!-- 回退：Spring Boot 2.3 + Java 8（旧服务器） -->
    <profile>
        <id>sb2</id>
        <properties>
            <spring-boot.version>2.3.7.RELEASE</spring-boot.version>
            <java.version>1.8</java.version>
            <elasticsearch-client.version>7.17.28</elasticsearch-client.version>
        </properties>
        <dependencies>
            <!-- 回退 javax.servlet -->
            <dependency>
                <groupId>javax.servlet</groupId>
                <artifactId>javax.servlet-api</artifactId>
                <version>4.0.1</version>
                <scope>provided</scope>
            </dependency>
            <!-- 回退 ES 客户端 -->
            <dependency>
                <groupId>org.elasticsearch.client</groupId>
                <artifactId>elasticsearch-rest-high-level-client</artifactId>
                <version>${elasticsearch-client.version}</version>
            </dependency>
        </dependencies>
    </profile>
</profiles>
```

**注意**：使用 `sb2` profile 时还需要：
1. 将所有 `jakarta.servlet.*` 导入改回 `javax.servlet.*`
2. 将所有 `jakarta.mail.*` 导入改回 `javax.mail.*`
3. 将 JJWT 回退到旧版（含 JAXB 依赖）
4. 将 `ElasticsearchClient` 代码改回 `RestHighLevelClient`

**建议**：不要维护双构建。仅在极端情况下执行方案 A（Git 回退）。

### 2.3 生产环境切换清单

从旧版（SB 2.3.7）切换到新版（SB 3.4.1）时的验证步骤：

```bash
# 1. 验证 Java 版本
docker exec gw-backend java -version  # 应输出: 21.x

# 2. 验证 Spring Boot 版本
docker exec gw-backend sh -c "unzip -p /home/gravitational-wave-backend/app.jar META-INF/MANIFEST.MF | grep 'Spring-Boot-Version'"

# 3. 验证 ES 客户端版本
docker exec gw-backend sh -c "find / -name 'elasticsearch-java-*.jar' 2>/dev/null | head -3"
# 应包含: elasticsearch-java-8.15.0.jar

# 4. 验证无 javax 残留（容器内不应有 javax.servlet 或 javax.mail jar）
docker exec gw-backend sh -c "find / -name 'javax.servlet-*.jar' 2>/dev/null"  # 应无输出

# 5. 功能验证
curl http://localhost:8093/api/app/gravitationalwave/error  # 应返回 JSON
curl http://localhost:8100/health                             # MCP 健康检查
curl http://localhost:8200/health                             # Pipeline 健康检查
```

---

## 3. ES 客户端架构：已完成与待完成

### 3.1 当前架构

```
┌─────────────────────────────────────────────┐
│           应用层 (Service)                    │
│  SearchService.java                         │
│  ErrorListService.java                      │
│  ErrorDetailService.java                    │
│  ErrorDetailServiceImpl.java                │
│  ErrorListServiceImpl.java                  │
│                                             │
│  全部使用: ElasticsearchClient (8.15.0)      │
│  旧 RestHighLevelClient: 已移除 ✅            │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│        传输层 (Transport)                    │
│  ElasticsearchConfig.java                   │
│                                             │
│  RestClient (org.elasticsearch.client)      │  ← 低层 HTTP，非 RestHighLevelClient
│  RestClientBuilder                          │  ← 构建器
│  RestClientTransport                        │  ← ES 8.x 官方适配器
│                                             │
│  这是 ES 8.x Java Client 的标准架构。         │
│  不能移除 — 移除会导致 ElasticsearchClient    │
│  无法连接 ES 服务器。                         │
└──────────────────┬──────────────────────────┘
                   │ HTTP :9200
┌──────────────────▼──────────────────────────┐
│          ES 服务器 (Docker)                   │
│  docker.elastic.co/elasticsearch:7.17.28    │  ← 服务器仍是 7.17
│                                             │
│  ⚠️ 客户端 8.15 vs 服务端 7.17 兼容性：     │
│  8.x Java Client 向后兼容 ES 7.x 服务端      │
│  （通过兼容模式，无需升级服务端）              │
└─────────────────────────────────────────────┘
```

### 3.2 RestHighLevelClient 下线检查清单

| 检查项 | 状态 | 备注 |
|--------|------|------|
| POM 中移除 `elasticsearch-rest-high-level-client` | ✅ 已完成 | v4.12 |
| 移除 `RestHighLevelClient` 所有 import | ✅ 已完成 | v4.12 |
| `SearchService` 迁移到 `ElasticsearchClient` | ✅ 已完成 | v4.12 |
| `ErrorListService` / `ErrorDetailService` 迁移 | ✅ 已完成 | v4.12 |
| 查询 DSL 重写（`SearchRequest` → `SearchRequest.Builder`） | ✅ 已完成 | v4.12 |
| ES 8.x 兼容性测试（向后兼容 ES 7.17 服务端） | ✅ 已验证 | 180 条数据正常 |
| 移除 `spring-boot-starter-data-elasticsearch` | ⚠️ 待评估 | 见 §3.3 |
| 旧 ES 7.x 文档/注释清理 | ⚠️ 部分残留 | `ErrorDetailServiceImpl.java:59` 注释 |

### 3.3 待评估：移除 `spring-boot-starter-data-elasticsearch`

**当前状态**：`spring-boot-starter-data-elasticsearch` 仍在 `service/pom.xml` 中。

**分析**：
- 此 starter 提供 Spring Data Elasticsearch 抽象（`ElasticsearchRepository`、`@Document` 注解等）
- Spring Boot 3.4.1 的 `spring-boot-starter-data-elasticsearch` 内部使用 `elasticsearch-java` 8.x 客户端
- 但当前代码**没有使用** `ElasticsearchRepository` — 所有查询都是通过 `ElasticsearchClient` 手写的
- ES 实体类（`ErrorDetailDO`、`GrawaveDataDO`）使用了 `@Document(indexName=...)` 注解，这来自 Spring Data ES

**建议**：
- **保留**：如果计划在未来使用 Spring Data ES 的 repository 抽象
- **移除**：如果确认永远手写 `ElasticsearchClient` 查询，移除可减少不确定性
- **折中**：保留 starter 但明确文档说明"仅用于 @Document 注解，查询全部手写"

### 3.4 ES 服务端升级路线图

```
当前：ES 7.17.28 (Docker)
       ↓
短期 (2026 Q4)：保持 ES 7.17 — 客户端 8.15 向后兼容
       ↓
中期 (2027 Q1)：ES 7.17 → 8.x （非破坏性升级）
  - 索引兼容，无需重建
  - 8.x 移除 mapping type（7.x 已废弃）
  - API 变化：_template → _index_template（脚本已使用新 API）
       ↓
长期 (2027 Q3+)：ES 8.x → 9.x（评估必要性）
```

---

## 4. 已知技术债清单

### 4.1 代码层面

| 位置 | 问题 | 严重程度 | 建议 |
|------|------|---------|------|
| `pom.xml:166` | ANTLR4 注释 "不支持之江的java8" — Java 8 已不再使用 | 低 | 删除注释，可升级 ANTLR |
| `ErrorDetailServiceImpl.java:59` | 注释提及 "migrated from RestHighLevelClient" | 低 | 删除迁移注释 |
| `ImageCutoutDataSet.java:97` | User-Agent header 字符串 "Java-Spring RestClient" | 低 | 重命名为 "GW-Backend/4.16" |
| `commons-lang3:3.11` | 版本较旧（最新 3.14） | 低 | 升级到 3.14 |
| `commons-collections4:4.4` | 版本较旧（最新 4.5） | 低 | 升级 |

### 4.2 架构层面

| 问题 | 说明 | 建议 |
|------|------|------|
| ES 服务端 7.17 vs 客户端 8.15 | 跨大版本，依赖向后兼容模式 | 2027 Q1 升级服务端 |
| `spring-boot-starter-data-elasticsearch` 未充分利用 | 导入了但仅用 @Document 注解 | 评估是否手写全部查询 |
| 无自动化版本兼容性测试 | 切换 Java/Spring Boot 版本依赖人工验证 | 添加 CI 矩阵测试 |
| Maven profiles 仅有 dev/test/prod | 无 sb2/sb3 版本 profile | 不建议添加（见 §2.2） |

---

## 5. 附录：依赖版本对照表

| 组件 | v4.11 (SB 2.3) | v4.16 (SB 3.4) | 变更原因 |
|------|---------------|---------------|---------|
| Spring Boot | 2.3.7 | 3.4.1 | 安全补丁停止、Jakarta EE 9+ |
| Java | 8 | 21 | LTS 支持、虚拟线程、更好 GC |
| ES Client | 7.17 (RHLClient) | 8.15 (ElasticsearchClient) | RHLClient 7.17 已停止维护 |
| Servlet API | javax 4.0 | jakarta 6.0 | Spring Boot 3.x 强制要求 |
| JJWT | 旧版 + JAXB | 0.12.6 | JAXB 在 Java 11+ 中移除 |
| MyBatis | 2.x | 3.0.3 | Spring Boot 3.x 兼容 |
| Logging | Logback | Log4j 2.24.0 | 异步日志、更低 GC 压力 |
| Bucket4j | 无 | 8.10.1 | 新增分布式限流 |
| OkHttp | 无 | 4.12.0 | ES 8.x Client 底层 HTTP |

---

## 6. 紧急回滚操作手册

如果生产环境切换后出现严重故障，按以下步骤回滚：

### 回滚到 v4.11（SB 2.3.7 + Java 8）

```bash
# 1. 停止当前服务
cd D:/AliCPT
docker compose down

# 2. 切换到 v4.11 代码
git stash
git checkout v4.11.0

# 3. 重建并启动（Dockerfile 自动使用 Java 8 镜像）
docker compose build --no-cache gw-backend
docker compose up -d

# 4. 验证
curl http://localhost:8093/actuator/health  # SB 2.3 使用 /actuator
```

### 数据兼容性

- **MongoDB**：数据格式在 SB 2.3 和 3.4 之间兼容（无 schema 变更）
- **Elasticsearch**：索引数据兼容（ES 7.17 服务端未变）
- **JWT Token**：格式未变（JJWT 0.12.6 生成标准 JWT）
- **评论/收藏/集合**：MongoDB 文档格式未变

**结论：回滚不影响数据完整性。**

---

## 7. 深度审计补充发现（2026-07-24 Agent 全量扫描）

### 7.1 🔴 HIGH：Jenkins CI/CD 使用 Java 8 构建容器

**文件**：`Jenkinsfile_k8s`（如存在）

```groovy
image: m.daocloud.io/docker.io/maven:3.8.2-openjdk-8
```

项目 pom.xml 指定 Java 21（`<java.version>21</java.version>`，`maven-compiler-plugin` source/target 21），但 Jenkins 构建容器仍为 **OpenJDK 8 + Maven 3.8.2**。Java 8 无法编译 `--source 21` 字节码。

**修复**：
```groovy
image: m.daocloud.io/docker.io/maven:3.9-eclipse-temurin-21
```

### 7.2 🟡 MEDIUM：硬编码凭据

| 位置 | 凭据 | 风险 |
|------|------|------|
| `application-dev.properties` | `elastic:elastic` ES 凭据 | 泄露到 Git |
| `application-dev.properties` | `admin:123456` MongoDB | 泄露到 Git |
| `docker-compose.yml` | `omatlhmtfastview` / `omatlhmtfastviewpasswd` | 生产凭据硬编码 |

**修复**：全部替换为环境变量占位符 `${VAR}`，实际值从 `.env` 读取。

### 7.3 🟡 MEDIUM：Lombok 版本偏差

`start/pom.xml` 硬编码 Lombok 1.18.26，而 Spring Boot 3.4.1 BOM 管理更新版本。

### 7.4 🟢 LOW：配置属性命名不一致

`spring.elasticsearch.passwd`（项目自定义）vs `spring.elasticsearch.password`（Spring Boot 标准）。当前可行（通过 `@Value` 手动读取），但增加维护成本。

### 7.5 🟢 LOW：ES 连接/读取超时仅 local profile 配置

`application-local.properties` 有 `connection-timeout=10s` + `socket-timeout=30s`，但 dev/prod/daily 缺失。生产环境 ES 超时依赖系统默认值（可能无限等待）。

**修复**：在 `application-prod.properties` 中添加：
```properties
spring.elasticsearch.connection-timeout=5s
spring.elasticsearch.socket-timeout=60s
```

### 7.6 ℹ️ INFO：ES 查询层无自动化测试

所有 `ElasticsearchClient` 查询（SearchService、ErrorListService、ErrorDetailService）均无单元测试或集成测试。

### 7.7 ℹ️ INFO：ANTLR4 遗留注释

`pom.xml:166` 注释 "不支持之江的java8" — Java 8 已不再使用，注释过时。

---

## 8. 修复优先级排序

| 优先级 | 问题 | 修复时间 | 风险 |
|--------|------|---------|------|
| **P0** | Jenkinsfile Java 8→21 | 10 分钟 | CI/CD 不可用 |
| **P1** | docker-compose.yml 硬编码凭据 | 10 分钟 | 生产凭据泄露 |
| **P1** | dev properties 硬编码凭据 | 5 分钟 | 凭据泄露 |
| **P2** | ES 超时配置补全（dev/prod） | 5 分钟 | 网络故障时阻塞 |
| **P2** | Lombok 版本对齐 | 2 分钟 | 版本冲突 |
| **P3** | ANTLR4 注释清理 | 1 分钟 | 零 |
| **P4** | ES 查询层添加测试 | 2-3 小时 | 中等 |
