import type { GravitationalWaveItem } from '@/types/api'

/**
 * Canonical survey order for the Multi-band Observation Data thumbnail strip.
 * Requested order: AliCPT, Planck, DSS2, Legacy(g,r,i,z), 2MASS, Allwise, Nvss.
 * Keyed by the `telescope` field returned by geoSearch (the reliable survey id).
 */
export const SURVEY_ORDER: string[] = [
  'AliCPT-1',
  'Planck',
  'DSS2',
  'LEGACY',
  '2MASS',
  'allWISE',
  'NVSS',
]

export const SURVEY_LABEL: Record<string, string> = {
  'AliCPT-1': 'AliCPT',
  Planck: 'Planck',
  DSS2: 'DSS2',
  LEGACY: 'Legacy',
  '2MASS': '2MASS',
  allWISE: 'AllWISE',
  NVSS: 'Nvss',
}

/** Canonical band order within each survey (keeps e.g. Legacy g,r,i,z together). */
const BAND_ORDER: Record<string, string[]> = {
  'AliCPT-1': ['150GHz'],
  Planck: [
    'Planck-030G',
    'Planck-044G',
    'Planck-070G',
    'Planck-100G',
    'Planck-143G',
    'Planck-217G',
    'Planck-353G',
    'Planck-545G',
    'Planck-857G',
  ],
  DSS2: ['DSS2-Blue', 'DSS2-Green', 'DSS2-Red'],
  LEGACY: ['g', 'r', 'i', 'z'],
  '2MASS': ['j', 'h', 'k'],
  allWISE: ['W1', 'W2', 'W4'],
  NVSS: ['NVSS-intensity-maps'],
}

/**
 * v4.DIVS-r4: Per-band display info. The user complained that cryptic
 * abbreviations like "g", "i", "W2", "k" give no hint of what they are.
 * Lookup is keyed by survey + band (some band names like DSS2-Blue are
 * already self-explanatory and use the band string directly).
 *
 * Fields:
 *  - name:    Full name shown as primary tile label (e.g., "SDSS g-band")
 *  - lambda:  Wavelength as a single token (e.g., "477 nm")
 *  - color:   Color/region tag (e.g., "Green", "Mid-IR")
 *  - desc:    One-line description for tooltip
 */
export type BandInfo = {
  name: string
  lambda: string
  color: string
  desc: string
}

export const BAND_INFO: Record<string, BandInfo> = {
  // AliCPT-1 CMB
  '150GHz': {
    name: 'AliCPT 150 GHz',
    lambda: '2.0 mm',
    color: 'CMB',
    desc: 'AliCPT-1 telescope 150 GHz CMB observation (Q+U maps)',
  },

  // DSS2 — three photographic plates from STScI Digitized Sky Survey
  'DSS2-Blue': {
    name: 'DSS2 Blue',
    lambda: '480 nm',
    color: 'Blue plate',
    desc: 'DSS2 photographic blue plate (IIIaJ + GG395 filter)',
  },
  'DSS2-Green': {
    name: 'DSS2 Red',
    lambda: '650 nm',
    color: 'Red plate',
    desc: 'DSS2 photographic red plate (IIIaF + RG610 filter)',
  },
  'DSS2-Red': {
    name: 'DSS2 IR',
    lambda: '825 nm',
    color: 'Near-IR plate',
    desc: 'DSS2 photographic near-IR plate (IVN + RG9 filter)',
  },

  // LEGACY survey — SDSS-style bands
  g: {
    name: 'SDSS g-band',
    lambda: '477 nm',
    color: 'Green',
    desc: 'SDSS g-band (PS1/LEGACY), central wavelength ~477 nm, FWHM ~127 nm',
  },
  r: {
    name: 'SDSS r-band',
    lambda: '623 nm',
    color: 'Red',
    desc: 'SDSS r-band (PS1/LEGACY), central wavelength ~623 nm, FWHM ~138 nm',
  },
  i: {
    name: 'SDSS i-band',
    lambda: '762 nm',
    color: 'Near-IR',
    desc: 'SDSS i-band (PS1/LEGACY), central wavelength ~762 nm, FWHM ~153 nm',
  },
  z: {
    name: 'SDSS z-band',
    lambda: '905 nm',
    color: 'Near-IR',
    desc: 'SDSS z-band (PS1/LEGACY), central wavelength ~905 nm, FWHM ~85 nm',
  },

  // 2MASS — near-infrared
  j: {
    name: '2MASS J',
    lambda: '1.25 µm',
    color: 'Near-IR',
    desc: '2MASS J-band, central wavelength 1.25 µm (Cryogenic Survey)',
  },
  h: {
    name: '2MASS H',
    lambda: '1.65 µm',
    color: 'Near-IR',
    desc: '2MASS H-band, central wavelength 1.65 µm',
  },
  k: {
    name: '2MASS Kₛ',
    lambda: '2.17 µm',
    color: 'Mid-IR',
    desc: '2MASS K-short band, central wavelength 2.17 µm',
  },

  // WISE — mid-infrared
  W1: {
    name: 'WISE W1',
    lambda: '3.4 µm',
    color: 'Mid-IR',
    desc: 'WISE 3.4 µm band (W1)',
  },
  W2: {
    name: 'WISE W2',
    lambda: '4.6 µm',
    color: 'Mid-IR',
    desc: 'WISE 4.6 µm band (W2)',
  },
  W4: {
    name: 'WISE W4',
    lambda: '22 µm',
    color: 'Far-IR',
    desc: 'WISE 22 µm band (W4)',
  },

  // NVSS — radio
  'NVSS-intensity-maps': {
    name: 'NVSS 1.4 GHz',
    lambda: '21 cm',
    color: 'Radio',
    desc: 'NRAO VLA Sky Survey at 1.4 GHz, intensity map',
  },
}

