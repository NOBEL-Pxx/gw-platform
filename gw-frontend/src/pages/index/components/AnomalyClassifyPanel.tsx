// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-nocheck — v4.32: DL Anomaly Classifier temporarily disabled
import { useState, useCallback } from 'react'
import { Button, Card, Progress, Spin, Tag, Typography } from 'antd'
import ThunderboltOutlined from '@ant-design/icons/ThunderboltOutlined'
import ReloadOutlined from '@ant-design/icons/ReloadOutlined'
import CheckCircleOutlined from '@ant-design/icons/CheckCircleOutlined'
import CloseCircleOutlined from '@ant-design/icons/CloseCircleOutlined'
import DownloadOutlined from '@ant-design/icons/DownloadOutlined'
// v4.32: DL Anomaly Classifier disabled
// import { classifyAnomaly } from '@/service'
// v4.48: Export
import { exportAnomaliesCsv } from '@/service'
// import type { AnomalyClassifyResponse, AnomalyClassifyResult } from '@/types/api'

const { Text, Paragraph } = Typography

// --- Color scheme matching the four anomaly types ---
const TYPE_COLORS: Record<string, string> = {
  spike: '#FF4D4F',
  dip: '#1890FF',
  pattern_break: '#FAAD14',
  wcs_mismatch: '#722ED1',
}

const TYPE_LABELS: Record<string, string> = {
  spike: 'SPIKE',
  dip: 'DIP',
  pattern_break: 'PATTERN BREAK',
  wcs_mismatch: 'WCS MISMATCH',
}

const TYPE_EMOJI: Record<string, string> = {
  spike: '⚡', // lightning
  dip: '🔵', // blue circle
  pattern_break: '🟡', // yellow circle
  wcs_mismatch: '🟣', // purple circle
}

// --- Props ---
interface AnomalyClassifyPanelProps {
  fitsPath: string
  ra?: number
  dec?: number
}

