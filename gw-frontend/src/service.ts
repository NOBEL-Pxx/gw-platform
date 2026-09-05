import axios from 'axios'
import { message } from '@/util/AntdMessage'
import {
  APIResponse,
  ResultListType,
  GravitationalWaveItem,
  GravitationalWaveParams,
  CommentItem,
  ErrorReportItem,
  QueryListParams,
  ErrorDetailResponse,
  FavoriteItem,
  CollectionItem,
  PhotometryResponse,
  // v4.32: DL Anomaly Classifier removed
  // AnomalyClassifyResponse,
  // AnomalyClassifyRequest,
} from '@/types/api'

const instance = axios.create({ timeout: 15000 })

const TOKEN_KEY = 'gw_auth_token'

function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

instance.interceptors.request.use(
  (config) => {
    const token = getToken()
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error),
)

const isDev = import.meta.env.DEV

instance.interceptors.response.use(
  (response) => {
    const isMockResponse =
      response.headers['x-mock-response'] === 'true' ||
      response.data?._mock === true

    if (isMockResponse && isDev) {
      console.log(
        `[Service] Mock response: ${response.config.url}`,
        response.headers,
      )
    }

    const error = response.data.error
    const data = response.data.data

    if (error && error.code !== '0') {
      if (error.code === '401' || error.code === '0401') {
        localStorage.removeItem(TOKEN_KEY)
        localStorage.removeItem('gw_auth_user')
        if (window.location.pathname !== '/login') {
          window.location.href = '/login'
        }
      }
      const errorMsg =
        isDev && isMockResponse ? `[MOCK] ${error?.msg}` : error?.msg
      message.error(errorMsg)
      return Promise.reject(new Error(errorMsg || 'Request failed'))
    }
    if (data?.message) {
      message.info(data?.message)
    }
    return response.data
  },
  (error) => {
    if (error.response) {
      if (error.response.status === 401) {
        localStorage.removeItem(TOKEN_KEY)
        localStorage.removeItem('gw_auth_user')
        if (window.location.pathname !== '/login') {
          window.location.href = '/login'
        }
      }
      const status = error.response.status
      const url = error.config?.url || ''
      // R6.29: suppress generic 429 toast for LLM endpoints.
      // chatWithAgentV434 in deepseek.ts already maps 429 to a friendly
      // explanation ("API request quota exhausted"). The generic
      // "429 - Request failed" toast double-displays and obscures the
      // real reason. For all other 4xx/5xx, keep the generic toast.
      const isLlmEndpoint = url.includes('/pipeline/agent/')
      if (!(status === 429 && isLlmEndpoint)) {
        message.error(
          `${status} - ${error.response.statusText || 'Request failed'}`,
        )
      }
    } else {
      if (isDev)
        console.log(
          `[Service] Network error: ${error.config?.url}`,
          error.message,
        )
      message.error(error.message)
    }
    return Promise.reject(error)
  },
)

// ── Search ──
export const getGravitationalWave = async (
  params: GravitationalWaveParams,
): Promise<APIResponse<ResultListType<GravitationalWaveItem>>> => {
  return instance({
    method: 'get',
    url: '/api/app/gravitationalwave/geoSearch',
    params,
  })
}

// ── Comments ──
export const getComments = async (
  id: string,
  params?: { page?: number; page_size?: number },
): Promise<APIResponse<ResultListType<CommentItem>>> => {
  return instance({
    method: 'get',
    url: `/api/app/gravitationalwave/comments/${id}`,
    params,
  })
}

export const getCommentsByUserId = async (
  userId: string,
  params?: { page?: number; size?: number },
): Promise<APIResponse<ResultListType<CommentItem>>> => {
  return instance({
    method: 'get',
    url: `/api/app/gravitationalwave/comments/user/${userId}`,
    params,
  })
}

export const postComment = async (data: {
  grawaveId: string
  content: string
  userId: string
  category: string
}): Promise<APIResponse<CommentItem>> => {
  return instance({
    method: 'post',
    url: '/api/app/gravitationalwave/comments',
    data,
  })
}

// v4.13: Export comments as CSV
export const exportCommentsCsv = async (params?: {
  grawaveId?: string
  userId?: string
  category?: string
}): Promise<string> => {
  return instance({
    method: 'get',
    url: '/api/app/gravitationalwave/comments/export/csv',
    params,
  })
}

// ── Favorites (v4.13) ──
export const toggleFavorite = async (data: {
  grawaveId: string
  band?: string
  ra?: number
  dec?: number
  telescope?: string
}): Promise<
  APIResponse<{ action: string; grawaveId: string; totalFavorites: number }>