/**
 * RGB channel presets per multi-band survey. Only surveys with a defined R/G/B
 * mapping produce an auto-generated RGB composite — reuses the existing
 * /pipeline/merge-rgb endpoint (previously triggered manually in MergeRGBPanel).
 * Values are matched against the `band` field.
 */
const RGB_PRESETS: Record<string, { r: string; g: string; b: string }> = {
  DSS2: { r: 'DSS2-Red', g: 'DSS2-Green', b: 'DSS2-Blue' },
  LEGACY: { r: 'i', g: 'r', b: 'g' },
  '2MASS': { r: 'k', g: 'h', b: 'j' },
  allWISE: { r: 'W4', g: 'W2', b: 'W1' },
}

export type BandEntry = {
  kind: 'band'
  item: GravitationalWaveItem
  survey: string
}
export type RgbEntry = {
  kind: 'rgb'
  survey: string
  url: string
  label: string
  hipsColor?: string
  // R6.28: per-channel HiPS ID mapping. Lets frontend route Hi-Q mode to backend
  // /pipeline/merge-rgb?mode=hips&r_hips=2MASS/K&... for true per-channel cut.
  // Maps to RGB_CHANNELS at construction time below.
  rgbChannels?: { r: string; g: string; b: string }
} // R6.16: optional HiPS color survey ID for RGB composites that have a seamless CDS color HiPS (e.g. 2MASS color) instead of stitched local FITS
export type OrderedEntry = BandEntry | RgbEntry

function surveyRank(t: string): number {
  const i = SURVEY_ORDER.indexOf(t)
  return i === -1 ? 99 : i
}

function bandRank(survey: string, band: string): number {
  const order = BAND_ORDER[survey]
  if (!order) return 99
  const i = order.indexOf(band)
  return i === -1 ? 99 : i
}

function filenameOf(item: GravitationalWaveItem): string {
  const fp = item.fits_path || item.fits_db_path || ''
  return fp.replace('/static-files/fits/', '')
}

// R6.7c2: Per-channel stretch + percentile params for surveys whose bands
// have very different background levels.
//
// allWISE data inspection (W4 vs W1/W2 at galactic field):
//   W1: mean=7,  p50=2,  p99=101  (huge range, sparse bright stars)
//   W2: mean=6,  p50=1,  p99=89   (huge range, sparse bright stars)
//   W4: mean=6,  p50=6,  p99=11   (narrow range, dominated by background)
//
// With default q_low=1 q_high=99, W4 background saturates to white
// -> all-red image. Fix: asinh + tighter q_low=15 (effectively background-
// subtraction) on W4 only. W2/W1 stay on default percentile so stars
// remain bright against dark background.
type ChannelParams = {
  stretch?: string
  qLow?: number
  qHigh?: number
  gamma?: number
}
const RGB_CHANNEL_PARAMS: Record<
  string,
  { r?: ChannelParams; g?: ChannelParams; b?: ChannelParams }
