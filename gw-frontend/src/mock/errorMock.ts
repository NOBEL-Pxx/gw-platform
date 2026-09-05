/**
 * Mock 数据用于测试错误报告相关接口
 * 在 vite.config.ts 中启用 mock 中间件后使用
 */

import { ErrorReportItem, ErrorDetailItem } from '@/types/api'

export type MockErrorReport = ErrorReportItem

export interface MockErrorReportDetail extends ErrorDetailItem {
  // 保留 id 字段用于 mock 数据内部关联
  id: string
  // 保留 error_id 和 logContent 用于生成顶层 logContent
  error_id: string
  logContent?: string
}

export interface MockErrorReference {
  raw_id: string
  uuid: string
  obs_h5_path: string
  alias: string
  band: string
  dec: number
  end_date: string
  fits_db_path: string
  fits_file_path: string
  id: string
  img: string
  index: string
  mapping_location: { lat: number; lon: number }
  module: string
  ra: number
  start_date: string
  tag: string
  target: string
  telescope: string
  type: string
}

// Mock 错误报告列表
export const mockErrorReports: MockErrorReport[] = [
  {
    id: 'error-001',
    error_id:
      'AliCPT_Abnormal_2025-04-15_14:36:04.861_2025-04-15_15:36:32.201_RA_159.647_Dec_44.796_FOV_3.435_Width_15_Height_15',
    anomaly_type: ['DEAD_PIX', 'NOISE'],
    band: 'X',
    decfield: [43.394393, 46.610227],
    rafield: [158.906, 162.246],
    end_date: '2025-04-15 15:36:32',
    fov: 3.435,
    height: 15,
    start_date: '2025-04-15 14:36:04',
    telescope: 'AliCPT',
    width: 15,
  },
  {
    id: 'error-002',
    error_id:
      'AliCPT_Abnormal_2025-04-15_14:36:04.861_2025-04-15_15:36:32.201_RA_162.246_Dec_36.424_FOV_3.435_Width_15_Height_15',
    anomaly_type: ['HOT_PIX'],
    band: 'Y',
    decfield: [35.0, 38.0],
    rafield: [160.0, 164.0],
    end_date: '2025-04-15 15:36:32',
    fov: 3.435,
    height: 15,
    start_date: '2025-04-15 14:36:04',
    telescope: 'AliCPT',
    width: 15,
  },
  {
    id: 'error-003',
    error_id:
      'AliCPT_Abnormal_2025-04-15_14:36:04.861_2025-04-15_15:36:32.201_RA_180.0_Dec_60.0_FOV_3.435_Width_15_Height_15',
    anomaly_type: ['DEAD_PIX'],
    band: 'Z',
    decfield: [58.0, 62.0],
    rafield: [178.0, 182.0],
    end_date: '2025-04-15 15:36:32',
    fov: 3.435,
    height: 15,
    start_date: '2025-04-15 14:36:04',
    telescope: 'AliCPT',
    width: 15,
  },
  {
    id: 'error-004',
    error_id:
      'AliCPT_Abnormal_2025-04-15_14:36:04.861_2025-04-15_15:36:32.201_RA_200.5_Dec_35.5_FOV_3.435_Width_15_Height_15',
    anomaly_type: ['NOISE', 'HOT_PIX'],
    band: 'W',
    decfield: [33.0, 38.0],
    rafield: [198.0, 203.0],
    end_date: '2025-04-15 15:36:32',
    fov: 3.435,
    height: 15,
    start_date: '2025-04-15 14:36:04',
    telescope: 'AliCPT',
    width: 15,
  },
]

