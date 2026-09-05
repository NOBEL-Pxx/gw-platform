import { memo, useState, useMemo, useCallback } from 'react'
import { Button, Select, Tooltip, Spin, Segmented, message } from 'antd'
import MergeCellsOutlined from '@ant-design/icons/MergeCellsOutlined'
import DownloadOutlined from '@ant-design/icons/DownloadOutlined'
import type { GravitationalWaveItem } from '@/types/api'

type StretchType = 'percentile' | 'asinh' | 'log'

const STRETCH_OPTIONS: { label: string; value: StretchType }[] = [
  { label: 'Percentile', value: 'percentile' },
  { label: 'Asinh', value: 'asinh' },
  { label: 'Log', value: 'log' },
]

interface MergeRGBPanelProps {
  bands: GravitationalWaveItem[]
  onMergeComplete?: (url: string) => void
}

function MergeRGBPanel({ bands, onMergeComplete }: MergeRGBPanelProps) {
  const [rBand, setRBand] = useState<string | undefined>(undefined)
  const [gBand, setGBand] = useState<string | undefined>(undefined)
  const [bBand, setBBand] = useState<string | undefined>(undefined)
  const [stretch, setStretch] = useState<StretchType>('percentile')
  const [merging, setMerging] = useState(false)
  const [mergedUrl, setMergedUrl] = useState<string | null>(null)
  const [mergeError, setMergeError] = useState<string | null>(null)

  // Group bands by telescope for easier selection
  const bandOptions = useMemo(() => {
    return bands.map((b) => {
      const label = `${b.telescope || '?'} — ${b.band || '?'}`
      // Use fits_path as the value for the merge API
      const fp = b.fits_path || ''
      const filename = fp.replace('/static-files/fits/', '')
      return {
        label,
        value: filename,
        telescope: b.telescope,
        band: b.band,
      }
    })
  }, [bands])

  // Pre-select common combinations
  const presets = useMemo(() => {
    // Find DSS2 bands for the most common RGB combo
    const dss2 = bandOptions.filter((b) => b.telescope === 'DSS2')
    const legacy = bandOptions.filter((b) => b.telescope === 'LEGACY')
    const twomass = bandOptions.filter((b) => b.telescope === '2MASS')
    return { dss2, legacy, twomass }
  }, [bandOptions])

  const applyPreset = useCallback(
    (preset: 'DSS2-RGB' | 'LEGACY-rgi' | '2MASS-jhk') => {
      setMergeError(null)
      setMergedUrl(null)
      if (preset === 'DSS2-RGB') {
        setRBand(presets.dss2.find((b) => b.band?.includes('Red'))?.value)
        setGBand(presets.dss2.find((b) => b.band?.includes('Green'))?.value)
        setBBand(presets.dss2.find((b) => b.band?.includes('Blue'))?.value)
      } else if (preset === 'LEGACY-rgi') {
        setRBand(presets.legacy.find((b) => b.band === 'i')?.value)
        setGBand(presets.legacy.find((b) => b.band === 'r')?.value)
        setBBand(presets.legacy.find((b) => b.band === 'g')?.value)
      } else if (preset === '2MASS-jhk') {
        setRBand(presets.twomass.find((b) => b.band === 'k')?.value)
        setGBand(presets.twomass.find((b) => b.band === 'h')?.value)
        setBBand(presets.twomass.find((b) => b.band === 'j')?.value)
      }
    },
    [presets],
  )

  const handleMerge = useCallback(async () => {
    if (!rBand || !gBand || !bBand) {
      message.warning('Select R, G, and B bands to merge')
      return
    }
    setMerging(true)
    setMergeError(null)
    try {
      const params = new URLSearchParams({
        r_file: rBand,
        g_file: gBand,
        b_file: bBand,
        size: '512',
        stretch,
      })
      const url = `/pipeline/merge-rgb?${params.toString()}`
      // Verify the URL returns an image
      const resp = await fetch(url)
      if (!resp.ok) {
        const errText = await resp.text()
        throw new Error(errText || `HTTP ${resp.status}`)
      }
      setMergedUrl(url)
      onMergeComplete?.(url)
      message.success('RGB merge complete')
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Merge failed'
      setMergeError(msg)
      message.error(`Merge failed: ${msg}`)
    } finally {
      setMerging(false)
    }
  }, [rBand, gBand, bBand, stretch, onMergeComplete])

  const canMerge = rBand && gBand && bBand && !merging

  if (bands.length === 0) {
    return (
      <div className='p-4 text-white/40 text-xs text-center'>
        Select an error report to enable RGB merge
      </div>
    )
  }

  return (
    <div
      className='p-3 border-t border-white/6'
      style={{ background: 'rgba(255,255,255,0.02)' }}
    >
      <div className='flex items-center gap-2 mb-2'>
        <MergeCellsOutlined className='text-cyan-400' />
        <span className='text-white/80 text-xs font-semibold'>
          RGB Channel Merge
        </span>
        <span className='text-white/30 text-xs ml-auto'>→ Aladin/Firefly</span>
      </div>

      {/* Quick presets */}
      <div className='flex gap-1 mb-2 flex-wrap'>
        {presets.dss2.length >= 3 && (
          <Tooltip title='DSS2 Red + Green + Blue'>
            <Button
              size='small'
              type='default'
              className='text-xs'
              onClick={() => applyPreset('DSS2-RGB')}
            >
              DSS2 RGB
            </Button>
          </Tooltip>
        )}
        {presets.legacy.length >= 3 && (
          <Tooltip title='LEGACY i + r + g'>
            <Button
              size='small'
              type='default'
              className='text-xs'
              onClick={() => applyPreset('LEGACY-rgi')}
            >
              LEGACY gri
            </Button>
          </Tooltip>
        )}
        {presets.twomass.length >= 2 && (
          <Tooltip title='2MASS J + H + K'>
            <Button
              size='small'
              type='default'
              className='text-xs'
              onClick={() => applyPreset('2MASS-jhk')}
            >
              2MASS JHK
            </Button>
          </Tooltip>
        )}
      </div>

      {/* Band selectors */}
      <div className='flex flex-col gap-1.5 mb-2'>
        {(['R', 'G', 'B'] as const).map((ch, i) => (
          <div key={ch} className='flex items-center gap-1.5'>
            <span
              className='text-xs font-bold w-5 h-5 flex items-center justify-center rounded'
              style={{
                background:
                  ch === 'R'
                    ? 'rgba(255,0,110,0.3)'
                    : ch === 'G'
                      ? 'rgba(0,230,118,0.3)'
                      : 'rgba(0,144,255,0.3)',
                color:
                  ch === 'R' ? '#FF006E' : ch === 'G' ? '#00E676' : '#0090FF',
              }}
            >
              {ch}
            </span>
            <Select
              size='small'
              className='flex-1'
              placeholder={`Select ${ch} channel...`}
              value={i === 0 ? rBand : i === 1 ? gBand : bBand}
              onChange={(v) => {
                if (i === 0) {
                  setRBand(v)
                  setMergedUrl(null)
                  setMergeError(null)
                } else if (i === 1) {
                  setGBand(v)
                  setMergedUrl(null)
                  setMergeError(null)
                } else {
                  setBBand(v)
                  setMergedUrl(null)
                  setMergeError(null)
                }
              }}
              options={bandOptions}
              showSearch
              filterOption={(input, option) =>
                (option?.label ?? '')
                  .toLowerCase()
                  .includes(input.toLowerCase())
              }
              popupMatchSelectWidth={false}
            />
          </div>
        ))}
      </div>

      {/* Stretch method */}
      <div className='flex items-center gap-2 mb-2'>
        <span className='text-white/50 text-xs'>Stretch:</span>
        <Segmented
          size='small'
          options={STRETCH_OPTIONS}
          value={stretch}
          onChange={(v) => setStretch(v as StretchType)}
        />
      </div>

      {/* Merge + Download buttons */}
      <div className='flex gap-2'>
        <Button
          size='small'
          type='primary'
          icon={<MergeCellsOutlined />}
          loading={merging}
          disabled={!canMerge}
          onClick={handleMerge}
          className='flex-1'
          style={{
            background: canMerge
              ? 'linear-gradient(135deg, #7C3AED, #FF006E, #00F0FF)'
              : undefined,
            border: 'none',
          }}
        >
          Merge RGB
        </Button>
        {mergedUrl && (
          <Tooltip title='Export as PDF (vector, publication-ready)'>
            <Button
              size='small'
              icon={<DownloadOutlined />}
              onClick={() => window.open(mergedUrl + '&fmt=pdf', '_blank')}
            />
          </Tooltip>
        )}
      </div>

      {/* Preview thumbnail */}
      {mergedUrl && (
        <div className='mt-2 text-center'>
          <img
            src={mergedUrl}
            alt='RGB Merged'
            className='rounded-lg border border-white/10 mx-auto'
            style={{ maxWidth: '100%', maxHeight: 200, objectFit: 'contain' }}
          />
        </div>
      )}

      {/* Error display */}
      {mergeError && (
        <div className='mt-1 text-red-400 text-xs text-center'>
          {mergeError}
        </div>
      )}

      {/* Loading spinner */}
      {merging && (
        <div className='mt-2 text-center'>
          <Spin size='small' />
          <span className='text-white/40 text-xs ml-2'>
            Merging channels...
          </span>
        </div>
      )}
    </div>
  )
}

export default memo(MergeRGBPanel)