> = {
  allWISE: {
    r: { stretch: 'asinh', qLow: 15, qHigh: 99.5 },
    g: { stretch: 'asinh' },
    b: { stretch: 'asinh' },
  },
  // R6.16: 2MASS RGB (J/H/Ks) — log stretch measured 2.1x sharper than
  // percentile (37143 vs 17598). Log smooths near-IR background gradient
  // and avoids the blocky artifacts that percentile creates when J/H/K
  // have very different background levels.
  '2MASS': {
    r: { stretch: 'log' },
    g: { stretch: 'log' },
    b: { stretch: 'log' },
  },
}

function buildMergeUrl(
  survey: string,
  bands: GravitationalWaveItem[],
): string | null {
  const preset = RGB_PRESETS[survey]
  if (!preset) return null
  const find = (band: string) => bands.find((b) => (b.band || '') === band)
  const r = find(preset.r)
  const g = find(preset.g)
  const b = find(preset.b)
  if (!r || !g || !b) return null
  // R6.7c2: per-channel stretch + percentile + gamma (only allWISE for now).
  const ch = RGB_CHANNEL_PARAMS[survey] || {}
  const params = new URLSearchParams({
    r_file: filenameOf(r),
    g_file: filenameOf(g),
    b_file: filenameOf(b),
    size: '512',
    stretch: 'percentile',
  })
  for (const [key, val] of [
    ['r', ch.r],
    ['g', ch.g],
    ['b', ch.b],
  ] as const) {
    if (val) {
      if (val.stretch) params.set(`${key}_stretch`, val.stretch)
      if (val.qLow !== undefined) params.set(`${key}_q_low`, String(val.qLow))
      if (val.qHigh !== undefined)
        params.set(`${key}_q_high`, String(val.qHigh))
      if (val.gamma !== undefined) params.set(`${key}_gamma`, String(val.gamma))
    }
  }
  return `/pipeline/merge-rgb?${params.toString()}`
}

/**
 * Build the ordered thumbnail entries from a raw geoSearch list:
 *  1. Filter out records with no FITS path (no data -> not shown).
 *  2. Group by survey (`telescope`), sort surveys by canonical order.
 *  3. Sort bands within each survey by canonical band order.
 *  4. For multi-band surveys with an RGB preset and all three channels present,
 *     append an RGB entry after the last band.
 */