// Mock 错误详情数据（数组格式）
// 每个 errorId 可以有多条详情记录
export const mockErrorDetails: MockErrorReportDetail[] = [
  {
    id: 'J8qm15oBmW_rMGLCB009',
    uuid: 'd8c16ac2-b7d2-4274-bc7a-3a782e362c69',
    error_id:
      'AliCPT_Abnormal_2025-04-15_14:36:04.861_2025-04-15_15:36:32.201_RA_159.647_Dec_44.796_FOV_3.435_Width_15_Height_15',
    anomaly_type: 'DEAD_PIX',
    anomaly_log_path:
      'abnormal_results/logs/AliCPT_Abnormal_2025-04-15_14:36:04.861_2025-04-15_15:36:32.201_RA_159.647_Dec_44.796_FOV_3.435_Width_15_Height_15.txt',
    ra: 159.647,
    dec: 44.796,
    start_date: '2025-04-15 14:36:04.861',
    end_date: '2025-04-15 15:36:32.201',
    fov: 3.435,
    width: 15,
    height: 15,
    fits_path:
      'abnormal_results/fits/AliCPT_Abnormal_2025-04-15_14:36:04.861_2025-04-15_15:36:32.201_RA_159.647_Dec_44.796_FOV_3.435_Width_15_Height_15.fits',
    img_path:
      'abnormal_results/imgs/AliCPT_Abnormal_2025-04-15_14:36:04.861_2025-04-15_15:36:32.201_RA_159.647_Dec_44.796_FOV_3.435_Width_15_Height_15.png',
    logContent:
      '2025-12-01T02:02:45Z | RA=[156.983523,161.645518] deg | Dec=[43.394393,46.610227] deg | Type=DEAD_PIX | UUID=d8c16ac2-b7d2-4274-bc7a-3a782e362c69 | Image=/data/abnormal_results/imgs/AliCPT_Abnormal_2025-04-15_14:36:04.861_2025-04-15_15:36:32.201_RA_159.647_Dec_44.796_FOV_3.435_Width_15_Height_15.png | FITS=/data/abnormal_results/fits/AliCPT_Abnormal_2025-04-15_14:36:04.861_2025-04-15_15:36:32.201_RA_159.647_Dec_44.796_FOV_3.435_Width_15_Height_15.fits',
  },
  {
    id: 'Jsqm15oBmW_rMGLCBk32',
    uuid: '542a2856-41a0-4b4c-b066-61dbb4e77339',
    error_id:
      'AliCPT_Abnormal_2025-04-15_14:36:04.861_2025-04-15_15:36:32.201_RA_159.647_Dec_44.796_FOV_3.435_Width_15_Height_15',
    anomaly_type: 'RFI',
    anomaly_log_path:
      'abnormal_results/logs/AliCPT_Abnormal_2025-04-15_14:36:04.861_2025-04-15_15:36:32.201_RA_159.647_Dec_44.796_FOV_3.435_Width_15_Height_15.txt',
    ra: 159.647,
    dec: 44.796,
    start_date: '2025-04-15 14:36:04.861',
    end_date: '2025-04-15 15:36:32.201',
    fov: 3.435,
    width: 15,
    height: 15,
    fits_path:
      'abnormal_results/fits/AliCPT_Abnormal_2025-04-15_14:36:04.861_2025-04-15_15:36:32.201_RA_159.647_Dec_44.796_FOV_3.435_Width_15_Height_15.fits',
    img_path:
      'abnormal_results/imgs/AliCPT_Abnormal_2025-04-15_14:36:04.861_2025-04-15_15:36:32.201_RA_159.647_Dec_44.796_FOV_3.435_Width_15_Height_15.png',
    logContent:
      '2025-12-01T02:02:45Z | RA=[156.982523,161.646518] deg | Dec=[43.394393,46.610227] deg | Type=RFI | UUID=542a2856-41a0-4b4c-b066-61dbb4e77339 | Image=/data/abnormal_results/imgs/AliCPT_Abnormal_2025-04-15_14:36:04.861_2025-04-15_15:36:32.201_RA_159.647_Dec_44.796_FOV_3.435_Width_15_Height_15.png | FITS=/data/abnormal_results/fits/AliCPT_Abnormal_2025-04-15_14:36:04.861_2025-04-15_15:36:32.201_RA_159.647_Dec_44.796_FOV_3.435_Width_15_Height_15.fits',
  },
  {
    id: 'error-002',
    uuid: 'Jsqm15oBmW_rMGLCBk32',
    error_id:
      'AliCPT_Abnormal_2025-04-15_14:36:04.861_2025-04-15_15:36:32.201_RA_162.246_Dec_36.424_FOV_3.435_Width_15_Height_15',
    anomaly_type: 'HOT_PIX',
    anomaly_log_path:
      'abnormal_results/logs/AliCPT_Abnormal_2025-04-15_14:36:04.861_2025-04-15_15:36:32.201_RA_162.246_Dec_36.424_FOV_3.435_Width_15_Height_15.txt',
    ra: 162.246,
    dec: 36.424,
    start_date: '2025-04-15 14:36:04.861',
    end_date: '2025-04-15 15:36:32.201',
    fov: 3.435,
    width: 15,
    height: 15,
    fits_path:
      'abnormal_results/fits/AliCPT_Abnormal_2025-04-15_14:36:04.861_2025-04-15_15:36:32.201_RA_162.246_Dec_36.424_FOV_3.435_Width_15_Height_15.fits',
    img_path:
      'abnormal_results/imgs/AliCPT_Abnormal_2025-04-15_14:36:04.861_2025-04-15_15:36:32.201_RA_162.246_Dec_36.424_FOV_3.435_Width_15_Height_15.png',
    logContent:
      '2025-12-01T02:02:45Z | RA=[160.0,164.0] deg | Dec=[35.0,38.0] deg | Type=HOT_PIX | UUID=Jsqm15oBmW_rMGLCBk32 | Image=/data/abnormal_results/imgs/AliCPT_Abnormal_2025-04-15_14:36:04.861_2025-04-15_15:36:32.201_RA_162.246_Dec_36.424_FOV_3.435_Width_15_Height_15.png | FITS=/data/abnormal_results/fits/AliCPT_Abnormal_2025-04-15_14:36:04.861_2025-04-15_15:36:32.201_RA_162.246_Dec_36.424_FOV_3.435_Width_15_Height_15.fits',
  },
]

