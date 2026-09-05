/**
 * Centralized asset path constants (v4.16).
 *
 * All image, icon, and static resource paths are defined here.
 * Batch-update assets by editing this single file instead of
 * searching across 7+ TSX components.
 *
 * Usage:
 *   import { ASSETS } from '@/constants/assets'
 *   <img src={ASSETS.icons.cas} alt='AI Models Hub' />
 */

export const ASSETS = {
  /** Core brand icons */
  icons: {
    /** CAS logo — floating AI button + drawer title */
    cas: '/CAS.jpg' as const,
  },

  /** Landing page entry card images (WebP with PNG fallback) */
  landingCards: {
    search: '/images/search-astro-data.webp' as const,
    anomaly: '/images/anomaly-detection.webp' as const,
    pipeline: '/images/science-pipeline.webp' as const,
    assistant: '/images/ai-assistant.webp' as const,
  } as const,

  /**
   * WebP → PNG fallback map.
   * The landing page onError handler automatically tries the PNG
   * counterpart when a WebP image fails to load.
   */
  webpToPng: (src: string): string => src.replace('.webp', '.png'),
} as const

/** Card config for landing page — paths from ASSETS.landingCards */
export const LANDING_CARDS = [
  {
    path: '/search',
    img: ASSETS.landingCards.search,
    title: 'Search Astronomical Data',
    color: '#00F0FF',
  },
  {
    path: '/index',
    img: ASSETS.landingCards.anomaly,
    title: 'Abnormal Data',
    color: '#FF006E',
  },
  {
    path: '/assistant',
    img: ASSETS.landingCards.assistant,
    title: 'AI Astronomy Assistant',
    color: '#00E676',
  },
] as const
