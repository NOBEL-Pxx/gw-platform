// R6.104-K review regression (BLOCKER 1).
//
// The four post-stretch coefficients (gamma / brightness / contrast /
// saturation) must be applied by EXACTLY ONE mechanism per render path. The
// Hi-Q path (/pipeline/hips-float) sends them to the server, which bakes them
// into the PNG, so the CSS filter must stay out of it. Applying both squares
// contrast and saturation -- a contrast of 2.0 rendered as ~4.0.
//
// Two writers touch `img.style.filter`: React's style prop (the parent passes
// 'none' for a Hi-Q tile) and this hook's direct DOM write. Both must agree.
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'

import { useContrastDOM, type ContrastDOM } from '../useContrastDOM'
import { DEFAULT_DISPLAY_PARAMS } from '@/components/DisplayControls/types'

afterEach(cleanup)

let api: ContrastDOM
const bigEl = document.createElement('img')

const CONTRAST_2 = { ...DEFAULT_DISPLAY_PARAMS, contrast: 2 }

// `register` mirrors what the parent does: it passes the element for a
// standard tile and null for a Hi-Q one, so the hook holds no reference to a
// server-rendered image.
function Harness({ band, register }: { band: string; register: boolean }) {
  api = useContrastDOM()
  return (
    <img
      alt=''
      data-testid='thumb'
      ref={(el) => {
        api.registerThumb(band, register ? el : null)
      }}
    />
  )
}

describe('useContrastDOM (R6.104-K review)', () => {
  it('writes the CSS filter to a standard-path thumb', () => {
    render(<Harness band='W4' register />)
    api.setDisplay('W4', CONTRAST_2)
    expect(screen.getByTestId('thumb').style.filter).toContain('contrast(2)')
  })

  it('leaves a Hi-Q thumb untouched -- the server already baked the coefficients', () => {
    render(<Harness band='W4' register={false} />)
    api.setDisplay('W4', CONTRAST_2)
    expect(screen.getByTestId('thumb').style.filter).not.toContain('contrast')
  })

  it('does not re-apply the coefficients to a server-rendered big image', () => {
    render(<Harness band='W4' register />)
    api.setActiveBand('W4')
    api.registerBig(bigEl)
    // Standard quality: the CSS filter is the mechanism that owns them.
    api.setDisplay('W4', CONTRAST_2)
    expect(bigEl.style.filter).toContain('contrast(2)')
    // Quality flips to Hi-Q: the server owns them now, so the filter must go.
    api.setActiveServerApplied(true)
    api.setDisplay('W4', CONTRAST_2)
    expect(bigEl.style.filter).not.toContain('contrast')
  })

  it('clears a stale filter when the active band becomes server-rendered', () => {
    render(<Harness band='W4' register />)
    api.setActiveBand('W4')
    api.registerBig(bigEl)
    api.setDisplay('W4', CONTRAST_2)
    expect(bigEl.style.filter).toContain('contrast(2)')
    // setActiveServerApplied alone must take effect, without a setDisplay.
    api.setActiveServerApplied(true)
    expect(bigEl.style.filter).not.toContain('contrast')
  })

  it('gamma is not expressible in a CSS filter (standard-path limitation)', () => {
    // Documents the honest limit: gamma works on the Hi-Q path only. If this
    // ever starts failing, someone invented a CSS gamma -- update the docs.
    render(<Harness band='W4' register />)
    api.setDisplay('W4', { ...DEFAULT_DISPLAY_PARAMS, gamma: 2 })
    expect(screen.getByTestId('thumb').style.filter).not.toContain('gamma')
  })
})