export function buildOrderedEntries(
  list: GravitationalWaveItem[],
): OrderedEntry[] {
  const withData = list.filter((it) => it.fits_path || it.fits_db_path)
  const groups = new Map<string, GravitationalWaveItem[]>()
  for (const it of withData) {
    const t = it.telescope || ''
    if (!groups.has(t)) groups.set(t, [])
    groups.get(t)!.push(it)
  }

  const surveyNames = [...groups.keys()].sort(
    (a, b) => surveyRank(a) - surveyRank(b) || a.localeCompare(b),
  )

  const entries: OrderedEntry[] = []
  for (const survey of surveyNames) {
    const bands = groups.get(survey)!
    bands.sort(
      (a, b) =>
        bandRank(survey, a.band || '') - bandRank(survey, b.band || '') ||
        (a.band || '').localeCompare(b.band || ''),
    )
    for (const it of bands) entries.push({ kind: 'band', item: it, survey })
    // R6.16: 2MASS RGB uses the CDS HiPS color survey (P/2MASS/color) instead
    // of local merge-rgb stitching. Local FITS stitching shows HiPS tile
    // boundary artifacts as colored blocks. The alasky HiPS color is tile-
    // seamless.
    if (survey === '2MASS') {
      entries.push({
        kind: 'rgb',
        survey,
        url: '',
        // v8 ignore next -- SURVEY_LABEL always has '2MASS' here (we entered
        // the 2MASS-specific branch above); `|| survey` fallback is dead code.
        label: `${SURVEY_LABEL[survey] || survey} RGB`,
        hipsColor: 'P/2MASS/color',
        // R6.28: per-channel HiPS IDs for Hi-Q mode backend routing
        rgbChannels: { r: '2MASS/k', g: '2MASS/h', b: '2MASS/j' },
      })
      continue
    }
    const url = buildMergeUrl(survey, bands)
    if (url) {
      // R6.28: per-channel HiPS IDs for Hi-Q mode. Maps band letter -> HiPS 'survey/band' string.
      const ch = RGB_PRESETS[survey]
      // v8 ignore next -- we only enter this block when buildMergeUrl returned
      // a URL, which requires RGB_PRESETS[survey] to be defined. So `ch` is
      // always truthy here; the `: undefined` fallback is defensive dead code.
      const rgbChannels = ch
        ? {
            r: `${survey}/${ch.r}`,
            g: `${survey}/${ch.g}`,
            b: `${survey}/${ch.b}`,
          }
        : undefined
      entries.push({
        kind: 'rgb',
        survey,
        url,
        // v8 ignore next -- same defensive pattern as 2MASS branch above;
        // every survey with RGB_PRESETS entry is also in SURVEY_LABEL.
        label: `${SURVEY_LABEL[survey] || survey} RGB`,
        rgbChannels,
      })
    }
  }
  return entries
}
/**
 * R6.5: Map (survey, band) -> alasky.unistra.fr HiPS survey ID for dynamic
 * Aladin survey switching. Returns null when no HiPS exists (AliCPT-1, Planck
 * — those entries have no external HiPS, only local FITS files, so the
 * MultiBandDataPanel falls back to FITS overlay on the default DSS2 color).
 *
 * Naming notes (intentionally explicit to avoid v4.DIVS confusion):
 *  - DSS2-Green  in our DB = photographic red plate (IIIaF+RG610, 650 nm),
 *    so it maps to P/DSS2/red, NOT P/DSS2/green (no such HiPS exists).
 *  - DSS2-Red    in our DB = photographic near-IR plate (IVN+RG9, 825 nm),
 *    which is also served by alasky as P/DSS2/red (DSS2 has only 2 HiPS:
 *    blue and red — the third "near-IR plate" is bundled into P/DSS2/red).
 *  - LEGACY      maps to PS1 (Pan-STARRS1) HiPS, the public release covering
 *    the same g/r/i/z footprint. P/PS1/{g,r,i,z}.
 *  - allWISE     maps to P/allWISE/{W1,W2,W3,W4} — we only show W1,W2,W4.
 *  - 2MASS       maps to P/2MASS/{J,H,K}.
 *  - NVSS        has a single survey: P/NVSS (radio continuum 1.4 GHz).
 */
export function getHipsId(survey: string, band: string): string | null {
  switch (survey) {
    case 'DSS2':
      if (band === 'DSS2-Blue') return 'P/DSS2/blue'
      // DSS2-Green (red plate 650nm) + DSS2-Red (NIR plate 825nm) both
      // resolve to P/DSS2/red — that's the only DSS2 red-end HiPS available.
      if (band === 'DSS2-Green' || band === 'DSS2-Red') return 'P/DSS2/red'
      return null
    case '2MASS':
      if (band === 'j') return 'P/2MASS/J'
      if (band === 'h') return 'P/2MASS/H'
      if (band === 'k') return 'P/2MASS/K'
      return null
    case 'allWISE':
      // allWISE HiPS IDs are case-sensitive: W1/W2/W3/W4 (uppercase).
      if (band === 'W1' || band === 'W2' || band === 'W4') {
        return 'P/allWISE/' + band
      }
      return null
    case 'NVSS':
      // NVSS is a single radio continuum survey — one HiPS covers all bands.
      return 'P/NVSS'
    case 'LEGACY':
      // LEGACY survey in our DB == Pan-STARRS1 (PS1) DR1 footprint.
      // R6.6c: P/PS1/{band} is rejected by CDS hips2fits ('Unknown HiPS').
      // Correct ID is P/panSTARRS/DR1/{band} (verified via direct curl).
      if (band === 'g' || band === 'r' || band === 'i' || band === 'z') {
        return 'P/panSTARRS/DR1/' + band
      }
      return null
    default:
      // AliCPT-1, Planck, and any unknown survey have no public HiPS —
      // MultiBandDataPanel will fall back to FITS overlay on DSS2 color.
      return null
  }
}
