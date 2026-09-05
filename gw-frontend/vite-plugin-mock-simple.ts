/**
 * 简单的 Vite Mock 插件
 * 使用方法：在 vite.config.ts 中引入此插件
 *
 * import mockPlugin from './vite-plugin-mock-simple'
 *
 * export default defineConfig({
 *   plugins: [react(), mockPlugin()],
 *   ...
 * })
 */

import type { Plugin } from 'vite'
import type { IncomingMessage, ServerResponse } from 'http'
import { loadEnv } from 'vite'
import {
  mockErrorReports,
  mockErrorDetails,
  mockErrorReferences,
  createMockResponse,
} from './src/mock/errorMock'

export default function mockPlugin(): Plugin {
  return {
    name: 'vite-plugin-mock-simple',
    config(_config, { mode }) {
      // 在 config 阶段加载环境变量
      const env = loadEnv(mode, process.cwd(), '')
      return {
        define: {
          // 将环境变量注入到代码中
          'import.meta.env.VITE_USE_MOCK': JSON.stringify(
            env.VITE_USE_MOCK || 'false',
          ),
        },
      }
    },
    configureServer(server) {
      // 获取当前 mode（从 server.config 中获取）
      const mode = server.config.mode || 'development'
      // 加载环境变量
      const env = loadEnv(mode, process.cwd(), '')

      const useMock = env.VITE_USE_MOCK === 'true'
      // 只在初始化时打印一次状态
      console.log(
        `[MOCK] 插件已加载 | Mode: ${mode} | Mock: ${useMock ? '已启用' : '未启用'}`,
      )

      // 创建一个通用的 mock 处理函数
      const handleMockRequest = (
        req: IncomingMessage,
        res: ServerResponse,
        next: () => void,
      ) => {
        // 获取完整 URL（包括查询参数）
        // 注意：当使用 server.middlewares.use('/path', handler) 时，
        // 匹配到的请求的 req.url 会被去掉前缀，所以需要从 originalUrl 获取完整路径
        const originalUrl =
          (req as IncomingMessage & { originalUrl?: string }).originalUrl ||
          req.url ||
          ''
        // 去掉查询参数，只保留路径部分
        const url = originalUrl.split('?')[0]
        const method = req.method || 'GET'

        // 检查是否是 mock 模式（从加载的环境变量中读取）
        const useMock = env.VITE_USE_MOCK === 'true'

        // Mock 未启用时，静默处理，不打印任何信息
        if (!useMock) {
          return next()
        }

        // 只处理我们关心的 API 路径
        const isErrorApiPath = url.startsWith(
          '/api/app/gravitationalwave/error',
        )

        if (!isErrorApiPath) {
          // 不是我们要处理的路径，继续下一个中间件
          return next()
        }

        // 设置标识响应头，用于区分 mock 响应
        res.setHeader('Content-Type', 'application/json')
        res.setHeader('X-Mock-Response', 'true')
        res.setHeader('X-Mock-Source', 'vite-plugin-mock-simple')

        // 控制台日志，便于调试
        console.log(`[MOCK] ${method} ${url} - 使用 Mock 数据响应`)

        // 处理 GET /api/app/gravitationalwave/error - 获取错误列表（支持分页）
        if (method === 'GET' && url === '/api/app/gravitationalwave/error') {
          // 从查询参数中获取分页信息
          const urlObj = new URL(`http://localhost${originalUrl}`)
          const page = parseInt(urlObj.searchParams.get('page') || '1', 10)
          const pageSize = parseInt(
            urlObj.searchParams.get('page_size') || '10',
            10,
          )

          const startIndex = (page - 1) * pageSize
          const endIndex = startIndex + pageSize
          const paginatedReports = mockErrorReports.slice(startIndex, endIndex)

          console.log(
            `[MOCK] 匹配到错误列表接口，返回分页数据 (page=${page}, page_size=${pageSize})`,
          )
          res.statusCode = 200
          res.end(
            JSON.stringify(
              createMockResponse({
                total_info: {
                  page,
                  page_size: pageSize,
                  total_count: mockErrorReports.length,
                },
                list: paginatedReports,
              }),
            ),
          )
          return
        }

        // 处理 GET /api/app/gravitationalwave/error/:id 获取错误详情
        const detailMatch = url.match(
          /^\/(api\/app\/gravitationalwave\/error)\/([^/]+)$/,
        )
        if (method === 'GET' && detailMatch) {
          const errorId = detailMatch[2]
          // 从数组中查找匹配的详情，返回该 errorId 对应的所有详情（数组格式）
          // 注意：使用 error_id 字段匹配，因为请求 URL 中使用的是完整的 error_id
          const detailsForErrorId = mockErrorDetails.filter(
            (item) => item.error_id === errorId,
          )

          if (detailsForErrorId.length > 0) {
            // 从查询参数中获取分页信息
            const urlObj = new URL(`http://localhost${originalUrl}`)
            const page = parseInt(urlObj.searchParams.get('page') || '1', 10)
            const pageSize = parseInt(
              urlObj.searchParams.get('page_size') || '10',
              10,
            )

            const startIndex = (page - 1) * pageSize
            const endIndex = startIndex + pageSize
            const paginatedDetails = detailsForErrorId.slice(
              startIndex,
              endIndex,
            )

            console.log(
              `[MOCK] 返回错误详情数组: ${errorId} (共 ${detailsForErrorId.length} 条, 分页: page=${page}, page_size=${pageSize})`,
            )

            // 生成合并的 logContent（包含所有详情记录的日志内容）
            // 格式：头部 + 每行一条日志记录
            const logContentLines = detailsForErrorId
              .map((detail) => detail.logContent)
              .filter((log) => log) // 过滤掉空的 logContent

            const mergedLogContent = [
              '# Anomaly Report (UTF-8)',
              '# Format: ISO8601Z | RA=[start,end] deg | Dec=[start,end] deg | Type | UUID | Image | FITS',
              ...logContentLines,
            ].join('\n')

            // 返回数组格式，只去掉 logContent 字段（logContent 在顶层），保留 id 字段（ErrorDetailItem 需要）
            const detailsWithoutLogContent = paginatedDetails.map(
              ({ logContent: _logContent, ...detail }) => detail,
            )

            res.statusCode = 200
            res.end(
              JSON.stringify(
                createMockResponse({
                  error_id: errorId,
                  logContent: mergedLogContent,
                  total_info: {
                    page,
                    page_size: pageSize,
                    total_count: detailsForErrorId.length,
                  },
                  list: detailsWithoutLogContent,
                }),
              ),
            )
          } else {
            console.warn(
              `[MOCK] 404 - 错误详情未找到: ${errorId} (这是 Mock 返回的 404)`,
            )
            res.statusCode = 404
            res.end(
              JSON.stringify({
                error: {
                  code: '404',
                  msg: '[MOCK] Error not found - 这是 Mock 数据返回的 404',
                },
                data: null,
                _mock: true, // 标识这是 mock 响应
              }),
            )
          }
          return
        }

        // 处理 GET /api/app/gravitationalwave/error/:errorId/:uuid - 获取错误引用
        const referenceMatch = url.match(
          /^\/api\/app\/gravitationalwave\/error\/([^/]+)\/([^/]+)$/,
        )
        if (method === 'GET' && referenceMatch) {
          const errorId = referenceMatch[1]
          const uuid = referenceMatch[2]
          const reference = mockErrorReferences[errorId]?.[uuid]

          if (reference) {
            console.log(`[MOCK] 返回错误引用: ${errorId}/${uuid}`)
            res.statusCode = 200
            res.end(JSON.stringify(createMockResponse(reference)))
          } else {
            console.warn(
              `[MOCK] 404 - 错误引用未找到: ${errorId}/${uuid} (这是 Mock 返回的 404)`,
            )
            res.statusCode = 404
            res.end(
              JSON.stringify({
                error: {
                  code: '404',
                  msg: '[MOCK] Reference not found - 这是 Mock 数据返回的 404',
                },
                data: null,
                _mock: true, // 标识这是 mock 响应
              }),
            )
          }
          return
        }

        console.log(`[MOCK] 未匹配到路由，继续下一个中间件: ${url}`)
        next()
      }

      // 注册中间件到根路径，然后在 handler 内部检查完整 URL
      // 注意：中间件的顺序很重要，需要在 proxy 之前注册
      console.log('[MOCK] 注册中间件到根路径')
      server.middlewares.use(handleMockRequest)
      console.log('[MOCK] 中间件注册完成')
    },
  }
}
