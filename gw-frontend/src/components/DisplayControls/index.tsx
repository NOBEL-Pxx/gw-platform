import { useState, useCallback } from 'react'
import {
  Select,
  Tooltip,
  InputNumber,
  Slider,
  Button,
  Segmented,
  Collapse,
} from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import {
  type DisplayParams,
  type StretchType,
  STRETCH_LABELS,
  DEFAULT_DISPLAY_PARAMS,
  clampDisplayParams,
} from './types'
import { ColorPaletteGrid } from './ColorPaletteGrid'
import { Histogram } from './Histogram'
import { AdvancedSliders } from './AdvancedSliders'

interface DisplayControlsProps {
  value: DisplayParams
  onChange: (next: DisplayParams) => void
  /** Histogram bins (256). Null disables Histogram preview. */
  histogram?: Uint32Array | null
  /** Optional Auto-stretch handler. Parent computes 2.5%/99.5% from canvas. */
  onAutoStretch?: () => void
  /** Compact hides Advanced section by default. */
  compact?: boolean
  /** Show Reset-all button. */
  showReset?: boolean
  /**
   * R6.104-K: show the colormap grid. False for consumers that render
   * server-side (MultiBandDataPanel gets grayscale HiPS JPEGs, so a LUT
   * choice would be a dead control). Defaults to true.
   */
  showColor?: boolean
}

export function DisplayControls({
  value,
  onChange,
  histogram = null,
  onAutoStretch,
  compact = false,
  showReset = true,
  showColor = true,
}: DisplayControlsProps) {
  const set = useCallback(
    <K extends keyof DisplayParams>(k: K, v: DisplayParams[K]) => {
      onChange(clampDisplayParams({ ...value, [k]: v }))
    },
    [value, onChange],
  )

  const cutMin = value.cutMode === 'percent' ? -1 : 0
  const cutMax = value.cutMode === 'percent' ? 100 : 65535
  const cutStep = value.cutMode === 'percent' ? 0.5 : 1

  return (
    <div
      className='flex flex-col gap-2 p-2'
      style={{ background: 'rgba(255,255,255,0.04)', borderRadius: 6 }}
    >
      {/* Row 1: Stretch + Color + Auto + Reset */}
      <div className='flex items-center gap-2 flex-wrap'>
        <span style={{ color: 'rgba(255,255,255,0.6)', fontSize: 12 }}>
          Stretch
        </span>
        <Select<StretchType>
          size='small'
          value={value.stretch}
          onChange={(v) => set('stretch', v)}
          style={{ width: 100 }}
          options={(Object.keys(STRETCH_LABELS) as StretchType[]).map((s) => ({
            label: STRETCH_LABELS[s],
            value: s,
          }))}
        />
        {showColor && (
          <>
            <span style={{ color: 'rgba(255,255,255,0.6)', fontSize: 12 }}>
              Color
            </span>
            <ColorPaletteGrid
              value={value.colormap}
              onChange={(v) => set('colormap', v)}
              compact={compact}
            />
          </>
        )}
        {onAutoStretch && (
          <Tooltip title='Auto-stretch (2.5% / 99.5% percentile clip from current viewport)'>
            <Button size='small' onClick={onAutoStretch} disabled={!histogram}>
              Auto
            </Button>
          </Tooltip>
        )}
        {showReset && (
          <Tooltip title='Reset to defaults'>
            <Button
              size='small'
              icon={<ReloadOutlined />}
              onClick={() => onChange(DEFAULT_DISPLAY_PARAMS)}
            >
              Reset
            </Button>
          </Tooltip>
        )}
      </div>

      {/* Row 2: Cut inputs + Histogram */}
      <div className='flex items-center gap-2 flex-wrap'>
        <Segmented
          size='small'
          value={value.cutMode}
          onChange={(v) => set('cutMode', v as DisplayParams['cutMode'])}
          options={[
            { label: '%', value: 'percent' },
            { label: 'abs', value: 'absolute' },
          ]}
        />
        <InputNumber
          size='small'
          min={cutMin}
          max={cutMax}
          step={cutStep}
          value={value.minCut}
          onChange={(v) => set('minCut', (v ?? cutMin) as number)}
          style={{ width: 72 }}
          placeholder={value.cutMode === 'percent' ? 'Auto' : '0'}
        />
        <div style={{ flex: 1, minWidth: 120, maxWidth: 280 }}>
          <Slider
            range
            min={cutMin}
            max={cutMax}
            step={cutStep}
            value={[value.minCut, value.maxCut]}
            onChange={([lo, hi]) =>
              onChange(
                clampDisplayParams({
                  ...value,
                  minCut: lo as number,
                  maxCut: hi as number,
                }),
              )
            }
            tooltip={{
              formatter: (v) =>
                v === -1
                  ? 'Auto'
                  : `${v}${value.cutMode === 'percent' ? '%' : ''}`,
            }}
          />
        </div>
        <InputNumber
          size='small'
          min={cutMin}
          max={cutMax}
          step={cutStep}
          value={value.maxCut}
          onChange={(v) =>
            set(
              'maxCut',
              (v ?? (value.cutMode === 'percent' ? 99.5 : 65535)) as number,
            )
          }
          style={{ width: 72 }}
          placeholder={value.cutMode === 'percent' ? '99.5' : '65535'}
        />
      </div>
      <Histogram
        bins={histogram}
        minCut={value.minCut}
        maxCut={value.maxCut}
        cutMode={value.cutMode}
        onMinChange={(v) => set('minCut', v)}
        onMaxChange={(v) => set('maxCut', v)}
      />

      {/* Row 3: Advanced (collapsible) */}
      <Collapse
        ghost
        size='small'
        items={[
          {
            key: 'advanced',
            label: compact
              ? ''
              : 'Advanced (γ / brightness / contrast / saturation)',
            // R6.104-K review (M11): this was the only control in the file
            // that bypassed the clampDisplayParams wrapper -- 75, 89, 119,
            // 131, 166, 180 and 181 all route through `set`. The four axis
            // bounds happen to match the clamp today, so this was latent
            // rather than active, but it left the SSOT invariant
            // (R6.104-K-A) non-universal and would break silently the moment
            // either range moved. AdvancedSliders emits a whole params
            // object, so clamp it whole.
            children: (
              <AdvancedSliders
                value={value}
                onChange={(next) => onChange(clampDisplayParams(next))}
              />
            ),
          },
        ]}
        defaultActiveKey={[]} // collapsed by default (dead ternary removed)
      />
    </div>
  )
}

/** Hook for components that want DisplayControls state managed internally. */
export function useDisplayControlsState(initial?: Partial<DisplayParams>) {
  const [value, setValue] = useState<DisplayParams>(() =>
    clampDisplayParams(initial ?? {}),
  )
  return { value, setValue }
}
