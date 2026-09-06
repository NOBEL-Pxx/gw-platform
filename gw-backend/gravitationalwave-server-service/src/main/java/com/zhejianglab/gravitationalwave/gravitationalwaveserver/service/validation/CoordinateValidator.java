package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.validation;

/**
 * Reusable astronomical coordinate validators — single source of truth
 * for RA / Dec / radius bounds across all controllers and services.
 */
public final class CoordinateValidator {

    private CoordinateValidator() {} // utility class

    public static final double RA_MIN = 0.0;
    public static final double RA_MAX = 360.0;
    public static final double DEC_MIN = -90.0;
    public static final double DEC_MAX = 90.0;
    public static final double RADIUS_MIN = 0.0;
    public static final double RADIUS_MAX = 180.0;

    /** Validate RA value. Returns null if valid, error message if invalid. */
    public static String validateRa(Double ra) {
        if (ra == null) return null;
        if (ra < RA_MIN || ra > RA_MAX)
            return String.format("Invalid RA value %.4f: must be between %.0f and %.0f", ra, RA_MIN, RA_MAX);
        return null;
    }

    /** Validate Dec value. Returns null if valid, error message if invalid. */
    public static String validateDec(Double dec) {
        if (dec == null) return null;
        if (dec < DEC_MIN || dec > DEC_MAX)
            return String.format("Invalid Dec value %.4f: must be between %.0f and %.0f", dec, DEC_MIN, DEC_MAX);
        return null;
    }

    /** Validate radius. Returns null if valid, error message if invalid. */
    public static String validateRadius(Double radius) {
        if (radius == null) return null;
        if (radius < RADIUS_MIN || radius > RADIUS_MAX)
            return String.format("Invalid radius value %.4f: must be between %.0f and %.0f degrees",
                    radius, RADIUS_MIN, RADIUS_MAX);
        return null;
    }

    /** Validate all three coordinate params at once. Returns first error or null. */
    public static String validate(Double ra, Double dec, Double radius) {
        String err = validateRa(ra);
        if (err != null) return err;
        err = validateDec(dec);
        if (err != null) return err;
        err = validateRadius(radius);
        if (err != null) return err;
        return null;
    }
}
