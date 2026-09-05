# Mock 开发指南 - 后端接口未完成时的本地开发方案

## 概述

当后端接口还未完成或不可用时，可以使用 `vite-plugin-mock-simple` 插件进行本地开发。该插件会在开发服务器中拦截指定的 API 请求，返回 Mock 数据，让你可以独立进行前端开发。

## 快速开始

### 1. 确认 Mock 插件已配置

`vite.config.ts` 中已经引入了 mock 插件：

```typescript
import mockPlugin from './vite-plugin-mock-simple'

export default defineConfig({
  plugins: [react(), mockPlugin()], // ✅ mock 插件已添加
  // ...
})
```

### 2. 启用 Mock

**创建 `.env.local` 文件**（在项目根目录下）：

```bash
VITE_USE_MOCK=true
```

**注意：**

- 文件必须在项目根目录（与 `package.json` 同级）
- 环境变量名必须是 `VITE_USE_MOCK`（必须以 `VITE_` 开头）
- 值不需要引号，直接写 `true`
- `.env.local` 文件不会被 git 提交（已在 .gitignore 中）

### 3. 重启开发服务器

**重要：修改环境变量后必须重启开发服务器！**

```bash
# 停止当前服务器（Ctrl+C）
npm run start
```

### 4. 验证 Mock 是否生效

启动后，在浏览器控制台应该能看到：

```
[MOCK] 插件初始化
[MOCK] Mode: development
[MOCK] VITE_USE_MOCK: true
[MOCK] GET /api/app/gravitationalwave/error - 使用 Mock 数据响应
[MOCK] 返回错误列表数据
```

如果看到这些日志，说明 Mock 已成功启用！

## 工作原理

### Mock 插件工作流程

1. **环境变量检查**：插件启动时检查 `VITE_USE_MOCK` 环境变量
2. **请求拦截**：如果 Mock 已启用，插件会拦截匹配的 API 请求
3. **返回 Mock 数据**：从 `src/mock/errorMock.ts` 中读取 Mock 数据并返回
4. **标识响应**：在响应头中添加 `X-Mock-Response: true` 标识

### 当前支持的接口

Mock 插件会拦截以下接口：

- `GET /api/app/gravitationalwave/error` - 获取错误报告列表
- `GET /api/app/gravitationalwave/error/:id` - 获取错误报告详情
- `GET /static-files/error/:errorId/:uuid` - 获取错误引用数据

### Mock 与代理的关系

- **Mock 中间件在 proxy 之前执行**
- 如果 `VITE_USE_MOCK=true`，Mock 会拦截请求并返回 mock 数据
- 如果 `VITE_USE_MOCK` 未设置或为 `false`，请求会继续走 proxy 到真实后端
- **两者不冲突**，可以随时切换

## 修改 Mock 数据

### Mock 数据位置

所有 Mock 数据定义在 `src/mock/errorMock.ts` 文件中：

```typescript
// 错误报告列表
export const mockErrorReports: MockErrorReport[] = [
  { id: 'error-001' },
  { id: 'error-002' },
  // ...
]

// 错误详情数据（数组格式）
export const mockErrorDetails: MockErrorReportDetail[] = [
  {
    id: 'error-001',
    uuid: 'uuid-001-1',
    logContent: '...',
    // ...
  },
  // ...
]
```

### 如何添加新的 Mock 数据

1. 打开 `src/mock/errorMock.ts`
2. 在对应的数组中添加新的数据项
3. 保存文件，**无需重启服务器**（HMR 会自动更新）

### 示例：添加新的错误报告

```typescript
// 在 mockErrorReports 中添加
export const mockErrorReports: MockErrorReport[] = [
  { id: 'error-001' },
  { id: 'error-002' },
  { id: 'error-005' }, // ✅ 新增
]

// 在 mockErrorDetails 中添加对应的详情
export const mockErrorDetails: MockErrorReportDetail[] = [
  // ... 现有数据
  {
    id: 'error-005', // ✅ 新增
    uuid: 'uuid-005-1',
    logContent: 'New error log content',
    logFileName: 'error-005.log',
    ra: 250.0,
    dec: 40.0,
  },
]
```

## 如何区分 Mock 响应和真实后端响应

### 1. 浏览器控制台日志

**Mock 响应：**

```
[MOCK] GET /api/app/gravitationalwave/error - 使用 Mock 数据响应
[MOCK] 返回错误列表数据
[Service] 检测到 Mock 响应: /api/app/gravitationalwave/error
```

**真实后端响应：**

```
[Service] 真实后端响应错误: /api/app/gravitationalwave/error 500
```

### 2. Network 面板 - 响应头

在浏览器开发者工具的 Network 面板中，查看响应头：

**Mock 响应会包含：**

- `X-Mock-Response: true`
- `X-Mock-Source: vite-plugin-mock-simple`

**真实后端响应：**

- 不会有这些响应头

### 3. 响应体标识

**Mock 响应示例：**

```json
{
  "error": {
    "code": "0",
    "msg": "success"
  },
  "data": { ... },
  "_mock": true  // ✅ Mock 标识
}
```

