package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.config;

/**
 * Rate-limiter abstraction — decouples the interceptor from the storage backend.
 *
 * Default: InMemoryRateLimiter (ConcurrentHashMap, single-instance).
 * Multi-instance: activate Spring profile "redis" for RedisRateLimiter
 * (shared counter across horizontally-scaled backends).
 */
public interface RateLimiter {
    /** Attempt to consume 1 token. Returns true if allowed, false if rate-limited. */
    boolean tryConsume(String key);
    /** Return the configured per-key capacity. */
    int getCapacity();
    /** Return the refill window in seconds (for Retry-After header). */
    long getRefillSeconds();
}
