# Gravitational Wave Frontend

基于 React + TypeScript + Vite 构建的重力波前端应用。

## 快速开始

### 安装依赖

```bash
npm install
```

### 启动开发服务器

```bash
npm run start
```

### 构建生产版本

```bash
npm run build
```

## 项目文档

所有项目文档已归档到 `docs/` 目录，请根据需要查阅：

### 📚 开发指南

- **[环境变量配置说明](./docs/ENV_VARIABLES.md)** - Vite 环境变量的配置和使用方法
- **[Mock 开发指南](./docs/MOCK_DEVELOPMENT_GUIDE.md)** - 后端接口未完成时如何使用 Mock 插件进行本地开发

### 🔧 技术文档

- **[Aladin 组件防重新挂载指南](./docs/ALADIN_PREVENT_REMOUNT.md)** - 如何保持 Aladin 组件不重新挂载，避免重复初始化

## 项目配置

### ESLint 配置

如果需要在生产环境中启用类型检查的 lint 规则：

- Configure the top-level `parserOptions` property like this:

```js
export default tseslint.config({
  languageOptions: {
    // other options...
    parserOptions: {
      project: ['./tsconfig.node.json', './tsconfig.app.json'],
      tsconfigRootDir: import.meta.dirname,
    },
  },
})
```

- Replace `tseslint.configs.recommended` to `tseslint.configs.recommendedTypeChecked` or `tseslint.configs.strictTypeChecked`
- Optionally add `...tseslint.configs.stylisticTypeChecked`
- Install [eslint-plugin-react](https://github.com/jsx-eslint/eslint-plugin-react) and update the config:

```js
// eslint.config.js
import react from 'eslint-plugin-react'

export default tseslint.config({
  // Set the react version
  settings: { react: { version: '18.3' } },
  plugins: {
    // Add the react plugin
    react,
  },
  rules: {
    // other rules...
    // Enable its recommended rules
    ...react.configs.recommended.rules,
    ...react.configs['jsx-runtime'].rules,
  },
})
```

## 部署说明

### 前端镜像打包

```bash
docker build -f Dockerfile --build-arg APP_NAME=gravitationalwave-frontend --build-arg APP_RUN_ENV=${PARAM_ENV} -t gravitationalwave-frontend-service:${IMAGE_TAG} ./
```

参数说明：

- `APP_RUN_ENV`：用于区分测试环境和线上环境，测试环境值为 `dev`，线上环境值为 `prod`
- `IMAGE_TAG`：镜像版本号

### Docker Compose 一键部署

项目根目录下提供了 `docker-compose.yml`，包含前端、后端、MongoDB 三个服务。部署步骤：

```bash
# 启动所有服务
docker compose up -d

# 查看服务状态
docker compose ps

# 停止所有服务
docker compose down
```

启动后，浏览器访问 `http://<服务器IP>:8091` 即可使用。

### Nginx 动态代理配置（核心机制）

前端容器使用 Nginx 官方 Docker 镜像的模板机制，**支持通过 Docker 环境变量动态配置后端代理地址，无需重新打包镜像**。

工作原理：

1. `default.conf.template` 中使用 `${BACKEND_SERVICE_URL}` 占位符
2. 容器启动时，Nginx 官方入口脚本自动执行 `envsubst`，将占位符替换为 `docker-compose.yml` 中定义的环境变量值
3. 替换后的配置文件写入 `/etc/nginx/conf.d/default.conf`，Nginx 随后启动

`docker-compose.yml` 中的关键配置：

```yaml
gravitationalwave-frontend-service:
  environment:
    # 后端服务地址（Docker 内部服务名，同一个 compose 内可直接使用）
    - BACKEND_SERVICE_URL=http://gravitationalwave-backend-service:8093
    # 限制 envsubst 只替换 BACKEND_SERVICE_URL，防止 Nginx 原生变量（如 $uri）被意外替换
    - NGINX_ENVSUBST_FILTER=BACKEND_SERVICE_URL
```

> **说明**：当前后端服务在同一个 `docker-compose.yml` 中时，使用 Docker 内部服务名（`gravitationalwave-backend-service`）即可，客户无需修改。如果后端部署在其他位置，只需修改 `BACKEND_SERVICE_URL` 为实际后端地址即可（如 `http://192.168.1.100:8093`）。

### 配置说明

#### 后端服务地址（本地开发）

本地开发时，Vite 开发服务器会自动将 `/api/` 和 `/static-files/` 请求代理到后端服务。

默认代理目标为 `http://localhost:8093`，如需指向其他地址，可在 `.env.development` 或 `.env.local` 中配置：

```bash
VITE_BACKEND_BASE_URL=http://你的后端地址:端口
```

修改后重启开发服务器即可生效。