**真实后端响应：**

```json
{
  "error": {
    "code": "0",
    "msg": "success"
  },
  "data": { ... }
  // ❌ 没有 _mock 字段
}
```

### 4. 错误消息提示

**Mock 404：**

- 错误消息会包含 `[MOCK]` 前缀
- 例如：`[MOCK] Error not found - 这是 Mock 数据返回的 404`

**真实后端 404：**

- 错误消息不会有 `[MOCK]` 前缀
- 例如：`404 - Not Found (这是真实后端返回的错误)`

## 常见问题排查

### Q1: 为什么设置了 `VITE_USE_MOCK=true` 但还是走真实接口？

**排查步骤：**

1. ✅ **检查文件位置**

   - `.env.local` 必须在项目根目录（与 `package.json` 同级）

2. ✅ **检查文件内容**

   - 变量名：`VITE_USE_MOCK`（必须以 `VITE_` 开头）
   - 值：`true`（不需要引号，区分大小写）
   - 格式：`VITE_USE_MOCK=true`（等号两边不要有空格）

3. ✅ **重启开发服务器**

   - 修改环境变量后**必须重启**开发服务器
   - 停止服务器（Ctrl+C），然后重新运行 `npm run start`

4. ✅ **查看启动日志**
   - 启动时应该看到：`[MOCK] VITE_USE_MOCK: true`
   - 如果显示 `undefined`，说明环境变量未加载

### Q2: 如何确认 Mock 是否生效？

**检查方法：**

1. **查看浏览器控制台**

   - ✅ Mock 生效：会看到 `[MOCK]` 开头的日志
   - ❌ Mock 未生效：会看到 `[Service] 真实后端响应错误` 的日志

2. **查看 Network 面板**

   - 响应头中是否有 `X-Mock-Response: true`？
   - 响应体中是否有 `_mock: true` 字段？

3. **查看错误消息**
   - Mock 返回的错误会包含 `[MOCK]` 前缀

### Q3: Mock 返回 404 怎么办？

**现象：**

```
[MOCK] 404 - 错误详情未找到: error-999 (这是 Mock 返回的 404)
```

**解决方案：**

- 在 `src/mock/errorMock.ts` 中添加对应的 Mock 数据
- 确保 `id` 或 `uuid` 匹配

### Q4: 如何关闭 Mock？

**方法1：删除环境变量**

- 删除 `.env.local` 文件中的 `VITE_USE_MOCK=true` 行

**方法2：设置为 false**

```bash
VITE_USE_MOCK=false
```

**然后重启开发服务器**

### Q5: Mock 和代理冲突吗？

**不冲突！**

- Mock 中间件在 proxy 之前执行
- 如果 `VITE_USE_MOCK=true`，Mock 会拦截请求
- 如果 `VITE_USE_MOCK=false` 或未设置，请求会继续走 proxy
- 可以随时通过环境变量切换

## 开发工作流建议

### 场景1：后端接口未完成

1. ✅ 启用 Mock：创建 `.env.local`，设置 `VITE_USE_MOCK=true`
2. ✅ 修改 Mock 数据：在 `src/mock/errorMock.ts` 中添加测试数据
3. ✅ 进行前端开发：独立开发，不依赖后端
4. ✅ 后端接口完成后：关闭 Mock，切换到真实接口

### 场景2：后端接口不稳定

1. ✅ 启用 Mock：使用稳定的 Mock 数据进行开发
2. ✅ 需要测试真实接口时：临时关闭 Mock（设置 `VITE_USE_MOCK=false`）
3. ✅ 测试完成后：重新启用 Mock 继续开发

### 场景3：联调测试

1. ✅ 关闭 Mock：设置 `VITE_USE_MOCK=false` 或删除环境变量
2. ✅ 重启服务器：确保使用真实后端接口
3. ✅ 进行联调测试

## 调试技巧

1. **使用控制台过滤器**

   - 在控制台中使用 `[MOCK]` 过滤，只看 Mock 相关日志

2. **同时打开控制台和 Network 面板**

   - 可以更清楚地看到请求流程和响应详情

3. **检查环境变量**

   - 在代码中临时添加：`console.log('VITE_USE_MOCK:', import.meta.env.VITE_USE_MOCK)`

4. **查看插件初始化日志**
   - 启动服务器时查看是否有 `[MOCK] 插件初始化` 日志
   - 确认 `VITE_USE_MOCK` 的值

## 总结

使用 Mock 插件进行本地开发的核心步骤：

1. ✅ **启用 Mock**：创建 `.env.local`，设置 `VITE_USE_MOCK=true`
2. ✅ **重启服务器**：修改环境变量后必须重启
3. ✅ **修改数据**：在 `src/mock/errorMock.ts` 中修改 Mock 数据
4. ✅ **验证效果**：查看控制台和 Network 面板确认 Mock 生效
5. ✅ **切换模式**：通过环境变量随时切换 Mock/真实接口

这样你就可以在后端接口未完成时，独立进行前端开发了！