> => {
  return instance({
    method: 'post',
    url: '/api/app/gravitationalwave/favorites/toggle',
    data,
  })
}

export const getFavorites = async (params?: {
  page?: number
  size?: number
}): Promise<APIResponse<ResultListType<FavoriteItem>>> => {
  return instance({
    method: 'get',
    url: '/api/app/gravitationalwave/favorites',
    params,
  })
}

export const checkFavorites = async (
  grawaveIds: string[],
): Promise<APIResponse<Record<string, boolean>>> => {
  return instance({
    method: 'post',
    url: '/api/app/gravitationalwave/favorites/check',
    data: { grawaveIds },
  })
}

export const removeFavorite = async (
  grawaveId: string,
): Promise<APIResponse<{ removed: boolean }>> => {
  return instance({
    method: 'delete',
    url: `/api/app/gravitationalwave/favorites/${grawaveId}`,
  })
}

// ── Collections (v4.13) ──
export const createCollection = async (data: {
  name: string
  description?: string
}): Promise<APIResponse<CollectionItem>> => {
  return instance({
    method: 'post',
    url: '/api/app/gravitationalwave/collections',
    data,
  })
}

export const getCollections = async (params?: {
  page?: number
  size?: number
}): Promise<APIResponse<ResultListType<CollectionItem>>> => {
  return instance({
    method: 'get',
    url: '/api/app/gravitationalwave/collections',
    params,
  })
}

export const getPublicCollections = async (params?: {
  page?: number
  size?: number
}): Promise<APIResponse<ResultListType<CollectionItem>>> => {
  return instance({
    method: 'get',
    url: '/api/app/gravitationalwave/collections/public',
    params,
  })
}

export const deleteCollection = async (
  id: string,
): Promise<APIResponse<{ deleted: boolean }>> => {
  return instance({
    method: 'delete',
    url: `/api/app/gravitationalwave/collections/${id}`,
  })
}

export const addToCollection = async (
  collectionId: string,
  data: {
    grawaveId: string
    band?: string
    ra?: number
    dec?: number
    telescope?: string
  },
): Promise<APIResponse<{ added: boolean; itemId: string }>> => {
  return instance({
    method: 'post',
    url: `/api/app/gravitationalwave/collections/${collectionId}/items`,
    data,
  })
}

export const removeFromCollection = async (
  collectionId: string,
  grawaveId: string,
): Promise<APIResponse<{ removed: boolean }>> => {
  return instance({
    method: 'delete',
    url: `/api/app/gravitationalwave/collections/${collectionId}/items/${grawaveId}`,
  })
}

export const shareCollection = async (
  id: string,
): Promise<APIResponse<{ shareToken: string; shareUrl: string }>> => {
  return instance({
    method: 'post',
    url: `/api/app/gravitationalwave/collections/${id}/share`,
  })
}

export const getSharedCollection = async (
  token: string,
): Promise<APIResponse<CollectionItem>> => {
  return instance({
    method: 'get',
    url: `/api/app/gravitationalwave/collections/shared/${token}`,
  })
}

// ── Pipeline (v4.13: photometry comparison) ──
export const getPhotometry = async (
  filenames: string[],
): Promise<PhotometryResponse> => {
  return instance({
    method: 'post',
    url: '/pipeline/photometry',
    data: { filenames },
  })
}

// ── v4.17: DL Anomaly Detector (REMOVED v4.32 — not currently needed) ──
// export const classifyAnomaly = async (data: AnomalyClassifyRequest): Promise<AnomalyClassifyResponse> => {
//   return instance({ method: "post", url: "/pipeline/anomaly/classify", data })
// }

// ── Error Reports ──
export const getErrorReports = async (
  params?: QueryListParams,
): Promise<APIResponse<ResultListType<ErrorReportItem>>> => {
  return instance({
    method: 'get',
    url: '/api/app/gravitationalwave/error',
    params,
  })
}

export const getErrorReportDetail = async (
  id: string,
  params?: QueryListParams,
): Promise<APIResponse<ErrorDetailResponse>> => {
  return instance({
    method: 'get',
    url: `/api/app/gravitationalwave/error/${id}`,
    params,
  })
}

export const getErrorReference = async (
  errorId: string,
  uuid: string,
): Promise<
  APIResponse<
    {
      raw_id: string
      uuid: string
      obs_h5_path: string
    } & GravitationalWaveItem
  >
> => {
  return instance({
    method: 'get',
    url: `/api/app/gravitationalwave/error/${errorId}/${uuid}`,
  })
}

// ── v4.18: Deep Learning Models (locally embedded astronomy-domain models) ──
// Response interceptor (line 68) returns response.data directly, so types
// match the pipeline response body without an Axios wrapper.