// --- Sub-component: single anomaly result card ---
function AnomalyCard({ result }: { result: AnomalyClassifyResult }) {
  const color = TYPE_COLORS[result.type] || '#888'
  const label = TYPE_LABELS[result.type] || result.type
  const emoji = TYPE_EMOJI[result.type] || ''
  const pct = Math.round(result.confidence * 100)

  return (
    <Card
      size='small'
      styles={{ body: { padding: '12px 14px' } }}
      style={{
        background: 'rgba(255,255,255,0.03)',
        border: `1px solid ${color}30`,
        borderRadius: 10,
        marginBottom: 8,
      }}
    >
      {/* Header: type badge + confidence */}
      <div className='flex items-center justify-between mb-2'>
        <div className='flex items-center gap-2'>
          <span style={{ fontSize: 16 }}>{emoji}</span>
          <Tag color={color} className='font-semibold !m-0'>
            {label}
          </Tag>
        </div>
        <Text className='text-xs text-white/55'>Confidence {pct}%</Text>
      </div>

      {/* Confidence progress bar */}
      <Progress
        percent={pct}
        strokeColor={color}
        trailColor='rgba(255,255,255,0.06)'
        size='small'
        showInfo={false}
        style={{ marginBottom: 8 }}
      />

      {/* Description */}
      <Paragraph
        className='!text-xs !text-white/70 !mb-2'
        style={{ lineHeight: 1.5 }}
      >
        {result.description}
      </Paragraph>

      {/* Pixel regions table (if any) */}
      {result.pixel_regions.length > 0 && (
        <div
          className='rounded p-2 text-xs'
          style={{
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.06)',
          }}
        >
          <table className='w-full' style={{ borderCollapse: 'collapse' }}>
            <thead>
              <tr className='text-white/45'>
                <th className='text-left font-normal py-1'>Region</th>
                <th className='text-left font-normal py-1'>Peak</th>
                <th className='text-left font-normal py-1'>SNR</th>
              </tr>
            </thead>
            <tbody>
              {result.pixel_regions.slice(0, 5).map((r, i) => (
                <tr
                  key={i}
                  className='text-white/75'
                  style={{ borderTop: '1px solid rgba(255,255,255,0.04)' }}
                >
                  <td className='py-1 font-mono' style={{ fontSize: 11 }}>
                    [{r.x_min}:{r.x_max}, {r.y_min}:{r.y_max}]
                  </td>
                  <td className='py-1'>{r.peak_value.toFixed(1)}</td>
                  <td className='py-1'>{r.snr}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {result.pixel_regions.length > 5 && (
            <Text className='text-white/35' style={{ fontSize: 11 }}>
              +{result.pixel_regions.length - 5} more region(s)
            </Text>
          )}
        </div>
      )}

      {/* WCS issues (for wcs_mismatch type) */}
      {result.wcs_issues.length > 0 && (
        <div className='mt-2'>
          {result.wcs_issues.map((issue, i) => (
            <div
              key={i}
              className='text-xs text-red-400/80 flex items-center gap-1'
            >
              <CloseCircleOutlined style={{ fontSize: 10 }} />
              {issue}
            </div>
          ))}
        </div>
      )}

      {/* FFT extra info */}
      {result.fft_hf_lf_ratio !== undefined && (
        <Text className='text-white/40' style={{ fontSize: 11 }}>
          FFT HF/LF ratio: {result.fft_hf_lf_ratio}
        </Text>
      )}
    </Card>
  )
}

// --- Main component ---
export default function AnomalyClassifyPanel({
  fitsPath,
  ra,
  dec,
}: AnomalyClassifyPanelProps) {
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<AnomalyClassifyResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleClassify = useCallback(async () => {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const res = await classifyAnomaly({
        filename: fitsPath,
        ra,
        dec,
      })
      if (res.error) {
        setError(res.error)
      } else {
        setResult(res)
      }
    } catch (e: unknown) {
      const msg =
        e instanceof Error ? e.message : 'Classification request failed'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }, [fitsPath, ra, dec])

  // Find anomalies with positive confidence
  const positiveAnomalies =
    result?.anomalies?.filter((a) => a.confidence > 0) ?? []
  const hasFindings = positiveAnomalies.length > 0

  return (
    <div className='mt-3'>
      {/* Header row */}
      <div className='flex items-center justify-between mb-3'>
        <div className='flex items-center gap-2'>
          <ThunderboltOutlined style={{ color: '#7C3AED', fontSize: 16 }} />
          <Text className='text-sm font-semibold text-white/85'>
            DL Anomaly Classifier
          </Text>
          <Tag
            color='green'
            className='!text-[10px] !leading-none !px-1.5 !py-0.5 font-semibold'
          >
            LIVE
          </Tag>
        </div>
        <Button
          size='small'
          type='primary'
          loading={loading}
          icon={result ? <ReloadOutlined /> : <ThunderboltOutlined />}
          onClick={handleClassify}
          style={{
            background: loading
              ? undefined
              : 'linear-gradient(135deg, #7C3AED, #A855F7)',
            border: 'none',
            borderRadius: 8,
            fontWeight: 600,
          }}
        >
          {result ? 'Re-classify' : 'Classify Anomalies'}
        </Button>
        {result && (
          <Button
            size='small'
            icon={<DownloadOutlined />}
            onClick={() => exportAnomaliesCsv(fitsPath!)}
            style={{
              background: 'rgba(0,240,255,0.08)',
              border: '1px solid rgba(0,240,255,0.2)',
              color: '#00F0FF',
              borderRadius: 8,
              fontWeight: 600,
              marginLeft: 8,
            }}
          >
            Export CSV
          </Button>
        )}
      </div>

      {/* Loading state */}
      {loading && (
        <div
          className='rounded-xl flex items-center justify-center py-6'
          style={{
            background: 'rgba(124,58,237,0.06)',
            border: '1px solid rgba(124,58,237,0.12)',
          }}
        >
          <Spin size='small' />
          <Text className='ml-3 text-sm text-white/55'>
            Running anomaly detection...
          </Text>
        </div>
      )}

      {/* Error state */}
      {error && !loading && (
        <div
          className='rounded-lg p-3 text-sm text-red-400/85'
          style={{
            background: 'rgba(255,77,79,0.08)',
            border: '1px solid rgba(255,77,79,0.15)',
          }}
        >
          <CloseCircleOutlined className='mr-1' />
          {error}
        </div>
      )}

      {/* Result cards */}
      {result && !loading && !error && (
        <>
          {/* Timing badge */}
          <div className='flex items-center gap-3 mb-3'>
            <Text className='text-xs text-white/45'>
              Completed in {result.detection_time_ms} ms
            </Text>
            <Text className='text-xs text-white/35'>
              Image stats: mean={result.image_stats.mean.toFixed(3)}, median=
              {result.image_stats.median.toFixed(3)}, std=
              {result.image_stats.std.toFixed(3)}
            </Text>
          </div>

          {hasFindings ? (
            <div className='max-h-[320px] overflow-y-auto pr-1'>
              {positiveAnomalies.map((a, i) => (
                <AnomalyCard key={`${a.type}-${i}`} result={a} />
              ))}
            </div>
          ) : (
            <div
              className='rounded-lg p-4 text-center'
              style={{
                background: 'rgba(0,240,255,0.04)',
                border: '1px solid rgba(0,240,255,0.08)',
              }}
            >
              <CheckCircleOutlined
                className='text-lg mb-1'
                style={{ color: '#00E676' }}
              />
              <Text className='text-sm text-white/60 block'>
                No anomalies detected
              </Text>
              <Text className='text-xs text-white/35'>
                All four detectors returned clean results
              </Text>
            </div>
          )}

          {/* WCS info footer */}
          {result.wcs_info && (
            <div
              className='rounded p-2 mt-2 text-xs text-white/40'
              style={{
                background: 'rgba(255,255,255,0.02)',
                border: '1px solid rgba(255,255,255,0.04)',
              }}
            >
              WCS: {result.wcs_info.projection || 'N/A'}
              {result.wcs_info.pixel_scale_arcsec && (
                <>
                  {' '}
                  &middot;{' '}
                  {result.wcs_info.pixel_scale_arcsec
                    .map((v) => `${v}"`)
                    .join(' x ')}{' '}
                  /px
                </>
              )}
              {result.wcs_info.image_size_arcmin && (
                <>
                  {' '}
                  &middot;{' '}
                  {result.wcs_info.image_size_arcmin
                    .map((v) => `${v}'`)
                    .join(' x ')}
                </>
              )}
            </div>
          )}
        </>
      )}

      {/* Idle state (no result yet) */}
      {!result && !loading && !error && (
        <div
          className='rounded-lg p-3 text-center'
          style={{
            background: 'rgba(255,255,255,0.02)',
            border: '1px solid rgba(255,255,255,0.05)',
          }}
        >
          <Text className='text-xs text-white/40'>
            Click &quot;Classify Anomalies&quot; to run all four detectors
            (spike, dip, pattern-break, WCS-mismatch) on this FITS file.
          </Text>
        </div>
      )}
    </div>
  )
}
