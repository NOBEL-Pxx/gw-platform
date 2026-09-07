// R6.67.4: inlined a local ErrorBoundary instead of importing the shared
// `@/components/ErrorBoundary` default export. The bundle's cross-chunk
// import (`import{t as E} from './index-...js'` where entry aliases J->t)
// was resolving to an object (React error #130) - the safest workaround is
// to keep the boundary component co-located with the consumer so it lives
// in the SAME chunk and avoids the cross-chunk default-export lookup.

import { Component, type ReactNode } from 'react'

interface AladinProps {
  // R6.13: parent (MultiBandDataPanel) pre-computes the big-viewer URL using
  // the SAME source logic as the thumbnail (HiPS cutout when the band has
  // a HiPS, else /pipeline/thumbnail for AliCPT-class FITS-only tiles,
  // else the merge-rgb URL for RGB composites). Guarantees thumbnail-vs-big
  // consistency: same orientation, same stretch, same source. Tiles without
  // FITS (DSS2 RGB, SDSS, allWISE RGB, LEGACY RGB) now have a big image too.
  imageUrl: string
  alt?: string
  // R6.27i: optional ref to the big <img> element so the parent can update
  // its style.filter directly (without re-rendering) for ms-level response.
  // The parent (useContrastDOM) decides what filter to apply; we just hand
  // out the DOM node. The `filter` prop is kept for SSR / fallback cases
  // (e.g. when the hook isn't used) but is typically undefined now.
  imgRef?: React.MutableRefObject<HTMLImageElement | null>
  // Legacy (R6.27h): CSS filter string passed via prop. Replaced by direct-DOM
  // mutation via useContrastDOM in R6.27i for ms-level response. Kept as
  // fallback for callers that don't use the hook.
  filter?: string
}

// R6.67.4: minimal local ErrorBoundary, co-located to avoid the
// cross-chunk default-export bug that resolved the shared
// @/components/ErrorBoundary to an object (React error #130) when
// imported from the CommentsTrigger chunk via `import{t as E}`.
class LocalErrorBoundary extends Component<
  { children: ReactNode },
  { hasError: boolean; error: Error | null }
> {
  state = { hasError: false, error: null as Error | null }
  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error }
  }
  componentDidCatch(error: Error) {
    console.error('[Aladin LocalErrorBoundary]', error)
  }
  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <div
          className='flex items-center justify-center p-4 text-white/60 text-sm'
          style={{ minHeight: 420, background: '#0A0F1E' }}
        >
          Aladin render error: {this.state.error?.message || 'unknown'}
        </div>
      )
    }
    return this.props.children
  }
}

// R6.13: pure renderer - no URL logic, no FITS prop. The old Aladin iframe +
// Aladin Lite v3.8.2 approach is gone (R6.12 replaced it with a plain <img>
// using /pipeline/thumbnail; R6.13 consumes a URL the parent already
// validated and cached).
export default function Aladin({
  imageUrl,
  alt,
  imgRef,
  filter,
}: AladinProps): JSX.Element {
  return (
    <LocalErrorBoundary>
      <div
        className='w-full h-full relative flex items-center justify-center'
        style={{ minHeight: 420, background: '#000' }}
      >
        {imageUrl ? (
          <img
            ref={imgRef}
            src={imageUrl}
            alt={alt || 'Multi-band preview'}
            className='w-full h-full'
            // R6.27i: filter is applied via direct DOM mutation in
            // useContrastDOM. The inline `filter` prop here is only used as
            // a fallback when the hook isn't wired (legacy callers).
            style={{ objectFit: 'contain', filter: filter || undefined }}
            draggable={false}
            loading='eager'
            // R6.27i.e: ms-level band-switch response.
            // - decoding="sync": forces synchronous decode, eliminating the
            //   async flicker (old image -> blank -> new image). For cached
            //   400px JPEGs, sync decode is ~20-30ms - acceptable trade-off
            //   for no flicker.
            // - fetchpriority="high": browser prioritizes this image's
            //   network/decode work over lower-priority images on the page.
            decoding='sync'
            fetchPriority='high'
          />
        ) : (
          <div className='text-white/40 text-sm'>Select a band to view</div>
        )}
      </div>
    </LocalErrorBoundary>
  )
}
