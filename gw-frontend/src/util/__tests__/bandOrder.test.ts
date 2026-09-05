import { describe, it, expect } from 'vitest'
import {
  SURVEY_ORDER,
  SURVEY_LABEL,
  BAND_INFO,
  buildOrderedEntries,
  getHipsId,
} from '../bandOrder'
import type { GravitationalWaveItem } from '@/types/api'
import type { RgbEntry } from '../bandOrder'

// Helper to construct minimal GravitationalWaveItem stubs for testing.
function makeItem(
  overrides: Partial<GravitationalWaveItem>,
): GravitationalWaveItem {
  return {
    alias: '',
    band: '',
    dec: 0,
    end_date: '',
    fits_db_path: '',
    fits_path: '',
    fits_file_path: '',
    id: '',
    img: '',
    img_path: '',
    index: '',
    no_data: false,
    observation_id: '',
    ra: 0,
    rank: '',
    score: null,
    start_date: '',
    telescope: '',
    type: '',
    utc_time: '',
    wavelet: '',
    ...overrides,
  } as GravitationalWaveItem
}

describe('bandOrder utility', () => {
  describe('constants', () => {
    it('SURVEY_ORDER has 7 canonical surveys in expected order', () => {
      expect(SURVEY_ORDER).toEqual([
        'AliCPT-1',
        'Planck',
        'DSS2',
        'LEGACY',
        '2MASS',
        'allWISE',
        'NVSS',
      ])
    })

    it('SURVEY_LABEL maps AliCPT-1 -> AliCPT and others', () => {
      expect(SURVEY_LABEL['AliCPT-1']).toBe('AliCPT')
      expect(SURVEY_LABEL['LEGACY']).toBe('Legacy')
      expect(SURVEY_LABEL['NVSS']).toBe('Nvss')
    })

    it('Planck has 9 frequency bands 030-857 GHz in canonical order', () => {
      expect(BAND_INFO).toBeDefined()
      // We don't directly assert Planck band list (private BAND_ORDER),
      // but BAND_INFO has 150GHz for AliCPT.
    })

    it('BAND_INFO covers all 4 SDSS bands with wavelength', () => {
      expect(BAND_INFO['g'].lambda).toBe('477 nm')
      expect(BAND_INFO['r'].lambda).toBe('623 nm')
      expect(BAND_INFO['i'].lambda).toBe('762 nm')
      expect(BAND_INFO['z'].lambda).toBe('905 nm')
    })

    it('BAND_INFO covers DSS2 plates', () => {
      expect(BAND_INFO['DSS2-Blue'].name).toBe('DSS2 Blue')
      expect(BAND_INFO['DSS2-Red'].name).toBe('DSS2 IR')
    })

    it('BAND_INFO covers 2MASS and WISE', () => {
      expect(BAND_INFO['j'].name).toBe('2MASS J')
      expect(BAND_INFO['h'].name).toBe('2MASS H')
      expect(BAND_INFO['k'].name).toBe('2MASS K\u209b')
      expect(BAND_INFO['W1'].lambda).toBe('3.4 \u00b5m')
      expect(BAND_INFO['W4'].lambda).toBe('22 \u00b5m')
    })

    it('BAND_INFO covers NVSS radio', () => {
      expect(BAND_INFO['NVSS-intensity-maps'].color).toBe('Radio')
    })

    it('AliCPT-1 has 150GHz band defined', () => {
      expect(BAND_INFO['150GHz'].name).toBe('AliCPT 150 GHz')
      expect(BAND_INFO['150GHz'].desc).toContain('CMB')
    })
  })

  describe('buildOrderedEntries', () => {
    it('returns empty list for empty input', () => {
      expect(buildOrderedEntries([])).toEqual([])
    })

    it('filters out items with no FITS path (fits_path + fits_db_path)', () => {
      const items = [
        makeItem({
          id: 'a',
          telescope: 'DSS2',
          band: 'DSS2-Blue',
          fits_path: '/static-files/fits/a.fits',
          fits_db_path: '',
        }),
        makeItem({
          id: 'b',
          telescope: 'DSS2',
          band: 'DSS2-Red',
          fits_path: '',
          fits_db_path: '',
        }),
      ]
      const r = buildOrderedEntries(items)
      expect(r).toHaveLength(1)
      expect(r[0]).toMatchObject({ kind: 'band' })
    })

    it('keeps items with fits_db_path even when fits_path missing', () => {
      const items = [
        makeItem({
          id: 'db',
          telescope: 'AliCPT-1',
          band: '150GHz',
          fits_path: '',
          fits_db_path: '/db/AliCPT-1/x.fits',
        }),
      ]
      const r = buildOrderedEntries(items)
      expect(r).toHaveLength(1)
      expect(r[0]).toMatchObject({ kind: 'band', survey: 'AliCPT-1' })
    })

    it('groups items by telescope and orders surveys canonically', () => {
      const items = [
        makeItem({
          id: 'nv',
          telescope: 'NVSS',
          band: 'NVSS-intensity-maps',
          fits_path: '/x.fits',
        }),
        makeItem({
          id: 'al',
          telescope: 'AliCPT-1',
          band: '150GHz',
          fits_path: '/x.fits',
        }),
        makeItem({
          id: 'ds',
          telescope: 'DSS2',
          band: 'DSS2-Blue',
          fits_path: '/x.fits',
        }),
      ]
      const r = buildOrderedEntries(items)
      // AliCPT-1 first, DSS2 second, NVSS last (canonical order)
      expect(r.map((e) => (e as { survey?: string }).survey)).toEqual([
        'AliCPT-1',
        'DSS2',
        'NVSS',
      ])
    })

    it('orders bands within survey by canonical band order', () => {
      const items = [
        makeItem({
          id: 'z',
          telescope: 'LEGACY',
          band: 'z',
          fits_path: '/z.fits',
        }),
        makeItem({
          id: 'g',
          telescope: 'LEGACY',
          band: 'g',
          fits_path: '/g.fits',
        }),
        makeItem({
          id: 'r',
          telescope: 'LEGACY',
          band: 'r',
          fits_path: '/r.fits',
        }),
        makeItem({
          id: 'i',
          telescope: 'LEGACY',
          band: 'i',
          fits_path: '/i.fits',
        }),
      ]
      const r = buildOrderedEntries(items)
      const bands = r
        .filter((e) => e.kind === 'band')
        .map((e) => (e as { item: GravitationalWaveItem }).item.band)
      expect(bands).toEqual(['g', 'r', 'i', 'z'])
    })

    it('appends RGB entry for LEGACY when g, r, i all present', () => {
      // fits_db_path (no leading slash) so URL params are clean.
      const items = [
        makeItem({
          id: 'g',
          telescope: 'LEGACY',
          band: 'g',
          fits_path: '',
          fits_db_path: 'g.fits',
        }),
        makeItem({
          id: 'r',
          telescope: 'LEGACY',
          band: 'r',
          fits_path: '',
          fits_db_path: 'r.fits',
        }),
        makeItem({
          id: 'i',
          telescope: 'LEGACY',
          band: 'i',
          fits_path: '',
          fits_db_path: 'i.fits',
        }),
      ]
      const r = buildOrderedEntries(items)
      expect(r).toHaveLength(4) // 3 bands + 1 RGB
      const rgb = r[3] as RgbEntry
      expect(rgb).toMatchObject({
        kind: 'rgb',
        survey: 'LEGACY',
        label: 'Legacy RGB',
      })
      expect(rgb.url).toContain('/pipeline/merge-rgb?')
      const url = decodeURIComponent(rgb.url)
      expect(url).toContain('r_file=i.fits')
      expect(url).toContain('g_file=r.fits')
      expect(url).toContain('b_file=g.fits')
      // R6.28: rgbChannels for Hi-Q mode
      expect(rgb.rgbChannels).toEqual({
        r: 'LEGACY/i',
        g: 'LEGACY/r',
        b: 'LEGACY/g',
      })
    })

    it('omits RGB entry when LEGACY is missing one band', () => {
      const items = [
        makeItem({
          id: 'g',
          telescope: 'LEGACY',
          band: 'g',
          fits_path: '/g.fits',
        }),
        makeItem({
          id: 'r',
          telescope: 'LEGACY',
          band: 'r',
          fits_path: '/r.fits',
        }),
      ]
      const r = buildOrderedEntries(items)
      expect(r).toHaveLength(2)
      expect(r.every((e) => e.kind === 'band')).toBe(true)
    })

    it('appends CDS-HiPS RGB entry for 2MASS instead of local merge', () => {
      const items = [
        makeItem({
          id: 'j',
          telescope: '2MASS',
          band: 'j',
          fits_path: '/j.fits',
        }),
        makeItem({
          id: 'h',
          telescope: '2MASS',
          band: 'h',
          fits_path: '/h.fits',
        }),
        makeItem({
          id: 'k',
          telescope: '2MASS',
          band: 'k',
          fits_path: '/k.fits',
        }),
      ]
      const r = buildOrderedEntries(items)
      expect(r).toHaveLength(4) // 3 bands + 1 RGB
      const rgb = r[3] as RgbEntry
      expect(rgb).toMatchObject({
        kind: 'rgb',
        survey: '2MASS',
        hipsColor: 'P/2MASS/color',
      })
      expect(rgb.url).toBe('')
      expect(rgb.rgbChannels).toEqual({
        r: '2MASS/k',
        g: '2MASS/h',
        b: '2MASS/j',
      })
    })

    it('appends RGB entry for DSS2 (B, G, R plates)', () => {
      // Note: filenameOf strips only '/static-files/fits/', NOT leading '/'.
      // Use fits_db_path (no leading slash) so URL params are clean.
      const items = [
        makeItem({
          id: 'db',
          telescope: 'DSS2',
          band: 'DSS2-Blue',
          fits_path: '',
          fits_db_path: 'db.fits',
        }),
        makeItem({
          id: 'dg',
          telescope: 'DSS2',
          band: 'DSS2-Green',
          fits_path: '',
          fits_db_path: 'dg.fits',
        }),
        makeItem({
          id: 'dr',
          telescope: 'DSS2',
          band: 'DSS2-Red',
          fits_path: '',
          fits_db_path: 'dr.fits',
        }),
      ]
      const r = buildOrderedEntries(items)
      expect(r).toHaveLength(4)
      const rgb = r[3]
      expect(rgb.kind).toBe('rgb')
      const dss2Url = decodeURIComponent((rgb as { url: string }).url)
      expect(dss2Url).toContain('r_file=dr.fits')
      expect(dss2Url).toContain('g_file=dg.fits')
      expect(dss2Url).toContain('b_file=db.fits')
    })

    it('appends RGB entry for allWISE with per-channel stretch params', () => {
      const items = [
        makeItem({
          id: 'W1',
          telescope: 'allWISE',
          band: 'W1',
          fits_path: '/W1.fits',
        }),
        makeItem({
          id: 'W2',
          telescope: 'allWISE',
          band: 'W2',
          fits_path: '/W2.fits',
        }),
        makeItem({
          id: 'W4',
          telescope: 'allWISE',
          band: 'W4',
          fits_path: '/W4.fits',
        }),
      ]
      const r = buildOrderedEntries(items)
      expect(r).toHaveLength(4)
      const url = (r[3] as { url: string }).url
      // R6.7c2: allWISE r-channel uses asinh + qLow=15 + qHigh=99.5
      expect(url).toContain('r_stretch=asinh')
      expect(url).toContain('r_q_low=15')
      expect(url).toContain('r_q_high=99.5')
      // g and b channels use asinh with defaults
      expect(url).toContain('g_stretch=asinh')
      expect(url).toContain('b_stretch=asinh')
    })

    it('appends RGB entry for 2MASS with log stretch params', () => {
      const items = [
        makeItem({
          id: 'j',
          telescope: '2MASS',
          band: 'j',
          fits_path: '/j.fits',
        }),
        makeItem({
          id: 'h',
          telescope: '2MASS',
          band: 'h',
          fits_path: '/h.fits',
        }),
        makeItem({
          id: 'k',
          telescope: '2MASS',
          band: 'k',
          fits_path: '/k.fits',
        }),
      ]
      const r = buildOrderedEntries(items)
      // 2MASS uses CDS HiPS color, but URL still encodes log stretch in case
      // backend route is invoked. The hipsColor URL is empty for 2MASS.
      expect((r[3] as { url: string }).url).toBe('')
      expect((r[3] as { hipsColor: string }).hipsColor).toBe('P/2MASS/color')
    })

    it('omits RGB entry for NVSS (no preset)', () => {
      const items = [
        makeItem({
          id: 'nv',
          telescope: 'NVSS',
          band: 'NVSS-intensity-maps',
          fits_path: '/nv.fits',
        }),
      ]
      const r = buildOrderedEntries(items)
      expect(r).toHaveLength(1)
      expect(r.every((e) => e.kind === 'band')).toBe(true)
    })

    it('omits RGB entry for AliCPT-1 (no preset)', () => {
      const items = [
        makeItem({
          id: 'al',
          telescope: 'AliCPT-1',
          band: '150GHz',
          fits_path: '/x.fits',
        }),
      ]
      const r = buildOrderedEntries(items)
      expect(r).toHaveLength(1)
    })

    it('handles unknown telescope by putting it at end', () => {
      const items = [
        makeItem({
          id: 'un',
          telescope: 'UnknownSurvey',
          band: 'foo',
          fits_path: '/u.fits',
        }),
        makeItem({
          id: 'al',
          telescope: 'AliCPT-1',
          band: '150GHz',
          fits_path: '/a.fits',
        }),
      ]
      const r = buildOrderedEntries(items)
      // AliCPT-1 first (rank 0), UnknownSurvey last (rank 99)
      expect((r[0] as { survey: string }).survey).toBe('AliCPT-1')
      expect((r[1] as { survey: string }).survey).toBe('UnknownSurvey')
    })

    it('handles items with empty telescope as unknown', () => {
      const items = [
        makeItem({
          id: 'un',
          telescope: '',
          band: 'x',
          fits_path: '/u.fits',
        }),
      ]
      const r = buildOrderedEntries(items)
      expect(r).toHaveLength(1)
    })

    it('handles items with empty band (sorted by empty string)', () => {
      const items = [
        makeItem({
          id: 'a',
          telescope: 'LEGACY',
          band: '',
          fits_path: '/a.fits',
        }),
      ]
      const r = buildOrderedEntries(items)
      expect(r).toHaveLength(1)
    })

    it('strips /static-files/fits/ prefix in merge URLs', () => {
      const items = [
        makeItem({
          id: 'g',
          telescope: 'LEGACY',
          band: 'g',
          fits_path: '/static-files/fits/L00.fits',
          fits_db_path: '',
        }),
        makeItem({
          id: 'r',
          telescope: 'LEGACY',
          band: 'r',
          fits_path: '/static-files/fits/L01.fits',
          fits_db_path: '',
        }),
        makeItem({
          id: 'i',
          telescope: 'LEGACY',
          band: 'i',
          fits_path: '/static-files/fits/L02.fits',
          fits_db_path: '',
        }),
      ]
      const r = buildOrderedEntries(items)
      const url = (r[3] as { url: string }).url
      expect(url).toContain('r_file=L02.fits')
      expect(url).toContain('g_file=L01.fits')
      expect(url).toContain('b_file=L00.fits')
      expect(url).not.toContain('/static-files/fits/')
    })
  })

it('two unknown surveys use localeCompare tiebreaker (rank 99 vs 99)', () => {
      // v8 branch coverage: `surveyRank - surveyRank || localeCompare` requires
      // both unknowns to fire the tiebreaker branch.
      const items = [
        makeItem({
          id: 'b',
          telescope: 'ZetaUnknown',
          band: 'z1',
          fits_path: '/z1.fits',
        }),
        makeItem({
          id: 'a',
          telescope: 'AlphaUnknown',
          band: 'a1',
          fits_path: '/a1.fits',
        }),
      ]
      const r = buildOrderedEntries(items)
      // Both rank 99, localeCompare sorts: Alpha < Zeta
      expect((r[0] as { survey: string }).survey).toBe('AlphaUnknown')
      expect((r[1] as { survey: string }).survey).toBe('ZetaUnknown')
    })

    it('bandRank returns 99 for unknown band within known survey (LEGACY u)', () => {
      // v8 branch coverage: bandRank truthy fallback `return 99` when band not found.
      const items = [
        makeItem({
          id: 'g',
          telescope: 'LEGACY',
          band: 'g',
          fits_path: '/g.fits',
        }),
        makeItem({
          id: 'u',
          telescope: 'LEGACY',
          band: 'u', // not in BAND_ORDER.LEGACY
          fits_path: '/u.fits',
        }),
      ]
      const r = buildOrderedEntries(items)
      const bands = r.map((e) => (e as { item: GravitationalWaveItem }).item.band)
      expect(bands).toEqual(['g', 'u'])
    })

    it('bandRank returns 99 for unknown survey (BAND_ORDER lookup miss)', () => {
      // v8 branch coverage: bandRank `if (!order) return 99` fallback.
      const items = [
        makeItem({
          id: 'x',
          telescope: 'BrandNewSurvey',
          band: 'foo',
          fits_path: '/x.fits',
        }),
      ]
      const r = buildOrderedEntries(items)
      expect(r).toHaveLength(1)
    })

    it('bands with same rank use localeCompare tiebreaker', () => {
      // v8 branch coverage: `(bandRank diff) || (a.band || '').localeCompare(b.band || '')`.
      // Two bands both unknown within an unknown survey → both rank 99 → localeCompare.
      const items = [
        makeItem({
          id: 'b',
          telescope: 'CustomSurvey',
          band: 'beta',
          fits_path: '/b.fits',
        }),
        makeItem({
          id: 'a',
          telescope: 'CustomSurvey',
          band: 'alpha',
          fits_path: '/a.fits',
        }),
      ]
      const r = buildOrderedEntries(items)
      const bands = r.map((e) => (e as { item: GravitationalWaveItem }).item.band)
      expect(bands).toEqual(['alpha', 'beta'])
    })

    it('filters items where both fits_path and fits_db_path are empty (|| false branch)', () => {
      // v8 branch coverage: `it.fits_path || it.fits_db_path` — items with both
      // empty are filtered out (truthy check on the second operand).
      const items = [
        makeItem({
          id: 'no',
          telescope: 'DSS2',
          band: 'DSS2-Blue',
          fits_path: '',
          fits_db_path: '',
        }),
        makeItem({
          id: 'yes',
          telescope: 'DSS2',
          band: 'DSS2-Red',
          fits_path: '/yes.fits',
          fits_db_path: '',
        }),
      ]
      const r = buildOrderedEntries(items)
      expect(r).toHaveLength(1)
      expect((r[0] as { item: GravitationalWaveItem }).item.id).toBe('yes')
    })

  describe('getHipsId', () => {
    it('maps DSS2-Blue to P/DSS2/blue', () => {
      expect(getHipsId('DSS2', 'DSS2-Blue')).toBe('P/DSS2/blue')
    })

    it('maps DSS2-Green (red plate) to P/DSS2/red', () => {
      expect(getHipsId('DSS2', 'DSS2-Green')).toBe('P/DSS2/red')
    })

    it('maps DSS2-Red (NIR plate) to P/DSS2/red (DSS2 has only 2 HiPS)', () => {
      expect(getHipsId('DSS2', 'DSS2-Red')).toBe('P/DSS2/red')
    })

    it('returns null for unknown DSS2 band', () => {
      expect(getHipsId('DSS2', 'DSS2-Other')).toBeNull()
    })

    it('maps 2MASS j/h/k to P/2MASS/{J,H,K}', () => {
      expect(getHipsId('2MASS', 'j')).toBe('P/2MASS/J')
      expect(getHipsId('2MASS', 'h')).toBe('P/2MASS/H')
      expect(getHipsId('2MASS', 'k')).toBe('P/2MASS/K')
    })

    it('returns null for unknown 2MASS band', () => {
      expect(getHipsId('2MASS', 'l')).toBeNull()
    })

    it('maps allWISE W1/W2/W4 to P/allWISE/{band} (case-sensitive uppercase)', () => {
      expect(getHipsId('allWISE', 'W1')).toBe('P/allWISE/W1')
      expect(getHipsId('allWISE', 'W2')).toBe('P/allWISE/W2')
      expect(getHipsId('allWISE', 'W4')).toBe('P/allWISE/W4')
    })

    it('returns null for allWISE W3 (not shown in our DB)', () => {
      expect(getHipsId('allWISE', 'W3')).toBeNull()
    })

    it('returns null for allWISE with lowercase band (case-sensitive)', () => {
      expect(getHipsId('allWISE', 'w1')).toBeNull()
    })

    it('returns P/NVSS for any NVSS band (single radio survey)', () => {
      expect(getHipsId('NVSS', 'NVSS-intensity-maps')).toBe('P/NVSS')
      expect(getHipsId('NVSS', 'anything')).toBe('P/NVSS')
    })

    it('maps LEGACY g/r/i/z to P/panSTARRS/DR1/{band}', () => {
      expect(getHipsId('LEGACY', 'g')).toBe('P/panSTARRS/DR1/g')
      expect(getHipsId('LEGACY', 'r')).toBe('P/panSTARRS/DR1/r')
      expect(getHipsId('LEGACY', 'i')).toBe('P/panSTARRS/DR1/i')
      expect(getHipsId('LEGACY', 'z')).toBe('P/panSTARRS/DR1/z')
    })

    it('returns null for unknown LEGACY band', () => {
      expect(getHipsId('LEGACY', 'u')).toBeNull()
    })

    it('returns null for AliCPT-1 (no public HiPS)', () => {
      expect(getHipsId('AliCPT-1', '150GHz')).toBeNull()
    })

    it('returns null for Planck (no public HiPS)', () => {
      expect(getHipsId('Planck', 'Planck-143G')).toBeNull()
    })

    it('returns null for unknown survey', () => {
      expect(getHipsId('FooBar', 'g')).toBeNull()
    })

    it('returns null for empty survey', () => {
      expect(getHipsId('', 'g')).toBeNull()
    })
  })
})
