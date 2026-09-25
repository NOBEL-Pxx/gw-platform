import { Slider, InputNumber, Tooltip } from 'antd'
import type { DisplayParams } from './types'

interface AdvancedSlidersProps {
  value: DisplayParams
  onChange: (next: DisplayParams) => void
}

const RANGES = {
  gamma:      { min: 0.3, max: 3.0, step: 0.05, default: 1.0, label: 'γ' },
  brightness: { min: -0.5, max: 0.5, step: 0.05, default: 0.0, label: '☀' },
  contrast:   { min: 0.5, max: 2.0, step: 0.05, default: 1.0, label: '◐' },
  saturation: { min: 0.0, max: 2.0, step: 0.05, default: 1.0, label: '◑' },
} as const

type Axis = keyof typeof RANGES

export function AdvancedSliders({ value, onChange }: AdvancedSlidersProps) {
  return (
    <div className='grid gap-2' style={{ gridTemplateColumns: 'auto 1fr 64px' }}>
      {(Object.keys(RANGES) as Axis[]).map((axis) => {
        const r = RANGES[axis]
        return (
          <div key={axis} style={{ display: 'contents' }}>
            <Tooltip title={`${axis} (default ${r.default})`}>
              <span style={{ color: 'rgba(255,255,255,0.6)', fontSize: 12, alignSelf: 'center' }}>
                {r.label}
              </span>
            </Tooltip>
            <Slider
              min={r.min}
              max={r.max}
              step={r.step}
              value={value[axis]}
              onChange={(v) => onChange({ ...value, [axis]: v as number })}
              tooltip={{ formatter: (v) => `${axis}=${v?.toFixed(2)}` }}
            />
            <InputNumber
              size='small'
              min={r.min}
              max={r.max}
              step={r.step}
              value={value[axis]}
              onChange={(v) => onChange({ ...value, [axis]: (v ?? r.default) as number })}
              style={{ width: 64 }}
            />
          </div>
        )
      })}
    </div>
  )
}
