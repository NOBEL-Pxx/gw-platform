/**
 * URL 工具函数
 *
 * 用于处理静态资源 URL，兼容相对路径和绝对路径
 *
 * 如果后端返回相对路径，会拼接后端服务地址（从环境变量 VITE_BACKEND_BASE_URL 读取）
 * 如果后端返回绝对路径，直接使用
 */

// 后端服务地址（从环境变量读取，在开发与生产环境中默认使用相对路径）
const BACKEND_BASE_URL = import.meta.env.VITE_BACKEND_BASE_URL || ''

/**
 * 处理静态资源 URL
 * @param path 后端返回的路径（可能是相对路径或绝对路径）
 * @returns 处理后的完整 URL
 */
export function getStaticResourceUrl(path: string | undefined | null): string {
  if (!path) {
    return ''
  }

  // 如果已经是完整的 URL（以 http:// 或 https:// 开头），直接返回
  if (path.startsWith('http://') || path.startsWith('https://')) {
    return path
  }

  // 如果是相对路径，确保以 / 开头
  const normalizedPath = path.startsWith('/') ? path : `/${path}`

  // 统一拼接后端地址（前后端在不同端口，需要完整 URL）
  return `${BACKEND_BASE_URL}${normalizedPath}`
}

/**
 * 处理 FITS 文件路径
 * @param fitsPath 后端返回的 FITS 文件路径
 * @returns 处理后的完整 URL
 */
export function getFitsUrl(fitsPath: string | undefined | null): string {
  return getStaticResourceUrl(fitsPath)
}

/**
 * 处理图片路径
 * @param imagePath 后端返回的图片路径
 * @returns 处理后的完整 URL
 */
export function getImageUrl(imagePath: string | undefined | null): string {
  return getStaticResourceUrl(imagePath)
}
