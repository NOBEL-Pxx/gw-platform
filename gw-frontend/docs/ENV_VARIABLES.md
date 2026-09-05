# 环境变量配置说明

## Vite 环境变量加载规则

Vite 会按以下顺序加载环境变量文件（后面的会覆盖前面的）：

1. `.env` - 所有环境都会加载
2. `.env.local` - 所有环境都会加载（会被 git 忽略，适合本地配置）
3. `.env.[mode]` - 只在指定 mode 时加载（如 `.env.development`）
4. `.env.[mode].local` - 只在指定 mode 时加载（会被 git 忽略）

## 当前项目配置

- `package.json` 中的 `start` 脚本：`vite --mode development`
- 所以会加载：`.env` → `.env.local` → `.env.development` → `.env.development.local`

## 环境变量列表

### VITE_USE_MOCK

是否启用 Mock 数据（用于本地开发，当后端接口未就绪时）

- 类型：`boolean`
- 默认值：`false`
- 示例：`VITE_USE_MOCK=true`

### VITE_BACKEND_BASE_URL

后端服务地址（本地开发使用）

- 类型：`string`
- 默认值：`http://localhost:8093`（在 `vite.config.ts` 中配置）
- 示例：`VITE_BACKEND_BASE_URL=http://localhost:8093`
- 说明：
  - 用于静态资源 URL 拼接（当后端返回相对路径时，通过 `src/util/url.ts`）
  - 用于 Vite 开发服务器代理配置（`/api/` 和 `/static-files/`）
  - 生产环境不需要配置（通过 Nginx 动态代理，由 Docker 环境变量 `BACKEND_SERVICE_URL` 控制）

## 如何设置 VITE_USE_MOCK

### 方式1：使用 `.env.development`（推荐用于开发环境）

创建或编辑 `.env.development` 文件：

```bash
VITE_USE_MOCK=true
```

### 方式2：使用 `.env.local`（推荐用于本地配置，不会被 git 提交）

创建 `.env.local` 文件：

```bash
VITE_USE_MOCK=true
```

**优点：**

- 不会被 git 提交（已在 .gitignore 中）
- 所有环境都会加载
- 适合个人本地配置

### 方式3：使用 `.env.development.local`（最高优先级）

创建 `.env.development.local` 文件：

```bash
VITE_USE_MOCK=true
```

**优点：**

- 最高优先级，会覆盖其他配置
- 不会被 git 提交

## 验证环境变量是否生效

1. **重启开发服务器**（重要！）
2. 查看控制台输出：
   - ✅ 如果看到 `[MOCK] GET /api/app/gravitationalwave/error - 使用 Mock 数据响应`，说明 Mock 已启用
   - ❌ 如果看到 `[MOCK] Mock 未启用 (VITE_USE_MOCK=undefined)`，说明环境变量未加载

## 常见问题

### Q: 为什么设置了 `.env.development` 但还是 `undefined`？

**A: 检查以下几点：**

1. **文件位置**：`.env.development` 必须在项目根目录（与 `package.json` 同级）
2. **变量名格式**：必须以 `VITE_` 开头
3. **值格式**：不需要引号，直接写 `true` 或 `false`
4. **重启服务器**：修改环境变量后必须重启开发服务器

### Q: `.env.development` 和 `.env.local` 有什么区别？

**A:**

- `.env.development`：只在 `--mode development` 时加载，会被 git 提交
- `.env.local`：所有环境都会加载，不会被 git 提交（适合个人配置）

### Q: 如何确认当前加载了哪些环境变量？

**A:** 在代码中使用 `import.meta.env` 查看：

```typescript
console.log('VITE_USE_MOCK:', import.meta.env.VITE_USE_MOCK)
```

## 推荐配置

**开发环境使用 Mock：**

- 创建 `.env.local` 文件（不会被 git 提交）
- 内容：`VITE_USE_MOCK=true`

**生产环境不使用 Mock：**

- 不设置 `VITE_USE_MOCK` 或设置为 `false`
- 或者不创建 `.env.local` 文件
