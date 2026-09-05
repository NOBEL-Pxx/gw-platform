export type KeyValues = {
  [key: string]: string
}

export type KeyObject = {
  [key: string]: KeyValues
}

type ErrorType = {
  code: string
  msg: string
}

export type APIResponse<T> = {
  error: ErrorType
  data: T
}
export type PageType = {
  page: number
  page_size: number
  total_count: number
}
export type ResultListType<T> = {
  total_info: PageType
  list: Array<T>
}
export type QueryListParams = {
  page?: number
  page_size?: number
}

/**
 * API 相关
 */
export type GravitationalWaveItem = {
  alias: string
  band: string
  dec: number
  end_date: string
  fits_db_path: string
  fits_path: string
  fits_file_path: string
  id: string
  img: string
  img_path: string
  index: string
  // v4.54-r4d: backend-probed blank/missing FITS indicator. When true, the
  // tile should be rendered with the "No substantive data" badge (same path
  // as the client-side lowDataImages set). Avoids the canvas stdev heuristic
  // that false-positived on 2MASS/WISE in R4b.
  isBlank?: boolean
  mapping_location: { lat: number; lon: number }
  width?: number
  height?: number
  module: string
  ra: number
  start_date: string
  tag: string
  target: string
  telescope: string
  type: string
}
export interface GravitationalWaveParams extends QueryListParams {
  ra?: number
  dec?: number
  radius?: number
  uuid?: string
}
export type CommentItem = {
  id: string
  grawaveId: string
  content: string
  userId: string
  username: string
  createdAt: string
  category: string
}
export type ErrorReportItem = {
  id: string
  error_id: string
  anomaly_type: string[]
  band: string
  decfield: number[]
  rafield: number[]
  end_date: string
  fov: number
  height: number
  start_date: string
  telescope: string
  width: number
}

export type ErrorDetailItem = {
  id: string
  uuid: string
  fits_path: string
  img_path: string
  anomaly_log_path: string
  anomaly_type: string
  fov: number
  ra: number
  dec: number
  width: number
  height: number
  start_date: string
  end_date: string
}

export type ErrorDetailResponse = {
  error_id: string
  logContent: string
  list: ErrorDetailItem[]
  total_info: PageType
}

// ── v4.13: Favorites & Collections ──
export type FavoriteItem = {
  id: string
  userId: string
  grawaveId: string
  band: string
  ra: number
  dec: number
  telescope: string
  createdAt: string
}

export type CollectionItem = {
  id: string
  name: string
  description: string
  ownerId: string
  isPublic: boolean
  shareToken: string | null
  createdAt: string
  updatedAt: string
  itemCount: number
  items?: CollectionDataItem[]
}

export type CollectionDataItem = {
  id: string
  collectionId: string
  grawaveId: string
  band: string
  ra: number
  dec: number
  telescope: string
  addedAt: string
}

// ── v4.13: Photometry / Comparison ──
export type PhotometryResult = {
  filename: string
  shape: number[]
  stats: {
    min: number
    max: number
    mean: number
    median: number
    std: number
    nonzero_mean?: number
    nonzero_median?: number
    nonzero_std?: number
    nonzero_fraction?: number
  }
  aperture: {
    center: [number, number]
    radius_px: number
    flux: number
    pixels: number
    flux_per_pixel: number
  }
  wcs: {
    projection?: string
    pixel_scale?: number
  }
  error?: string
}

export type PhotometryResponse = {
  count: number
  results: PhotometryResult[]
}

// -- v4.32: DL Anomaly Detector --
export interface PixelRegion {
  x_min: number
  x_max: number
  y_min: number
  y_max: number
  peak_value: number
  snr: number
}

export interface AnomalyClassifyResult {
  type: 'spike' | 'dip' | 'pattern_break' | 'wcs_mismatch'
  confidence: number
  pixel_regions: PixelRegion[]
  description: string
  wcs_issues: string[]
  fft_hf_lf_ratio?: number
}

export interface AnomalyClassifyResponse {
  filename: string
  detection_time_ms: number
  image_stats: {
    mean: number
    median: number
    std: number
  }
  anomalies: AnomalyClassifyResult[]
  wcs_info?: {
    projection?: string
    pixel_scale_arcsec?: number[]
    image_size_arcmin?: number[]
  }
  parameters_used: {
    spike_sigma: number
    dip_sigma: number
    pattern_break_sigma: number
    window_size: number
  }
  error?: string
}

export interface AnomalyClassifyRequest {
  filename: string
  ra?: number
  dec?: number
  size_arcmin?: number
  spike_sigma?: number
  dip_sigma?: number
  pattern_break_sigma?: number
  window_size?: number
}

// -- v4.18: Deep Learning Models (locally embedded astronomy-domain open-source models) --

export interface GalaxyMorphologyResult {
  filename: string
  morphology_class: string // "spiral" | "elliptical" | "edge-on" | "merger" | "irregular"
  confidence: number
  probabilities: Record<string, number>
  model_name: string
  inference_time_ms: number
  needs_onnx_upgrade: boolean
}

export interface SourceTypeResult {
  filename: string
  source_class: string // "star" | "galaxy" | "quasar"
  confidence: number
  probabilities: Record<string, number>
  model_name: string
  inference_time_ms: number
  features_used: string[]
}

export interface DLAnomalyEnhanceResult {
  filename: string
  original_type: string
  original_confidence: number
  enhanced_confidence: number
  dl_verdict: string // "confirmed" | "downgraded" | "rejected"
  explanation: string
  model_name: string
}

export interface DLClassifyRequest {
  filename: string
}

export interface DLAnomalyEnhanceRequest {
  filename: string
  anomaly_type: string
  rule_confidence: number
}

export interface DLModelStatus {
  onnx_available: boolean
  models: Array<{
    name: string
    type: string
    status: string
    size_mb?: number
    description?: string
    upgrade_available?: boolean
    upgrade_note?: string
  }>
}
