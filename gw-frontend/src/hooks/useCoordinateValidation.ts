import { useMemo } from 'react'

interface CoordinateValidation {
  ra: number | undefined
  dec: number | undefined
  radius: number | undefined
  /** Ready to search: both RA and Dec are valid numbers */
  ready: boolean
  /** Individual field errors (null = valid or empty) */
  errors: { ra: string | null; dec: string | null; radius: string | null }
  /** First error message, or null if all valid */
  firstError: string | null
}

/**
 * Reusable astronomical coordinate validator hook.
 *
 * Rules (aligned with backend CoordinateValidator):
 *   RA:    0 ≤ ra ≤ 360 (v4.16: RA=360 normalized to 0)
 *   Dec:   -90 ≤ dec ≤ 90
 *   Radius: 0 ≤ radius ≤ 180
 *
 * Edge cases handled:
 *   - RA=0 (spring equinox) → valid (was a bug: !!ra converted 0 to false)
 *   - RA=360 → normalized to 0 before search (same sky position)
 *   - Dec=0 → valid
 *   - radius=0 → valid (backend skips geo filter; frontend shows tooltip)
 *   - null/undefined → no error (optional field)
 */
export function useCoordinateValidation(
  ra: number | undefined,
  dec: number | undefined,
  radius: number | undefined,
): CoordinateValidation {
  return useMemo(() => {
    const errors = {
      ra: null as string | null,
      dec: null as string | null,
      radius: null as string | null,
    }

    // v4.16: Normalize RA=360→0 (same sky position, avoids meridian ambiguity)
    let normalizedRa = ra
    if (ra !== undefined && ra !== null) {
      if (ra === 360) {
        normalizedRa = 0
      } else if (ra < 0 || ra > 360) {
        errors.ra = `RA must be 0–360 (got ${ra})`
      }
    }
    if (dec !== undefined && dec !== null) {
      if (dec < -90 || dec > 90) errors.dec = `Dec must be −90–90 (got ${dec})`
    }
    if (radius !== undefined && radius !== null) {
      if (radius < 0 || radius > 180)
        errors.radius = `Radius must be 0–180° (got ${radius})`
    }

    const ready =
      normalizedRa !== undefined &&
      normalizedRa !== null &&
      dec !== undefined &&
      dec !== null &&
      errors.ra === null &&
      errors.dec === null

    const firstError = errors.ra || errors.dec || errors.radius || null

    // v4.16: radius=0 hint — backend skips geo filter, returns ALL observations at this coordinate
    const radiusZeroHint =
      radius === 0
        ? 'Radius=0 disables geo filtering — all observations at this exact coordinate will be returned'
        : null

    return {
      ra: normalizedRa,
      dec,
      radius,
      ready,
      errors,
      firstError,
      radiusZeroHint,
    }
  }, [ra, dec, radius])
}
