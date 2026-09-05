import { describe, it, expect } from 'vitest'
import { getStaticResourceUrl, getFitsUrl, getImageUrl } from '../url'

describe('url utility', () => {
  it('returns empty string for null/undefined/empty', () => {
    expect(getStaticResourceUrl(null)).toBe('')
    expect(getStaticResourceUrl(undefined)).toBe('')
    expect(getStaticResourceUrl('')).toBe('')
  })

  it('passes through absolute http URLs unchanged', () => {
    expect(getStaticResourceUrl('http://example.com/foo.png')).toBe(
      'http://example.com/foo.png',
    )
    expect(getStaticResourceUrl('https://cdn.example.com/foo.png')).toBe(
      'https://cdn.example.com/foo.png',
    )
  })

  it('normalizes leading slash for relative paths', () => {
    const out = getStaticResourceUrl('static/img.png')
    expect(out.endsWith('/static/img.png')).toBe(true)
  })

  it('keeps existing leading slash for relative paths (no double slash)', () => {
    const out = getStaticResourceUrl('/static/img.png')
    expect(out.endsWith('/static/img.png')).toBe(true)
    expect(out.includes('//')).toBe(false)
  })

  it('getFitsUrl delegates to getStaticResourceUrl', () => {
    expect(getFitsUrl(null)).toBe('')
    expect(getFitsUrl('/fits/x.fits')).toContain('/fits/x.fits')
  })

  it('getImageUrl delegates to getStaticResourceUrl', () => {
    expect(getImageUrl(null)).toBe('')
    expect(getImageUrl('/img/x.png')).toContain('/img/x.png')
  })
})