export function classifyGalaxyMorphology(
  filename: string,
): Promise<import('@/types/api').GalaxyMorphologyResult> {
  return instance({
    method: 'post',
    url: '/pipeline/dl/morphology',
    data: { filename },
  })
}

export function classifySourceType(
  filename: string,
): Promise<import('@/types/api').SourceTypeResult> {
  return instance({
    method: 'post',
    url: '/pipeline/dl/source-type',
    data: { filename },
  })
}

export function enhanceAnomalyDetection(
  filename: string,
  anomaly_type: string,
  rule_confidence: number,
): Promise<import('@/types/api').DLAnomalyEnhanceResult> {
  return instance({
    method: 'post',
    url: '/pipeline/dl/anomaly/enhance',
    data: { filename, anomaly_type, rule_confidence },
  })
}

export function getDLModelStatus(): Promise<
  import('@/types/api').DLModelStatus
> {
  return instance({ method: 'get', url: '/pipeline/dl/status' })
}

// ── v4.43: Config Admin (Fix #3) ──
export function getConfig(
  namespace: string,
): Promise<
  APIResponse<{ namespace: string; config: Record<string, unknown> }>
> {
  return instance({ method: 'get', url: `/pipeline/admin/config/${namespace}` })
}
export function updateConfig(
  namespace: string,
  data: Record<string, unknown>,
): Promise<
  APIResponse<{ namespace: string; config: Record<string, unknown> }>
> {
  return instance({
    method: 'put',
    url: `/pipeline/admin/config/${namespace}`,
    data,
  })
}
export function resetConfig(namespace: string): Promise<
  APIResponse<{
    namespace: string
    config: Record<string, unknown>
    reset: boolean
  }>
> {
  return instance({
    method: 'post',
    url: `/pipeline/admin/config/${namespace}/reset`,
  })
}

// ── v4.43: Provenance / DOI (Fix #4) ──
export function getDOIs(params?: {
  survey?: string
  page?: number
  page_size?: number
}): Promise<APIResponse<{ dois: unknown[]; total: number }>> {
  return instance({ method: 'get', url: '/pipeline/provenance/dois', params })
}
export function registerDOI(
  data: Record<string, unknown>,
): Promise<APIResponse<{ doi: Record<string, unknown> }>> {
  return instance({ method: 'post', url: '/pipeline/provenance/doi', data })
}
export function getDOIChain(
  observationId: string,
): Promise<APIResponse<{ chain: unknown[]; length: number }>> {
  return instance({
    method: 'get',
    url: `/pipeline/provenance/chain/${observationId}`,
  })
}

// ── v4.43: FITS Upload + Vision (Fix #5) ──
export async function uploadFits(file: File): Promise<{
  upload_id: string
  filename: string
  file_size_mb: number
  checksum_sha256: string
  header_summary: Record<string, unknown>
}> {
  const buf = await file.arrayBuffer()
  const resp = await instance({
    method: 'post',
    url: '/pipeline/fits/upload',
    data: buf,
    headers: {
      'Content-Type': 'application/octet-stream',
      'X-Filename': file.name,
    },
    timeout: 120000,
  })
  return resp.data || resp
}
export function askVision(
  filename: string,
  question: string,
): Promise<{ answer: string; model: string; vision_mode: boolean }> {
  return instance({
    method: 'post',
    url: '/pipeline/agent/vision',
    data: { filename, question },
    timeout: 120000,
  })
}

// ── v4.43: Batch Export (Fix #6) ──
import { downloadBlob, exportTimestamp } from '@/util/export'
export async function exportAnomaliesCsv(filename: string): Promise<void> {
  const resp = await instance({
    method: 'get',
    url: '/pipeline/export/anomalies',
    params: { filename, format: 'csv' },
    responseType: 'blob',
  })
  downloadBlob(
    resp as unknown as Blob,
    `anomalies_${filename}_${exportTimestamp()}.csv`,
  )
}
export async function exportPhotometryCsv(filenames: string[]): Promise<void> {
  const resp = await instance({
    method: 'get',
    url: '/pipeline/export/photometry',
    params: { filenames: filenames.join(','), format: 'csv' },
    responseType: 'blob',
  })
  downloadBlob(resp as unknown as Blob, `photometry_${exportTimestamp()}.csv`)
}
export async function exportSourcesCsv(
  filename: string,
  snrThreshold?: number,
): Promise<void> {
  const resp = await instance({
    method: 'get',
    url: '/pipeline/export/sources',
    params: { filename, snr_threshold: snrThreshold, format: 'csv' },
    responseType: 'blob',
  })
  downloadBlob(
    resp as unknown as Blob,
    `sources_${filename}_${exportTimestamp()}.csv`,
  )
}
