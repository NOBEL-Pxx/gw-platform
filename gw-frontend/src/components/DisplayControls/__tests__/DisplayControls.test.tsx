// R6.104-K T17: DisplayControls unit tests.
//
// Scope note: these assert DOM structure, the clamp contract, and what each
// control emits on interaction. They do NOT assert rasterized pixels -- the
// histogram/swatch painters need a real 2D canvas backend, which happy-dom
// does not ship (see the getContext stub below).
import { describe, it, expect, vi, beforeAll, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'

import { DisplayControls, useDisplayControlsState } from '../index'
import {
  DEFAULT_DISPLAY_PARAMS,
  FALLBACK_DISPLAY_PARAMS,
  clampDisplayParams,
  type DisplayParams,
} from '../types'

// happy-dom ships no canvas backend, so HTMLCanvasElement.getContext('2d')
// returns null and both painters (ColorPaletteGrid swatches, Histogram bars)
// would throw on `ctx.fillStyle = ...`. Stub a minimal 2D context: these tests
// care about DOM structure and interaction, not rasterized pixels.
beforeAll(() => {
  const stub = () => ({
    clearRect: () => {},
    fillRect: () => {},
    fillText: () => {},
    fillStyle: '',
    font: '',
    textAlign: '',
  })
  HTMLCanvasElement.prototype.getContext = (() => stub()) as never
})

afterEach(cleanup)

function makeProps(
  overrides: Partial<Parameters<typeof DisplayControls>[0]> = {},
) {
  return {
    value: DEFAULT_DISPLAY_PARAMS,
    onChange: vi.fn(),
    histogram: null,
    compact: false,
    showReset: true,
    ...overrides,
  }
}

describe('DisplayControls', () => {
  // --- the clamp contract (pure) -------------------------------------------

  it('percent mode preserves the -1 Auto sentinel and clamps to [-1, 100]', () => {
    const p = clampDisplayParams({
      cutMode: 'percent',
      minCut: -1,
      maxCut: 99.5,
    })
    expect(p.minCut).toBe(-1) // -1 means "no bottom clipping", NOT 0
    expect(p.maxCut).toBe(99.5)
    expect(clampDisplayParams({ cutMode: 'percent', minCut: -50 }).minCut).toBe(
      -1,
    )
    expect(clampDisplayParams({ cutMode: 'percent', maxCut: 500 }).maxCut).toBe(
      100,
    )
  })

  it('percent maxCut floors at 0: -1 is a MIN-only sentinel (review regression)', () => {
    // -1 means "no bottom clipping" and is legal for minCut only. It used to be
    // accepted for maxCut too, and travelled to np.percentile as q=-1 ->
    // ValueError -> HTTP 500 on /pipeline/merge-rgb.
    expect(clampDisplayParams({ cutMode: 'percent', maxCut: -1 }).maxCut).toBe(0)
    expect(clampDisplayParams({ cutMode: 'percent', maxCut: -50 }).maxCut).toBe(0)
    // The sentinel must stay legal where it is meaningful.
    expect(clampDisplayParams({ cutMode: 'percent', minCut: -1 }).minCut).toBe(-1)
  })

  it('reconciles a degenerate absolute cut window (review M3 regression)', () => {
    // hips.py 400s on min_cut_abs >= max_cut_abs and the tile then vanishes with
    // no message. Both sliders clamp to [0, 65535] independently, so the state
    // was reachable; clampDisplayParams now makes it unrepresentable.
    const abs = (minCut: number, maxCut: number) =>
      clampDisplayParams({ cutMode: 'absolute', minCut, maxCut })

    // Crossed pair -> swapped, both requested values preserved.
    expect(abs(5000, 100)).toMatchObject({ minCut: 100, maxCut: 5000 })
    // Zero-width -> widened by one level.
    expect(abs(5000, 5000)).toMatchObject({ minCut: 5000, maxCut: 5001 })
    // Zero-width at the ceiling -> pulled down. Computing maxCut as minCut + 1
    // here would emit 65536, which the backend's le=65535 rejects.
    expect(abs(65535, 65535)).toMatchObject({ minCut: 65534, maxCut: 65535 })
    // Crossed at the extremes -> still inside [0, 65535].
    expect(abs(65535, 0)).toMatchObject({ minCut: 0, maxCut: 65535 })

    // Every arm must satisfy the invariant the backend enforces.
    for (const [lo, hi] of [[5000, 100], [5000, 5000], [65535, 65535], [65535, 0], [1, 2]]) {
      const r = abs(lo, hi)
      expect(r.minCut).toBeLessThan(r.maxCut)
      expect(r.minCut).toBeGreaterThanOrEqual(0)
      expect(r.maxCut).toBeLessThanOrEqual(65535)
    }
  })

  it('leaves the percent window alone, including the -1 Auto sentinel', () => {
    // Percent mode must NOT be reconciled: minCut = -1 is the legal "Auto / no
    // bottom clipping" state, and the backend's 0-49 / 51-100 Query bounds
    // already keep the pair from crossing.
    expect(clampDisplayParams({ cutMode: 'percent', minCut: -1, maxCut: 100 }))
      .toMatchObject({ minCut: -1, maxCut: 100 })
    expect(clampDisplayParams({ cutMode: 'percent', minCut: -1, maxCut: -1 }))
      .toMatchObject({ minCut: -1, maxCut: 0 })
  })

  it('absolute mode clamps cuts to the [0, 65535] pixel range', () => {
    const lo = clampDisplayParams({ cutMode: 'absolute', minCut: -1 })
    const hi = clampDisplayParams({ cutMode: 'absolute', maxCut: 99999 })
    expect(lo.minCut).toBe(0) // the percent sentinel is NOT meaningful here
    expect(hi.maxCut).toBe(65535)
  })

  it('gamma clamps to [0.3, 3.0]', () => {
    expect(clampDisplayParams({ gamma: 5.0 }).gamma).toBe(3.0)
    expect(clampDisplayParams({ gamma: 0.1 }).gamma).toBe(0.3)
    expect(clampDisplayParams({ gamma: 1.7 }).gamma).toBe(1.7)
  })

  it('saturation clamps to [0, 2] and preserves an exact 0', () => {
    // 0 is a meaningful value (full desaturation), not a missing input.
    expect(clampDisplayParams({ saturation: 0.0 }).saturation).toBe(0.0)
    expect(clampDisplayParams({ saturation: -1.0 }).saturation).toBe(0.0)
    expect(clampDisplayParams({ saturation: 5.0 }).saturation).toBe(2.0)
  })

  it('contrast clamps to [0.5, 2.0] and brightness to [-0.5, 0.5]', () => {
    expect(clampDisplayParams({ contrast: 0.1 }).contrast).toBe(0.5)
    expect(clampDisplayParams({ contrast: 9 }).contrast).toBe(2.0)
    expect(clampDisplayParams({ brightness: -2 }).brightness).toBe(-0.5)
    expect(clampDisplayParams({ brightness: 2 }).brightness).toBe(0.5)
  })

  it('clampDisplayParams fills every field from a partial object', () => {
    // The R6.104-K migration path relies on this: the legacy scalar slider
    // seeded only { contrast, brightness } and the rest must come from the
    // defaults, not be left undefined.
    const p = clampDisplayParams({ contrast: 1.5, brightness: 0.2 })
    expect(p).toEqual({
      ...DEFAULT_DISPLAY_PARAMS,
      contrast: 1.5,
      brightness: 0.2,
    })
  })

  // --- rendering + interaction ---------------------------------------------

  it('Reset emits DEFAULT_DISPLAY_PARAMS regardless of how dirty the value is', () => {
    const onChange = vi.fn()
    const dirty: DisplayParams = {
      ...DEFAULT_DISPLAY_PARAMS,
      stretch: 'pow2',
      gamma: 2.5,
      minCut: 5,
      maxCut: 90,
    }
    render(<DisplayControls {...makeProps({ value: dirty, onChange })} />)
    fireEvent.click(screen.getByRole('button', { name: /reset/i }))
    expect(onChange).toHaveBeenCalledWith(DEFAULT_DISPLAY_PARAMS)
  })

  it('Auto is disabled without a histogram and fires onAutoStretch once with one', () => {
    const onAutoStretch = vi.fn()
    const { unmount } = render(
      <DisplayControls {...makeProps({ onAutoStretch, histogram: null })} />,
    )
    const noBins = screen.getByRole('button', {
      name: /auto/i,
    }) as HTMLButtonElement
    expect(noBins.disabled).toBe(true)
    fireEvent.click(noBins)
    expect(onAutoStretch).not.toHaveBeenCalled()
    unmount()

    render(
      <DisplayControls
        {...makeProps({
          onAutoStretch,
          histogram: new Uint32Array(256).fill(1),
        })}
      />,
    )
    const withBins = screen.getByRole('button', { name: /auto/i })
    expect((withBins as HTMLButtonElement).disabled).toBe(false)
    fireEvent.click(withBins)
    expect(onAutoStretch).toHaveBeenCalledTimes(1)
  })

  it('the color palette is shown by default and hidden when showColor={false}', () => {
    const { unmount } = render(<DisplayControls {...makeProps()} />)
    expect(
      screen.getByRole('radiogroup', { name: /color palette/i }),
    ).toBeTruthy()
    unmount()

    // MultiBandDataPanel passes showColor={false}: the HiPS JPEG arrives from
    // the server already grayscale, so a LUT choice there would be dead UI.
    render(<DisplayControls {...makeProps({ showColor: false })} />)
    expect(
      screen.queryByRole('radiogroup', { name: /color palette/i }),
    ).toBeNull()
    expect(screen.queryByText('Color')).toBeNull()
    // The rest of row 1 must survive: hiding the palette hides only the palette.
    expect(screen.getByRole('button', { name: /reset/i })).toBeTruthy()
  })

  it('clicking a palette radio emits that colormap', () => {
    const onChange = vi.fn()
    render(<DisplayControls {...makeProps({ onChange })} />)
    fireEvent.click(screen.getByRole('radio', { name: 'Plasma' }))
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ colormap: 'plasma' }),
    )
  })

  it('the histogram exposes exactly two draggable handles, and only with bins (R6.104-K-B)', () => {
    // Without bins the component is a bare canvas: no handles, so nothing can
    // absorb a pointer event over the image area.
    const { unmount } = render(<DisplayControls {...makeProps()} />)
    expect(screen.queryByLabelText(/min cut handle/i)).toBeNull()
    expect(screen.queryByLabelText(/max cut handle/i)).toBeNull()
    unmount()

    render(
      <DisplayControls
        {...makeProps({
          histogram: new Uint32Array(256).fill(1),
          value: { ...DEFAULT_DISPLAY_PARAMS, minCut: 2, maxCut: 98 },
        })}
      />,
    )
    const handles = screen.getAllByLabelText(/cut handle/i)
    expect(handles).toHaveLength(2)
    expect(
      screen.getByLabelText(/min cut handle/i).getAttribute('aria-valuenow'),
    ).toBe('2')
    expect(
      screen.getByLabelText(/max cut handle/i).getAttribute('aria-valuenow'),
    ).toBe('98')
  })

  it('the %/abs segmented control emits the other cut mode', () => {
    const onChange = vi.fn()
    render(
      <DisplayControls
        {...makeProps({
          onChange,
          value: { ...DEFAULT_DISPLAY_PARAMS, cutMode: 'absolute' },
        })}
      />,
    )
    // Clicking the ALREADY-selected segment is a no-op in antd, so this only
    // exercises the real switch: absolute -> percent.
    fireEvent.click(screen.getByText('%'))
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ cutMode: 'percent' }),
    )
  })

  it('compact hides the Advanced header; non-compact shows it', () => {
    const { unmount } = render(<DisplayControls {...makeProps()} />)
    expect(
      screen.getByText(
        /Advanced \(γ \/ brightness \/ contrast \/ saturation\)/,
      ),
    ).toBeTruthy()
    unmount()

    render(<DisplayControls {...makeProps({ compact: true })} />)
    expect(
      screen.queryByText(
        /Advanced \(γ \/ brightness \/ contrast \/ saturation\)/,
      ),
    ).toBeNull()
  })

  it('showReset={false} removes the Reset button but keeps the rest', () => {
    render(<DisplayControls {...makeProps({ showReset: false })} />)
    expect(screen.queryByRole('button', { name: /reset/i })).toBeNull()
    expect(
      screen.getByRole('radiogroup', { name: /color palette/i }),
    ).toBeTruthy()
  })

  it('useDisplayControlsState seeds from a partial and clamps it', () => {
    // Asserted on the hook value itself rather than through an input: the
    // Advanced sliders live inside a collapsed Collapse, so gamma has no
    // mounted input to query until the panel is opened.
    function Harness() {
      const { value } = useDisplayControlsState({ gamma: 9, minCut: 4 })
      return (
        <div>
          <span data-testid='value'>{JSON.stringify(value)}</span>
          <DisplayControls value={value} onChange={() => {}} histogram={null} />
        </div>
      )
    }
    render(<Harness />)
    const value = JSON.parse(screen.getByTestId('value').textContent || '{}')
    expect(value.gamma).toBe(3) // clamped 9 -> 3.0
    expect(value.minCut).toBe(4) // in range, passes through
    expect(value.maxCut).toBe(DEFAULT_DISPLAY_PARAMS.maxCut) // filled from defaults
  })

  it('FALLBACK_DISPLAY_PARAMS is an explicit 3% / 99.7% window, not the Auto sentinel (R6.104-K-C)', () => {
    // The unknown-survey fallback must be a CONCRETE window. If it carried the
    // sentinel pair (minCut -1, maxCut 100) the cut params would be omitted and
    // an unprofiled survey would silently render with the renderer's default
    // instead of the spec'd asinh + 3%/99.7%.
    expect(FALLBACK_DISPLAY_PARAMS.stretch).toBe('asinh')
    expect(FALLBACK_DISPLAY_PARAMS.minCut).toBe(3)
    expect(FALLBACK_DISPLAY_PARAMS.maxCut).toBe(99.7)
  })
})
