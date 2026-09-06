package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.auth.util;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;

/**
 * In-memory JWT token blacklist (v4.16).
 *
 * Supports:
 *  - Logout: blacklist the current token so it cannot be reused
 *  - Password change: blacklist ALL tokens for a user (by userId)
 *  - Auto-cleanup: expired entries purged every 5 minutes
 *
 * Production: Replace with Redis Set for multi-instance deployment.
 */
@Component
public class TokenBlacklist {

    private static final Logger log = LoggerFactory.getLogger(TokenBlacklist.class);

    /**
     * Blacklisted tokens by JWT ID (jti) → expiry timestamp.
     * When a user logs out, their current token goes here.
     */
    private final ConcurrentHashMap<String, Long> tokenBlacklist = new ConcurrentHashMap<>();

    /**
     * Global invalidation timestamps by userId.
     * If a token was issued BEFORE this timestamp, it's invalid.
     * Used for password-change → invalidate all existing tokens.
     */
    private final ConcurrentHashMap<String, Long> userInvalidationTimes = new ConcurrentHashMap<>();

    /**
     * Blacklist a specific token. Used on logout.
     * @param jti  JWT ID (claim "jti")
     * @param expiryEpochMs  when the token would naturally expire
     */
    public void blacklistToken(String jti, long expiryEpochMs) {
        tokenBlacklist.put(jti, expiryEpochMs);
        log.debug("Token blacklisted: jti={}, expires={}", jti.substring(0, Math.min(8, jti.length())), expiryEpochMs);
    }

    /**
     * Invalidate ALL tokens for a user issued before this moment.
     * Call on password change or account lockout.
     */
    public void invalidateAllUserTokens(String userId) {
        long now = System.currentTimeMillis();
        userInvalidationTimes.put(userId, now);
        log.info("All tokens invalidated for user={}, cutoff={}", userId, now);
    }

    /**
     * Check if a token is blacklisted (by jti or user invalidation).
     *
     * @param jti       JWT ID from token claims
     * @param userId    userId from token claims
     * @param issuedAt  epoch-ms when token was issued
     * @return true if the token should be rejected
     */
    public boolean isBlacklisted(String jti, String userId, long issuedAt) {
        // Check direct blacklist (logout)
        if (jti != null && tokenBlacklist.containsKey(jti)) {
            return true;
        }
        // Check user-level invalidation (password change)
        if (userId != null) {
            Long cutoff = userInvalidationTimes.get(userId);
            if (cutoff != null && issuedAt < cutoff) {
                return true;
            }
        }
        return false;
    }

    /**
     * Remove a user's invalidation record (e.g., after they log in successfully
     * with a new password, old tokens are already invalid, clean up the record).
     */
    public void clearUserInvalidation(String userId) {
        userInvalidationTimes.remove(userId);
    }

    /**
     * Periodic cleanup: remove expired entries.
     * Runs every 5 minutes.
     */
    @Scheduled(fixedDelay = 5, initialDelay = 5, timeUnit = TimeUnit.MINUTES)
    public void cleanup() {
        long now = System.currentTimeMillis();
        int before = tokenBlacklist.size();
        tokenBlacklist.entrySet().removeIf(e -> e.getValue() < now);
        int removed = before - tokenBlacklist.size();
        if (removed > 0) {
            log.debug("Token blacklist cleanup: removed {} expired entries ({} remaining)",
                    removed, tokenBlacklist.size());
        }
    }

    /** For monitoring */
    public int size() {
        return tokenBlacklist.size();
    }
    public int userInvalidationCount() {
        return userInvalidationTimes.size();
    }
}