// Mock 错误引用数据
export const mockErrorReferences: Record<
  string,
  Record<string, MockErrorReference>
> = {
  'error-001': {
    'uuid-001-1': {
      raw_id: 'raw-001-1',
      uuid: 'uuid-001-1',
      obs_h5_path: '/path/to/obs-001-1.h5',
      alias: 'GW001-1',
      band: 'X',
      dec: 30.2,
      end_date: '2024-01-01',
      fits_db_path: 'fits/001-1.fits',
      fits_file_path: '/path/to/001-1.fits',
      id: 'ref-001-1',
      img: 'img/001-1.jpg',
      index: 'idx-001-1',
      mapping_location: { lat: 30.2, lon: 120.5 },
      module: 'module-1',
      ra: 120.5,
      start_date: '2023-12-01',
      tag: 'tag-001-1',
      target: 'target-001-1',
      telescope: 'Telescope-1',
      type: 'type-1',
    },
    'uuid-001-2': {
      raw_id: 'raw-001-2',
      uuid: 'uuid-001-2',
      obs_h5_path: '/path/to/obs-001-2.h5',
      alias: 'GW001-2',
      band: 'Y',
      dec: 30.3,
      end_date: '2024-01-02',
      fits_db_path: 'fits/001-2.fits',
      fits_file_path: '/path/to/001-2.fits',
      id: 'ref-001-2',
      img: 'img/001-2.jpg',
      index: 'idx-001-2',
      mapping_location: { lat: 30.3, lon: 120.6 },
      module: 'module-1',
      ra: 120.6,
      start_date: '2023-12-02',
      tag: 'tag-001-2',
      target: 'target-001-2',
      telescope: 'Telescope-1',
      type: 'type-1',
    },
  },
}

/**
 * 生成符合后端格式的响应
 * 添加 _mock 标识用于区分 mock 响应和真实后端响应
 */
export function createMockResponse<T>(data: T) {
  return {
    error: {
      code: '0',
      msg: 'success',
    },
    data,
    _mock: true, // 标识这是 mock 响应
  }
}
