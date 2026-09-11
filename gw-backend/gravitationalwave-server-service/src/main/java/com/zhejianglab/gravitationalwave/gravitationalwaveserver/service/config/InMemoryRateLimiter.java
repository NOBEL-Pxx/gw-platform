package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.config;

import io.github.bucket4j.Bandwidth;
import io.github.bucket4j.Bucket;
import io.github.bucket4j.Refill;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;

/**
 * Default single-instance rate limiter backed by ConcurrentHashMap.
 *
 * R6.89: @Profile("!redis") restored. Active when the "redis" profile is NOT set.
 * When "redis" profile IS set, RedisRateLimiter takes over (multi-instance distributed
 * bucket4j via Lettuce + Redis Lua scripts). Fall-through pattern: dev/local still gets
 * this in-memory impl; production with the "redis" profile gets distributed.
 *
 * R6.66.1 history: RedisRateLimiter was deleted as dead code; R6.89 brings it back because
 * the bucket4j-redis dependency + application-redis.properties were already authored, and
 * the practical need (multi-instance scaling) is now on the horizon. Until scaling ships,
 * this in-memory impl remains the only one running in production.
 */
@Component
@org.springframework.context.annotation.Profile("!redis")
public class InMemoryRateLimiter implements RateLimiter {

    private static final Logger log = LoggerFactory.getLogger(InMemoryRateLimiter.class);

    private final ConcurrentHashMap<String, Bucket> buckets = new ConcurrentHashMap<>();

    @Value("${rate.limit.capacity:60}")
    private int capacity = 60;

    @Value("${rate.limit.refill-minutes:1}")
    private int refillMinutes = 1;

    @Value("${rate.limit.cleanup-minutes:15}")
    private int cleanupMinutes = 15;

    @Override
    public boolean tryConsume(String key) {
        Bucket bucket = buckets.computeIfAbsent(key, k -> createNewBucket());
        return bucket.tryConsume(1);
    }

    @Override
    public int getCapacity() { return capacity; }

    @Override
    public long getRefillSeconds() { return Math.max(refillMinutes * 60L, 1); }

    private Bucket createNewBucket() {
        Bandwidth limit = Bandwidth.classic(capacity,
                Refill.intervally(capacity, Duration.ofMinutes(refillMinutes)));
        return Bucket.builder().addLimit(limit).build();
    }

    @Scheduled(fixedDelayString = "${rate.limit.cleanup-minutes:15}",
               initialDelayString = "${rate.limit.cleanup-minutes:15}",
               timeUnit = TimeUnit.MINUTES)
    public void cleanUpStaleBuckets() {
        int before = buckets.size();
        buckets.entrySet().removeIf(e -> e.getValue().getAvailableTokens() >= capacity);
        int removed = before - buckets.size();
        if (removed > 0) {
            log.info("Rate-limit bucket cleanup: removed {} stale entries ({} remaining)",
                    removed, buckets.size());
        }
    }
}
