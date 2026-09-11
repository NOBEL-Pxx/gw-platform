package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.config;

/**
 * Rate-limiter abstraction — decouples the interceptor from the storage backend.
 *
 * Default: InMemoryRateLimiter (ConcurrentHashMap, single-instance). Active when
 * Spring profile "redis" is NOT set (i.e., dev/local/single-instance deployments).
 *
 * Multi-instance: activate Spring profile "redis" for RedisRateLimiter — distributed
 * bucket4j via Lettuce + Redis Lua scripts. Shared counter across horizontally-scaled
 * backends. Requires the bucket4j-lettuce dependency on the classpath + a reachable
 * Redis service (env: RATE_LIMIT_REDIS_URI, REDIS_HOST, REDIS_PORT).
 *
 * R6.89: RedisRateLimiter re-introduced (was deleted in R6.66.1 as dead code; the
 * property scaffold in application-redis.properties was preserved).
 */
public interface RateLimiter {
    /** Attempt to consume 1 token. Returns true if allowed, false if rate-limited. */
    boolean tryConsume(String key);
    /** Return the configured per-key capacity. */
    int getCapacity();
    /** Return the refill window in seconds (for Retry-After header). */
    long getRefillSeconds();
}
